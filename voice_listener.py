r"""
Voice-activated listener.

Continuously listens on the mic, using a
small/fast Whisper model to poll a rolling window of recent audio for the
wake word ("wallace" by default). Once heard, it starts accumulating audio
into a separate ticket buffer until it hears the stop word ("gromit"), then
hands that audio off to the LangGraph pipeline for the real (accurate)
transcription + structuring + review + creation.

Three models/techniques are combined deliberately:
- WAKE_LISTEN_MODEL (tiny): fast enough to poll every ~1.5s without lagging,
  used while idle waiting for the wake word
- STOP_LISTEN_MODEL (base): slightly more accurate, used once recording has
  started — missing the stop word is more costly (stuck recording until the
  safety cap) than missing the wake word, so accuracy matters more here
- Fuzzy word matching: uncommon words like "gromit" get misheard by small
  Whisper models more often than common names like "wallace" (-> "grommit",
  "chromite", etc.). Matching each transcribed word against the target with
  a similarity ratio, instead of requiring an exact substring match, catches
  these near-misses.
- Alias phrases (WAKE_WORD_ALIASES/STOP_WORD_ALIASES in config/settings.py): fuzzy
  matching above scores one transcribed word at a time, so it can't catch Whisper
  splitting the target into two words (e.g. "gromit" -> "grum it"). Known splits
  like that are matched as plain substrings instead.

Trade-off worth knowing: continuous polling means a model is transcribing
constantly in the background. On an M4 this is cheap, but if you notice fan
noise/battery drain, raise CHECK_INTERVAL_SECONDS.
"""

import difflib
import re
import threading
import time

import numpy as np
import sounddevice as sd

from agents.transcribe import transcribe
from graph import ticket_graph
from config.settings import (
    SAMPLE_RATE,
    WAKE_WORD,
    STOP_WORD,
    WAKE_WORD_ALIASES,
    STOP_WORD_ALIASES,
    WAKE_LISTEN_MODEL,
    STOP_LISTEN_MODEL,
    CHECK_INTERVAL_SECONDS,
    ROLLING_WINDOW_SECONDS,
    MAX_RECORD_SECONDS,
    FUZZY_MATCH_CUTOFF,
    DEBUG_PRINT_TRANSCRIPTS,
)

IDLE = "idle"
RECORDING = "recording"


def fuzzy_contains(text: str, target: str, cutoff: float = FUZZY_MATCH_CUTOFF) -> bool:
    """
    True if any word in `text` is a close match to `target`, not just an exact
    substring. Handles small-model mishearings of uncommon words.
    """
    words = re.findall(r"[a-z']+", text.lower())
    target = target.lower()
    for word in words:
        if difflib.SequenceMatcher(None, word, target).ratio() >= cutoff:
            return True
    return False


def heard_target(text: str, target: str, aliases: list) -> bool:
    """
    True if `target` was heard in `text`: either a fuzzy word match, or `text`
    contains one of `target`'s known multi-word mishearing aliases verbatim.
    """
    if fuzzy_contains(text, target):
        return True
    return any(alias in text for alias in aliases)


class VoiceListener:
    def __init__(self):
        self._lock = threading.Lock()
        self._mode = IDLE
        self._rolling_chunks = []       # recent audio, used only to detect the wake word
        self._ticket_chunks = []        # accumulated audio for the current ticket
        self._recording_started_at = None
        self._stop_flag = threading.Event()

    # Audio capture

    def _on_audio(self, indata, frames, time_info, status):
        chunk = indata.copy()
        with self._lock:
            self._rolling_chunks.append(chunk)
            if self._mode == RECORDING:
                self._ticket_chunks.append(chunk)

            # Trim rolling buffer to the configured window so wake-word
            # polling always looks at a bounded, recent slice of audio.
            max_frames = int(ROLLING_WINDOW_SECONDS * SAMPLE_RATE)
            total = sum(c.shape[0] for c in self._rolling_chunks)
            while total > max_frames and len(self._rolling_chunks) > 1:
                removed = self._rolling_chunks.pop(0)
                total -= removed.shape[0]

    def _snapshot_rolling(self) -> np.ndarray:
        with self._lock:
            if not self._rolling_chunks:
                return np.zeros((0,), dtype=np.float32)
            return np.concatenate(self._rolling_chunks, axis=0).flatten()

    def _start_recording(self):
        with self._lock:
            self._mode = RECORDING
            self._ticket_chunks = []
            self._recording_started_at = time.time()
        print(f'\nWake word "{WAKE_WORD}" heard — recording ticket. Say "{STOP_WORD}" to finish.')

    def _stop_recording_and_dispatch(self):
        with self._lock:
            self._mode = IDLE
            audio = (
                np.concatenate(self._ticket_chunks, axis=0).flatten()
                if self._ticket_chunks
                else np.zeros((0,), dtype=np.float32)
            )
            self._ticket_chunks = []
            self._recording_started_at = None

        print(f'Stop word "{STOP_WORD}" heard — sending to pipeline.\n')
        threading.Thread(target=self._run_pipeline, args=(audio,), daemon=True).start()

    def _run_pipeline(self, audio: np.ndarray):
        # Runs on its own thread: an uncaught exception here would otherwise die
        # silently and leave the listener looking "stuck" with no wake-word prompt.
        try:
            ticket_graph.invoke({"audio": audio})
        except Exception as e:
            print(f"\nPipeline failed: {e}")
        print(f'\nListening for "{WAKE_WORD}"...')

    # Poll loop

    def _poll_loop(self):
        while not self._stop_flag.is_set():
            time.sleep(CHECK_INTERVAL_SECONDS)

            with self._lock:
                mode = self._mode
                started_at = self._recording_started_at

            # Safety cap: force-stop a ticket recording that's run too long
            # (e.g. stop word was missed/misheard).
            if mode == RECORDING and started_at and (time.time() - started_at) > MAX_RECORD_SECONDS:
                print(f"\nHit {MAX_RECORD_SECONDS}s safety cap without hearing the stop word, finalizing anyway.")
                self._stop_recording_and_dispatch()
                continue

            audio_window = self._snapshot_rolling()
            if audio_window.size == 0:
                continue

            # Use the more accurate model once we're actually recording, since a missed
            # stop word is costlier than a missed wake word.
            model = STOP_LISTEN_MODEL if mode == RECORDING else WAKE_LISTEN_MODEL
            try:
                text = transcribe(audio_window, model=model).lower()
            except Exception as e:
                # A single bad poll shouldn't take down the whole listener.
                print(f"\nTranscription error, skipping this poll: {e}")
                continue

            if DEBUG_PRINT_TRANSCRIPTS and text:
                tag = "listening for stop word" if mode == RECORDING else "idle"
                print(f"   [{tag}] heard: \"{text}\"")

            if not text:
                continue

            if mode == IDLE and heard_target(text, WAKE_WORD, WAKE_WORD_ALIASES):
                self._start_recording()
            elif mode == RECORDING and heard_target(text, STOP_WORD, STOP_WORD_ALIASES):
                self._stop_recording_and_dispatch()
    # Run public
    def run(self):
        print(f'Listening for "{WAKE_WORD}"... (Ctrl+C to quit)')
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=self._on_audio
        )
        with stream:
            poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            poll_thread.start()
            try:
                while poll_thread.is_alive():
                    poll_thread.join(timeout=0.5)
            except KeyboardInterrupt:
                self._stop_flag.set()
                print("\nStopping listener.")