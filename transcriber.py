"""Speech-to-text transcription for iMessage voice memos."""

from __future__ import annotations
import logging
import os
import subprocess
from typing import Optional

log = logging.getLogger("imessage-bridge")

AUDIO_MIME_TYPES = {"audio/mp4", "audio/m4a", "audio/x-m4a", "audio/wav", "audio/mpeg", "audio/caf"}
AUDIO_UTIS = {"com.apple.m4a-audio", "public.mp3", "com.microsoft.waveform-audio", "public.audio"}


def is_audio_attachment(mime_type: Optional[str], uti: Optional[str]) -> bool:
    """Check if attachment is an audio file (voice memo)."""
    if mime_type and mime_type.lower() in AUDIO_MIME_TYPES:
        return True
    if uti and uti.lower() in AUDIO_UTIS:
        return True
    if mime_type and mime_type.lower().startswith("audio/"):
        return True
    return False


def convert_to_wav(input_path: str) -> Optional[str]:
    """Convert audio file to WAV format for Whisper. Returns path to wav file."""
    if not os.path.isfile(input_path):
        return None

    # If already wav, return as-is
    if input_path.lower().endswith(".wav"):
        return input_path

    output_path = input_path.rsplit(".", 1)[0] + ".wav"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", output_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and os.path.isfile(output_path):
            return output_path
        log.warning(f"ffmpeg conversion failed: {result.stderr[:100]}")
    except Exception as e:
        log.warning(f"Audio conversion failed: {e}")
    return None


def transcribe(audio_path: str) -> Optional[str]:
    """Transcribe audio file to text using Whisper.

    Converts to WAV first if needed, then runs Whisper.
    Returns transcribed text or None on failure.
    """
    # Expand tilde
    audio_path = os.path.expanduser(audio_path)

    if not os.path.isfile(audio_path):
        log.warning(f"Audio file not found: {audio_path}")
        return None

    # Convert to wav if not already
    wav_path = convert_to_wav(audio_path)
    if not wav_path:
        return None

    try:
        import whisper
        model = whisper.load_model("base")  # Fast + decent accuracy
        result = model.transcribe(wav_path, fp16=False)
        text = result.get("text", "").strip()
        return text if text else None
    except ImportError:
        log.warning("Whisper not installed. Run: pip3 install --break-system-packages openai-whisper")
        return None
    except Exception as e:
        log.warning(f"Transcription failed: {e}")
        return None
    finally:
        # Clean up converted wav (if we created it)
        if wav_path != audio_path and os.path.isfile(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
