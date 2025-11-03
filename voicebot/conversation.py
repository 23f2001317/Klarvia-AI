import os
import time
from typing import List, Optional
from queue import Queue
import subprocess
import wave

from dotenv import load_dotenv
from . import monitoring

logger = monitoring.get_logger("conversation")

# HTTP client for local model proxy
try:
    import requests
except Exception:
    requests = None  # type: ignore

# OpenAI SDK v1+
try:
    from openai import OpenAI
except Exception:  # pragma: no cover - SDK not installed yet
    OpenAI = None  # type: ignore

# AssemblyAI SDK
try:
    import assemblyai as aai
except Exception:  # pragma: no cover
    aai = None  # type: ignore


class ConversationManager:
    """Chat manager using either a local HTTP proxy or OpenAI, without hard dependency on OpenAI.

    - If AI_CHAT_URL is set, uses that endpoint first.
    - Else, if OPENAI_API_KEY is set, uses OpenAI Chat Completions.
    - Else, it will return empty string (caller should fallback).
    """

    def __init__(self, system_prompt: Optional[str] = None):
        load_dotenv()
        self.ai_chat_url = os.getenv("AI_CHAT_URL") or None
        api_key = os.getenv("OPENAI_API_KEY") or None

        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.client = None
        if api_key:
            if OpenAI is None:  # pragma: no cover
                raise RuntimeError("openai package not available. Install dependencies from requirements.txt")
            self.client = OpenAI(api_key=api_key)

        self.messages = []
        default_system = (
            "You are Klarvia, a friendly and concise voice AI assistant. "
            "Answer clearly and keep responses short for text-to-speech."
        )
        self.system_prompt = system_prompt or default_system
        self.messages.append({"role": "system", "content": self.system_prompt})

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def get_response(self, content: str, max_tokens: int = 256) -> str:
        self.add_user(content)
        payload = {
            "model": self.model,
            "messages": self.messages,
            "max_tokens": max_tokens,
            "temperature": 0.6,
        }

        # Prefer local proxy
        if self.ai_chat_url:
            if requests is None:
                logger.error("AI_CHAT_URL is set but 'requests' is not installed in the environment.")
                return ""
            try:
                r = requests.post(self.ai_chat_url, json={"text": content}, timeout=30)
                text = ""
                if r.ok:
                    try:
                        data = r.json()
                        if isinstance(data, dict):
                            text = data.get("reply") or data.get("text") or data.get("output") or ""
                        elif isinstance(data, str):
                            text = data
                    except Exception:
                        text = (r.text or "")
                else:
                    logger.error(f"[ConversationManager] AI proxy returned status={r.status_code} text={r.text}")
                text = (text or "").strip()
                if text:
                    self.add_assistant(text)
                return text
            except Exception as e:
                logger.exception(f"[ConversationManager] AI proxy request failed: {e}")
                return ""

        # Fallback to OpenAI if configured
        try:
            if self.client is None:
                logger.warning("OpenAI client not configured; skipping OpenAI path")
                return ""
            resp = self.client.chat.completions.create(**payload)
            try:
                text = resp.choices[0].message.content or ""
            except Exception:
                text = getattr(getattr(resp.choices[0], "message", None), "content", "") or getattr(
                    getattr(resp.choices[0], "delta", None), "content", ""
                ) or ""
            self.add_assistant(text)
            return text
        except Exception as e:
            try:
                err_msg = str(e)
                status = getattr(e, "http_status", None) or getattr(e, "status_code", None) or getattr(e, "status", None)
                headers = getattr(e, "headers", None)
                logger.error(f"[ConversationManager OpenAI error] message={err_msg} status={status} headers={headers}")
            except Exception:
                logger.exception(f"[ConversationManager OpenAI error] {e}")
            return ""


# Global transcript queue for downstream consumers
TRANSCRIPTS: "Queue[str]" = Queue()


def transcribe_audio(file_path: str) -> str:
    """Transcribe an audio file using AssemblyAI and enqueue the result.

    Returns the transcript text (empty string on failure).
    """
    load_dotenv()

    if aai is None:
        raise RuntimeError("assemblyai package not available. Install dependencies from requirements.txt")

    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY is missing in environment.")
    aai.settings.api_key = api_key

    # Optional: basic file info logging and monitoring
    try:
        size = os.path.getsize(file_path)
    except Exception:
        size = None
    try:
        with wave.open(file_path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            duration = frames / float(rate) if rate else None
    except Exception:
        frames = rate = duration = None

    stage = "AssemblyAI"
    try:
        monitoring.stage_start(stage)
    except Exception:
        pass

    try:
        logger.info(
            f"[STT] Transcribing {file_path} size={size} frames={frames} sr={rate} duration={duration}"
        )
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(file_path)
        if getattr(transcript, "error", None):
            try:
                monitoring.stage_end(stage, success=False, msg=str(getattr(transcript, "error")))
            except Exception:
                pass
            return ""
        raw_text = transcript.text or ""
        text = normalize_transcript(raw_text)
        if text:
            TRANSCRIPTS.put(text)
        try:
            monitoring.stage_end(stage, success=True, msg=f"len={len(text)}")
        except Exception:
            pass
        if raw_text and raw_text != text:
            logger.info(f"[STT normalize] raw='{raw_text}' -> normalized='{text}'")
        return text
    except Exception as e:
        try:
            monitoring.stage_end(stage, success=False, msg=str(e))
        except Exception:
            pass
        return ""


def get_transcript_queue() -> Queue:
    """Expose the transcript queue for consumers."""
    return TRANSCRIPTS


# Module-level singleton for conversation handling
_CONVO: Optional[ConversationManager] = None


def _get_conversation_manager() -> ConversationManager:
    global _CONVO
    if _CONVO is None:
        _CONVO = ConversationManager()
    return _CONVO


def handle_conversation(transcript: str) -> str:
    """Local-first conversation handler.

    Order:
    1) KLARVIA_MODEL_CMD (subprocess stdin->stdout)
    2) AI_CHAT_URL (HTTP POST {text})
    3) klarvia_voice_bot.infer(text)
    4) OpenAI via ConversationManager
    Returns "" on total failure (caller may echo transcript or handle otherwise).
    """
    if not isinstance(transcript, str):
        transcript = str(transcript)
    if not transcript.strip():
        return ""

    # 1) KLARVIA_MODEL_CMD
    cmd = os.getenv("KLARVIA_MODEL_CMD")
    if cmd:
        try:
            p = subprocess.run(
                cmd,
                input=transcript.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                timeout=30,
            )
            if p.returncode == 0:
                out = p.stdout.decode("utf-8", errors="ignore").strip()
                if out:
                    return out
            else:
                try:
                    err = p.stderr.decode("utf-8", errors="ignore").strip()
                except Exception:
                    err = str(p.stderr)
                logger.error("KLARVIA model command error: %s", err)
        except Exception as e:
            logger.exception("KLARVIA model command failed: %s", e)

    # 2) AI_CHAT_URL proxy
    ai_chat_url = os.getenv("AI_CHAT_URL")
    if ai_chat_url:
        stage = "Model_AI_CHAT_URL"
        try:
            monitoring.stage_start(stage)
        except Exception:
            pass
        try:
            if requests is None:
                logger.error("AI_CHAT_URL is set but 'requests' is not installed.")
            else:
                r = requests.post(ai_chat_url, json={"text": transcript}, timeout=30)
                if r.ok:
                    try:
                        data = r.json()
                        if isinstance(data, dict):
                            out = (data.get("reply") or data.get("text") or data.get("output") or "").strip()
                        elif isinstance(data, str):
                            out = data.strip()
                        else:
                            out = (r.text or "").strip()
                    except Exception:
                        out = (r.text or "").strip()
                    try:
                        monitoring.stage_end(stage, success=True, msg=f"len={len(out)}")
                    except Exception:
                        pass
                    return out
                else:
                    logger.error(f"AI proxy returned status={r.status_code} text={r.text}")
        except Exception as e:
            logger.exception(f"AI proxy request failed: {e}")
        try:
            monitoring.stage_end(stage, success=False, msg="AI_CHAT_URL failed")
        except Exception:
            pass

    # 3) Python shim module
    try:
        import importlib
        mod = importlib.import_module("klarvia_voice_bot")
        infer = getattr(mod, "infer", None)
        if callable(infer):
            try:
                out = infer(transcript)
                if isinstance(out, str):
                    out = out.strip()
                    if out:
                        return out
            except Exception as e:
                logger.exception("klarvia_voice_bot.infer error: %s", e)
    except ModuleNotFoundError:
        pass
    except Exception as e:
        logger.exception("klarvia_voice_bot import error: %s", e)

    # 4) OpenAI via ConversationManager
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        stage = "Model_OpenAI"
        try:
            monitoring.stage_start(stage)
        except Exception:
            pass
        cm = _get_conversation_manager()
        ai_response: str = cm.get_response(transcript)
        try:
            monitoring.stage_end(stage, success=True, msg=f"len={len(ai_response or '')}")
        except Exception:
            pass
        return ai_response

    return ""


def normalize_transcript(text: str) -> str:
    """Normalize known misrecognitions (e.g., brand name variants) to "Klarvia".

    Applies case-insensitive word-boundary replacements for common variants.
    """
    if not text:
        return text
    import re
    variants = [
        "claria",
        "glaria",
        "glarvia",
        "clarvia",
        "clavia",
        "klaria",
        "klavia",
    ]
    out = text
    for wrong in variants:
        out = re.sub(rf"\b{re.escape(wrong)}\b", "Klarvia", out, flags=re.IGNORECASE)
    return out
