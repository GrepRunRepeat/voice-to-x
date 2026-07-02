"""
LangGraph orchestration for voice-to-x.

Each node reads/writes a shared TypedDict state. Keeping the agents as plain
functions (agents/transcribe.py, agents/structure.py, agents/jira_create.py,
agents/notes_create.py) and only wiring them here keeps each agent
independently testable.
"""

from typing import Optional, TypedDict
import numpy as np

from langgraph.graph import StateGraph, START, END

from agents.transcribe import transcribe as agent_transcribe
from agents.structure import structure_request as agent_structure
from agents.jira_create import create_jira_ticket as agent_create_ticket
from agents.notes_create import create_note as agent_create_note


class TicketState(TypedDict, total=False):
    audio: np.ndarray            # raw recorded audio, set before graph.invoke()
    transcript: str              # Agent 1 output
    fields: dict                 # Agent 2 output (structured ticket or note, incl. "target")
    action: str                  # "create" | "cancel", set by review node
    result: Optional[dict]       # Agent 3 output (created Jira issue or note)
    error: Optional[str]         # populated if any node fails


# --- Nodes ---

def transcribe_node(state: TicketState) -> TicketState:
    print("[Agent 1] Transcribing locally...")
    text = agent_transcribe(state["audio"])
    if not text:
        return {**state, "transcript": "", "error": "empty_transcript"}
    print(f'   Heard: "{text}"')
    return {**state, "transcript": text}


def structure_node(state: TicketState) -> TicketState:
    print("[Agent 2] Structuring and classifying (ticket vs note)...")
    fields = agent_structure(state["transcript"])
    return {**state, "fields": fields}


def _review_ticket(fields: dict) -> None:
    print("PROPOSED TICKET")
    print("=" * 60)
    print(f"Project:     {fields['project_key']}")
    print(f"Type:        {fields['issue_type']}")
    print(f"Priority:    {fields['priority']}")
    print(f"Title:       {fields['title']}")
    print(f"Description: {fields['description']}")
    print(f"Labels:      {', '.join(fields.get('labels', [])) or '(none)'}")


def _edit_ticket(fields: dict) -> None:
    fields["project_key"] = input(f"Project key [{fields['project_key']}]: ").strip() or fields["project_key"]
    fields["issue_type"] = input(f"Issue type [{fields['issue_type']}]: ").strip() or fields["issue_type"]
    fields["priority"] = input(f"Priority [{fields['priority']}]: ").strip() or fields["priority"]
    fields["title"] = input(f"Title [{fields['title']}]: ").strip() or fields["title"]
    new_desc = input(f"Description [{fields['description']}]: ").strip()
    if new_desc:
        fields["description"] = new_desc


def _review_note(fields: dict) -> None:
    print("PROPOSED NOTE")
    print("=" * 60)
    print(f"Title:       {fields['title']}")
    print(f"Description: {fields['description']}")


def _edit_note(fields: dict) -> None:
    fields["title"] = input(f"Title [{fields['title']}]: ").strip() or fields["title"]
    new_desc = input(f"Description [{fields['description']}]: ").strip()
    if new_desc:
        fields["description"] = new_desc


def review_node(state: TicketState) -> TicketState:
    """Human-in-the-loop gate. Runs in the terminal."""
    fields = state["fields"]
    is_note = fields.get("target") == "note"

    print("\n" + "=" * 60)
    if is_note:
        _review_note(fields)
    else:
        _review_ticket(fields)
    if fields.get("_parse_error"):
        print("\n!! Model output wasn't valid JSON — fields above are a rough fallback.")
    print("=" * 60)

    choice = input("[Enter]=create  [e]=edit  [c]=cancel: ").strip().lower()

    if choice == "c":
        return {**state, "action": "cancel"}

    if choice == "e":
        if is_note:
            _edit_note(fields)
        else:
            _edit_ticket(fields)

    return {**state, "fields": fields, "action": "create"}


def create_ticket_node(state: TicketState) -> TicketState:
    print("[Agent 3] Creating ticket in Jira...")
    try:
        result = agent_create_ticket(state["fields"])
        print(f"Created {result['key']}: {result['browse_url']}")
        return {**state, "result": result}
    except Exception as e:
        print(f"Failed to create ticket: {e}")
        return {**state, "error": str(e)}


def create_note_node(state: TicketState) -> TicketState:
    print("[Agent 3b] Creating note in Notes...")
    try:
        result = agent_create_note(state["fields"])
        print(f"Created note \"{result['title']}\" in folder \"{result['folder']}\".")
        return {**state, "result": result}
    except Exception as e:
        print(f"Failed to create note: {e}")
        return {**state, "error": str(e)}


# --- Conditional Routing ---

def route_after_transcribe(state: TicketState) -> str:
    if state.get("error") == "empty_transcript":
        print("Heard nothing, skipping.")
        return "end"
    return "structure"


def route_after_review(state: TicketState) -> str:
    if state.get("action") == "cancel":
        print("Cancelled, nothing created.")
        return "end"
    return "note" if state["fields"].get("target") == "note" else "ticket"


# --- Graph assembly ---

def build_graph():
    graph = StateGraph(TicketState)

    graph.add_node("transcribe", transcribe_node)
    graph.add_node("structure", structure_node)
    graph.add_node("review", review_node)
    graph.add_node("create_ticket", create_ticket_node)
    graph.add_node("create_note", create_note_node)

    graph.add_edge(START, "transcribe")
    graph.add_conditional_edges("transcribe", route_after_transcribe, {"structure": "structure", "end": END})
    graph.add_edge("structure", "review")
    graph.add_conditional_edges(
        "review", route_after_review, {"ticket": "create_ticket", "note": "create_note", "end": END}
    )
    graph.add_edge("create_ticket", END)
    graph.add_edge("create_note", END)

    return graph.compile()


# Compiled once, reused across every ticket the voice listener dispatches.
ticket_graph = build_graph()


if __name__ == "__main__":
    # Quick manual test: records a fixed 6s clip and runs it through the full graph,
    # bypassing the wake-word listener. Useful for testing structure/create nodes
    # without needing to say "wallace"/"gromit".
    from agents.transcribe import record_fixed

    audio = record_fixed(6)
    ticket_graph.invoke({"audio": audio})
