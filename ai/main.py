"""
Minimal dependency-free ASGI app for uvicorn.

Adds simple WebSocket endpoints to support the React voice UI:
- GET  /health         -> { status: "ok" }
- POST /chat           -> { reply: string }
- GET  /config         -> { stt_backend: "file" | "assemblyai" }
- GET  /ws-token       -> { token: string } (dev helper)
- WS   /ws/audio       -> Accepts a single audio blob (audio/webm;codecs=opus),
                          transcribes with AssemblyAI, gets a model reply, TTS,
                          then sends back JSON events and a final binary audio frame.

Notes:
- This is intentionally simple and avoids realtime opus->PCM decoding.
- The frontend defaults to non-streaming mode unless /config says otherwise.
"""

import json
import os
import tempfile
import secrets
import asyncio
import time
from typing import Callable, Awaitable, Dict, Any, List, Optional

# Optional helpers for the pipeline
try:
    from voicebot.conversation import transcribe_audio as _transcribe_audio, handle_conversation as _handle_conversation
    from voicebot.voice_utils import generate_voice as _generate_voice
except Exception:
    _transcribe_audio = None  # type: ignore
    _handle_conversation = None  # type: ignore
    _generate_voice = None  # type: ignore

# Optional transcript normalization
try:
    from voicebot.conversation import normalize_transcript as _normalize_transcript  # type: ignore
except Exception:
    _normalize_transcript = None  # type: ignore

# Monitoring (timestamps/latency logging)
try:
    from voicebot import monitoring  # type: ignore
except Exception:
    monitoring = None  # type: ignore

# Optional OpenAI client for streaming replies
try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None  # type: ignore

# Ephemeral WebSocket token (dev convenience) resolved at import
_WS_TOKEN: str = os.getenv("WS_AUTH_TOKEN", "") or secrets.token_urlsafe(16)


async def _tts_worker(queue: "asyncio.Queue[Optional[str]]", send_ws, monitoring_mod) -> None:
    """Background worker: consumes text chunks, synthesizes with ElevenLabs, sends audio bytes."""
    while True:
        text = await queue.get()
        if text is None:
            queue.task_done()
            break
        try:
            if not text.strip():
                continue
            # Stage per chunk for visibility
            if monitoring_mod:
                try:
                    monitoring_mod.stage_start("TTS_CHUNK")
                except Exception:
                    pass
            # Generate voice in thread, then read bytes
            out_path = await asyncio.to_thread(_generate_voice, text)  # type: ignore[arg-type]
            audio_bytes = await asyncio.to_thread(lambda p=out_path: open(p, "rb").read())
            if audio_bytes:
                await send_ws({"type": "websocket.send", "bytes": audio_bytes})
            if monitoring_mod:
                try:
                    monitoring_mod.stage_end("TTS_CHUNK", success=True, msg=f"bytes={len(audio_bytes) if audio_bytes else 0}")
                except Exception:
                    pass
        except Exception as e:
            if monitoring_mod:
                try:
                    monitoring_mod.stage_end("TTS_CHUNK", success=False, msg=str(e))
                except Exception:
                    pass
        finally:
            queue.task_done()


async def _read_body(receive) -> bytes:
    body = b""
    more = True
    while more:
        message = await receive()
        if message["type"] != "http.request":
            continue
        body += message.get("body", b"")
        more = message.get("more_body", False)
    return body


async def app(scope: Dict[str, Any], receive: Callable[[], Awaitable[Dict[str, Any]]], send: Callable[[Dict[str, Any]], Awaitable[None]]):
    # --- WebSocket handling ---
    if scope["type"] == "websocket":
        path = scope.get("path", "/")
        query_bytes: bytes = scope.get("query_string", b"") or b""
        query_str = query_bytes.decode("utf-8", errors="ignore")
        query: Dict[str, str] = {}
        if query_str:
            for part in query_str.split("&"):
                if not part:
                    continue
                if "=" in part:
                    k, v = part.split("=", 1)
                else:
                    k, v = part, ""
                query[k] = v

        # Simple token auth (optional)
        ws_token: Optional[str] = os.getenv("WS_AUTH_TOKEN", "") or _WS_TOKEN

        # If a token is configured, enforce it via query param `token`
        if ws_token:
            supplied = query.get("token", "")
            if supplied != ws_token:
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": "Unauthorized"})})
                await send({"type": "websocket.close", "code": 4401})
                return

        # Streaming endpoint: expects raw PCM int16 little-endian frames (mono, 16000 Hz)
        # Sends back {type:"partial", text}, then {type:"final", text}, then reply+audio.
        if path == "/ws/audio-stream":
            await send({"type": "websocket.accept"})
            # Lazy import AssemblyAI to keep base app dependency-light
            fake_stt = False
            try:
                import assemblyai as aai  # type: ignore
            except Exception as e:
                aai = None  # type: ignore
            # Respect FAKE_STT env to force local dev STT even if assemblyai is installed
            if os.getenv("FAKE_STT", "") in ("1", "true", "True"):
                fake_stt = True
                aai = None  # type: ignore

            api_key = os.getenv("ASSEMBLYAI_API_KEY") or ""
            if not api_key and not fake_stt:
                await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": "ASSEMBLYAI_API_KEY missing"})})
                await send({"type": "websocket.close", "code": 1011})
                return
            if not fake_stt:
                aai.settings.api_key = api_key

            # Queue for callback-to-WS messages
            from queue import Queue, Empty
            outbound: "Queue[dict]" = Queue()

            # Latency markers
            t_first_byte: Optional[float] = None
            t_first_partial: Optional[float] = None
            t_final_seen: Optional[float] = None

            # Allow runtime fallback to fake STT if provider errors (e.g., deprecated model)
            fallback_to_fake = False

            def _on_data(evt: dict):
                try:
                    mt = evt.get("message_type")
                    if mt == "PartialTranscript":
                        text = (evt.get("text") or "").strip()
                        if text:
                            nonlocal t_first_partial, t_first_byte
                            if t_first_partial is None:
                                t_first_partial = time.time()
                                try:
                                    if t_first_byte is not None:
                                        latency_ms = int((t_first_partial - t_first_byte) * 1000)
                                        outbound.put({"type": "debug", "stage": "stt_first_partial", "latency_ms": latency_ms})
                                except Exception:
                                    pass
                            outbound.put({"type": "partial", "text": text})
                    elif mt == "FinalTranscript":
                        text = (evt.get("text") or "").strip()
                        if text:
                            nonlocal t_final_seen
                            t_final_seen = time.time()
                            outbound.put({"type": "final", "text": text})
                except Exception:
                    pass

            def _on_error(e: Exception):
                try:
                    msg = str(e)
                    outbound.put({"type": "error", "message": msg})
                    # If the provider indicates a deprecated/invalid model, fall back to fake STT so UI keeps working
                    nonlocal fallback_to_fake
                    low = msg.lower()
                    if ("deprecated" in low) or ("universal" in low and "use" in low):
                        fallback_to_fake = True
                        try:
                            outbound.put({"type": "debug", "stage": "stt_fallback", "reason": msg})
                        except Exception:
                            pass
                except Exception:
                    pass

            # Create transcriber (or fake STT emitter in dev)
            rt = None
            fake_started = False
            fake_task = None
            audio_q: "asyncio.Queue[int]" = asyncio.Queue()
            client_done = asyncio.Event()
            async def _fake_emitter(out_queue: "Queue[dict]", aq: "asyncio.Queue[int]", done_evt: asyncio.Event):
                """Emit partials paced by incoming audio length.

                - Convert bytes -> ms at 16kHz, 16-bit mono.
                - Every ~250ms of ingested audio, unlock one more word.
                - When all words unlocked and either client signals done or idle > 300ms, emit final.
                """
                nonlocal t_first_partial, t_final_seen, t_first_byte
                words = ["Hello", "Klarvia", "I", "have", "a", "headache"]
                built_count = 0
                ingested_ms = 0.0
                last_in_ms = 0.0
                last_bytes_seen = time.time()
                per_word_ms = 250.0
                idle_final_ms = 0.3
                sent_final = False

                def bytes_to_ms(n: int) -> float:
                    # 2 bytes per sample @ 16kHz
                    return (n / 2.0) / 16000.0 * 1000.0

                try:
                    while not sent_final:
                        try:
                            n = await asyncio.wait_for(aq.get(), timeout=0.05)
                            if n and n > 0:
                                ingested_ms += bytes_to_ms(n)
                                last_in_ms = ingested_ms
                                last_bytes_seen = time.time()
                        except asyncio.TimeoutError:
                            pass

                        # Allow more words based on ingested audio time
                        allow = min(int(ingested_ms // per_word_ms), len(words))
                        if allow > built_count:
                            built_count = allow
                            text = " ".join(words[:built_count])
                            try:
                                if t_first_partial is None and t_first_byte is not None:
                                    t_first_partial = time.time()
                                    lat_ms = int((t_first_partial - t_first_byte) * 1000)
                                    out_queue.put({"type": "debug", "stage": "stt_first_partial", "latency_ms": lat_ms})
                                out_queue.put({"type": "partial", "text": text})
                            except Exception:
                                pass

                        # Finalization conditions
                        all_words = (built_count >= len(words))
                        idle = (time.time() - last_bytes_seen) if last_bytes_seen else 0.0
                        if all_words and (done_evt.is_set() or idle >= idle_final_ms):
                            final_text = " ".join(words)
                            try:
                                t_final_seen = time.time()
                                out_queue.put({"type": "final", "text": final_text})
                            except Exception:
                                pass
                            sent_final = True
                            break

                        # Small pacing delay to avoid tight loop
                        await asyncio.sleep(0.01)
                except Exception:
                    # On any failure, try to deliver whatever we have
                    try:
                        if built_count > 0:
                            out_queue.put({"type": "final", "text": " ".join(words[:built_count])})
                    except Exception:
                        pass

            if not fake_stt:
                try:
                    # Use AssemblyAI's Universal Streaming model when supported
                    _kwargs = {
                        "sample_rate": 16000,
                        "on_data": _on_data,
                        "on_error": _on_error,
                    }
                    # Hint model/language via kwargs (ignored by older SDKs)
                    try:
                        _kwargs.update({
                            "model": "universal-2",
                            "language_code": os.getenv("STT_LANGUAGE", "en"),
                        })
                        rt = aai.RealtimeTranscriber(**_kwargs)  # type: ignore[attr-defined]
                    except TypeError:
                        # Fallback for older SDK signatures
                        _kwargs.pop("model", None)
                        _kwargs.pop("language_code", None)
                        rt = aai.RealtimeTranscriber(**_kwargs)  # type: ignore[attr-defined]
                    # Some SDKs offer connect(); ignore typing complaints
                    getattr(rt, "connect", lambda: None)()  # type: ignore[attr-defined]
                except Exception as e:
                    await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": f"AAI connect failed: {e}"})})
                    await send({"type": "websocket.close", "code": 1011})
                    return

            got_final_text = ""
            stt_stage = None
            if monitoring:
                stt_stage = "STT"
                try:
                    monitoring.stage_start(stt_stage)
                except Exception:
                    pass
            try:
                while True:
                    # First, drain outbound queue to client
                    try:
                        while True:
                            msg = outbound.get_nowait()
                            # Track final text if seen
                            if msg.get("type") == "final":
                                final_text = msg.get("text") or ""
                                # Normalize known ASR mistakes (e.g., brand names)
                                try:
                                    if _normalize_transcript is not None and final_text:
                                        norm = _normalize_transcript(final_text)
                                        if norm != final_text:
                                            await send({"type": "websocket.send", "text": json.dumps({"type": "debug", "stage": "normalize", "raw": final_text, "normalized": norm})})
                                        final_text = norm
                                except Exception:
                                    pass
                                got_final_text = final_text or got_final_text
                                # STT complete: end stage
                                if monitoring and stt_stage:
                                    try:
                                        monitoring.stage_end(stt_stage, success=True, msg=f"len={len(got_final_text)}")
                                    except Exception:
                                        pass
                            await send({"type": "websocket.send", "text": json.dumps(msg)})
                    except Empty:
                        pass

                    # Then, receive input frame or control text
                    event = None
                    try:
                        event = await receive()
                    except Exception:
                        event = None

                    if event is None:
                        continue

                    if event["type"] == "websocket.receive":
                        if event.get("bytes") is not None:
                            # Raw PCM frame
                            try:
                                if t_first_byte is None:
                                    t_first_byte = time.time()
                                if fake_stt or fallback_to_fake:
                                    # Feed bytes to fake emitter; start it on first frame
                                    try:
                                        await audio_q.put(len(event["bytes"]))
                                    except Exception:
                                        pass
                                    if not fake_started:
                                        try:
                                            fake_task = asyncio.create_task(_fake_emitter(outbound, audio_q, client_done))
                                            fake_started = True
                                        except Exception:
                                            pass
                                else:
                                    send_audio = getattr(rt, "send_audio", None)
                                    if callable(send_audio):
                                        send_audio(event["bytes"])  # type: ignore[misc]
                            except Exception:
                                # Ignore send errors; client may stop soon
                                pass
                        elif event.get("text"):
                            try:
                                payload = json.loads(event["text"]) if event["text"].startswith("{") else {}
                            except Exception:
                                payload = {}
                            if payload.get("type") in ("stop", "end"):
                                try:
                                    end_fn = getattr(rt, "end", None)
                                    if callable(end_fn):
                                        end_fn()
                                except Exception:
                                    pass
                                try:
                                    client_done.set()
                                except Exception:
                                    pass
                                break
                    elif event["type"] == "websocket.disconnect":
                        try:
                            client_done.set()
                        except Exception:
                            pass
                        break

                # After stop, drain final messages briefly
                # If using fake STT, give it a brief moment to flush final
                if fake_task is not None:
                    try:
                        await asyncio.wait_for(fake_task, timeout=0.75)
                    except Exception:
                        pass

                for _ in range(20):
                    try:
                        msg = outbound.get_nowait()
                        if msg.get("type") == "final":
                            got_final_text = msg.get("text") or got_final_text
                        await send({"type": "websocket.send", "text": json.dumps(msg)})
                    except Empty:
                        break

                # Model + TTS for the final transcript (local-first)
                reply = ""
                if got_final_text:
                    model_stage = "Model"
                    if monitoring:
                        try:
                            monitoring.stage_start(model_stage)
                        except Exception:
                            pass
                    # Prefer local pipeline (KLARVIA_MODEL_CMD or klarvia_voice_bot.infer via handle_conversation).
                    if _handle_conversation is not None:
                        try:
                            reply = await asyncio.to_thread(_handle_conversation, got_final_text)
                            reply = reply or ""
                            if monitoring:
                                try:
                                    monitoring.stage_end(model_stage, success=True, msg=f"len={len(reply)} (local-first)")
                                except Exception:
                                    pass
                        except Exception as e:
                            if monitoring:
                                try:
                                    monitoring.stage_end(model_stage, success=False, msg=str(e))
                                except Exception:
                                    pass
                            reply = ""
                    # Emit debug timings snapshot
                    if monitoring:
                        try:
                            await send({"type": "websocket.send", "text": json.dumps({"type": "debug", "stage": "timings", "data": monitoring.debug_report()})})
                        except Exception:
                            pass
                    # Also emit first-partial and final latencies if captured
                    try:
                        if t_first_byte and t_first_partial:
                            await send({"type": "websocket.send", "text": json.dumps({
                                "type": "debug",
                                "stage": "stt_first_partial",
                                "latency_ms": int((t_first_partial - t_first_byte) * 1000)
                            })})
                        if t_first_byte and t_final_seen:
                            await send({"type": "websocket.send", "text": json.dumps({
                                "type": "debug",
                                "stage": "stt_final",
                                "latency_ms": int((t_final_seen - t_first_byte) * 1000)
                            })})
                    except Exception:
                        pass
                if not reply and got_final_text:
                    reply = f"You said: {got_final_text}"
                await send({"type": "websocket.send", "text": json.dumps({"type": "reply", "text": reply})})

                audio_bytes = b""
                if reply and _generate_voice is not None:
                    tts_stage = "TTS"
                    if monitoring:
                        try:
                            monitoring.stage_start(tts_stage)
                        except Exception:
                            pass
                    try:
                        out_path = await asyncio.to_thread(_generate_voice, reply)
                        audio_bytes = await asyncio.to_thread(lambda p=out_path: open(p, "rb").read())
                        if monitoring:
                            try:
                                monitoring.stage_end(tts_stage, success=True, msg=f"bytes={len(audio_bytes)}")
                            except Exception:
                                pass
                    except Exception as e:
                        if monitoring:
                            try:
                                monitoring.stage_end(tts_stage, success=False, msg=str(e))
                            except Exception:
                                pass
                        audio_bytes = b""
                if audio_bytes:
                    await send({"type": "websocket.send", "bytes": audio_bytes})
                    try:
                        await send({"type": "websocket.send", "text": json.dumps({"type": "debug", "stage": "tts_bytes", "bytes": len(audio_bytes)})})
                    except Exception:
                        pass

                await send({"type": "websocket.close", "code": 1000})
                return
            finally:
                try:
                    if not fake_stt:
                        close_fn = getattr(rt, "close", None)
                        if callable(close_fn):
                            close_fn()
                except Exception:
                    pass

        # Non-streaming endpoint
        if path == "/ws/audio":
            await send({"type": "websocket.accept"})
            # Accumulate binary frames until a text {type:end} or close
            chunks: List[bytes] = []
            tmp_path: Optional[str] = None
            try:
                while True:
                    event = await receive()
                    if event["type"] == "websocket.receive":
                        if "bytes" in event and event["bytes"] is not None:
                            chunks.append(event["bytes"])  # webm bytes
                            # In non-streaming mode, a single blob is expected; proceed immediately
                            break
                        elif "text" in event and event["text"]:
                            # End-of-input marker
                            try:
                                payload = json.loads(event["text"]) if event["text"].startswith("{") else {}
                            except Exception:
                                payload = {}
                            if payload.get("type") in ("end", "stop"):
                                break
                    elif event["type"] == "websocket.disconnect":
                        break

                # Process the received audio
                if not chunks:
                    await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": "No audio received"})})
                    await send({"type": "websocket.close", "code": 1000})
                    return

                # Write to a temp .webm file
                fd, tmp_path = tempfile.mkstemp(suffix=".webm")
                with os.fdopen(fd, "wb") as f:
                    for c in chunks:
                        f.write(c)

                # Transcribe (offload to thread)
                transcript = ""
                if _transcribe_audio is None:
                    # Fallback: no STT available
                    transcript = ""
                else:
                    stt_stage = "STT"
                    if monitoring:
                        try:
                            monitoring.stage_start(stt_stage)
                        except Exception:
                            pass
                    try:
                        transcript = await asyncio.to_thread(_transcribe_audio, tmp_path)
                        transcript = transcript or ""
                        if monitoring:
                            try:
                                monitoring.stage_end(stt_stage, success=True, msg=f"len={len(transcript)}")
                            except Exception:
                                pass
                    except Exception as e:
                        transcript = ""
                        # Inform client of the failure, but continue to try model on empty text
                        await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": f"transcription failed: {e}"})})
                        if monitoring:
                            try:
                                monitoring.stage_end(stt_stage, success=False, msg=str(e))
                            except Exception:
                                pass

                if transcript:
                    await send({"type": "websocket.send", "text": json.dumps({"type": "final", "text": transcript})})

                # Model reply (non-streaming path). Prefer local-first via handle_conversation.
                reply = ""
                if transcript:
                    model_stage = "Model"
                    if monitoring:
                        try:
                            monitoring.stage_start(model_stage)
                        except Exception:
                            pass
                    if _handle_conversation is not None:
                        try:
                            reply = await asyncio.to_thread(_handle_conversation, transcript)
                            reply = reply or ""
                            if monitoring:
                                try:
                                    monitoring.stage_end(model_stage, success=True, msg=f"len={len(reply)} (local-first)")
                                except Exception:
                                    pass
                        except Exception as e:
                            if monitoring:
                                try:
                                    monitoring.stage_end(model_stage, success=False, msg=str(e))
                                except Exception:
                                    pass
                            reply = ""

                # Emit timings snapshot after model stage
                if monitoring:
                    try:
                        await send({"type": "websocket.send", "text": json.dumps({"type": "debug", "stage": "timings", "data": monitoring.debug_report()})})
                    except Exception:
                        pass

                if not reply and transcript:
                    reply = f"You said: {transcript}"
                elif not reply and not transcript:
                    reply = "I couldn't hear anything. Please try again."

                await send({"type": "websocket.send", "text": json.dumps({"type": "reply", "text": reply})})

                # TTS
                audio_bytes: Optional[bytes] = None
                if _generate_voice is not None and reply:
                    tts_stage = "TTS"
                    if monitoring:
                        try:
                            monitoring.stage_start(tts_stage)
                        except Exception:
                            pass
                    try:
                        out_path = await asyncio.to_thread(_generate_voice, reply)
                        # Read and send bytes (as wav by default)
                        audio_bytes = await asyncio.to_thread(lambda p=out_path: open(p, "rb").read())
                        if monitoring:
                            try:
                                monitoring.stage_end(tts_stage, success=True, msg=f"bytes={len(audio_bytes or b'')} ")
                            except Exception:
                                pass
                    except Exception as e:
                        if monitoring:
                            try:
                                monitoring.stage_end(tts_stage, success=False, msg=str(e))
                            except Exception:
                                pass
                        audio_bytes = None

                if audio_bytes:
                    await send({"type": "websocket.send", "bytes": audio_bytes})
                    try:
                        await send({"type": "websocket.send", "text": json.dumps({"type": "debug", "stage": "tts_bytes", "bytes": len(audio_bytes or b'')})})
                    except Exception:
                        pass

                await send({"type": "websocket.close", "code": 1000})
                return
            finally:
                try:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

        # Unknown WS path
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": "Unknown WebSocket path"})})
        await send({"type": "websocket.close", "code": 1008})
        return

    # --- HTTP handling ---
    if scope["type"] != "http":
        await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"Not Found"})
        return

    path = scope.get("path", "/")
    method = scope.get("method", "GET").upper()

    # CORS preflight
    if method == "OPTIONS":
        await send({
            "type": "http.response.start",
            "status": 204,
            "headers": [
                (b"access-control-allow-origin", b"*"),
                (b"access-control-allow-methods", b"POST, GET, OPTIONS"),
                (b"access-control-allow-headers", b"content-type"),
            ],
        })
        await send({"type": "http.response.body", "body": b""})
        return

    if path == "/health" and method == "GET":
        payload = json.dumps({"status": "ok"}).encode()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"access-control-allow-origin", b"*"),
            ],
        })
        await send({"type": "http.response.body", "body": payload})
        return

    if path == "/config" and method == "GET":
        # Advertise STT backend based on available API key or dev-mode FAKE_STT
        stt = "assemblyai" if ((os.getenv("ASSEMBLYAI_API_KEY") or "") or (os.getenv("FAKE_STT") in ("1","true","True"))) else "file"
        payload = json.dumps({"stt_backend": stt}).encode()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"access-control-allow-origin", b"*"),
            ],
        })
        await send({"type": "http.response.body", "body": payload})
        return

    if path == "/ws-token" and method == "GET":
        token = os.getenv("WS_AUTH_TOKEN", "") or _WS_TOKEN
        payload = json.dumps({"token": token}).encode()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"access-control-allow-origin", b"*"),
            ],
        })
        await send({"type": "http.response.body", "body": payload})
        return

    if path == "/chat" and method == "POST":
        body = await _read_body(receive)
        try:
            data = json.loads(body.decode() or "{}")
        except Exception:
            data = {}
        text = (data.get("text") or "").strip()
        # Apply optional normalization for brand/name misrecognitions even in /chat
        try:
            if _normalize_transcript is not None and text:
                norm = _normalize_transcript(text)
                if norm != text:
                    print("[ai.chat] normalize:", {"raw": text, "normalized": norm})
                text = norm
        except Exception:
            pass
        if not text:
            payload = json.dumps({"error": "text is required"}).encode()
            await send({
                "type": "http.response.start",
                "status": 400,
                "headers": [(b"content-type", b"application/json"), (b"access-control-allow-origin", b"*")],
            })
            await send({"type": "http.response.body", "body": payload})
            return

        # Prefer a pluggable local model if configured:
        reply = None
        # 1) If KLARVIA_MODEL_CMD is set, run it as a subprocess and pass text on stdin
        cmd = os.getenv("KLARVIA_MODEL_CMD")
        if cmd:
            try:
                import subprocess
                p = subprocess.run(cmd, input=text.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, timeout=30)
                if p.returncode == 0:
                    reply = p.stdout.decode().strip()
                else:
                    # log stderr
                    print("klarvia model cmd error:", p.stderr.decode())
            except Exception as e:
                print("klarvia model cmd failed:", e)

        # 2) Prefer voicebot.conversation (supports AI_CHAT_URL/OpenAI) before the local shim
        if reply is None:
            ai_chat_url = os.getenv("AI_CHAT_URL") or ""
            openai_key = os.getenv("OPENAI_API_KEY") or ""
            try:
                # Only attempt this path if at least one backend is configured to avoid noisy errors
                if ai_chat_url or openai_key:
                    from voicebot.conversation import handle_conversation
                    try:
                        reply = handle_conversation(text)
                        if reply:
                            print("[ai.chat] backend=voicebot.conversation (ai_chat_url=" + str(bool(ai_chat_url)) + ", openai=" + str(bool(openai_key)) + ")")
                    except Exception as e:
                        print("voicebot.conversation error:", e)
            except Exception:
                pass

        # 3) If a Python module `klarvia_voice_bot` provides an `infer(text)` function, use it (may be a stub)
        if reply is None:
            try:
                import importlib
                mod = importlib.import_module("klarvia_voice_bot")
                infer = getattr(mod, "infer", None)
                if callable(infer):
                    try:
                        out = infer(text)
                        if isinstance(out, str):
                            reply = out.strip()
                            if reply:
                                print("[ai.chat] backend=klarvia_voice_bot.infer")
                    except Exception as e:
                        print("klarvia_voice_bot.infer error:", e)
            except ModuleNotFoundError:
                pass

        # 4) Fallback: echo
        if not reply:
            reply = f"You said: {text}"
        payload = json.dumps({"reply": reply}).encode()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json"), (b"access-control-allow-origin", b"*")],
        })
        await send({"type": "http.response.body", "body": payload})
        return

    await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"text/plain"), (b"access-control-allow-origin", b"*") ]})
    await send({"type": "http.response.body", "body": b"Not Found"})
