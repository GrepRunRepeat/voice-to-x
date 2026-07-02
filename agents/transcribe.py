"""
Agent 1 — Transcription
Records audio from the mic and transcribes it locally using MLX Whisper.
Nothing leaves your machine.

Supports two models (see config/settings.py):
- WAKE_LISTEN_MODEL: small/fast, used by the continuous wake-word listener
- WHISPER_MODEL: larger/accurate, used for the final ticket transcription
"""

import numpy as np
import sounddevice as sd
import mlx_whisper

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config.settings import WHISPER_MODEL, SAMPLE_RATE


def record_fixed(duration_seconds, samplerate=SAMPLE_RATE):
    """Simple fixed-duration recording, mainly useful for manual testing."""
    print(f"Recording for {duration_seconds}s... speak now.")
    audio = sd.rec(int(duration_seconds * samplerate), samplerate=samplerate, channels=1, dtype="float32")
    sd.wait()
    return audio.flatten()


def transcribe(audio: np.ndarray, model: str = WHISPER_MODEL) -> str:
    """Transcribe an audio array. Pass model=WAKE_LISTEN_MODEL for fast polling checks."""
    if audio.size == 0:
        return ""
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=model)
    return result["text"].strip()


if __name__ == "__main__":
    # Quick manual test: records 6 seconds, transcribes, prints result.
    audio = record_fixed(6)
    text = transcribe(audio)
    print("Transcript:", text)
