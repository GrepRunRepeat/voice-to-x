"""
Agent 2 — Structuring
Takes raw spoken transcript, classifies it as either a Jira ticket or a personal
note, and extracts the matching structured fields using a local LLM via Ollama.
Returns a dict, never calls Jira or Notes directly.
"""

import json
import re
import ollama

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config.settings import OLLAMA_MODEL, PROJECT_ALIASES, DEFAULT_PROJECT_KEY

SYSTEM_PROMPT = """You convert spoken requests into either a Jira ticket or a personal note.

First decide the target:
- "ticket": the request describes a bug, task, or new feature that should be tracked as work
  (e.g. "there's a bug where...", "we need to build...", "create a ticket for...").
- "note": the request is a personal reminder, idea, or observation that doesn't belong in Jira
  (e.g. "note that...", "remind me to...", "idea:...").

Return ONLY a JSON object, no markdown fences, no commentary. Schema:

{
  "target": "note" | "ticket",
  "title": "short imperative summary, max 10 words",
  "description": "1-3 sentence expansion of the request, cleaned up from filler words",
  "issue_type": "Bug" | "Task" | "Story",
  "priority": "Low" | "Medium" | "High",
  "project_hint": "whatever project name/team was mentioned, or empty string",
  "labels": ["array", "of", "short", "lowercase", "labels", "nospaces"]
}

issue_type/priority/project_hint/labels only matter when target is "ticket" — still fill them
in with reasonable defaults for a note, they'll simply be ignored.

Rules:
- issue_type: "Bug" if describing broken/incorrect behavior, "Story" if describing new user-facing
  functionality, "Task" for anything else (chores, investigation, tech debt).
- priority: infer from urgency language ("urgent", "blocking", "asap" -> High; no signal -> Medium).
- Keep description factual, don't invent details not mentioned.
- Never include the keywords wallace or grommet / grommit etc. in the description. They are reserved!
- Jira labels cannot have spaces!
"""


VALID_TARGETS = {"note", "ticket"}
VALID_ISSUE_TYPES = {"Bug", "Task", "Story"}
VALID_PRIORITIES = {"Low", "Medium", "High"}


def _extract_json(text: str) -> dict:
    # Models sometimes wrap JSON in ```json fences despite instructions; strip defensively.
    cleaned = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    return json.loads(cleaned)


def _fallback_fields(transcript: str, raw: str = "") -> dict:
    return {
        "target": "ticket",
        "title": transcript[:60],
        "description": transcript,
        "issue_type": "Task",
        "priority": "Medium",
        "project_hint": "",
        "labels": [],
        "_parse_error": True,
        "_raw_model_output": raw,
    }


def resolve_project_key(project_hint: str) -> str:
    if not project_hint:
        return DEFAULT_PROJECT_KEY
    hint_lower = project_hint.lower().strip()
    for alias, key in PROJECT_ALIASES.items():
        if alias in hint_lower:
            return key
    return DEFAULT_PROJECT_KEY


def structure_request(transcript: str) -> dict:
    if not transcript.strip():
        raise ValueError("Empty transcript, nothing to structure.")

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f'Spoken request: "{transcript}"'},
            ],
            options={"temperature": 0.2},
        )
        raw = response["message"]["content"]
    except Exception as e:
        # Ollama unreachable/model missing, etc. Don't crash the pipeline over it —
        # fall back to a raw-text ticket the user can fix up in the review step.
        return _fallback_fields(transcript, raw=f"<no model output: {e}>")

    try:
        fields = _extract_json(raw)
    except json.JSONDecodeError:
        # Fallback: don't silently fail, surface the raw text for manual fixup in the review step.
        return _fallback_fields(transcript, raw=raw)

    # The model can return valid JSON that's still missing/malformed fields
    # (e.g. drops "priority", or invents an issue type). Backfill/clamp so
    # every downstream consumer can rely on this shape without KeyErrors.
    fields.setdefault("title", transcript[:60])
    fields.setdefault("description", transcript)
    fields.setdefault("labels", [])
    if fields.get("target") not in VALID_TARGETS:
        fields["target"] = "ticket"
    if fields.get("issue_type") not in VALID_ISSUE_TYPES:
        fields["issue_type"] = "Task"
    if fields.get("priority") not in VALID_PRIORITIES:
        fields["priority"] = "Medium"

    fields["project_key"] = resolve_project_key(fields.get("project_hint", ""))
    return fields


if __name__ == "__main__":
    ticket_sample = "we need a ticket for the login bug, users can't reset passwords on mobile, this is high priority, put it in the auth project"
    note_sample = "note that we should revisit our onboarding flow sometime next quarter"
    print(json.dumps(structure_request(ticket_sample), indent=2))
    print(json.dumps(structure_request(note_sample), indent=2))
