"""Speech-to-Text using OpenAI Whisper (local) with async offloading.

Function: transcribe_audio(audio_bytes) -> str
- Decodes received WAV bytes in-memory (avoids ffmpeg dependency)
- Ensures mono float32 audio at 16 kHz
- Loads Whisper model (default: base) lazily
- Runs blocking transcribe in a worker thread using asyncio.to_thread
"""

from __future__ import annotations

import asyncio
import logging
import os
import io
from typing import Optional
import numpy as np

logger = logging.getLogger("ai.stt")

_whisper_model = None


def _get_whisper_model():
    """Load and cache the Whisper model (blocking)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    import whisper

    model_name = os.environ.get("WHISPER_MODEL", "base")
    logger.info("Loading Whisper model: %s", model_name)
    _whisper_model = whisper.load_model(model_name)
    logger.info("Whisper model ready")
    return _whisper_model


def _decode_wav_to_16k_mono_float32(data: bytes) -> Optional[np.ndarray]:
    """Decode WAV bytes to mono float32 at 16 kHz using pure Python libs.

    Avoids Whisper's ffmpeg dependency by feeding numpy audio directly.
    Returns None on failure.
    """
    try:
        import soundfile as sf

        with io.BytesIO(data) as bio:
            audio, sr = sf.read(bio, dtype="float32", always_2d=True)
        if audio.ndim == 2 and audio.shape[1] > 1:
            audio = np.mean(audio, axis=1)
        else:
            audio = audio.reshape(-1)

        target_sr = 16000
        if sr != target_sr:
            x = np.arange(len(audio), dtype=np.float64)
            new_len = int(round(len(audio) * (target_sr / float(sr))))
            xp = np.linspace(0, len(audio) - 1, num=new_len, dtype=np.float64)
            audio = np.interp(xp, x, audio).astype(np.float32)

        return audio.astype(np.float32)
    except Exception as e:
        logger.exception("WAV decode/resample failed: %s", e)
        return None


async def transcribe_audio(audio_bytes: bytes) -> str:
    """Asynchronously transcribe audio bytes to text using Whisper.

    Offloads the blocking transcribe() call to a worker thread with
    asyncio.to_thread to keep the event loop responsive.
    """
    if not audio_bytes:
        return ""

    def _do_transcribe(data: bytes) -> str:
        try:
            audio = _decode_wav_to_16k_mono_float32(data)
            if audio is None or audio.size == 0:
                logger.warning("STT: empty or undecodable audio")
                return ""

            model = _get_whisper_model()
            result = model.transcribe(audio, fp16=False)
            raw_text = result.get("text")
            text = raw_text.strip() if isinstance(raw_text, str) else ""
            logger.info("STT transcription: %s", text)
            return text
        except Exception as e:
            logger.exception("STT error: %s", e)
            return ""

    return await asyncio.to_thread(_do_transcribe, audio_bytes)
