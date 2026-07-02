"""
Agent 3 — Jira creation
Takes confirmed structured fields and creates the issue via Jira Cloud REST API v3.
"""

import requests
from requests.auth import HTTPBasicAuth

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config.settings import JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN

REQUEST_TIMEOUT_SECONDS = 15

def clean_text(text: str) -> str:
    return (
        text.replace("“", '"')
            .replace("”", '"')
            .replace("’", "'")
            .replace("–", "-")
            .replace("—", "-")
    )

def capitalize_first(text: str) -> str:
    """Uppercase just the first character, unlike str.capitalize() which also
    lowercases the rest of the string (mangling things like "API" -> "api")."""
    return text[0].upper() + text[1:] if text else text

def create_jira_ticket(fields: dict) -> dict:
    required_env = {"JIRA_URL": JIRA_URL, "JIRA_EMAIL": JIRA_EMAIL, "JIRA_API_TOKEN": JIRA_API_TOKEN}
    missing_env = [name for name, value in required_env.items() if not value]
    if missing_env:
        raise RuntimeError(f"{', '.join(missing_env)} not set. Export as environment variable(s).")

    required_fields = ("project_key", "title", "description", "issue_type")
    missing_fields = [key for key in required_fields if not fields.get(key)]
    if missing_fields:
        raise ValueError(f"Ticket fields missing required key(s): {', '.join(missing_fields)}")

    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    title = capitalize_first(clean_text(fields["title"]))
    description = capitalize_first(clean_text(fields["description"]))
    issue_type = clean_text(fields["issue_type"])
    payload = {
        "fields": {
            "project": {"key": fields["project_key"]},
            "summary": title,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            },
            "issuetype": {"name": issue_type},
            "labels": fields.get("labels", []),
        }
    }

    # Priority field name varies by Jira config
    if fields.get("priority"):
        payload["fields"]["priority"] = {"name": fields["priority"]}

    try:
        response = requests.post(
            f"{JIRA_URL}/rest/api/3/issue",
            headers=headers,
            auth=auth,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Could not reach Jira at {JIRA_URL}: {e}") from e

    if response.status_code >= 400:
        raise RuntimeError(f"Jira API error {response.status_code}: {response.text}")

    result = response.json()
    result["browse_url"] = f"{JIRA_URL}/browse/{result['key']}"
    return result


if __name__ == "__main__":
    test_fields = {
        "title": "Test ticket from voice-to-x",
        "description": "This is a test, safe to delete.",
        "issue_type": "Task",
        "priority": "Low",
        "project_key": "UNSPEC",
        "labels": ["voice-created"],
    }
    print(create_jira_ticket(test_fields))
