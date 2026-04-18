"""Speech-to-text transcription for iMessage voice memos.

Priority: Parakeet V3 (via parakeet-mlx, Apple Silicon optimized)
Fallback: OpenAI Whisper (universal, works on any hardware)
"""

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
    """Convert audio file to 16kHz mono WAV. Returns path to wav file."""
    if not os.path.isfile(input_path):
        return None

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


def _transcribe_parakeet(wav_path: str) -> Optional[str]:
    """Transcribe using Parakeet V3 via parakeet-mlx (Apple Silicon optimized)."""
    try:
        from parakeet_mlx import from_pretrained
        model = from_pretrained("mlx-community/parakeet-tdt-0.6b-v3")
        result = model.transcribe(wav_path)
        text = result.text.strip() if hasattr(result, 'text') else str(result).strip()
        log.info(f"Parakeet V3 transcribed: {text[:60]}...")
        return text if text else None
    except ImportError:
        return None
    except Exception as e:
        log.warning(f"Parakeet V3 failed: {e}")
        return None


def _transcribe_whisper(wav_path: str) -> Optional[str]:
    """Transcribe using OpenAI Whisper (fallback)."""
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(wav_path, fp16=False)
        text = result.get("text", "").strip()
        log.info(f"Whisper transcribed: {text[:60]}...")
        return text if text else None
    except ImportError:
        return None
    except Exception as e:
        log.warning(f"Whisper failed: {e}")
        return None


def transcribe(audio_path: str) -> Optional[str]:
    """Transcribe audio file to text.

    Tries Parakeet V3 first (faster on Apple Silicon), falls back to Whisper.
    Converts to WAV first if needed.
    """
    audio_path = os.path.expanduser(audio_path)

    if not os.path.isfile(audio_path):
        log.warning(f"Audio file not found: {audio_path}")
        return None

    wav_path = convert_to_wav(audio_path)
    if not wav_path:
        return None

    cleanup_wav = wav_path != audio_path

    try:
        # Try Parakeet V3 first (Apple Silicon optimized)
        text = _transcribe_parakeet(wav_path)
        if text:
            return text

        # Fallback to Whisper
        text = _transcribe_whisper(wav_path)
        if text:
            return text

        log.warning("No STT model available. Install: pip3 install parakeet-mlx or openai-whisper")
        return None
    finally:
        if cleanup_wav and os.path.isfile(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
