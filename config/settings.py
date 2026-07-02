import os

# ─── Jira ────────────────────────────────────────────────────────────────
JIRA_URL = os.environ.get("JIRA_URL", "") # set via env var, don't hardcode
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "") # set via env var, don't hardcode
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")  # set via env var, don't hardcode

# Map spoken project names -> actual Jira project keys.
# Add whatever shorthand you naturally say out loud.
PROJECT_ALIASES = {
    "auth project": "AUTH",
    "auth": "AUTH",
    "backend": "BACK",
    "backend project": "BACK",
    "frontend": "FRONT",
    "data platform": "DATA",
    "data": "DATA",
}
DEFAULT_PROJECT_KEY = "AUTH"  # fallback if nothing matches

# ─── Local models ────────────────────────────────────────────────────────
WHISPER_MODEL = "mlx-community/whisper-small.en-mlx"
WAKE_LISTEN_MODEL = "mlx-community/whisper-small.en-mlx" # tiny might also work here
STOP_LISTEN_MODEL = "mlx-community/whisper-small.en-mlx" # tiny might also work here 
OLLAMA_MODEL = "qwen2.5:7b"
 
# ─── Audio ───────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000
MAX_RECORD_SECONDS = 45  # safety cap per ticket
 
# ─── Voice activation ────────────────────────────────────────────────────
WAKE_WORD = "wallace"     # say this to start recording a ticket
STOP_WORD = "gromit"      # say this to stop recording and send it to the pipeline

# Known multi-word mishearings of the wake/stop word that should count as a match even
# though fuzzy_contains() (which scores one transcribed word at a time) can't catch them —
# e.g. Whisper splitting "gromit" into two words like "grum it" or "grum et". Add more here
# as you notice them; checked as plain substrings of the transcript, not fuzzy-matched.
WAKE_WORD_ALIASES = []
STOP_WORD_ALIASES = ["grum it", "grum et", "gromm et"]

CHECK_INTERVAL_SECONDS = 1   # how often the listener polls for wake/stop words
ROLLING_WINDOW_SECONDS = 4     # how much recent audio is checked each poll (needs enough
                                # context for whisper to catch a full word reliably)
 
# Fuzzy matching tolerance for wake/stop word detection (0-1, higher = stricter).
# Small/tiny Whisper models often mishear uncommon words ("gromit" -> "grommit",
# "chromite", etc.) — fuzzy matching against individual transcribed words catches
# these near-misses instead of requiring an exact substring match.
FUZZY_MATCH_CUTOFF = 0.75
 
# Print what the listener actually heard on every poll (not just on a match).
# Very useful for tuning wake/stop words or diagnosing missed detections —
# turn off once things are working reliably, since it's noisy.
DEBUG_PRINT_TRANSCRIPTS = True
