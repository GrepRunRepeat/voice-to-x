"""
Voice-to-X — main entry point

Say "wallace" to start recording a request, "gromit" to stop and send it
through the pipeline (transcribe -> structure -> review -> create). Depending
on what was said, the request becomes either a Jira ticket or a macOS Note.

All orchestration between agents lives in graph.py (LangGraph StateGraph).
This file just starts the continuous voice listener defined in
voice_listener.py, which detects the wake/stop words and hands audio off
to the graph.
"""

from voice_listener import VoiceListener


def main():
    listener = VoiceListener()
    listener.run()


if __name__ == "__main__":
    main()
