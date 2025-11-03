import os
import threading
import time
from dataclasses import dataclass
from queue import Queue, Empty
from typing import Optional, Callable
import array
import math

from dotenv import load_dotenv

try:
    import sounddevice as sd
except Exception:
    sd = None  # type: ignore

# AssemblyAI realtime
try:
    import assemblyai as aai
except Exception:
    aai = None  # type: ignore

# OpenAI
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

# Optional HTTP client for local model proxy
try:
    import requests
except Exception:
    requests = None  # type: ignore

# For optional ElevenLabs realtime, we'll fall back if not configured
try:
    import websockets  # type: ignore
except Exception:
    websockets = None  # type: ignore

from .voice_utils import play_audio, generate_voice
from . import monitoring

logger = monitoring.get_logger("realtime")


class TTSChunker:
    """Quasi-realtime TTS: buffer streaming text deltas and speak partial chunks.

    This avoids hard-coding ElevenLabs realtime WebSocket protocol. When a
    sentence boundary or min size is reached, we synthesize that chunk and
    play immediately. This yields near-realtime speech without vendor-specific
    streaming payloads.
    """

    def __init__(self, min_chars: int = 60, sentence_delims: str = ".!?\n"):
        self.buf = []
        self.min_chars = min_chars
        self.delims = sentence_delims
        self.lock = threading.Lock()
        self.queue: Queue[str] = Queue()
        self.shutdown = threading.Event()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def add_text(self, delta: str):
        if not delta:
            return
        emit = None
        with self.lock:
            self.buf.append(delta)
            text = "".join(self.buf)
            if any(text.endswith(d) for d in self.delims) and len(text) >= self.min_chars:
                emit = text
                self.buf.clear()
        if emit:
            self.queue.put(emit)

    def flush(self):
        with self.lock:
            remaining = "".join(self.buf).strip()
            self.buf.clear()
        if remaining:
            self.queue.put(remaining)

    def _worker(self):
        while not self.shutdown.is_set():
            try:
                chunk = self.queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                # Trace: chunk about to be sent to ElevenLabs
                try:
                    display = chunk if len(chunk) < 200 else (chunk[:197] + '...')
                except Exception:
                    display = '[unrepresentable chunk]'

                logger.info(f"[STAGE: ElevenLabs] Sending chunk to TTS (len={len(chunk)}): {display}")
                monitoring.stage_start('ElevenLabs')
                try:
                    path = generate_voice(chunk)
                    monitoring.stage_end('ElevenLabs', success=True, msg=f"wrote {path}")
                    logger.info(f"[STAGE: ElevenLabs] Received TTS file: {path}")
                    play_audio(path)
                except Exception as e:
                    monitoring.stage_end('ElevenLabs', success=False, msg=str(e))
                    logger.exception(f"[TTSChunker error] {e}")
            finally:
                self.queue.task_done()

    def close(self):
        self.flush()
        self.shutdown.set()


@dataclass
class RTConfig:
    sample_rate: int = 16000
    channels: int = 1
    input_blocksize: int = 1024
    vad_silence_secs: float = 0.6


class RealtimeBot:
    """Realtime voice pipeline using AssemblyAI streaming STT and optional ElevenLabs realtime TTS.

    Fallbacks:
    - If ElevenLabs realtime isn't configured, uses non-streaming generate_voice() per message.
    - If sounddevice/AssemblyAI is unavailable, raises a clear error.
    """

    def __init__(self, on_user_text: Optional[Callable[[str], None]] = None):
        load_dotenv()
        self.cfg = RTConfig(
            sample_rate=int(os.getenv("SAMPLE_RATE", "16000")),
            channels=int(os.getenv("CHANNELS", "1")),
        )
        self.on_user_text = on_user_text

        # OpenAI client
        # Support either a local AI proxy (AI_CHAT_URL) or OpenAI API key
        self.ai_chat_url = os.getenv("AI_CHAT_URL") or None
        api_key = os.getenv("OPENAI_API_KEY")
        if not self.ai_chat_url and not api_key:
            raise RuntimeError("OPENAI_API_KEY or AI_CHAT_URL required for realtime bot.")

        self.openai = None
        if api_key:
            if OpenAI is None:
                raise RuntimeError("openai package not installed.")
            self.openai = OpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        # AssemblyAI
        if aai is None:
            raise RuntimeError("assemblyai package not installed.")
        aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY") or ""
        if not aai.settings.api_key:
            raise RuntimeError("ASSEMBLYAI_API_KEY missing for realtime bot.")

        # ElevenLabs realtime optional
        self.elevenlabs_realtime_enabled = bool(os.getenv("ELEVENLABS_VOICE_ID"))
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "")
        self.eleven_api_key = os.getenv("ELEVENLABS_API_KEY") or ""

        self.transcript_q: Queue[str] = Queue()
        self.shutdown = threading.Event()

    # --- AssemblyAI realtime ---

    def _audio_stream_thread(self, rt):
        assert sd is not None
        with sd.InputStream(
            samplerate=self.cfg.sample_rate,
            channels=self.cfg.channels,
            dtype="float32",
            blocksize=self.cfg.input_blocksize,
        ) as stream:
            while not self.shutdown.is_set():
                buf, _ = stream.read(self.cfg.input_blocksize)
                # Convert float32 [-1,1] to int16 PCM bytes for AAI
                pcm = (buf * 32767.0).astype("<i2").tobytes()
                # --- Logging: verify microphone input and buffer size ---
                try:
                    # Number of bytes and frames
                    byte_len = len(pcm)
                    bytes_per_sample = 2
                    frames = byte_len // (bytes_per_sample * max(1, self.cfg.channels))

                    # Compute a simple RMS from raw int16 samples (avoid numpy here)
                    rms = 0.0
                    try:
                        arr = array.array('h')
                        arr.frombytes(pcm)
                        if len(arr) > 0:
                            s = 0
                            for v in arr:
                                s += v * v
                            rms = math.sqrt(s / len(arr))
                        else:
                            rms = 0.0
                    except Exception:
                        rms = 0.0

                    # ASCII bar visualization (scaled)
                    try:
                        scale = int(min(50, (rms / 3000.0) * 50)) if rms > 0 else 0
                    except Exception:
                        scale = 0
                    bar = '#' * scale + '-' * (50 - scale)
                    logger.debug(f"[Mic] frames={frames} bytes={byte_len} rms={rms:.1f} |{bar}|")
                except Exception as e:
                    # Non-fatal logging error
                    logger.exception(f"[Mic logging error] {e}")

                try:
                    rt.send_audio(pcm)
                except Exception:
                    # Connection might be closed during shutdown
                    break
        try:
            rt.end()
        except Exception:
            pass

    def _on_rt_data(self, data: dict):
        # data has keys like message_type, text, confidence, etc.
        # Log every chunk received for debugging/inspection
        try:
            logger.debug(f"[AssemblyAI chunk] {data}")
        except Exception:
            logger.exception("Failed to log AssemblyAI chunk")

        mt = data.get("message_type")
        # For PartialTranscript, log and optionally surface interim text
        if mt == "PartialTranscript":
            text = (data.get("text") or "").strip()
            if text:
                # Put partials on the queue if you want real-time consumption
                # but avoid flooding downstream consumers; here we just log
                try:
                    logger.debug(f"[AssemblyAI partial] {text}")
                except Exception:
                    logger.exception("Failed to log AssemblyAI partial")

        if mt == "FinalTranscript":
            text = (data.get("text") or "").strip()
            if text:
                self.transcript_q.put(text)
                if self.on_user_text:
                    try:
                        self.on_user_text(text)
                    except Exception as e:
                        logger.exception(f"[on_user_text handler error] {e}")

    def _on_rt_error(self, err: Exception):
        logger.error(f"[Realtime STT error] {err}")

    def _on_rt_open(self, _evt: object = None) -> None:
        # Connection opened
        pass

    def _on_rt_close(self, _evt: object = None) -> None:
        # Connection closed
        pass

    # --- ElevenLabs realtime (optional) ---

    async def _elevenlabs_ws(self):  # pragma: no cover - advanced / optional
        if not (websockets and self.elevenlabs_realtime_enabled and self.voice_id and self.eleven_api_key):
            return None
        url = f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream"
        headers = [("XI-API-Key", self.eleven_api_key)]
        try:
            conn = await websockets.connect(url, extra_headers=headers)  # type: ignore[attr-defined]
            return conn
        except Exception as e:
            logger.exception(f"[ElevenLabs RT] WebSocket connect failed: {e}")
            return None

    # --- Workers ---

    def _conversation_worker(self):
        while not self.shutdown.is_set():
            try:
                text = self.transcript_q.get(timeout=0.2)
            except Empty:
                continue
            try:
                # Trace: transcript received from AssemblyAI
                try:
                    logger.debug(f"[Trace] Transcript received: {repr(text)}")
                    if not isinstance(text, str) or not text.strip():
                        logger.warning("[Trace WARNING] Transcript is empty or invalid; skipping.")
                except Exception:
                    logger.exception("Failed during transcript trace logging")

                if text.lower() in ("stop", "exit"):
                    self.shutdown.set()
                    break
                # Stream OpenAI response tokens and concatenate
                full = []
                tts_chunker: Optional[TTSChunker] = None
                try:
                    tts_chunker = TTSChunker()
                    # If a local AI proxy is configured, call it over HTTP (non-streaming)
                    if self.ai_chat_url:
                        if requests is None:
                            logger.error("AI_CHAT_URL configured but 'requests' is not installed; cannot call proxy.")
                        else:
                            try:
                                logger.info(f"[AI_PROXY] POST -> {self.ai_chat_url} (text length={len(text)})")
                                r = requests.post(self.ai_chat_url, json={"text": text}, timeout=30)
                                if not r.ok:
                                    logger.error(f"AI proxy returned status={r.status_code} text={r.text}")
                                else:
                                    reply = ""
                                    try:
                                        data = r.json()
                                        if isinstance(data, dict):
                                            reply = data.get("reply") or data.get("text") or data.get("output") or ""
                                        elif isinstance(data, str):
                                            reply = data
                                    except Exception:
                                        reply = (r.text or "").strip()
                                    reply = (reply or "").strip()
                                    if reply:
                                        # For parity with streaming, feed to chunker in sentence-sized chunks
                                        tts_chunker.add_text(reply)
                                        full.append(reply)
                            except Exception as e:
                                logger.exception(f"AI proxy request failed: {e}")
                    else:
                        # Prepare payload for logging
                        payload = {
                            'model': self.model,
                            'messages': [
                                {'role': 'system', 'content': 'You are Klarvia, a fast, concise, voice-first assistant. Respond in short sentences.'},
                                {'role': 'user', 'content': text},
                            ],
                            'stream': True,
                            'temperature': 0.6,
                            'max_tokens': 256,
                        }
                        logger.info(f"[OpenAI] Sending streaming payload: {payload}")

                        if self.openai is None:
                            logger.error("OpenAI client not configured; cannot stream responses")
                            stream = []
                        else:
                            stream = self.openai.chat.completions.create(**payload)
                        for chunk in stream:
                            # Extract delta content for various SDK shapes
                            delta = getattr(getattr(chunk.choices[0], 'delta', None), 'content', None)
                            if not delta:
                                delta = getattr(getattr(chunk.choices[0], 'message', None), 'content', None)
                            if delta:
                                full.append(delta)
                                # Quasi-realtime: speak chunks as they arrive
                                tts_chunker.add_text(delta)
                        # After streaming completes, log assembled reply
                        logger.debug(f"[OpenAI] Streaming completed. Assembled reply length={len(''.join(full))}")
                except Exception as e:
                    # Try to surface richer error info if available
                    try:
                        err_msg = str(e)
                        status = getattr(e, 'http_status', None) or getattr(e, 'status_code', None) or getattr(e, 'status', None)
                        headers = getattr(e, 'headers', None)
                        logger.error(f"[OpenAI stream error] message={err_msg} status={status} headers={headers}")
                    except Exception:
                        logger.exception(f"[OpenAI stream error] {e}")
                finally:
                    try:
                        if tts_chunker is not None:
                            tts_chunker.flush()
                            # Allow worker queue to drain a bit
                            time.sleep(0.05)
                    except Exception:
                        pass
                reply = "".join(full).strip()
                if not reply:
                    # Non-streaming fallback
                    try:
                        payload = {
                            'model': self.model,
                            'messages': [
                                {'role': 'system', 'content': 'You are Klarvia, a fast, concise, voice-first assistant. Respond in short sentences.'},
                                {'role': 'user', 'content': text},
                            ],
                            'temperature': 0.6,
                            'max_tokens': 256,
                        }
                        logger.info(f"[OpenAI] Sending payload: {payload}")
                        if self.openai is None:
                            logger.error("OpenAI client not configured; cannot request completion")
                            resp = None
                        else:
                            resp = self.openai.chat.completions.create(**payload)
                        # Log the raw response object then extract message
                        try:
                            logger.debug(f"[OpenAI] Raw response: {resp}")
                        except Exception:
                            logger.exception("Failed to log raw OpenAI response")
                        try:
                            m = getattr(getattr(resp.choices[0], 'message', None), 'content', '') if resp else ''
                        except Exception:
                            m = ''
                        if m:
                            reply = m
                    except Exception:
                        logger.exception("[OpenAI fallback] request failed")

                # Speak full reply if any
                if reply:
                    try:
                        path = generate_voice(reply)
                        play_audio(path)
                    except Exception:
                        logger.exception("[TTS fallback] failed to synthesize speech")
            finally:
                self.transcript_q.task_done()

    def run(self):
        if aai is None:
            raise RuntimeError("assemblyai package not available")
        if sd is None:
            raise RuntimeError("sounddevice package not available")
        transcriber = aai.RealtimeTranscriber(
            sample_rate=self.cfg.sample_rate,
            on_data=self._on_rt_data,
            on_error=self._on_rt_error,
            on_open=self._on_rt_open,
            on_close=self._on_rt_close,
        )
        transcriber.connect()

        # Start audio producer and consumer workers
        t1 = threading.Thread(target=self._audio_stream_thread, args=(transcriber,), daemon=True)
        t1.start()
        t2 = threading.Thread(target=self._conversation_worker, daemon=True)
        t2.start()
        try:
            while not self.shutdown.is_set():
                time.sleep(0.2)
        except KeyboardInterrupt:
            self.shutdown.set()
        finally:
            try:
                transcriber.close()
            except Exception:
                pass
            t1.join(timeout=1.0)
            t2.join(timeout=1.0)
