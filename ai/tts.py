"""Text-to-speech wrapper with lazy backend imports.

Supported backends by TTS_BACKEND env var:
- pyttsx3: offline TTS library (cross-platform)
- fallback: generate a short silent WAV so client can play audio

Function `text_to_speech(text)` returns bytes containing WAV audio.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

logger = logging.getLogger("ai.tts")

TTS_BACKEND = os.environ.get("TTS_BACKEND", "fallback").lower()


async def text_to_speech(text: str) -> bytes:
    logger.info("TTS backend: %s | text=%s", TTS_BACKEND, text[:40])

    if TTS_BACKEND == "pyttsx3":
        try:
            import pyttsx3
            import tempfile
            import os as _os

            engine = pyttsx3.init()
            # pyttsx3 can save to file via drivers; we use a temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            engine.save_to_file(text, tmp_path)
            engine.runAndWait()
            with open(tmp_path, "rb") as f:
                data = f.read()
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass
            logger.info("pyttsx3 generated %d bytes", len(data))
            return data
        except Exception as e:
            logger.warning("pyttsx3 TTS failed: %s", e)
            # fallthrough to fallback

    # fallback: return a 0.5 second silent WAV using soundfile
    try:
        import io
        import soundfile as sf
        import numpy as np

        samplerate = 22050
        duration_s = 0.5
        samples = int(samplerate * duration_s)
        data = np.zeros(samples, dtype="float32")
        buf = io.BytesIO()
        sf.write(buf, data, samplerate, format="WAV")
        buf.seek(0)
        audio_bytes = buf.read()
        logger.info("Generated fallback silent WAV, %d bytes", len(audio_bytes))
        return audio_bytes
    except Exception as e:
        logger.error("Fallback TTS generation failed: %s", e)
        return b""
