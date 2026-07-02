"""
Agent 3b — macOS Notes creation
Takes confirmed note fields and creates a note in the macOS Notes app via AppleScript.
"""

import subprocess

NOTES_FOLDER = "Notes"  # default Notes.app folder new voice notes are filed into

_APPLESCRIPT = """
on run argv
    set noteBody to item 1 of argv
    set noteFolderName to item 2 of argv
    tell application "Notes"
        make new note at folder noteFolderName with properties {body:noteBody}
    end tell
end run
"""


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def create_note(fields: dict) -> dict:
    title = fields.get("title", "").strip()
    description = fields.get("description", "").strip()
    if not title and not description:
        raise ValueError("Note has no title or description, nothing to create.")

    title = title or description[:60]
    # Notes.app has no separate title property — the title shown in the Notes
    # list is just the first line of the body, so the title is bolded as that
    # first line rather than passed to AppleScript separately.
    body_html = f"<b>{_html_escape(title)}</b><br>{_html_escape(description)}"

    try:
        result = subprocess.run(
            ["osascript", "-e", _APPLESCRIPT, "--", body_html, NOTES_FOLDER],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Timed out creating note in Notes.app.") from e

    if result.returncode != 0:
        raise RuntimeError(f"Failed to create note: {result.stderr.strip()}")

    return {"title": title, "folder": NOTES_FOLDER}


if __name__ == "__main__":
    print(create_note({"title": "Test note", "description": "Created by voice-to-x notes agent."}))
