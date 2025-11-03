import json
import os
import tempfile
import secrets
import asyncio
import time
from typing import Callable, Awaitable, Dict, Any, List, Optional


try:
    from voicebot.conversation import transcribe_audio as _transcribe_audio, handle_conversation as _handle_conversation
    from voicebot.voice_utils import generate_voice as _generate_voice
except Exception:
    _transcribe_audio = None  
    _handle_conversation = None  
    _generate_voice = None  


try:
    from voicebot.conversation import normalize_transcript as _normalize_transcript
except Exception:
    _normalize_transcript = None


try:
    from voicebot import monitoring  
except Exception:
    monitoring = None


try:
    from openai import OpenAI 
except Exception:
    OpenAI = None  


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
            
            if monitoring_mod:
                try:
                    monitoring_mod.stage_start("TTS_CHUNK")
                except Exception:
                    pass
            
            out_path = await asyncio.to_thread(_generate_voice, text)  
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

        
        ws_token: Optional[str] = os.getenv("WS_AUTH_TOKEN", "") or _WS_TOKEN

        
        if ws_token:
            supplied = query.get("token", "")
            if supplied != ws_token:
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": "Unauthorized"})})
                await send({"type": "websocket.close", "code": 4401})
                return

        
        if path == "/ws/audio-stream":
            await send({"type": "websocket.accept"})
            
            fake_stt = False
            try:
                import assemblyai as aai  
            except Exception as e:
                aai = None  
            
            if os.getenv("FAKE_STT", "") in ("1", "true", "True"):
                fake_stt = True
                aai = None  

            api_key = os.getenv("ASSEMBLYAI_API_KEY") or ""
            if not api_key and not fake_stt:
                await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": "ASSEMBLYAI_API_KEY missing"})})
                await send({"type": "websocket.close", "code": 1011})
                return
            if not fake_stt:
                aai.settings.api_key = api_key

            
            from queue import Queue, Empty
            outbound: "Queue[dict]" = Queue()

            
            t_first_byte: Optional[float] = None
            t_first_partial: Optional[float] = None
            t_final_seen: Optional[float] = None

            
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

            
            rt = None
            fake_started = False
            fake_task = None
            audio_q: "asyncio.Queue[int]" = asyncio.Queue()
            client_done = asyncio.Event()
            async def _fake_emitter(out_queue: "Queue[dict]", aq: "asyncio.Queue[int]", done_evt: asyncio.Event):
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

                        
                        await asyncio.sleep(0.01)
                except Exception:
                    
                    try:
                        if built_count > 0:
                            out_queue.put({"type": "final", "text": " ".join(words[:built_count])})
                    except Exception:
                        pass

            if not fake_stt:
                try:
                    
                    _kwargs = {
                        "sample_rate": 16000,
                        "on_data": _on_data,
                        "on_error": _on_error,
                    }
                    
                    try:
                        _kwargs.update({
                            "model": "universal-2",
                            "language_code": os.getenv("STT_LANGUAGE", "en"),
                        })
                        rt = aai.RealtimeTranscriber(**_kwargs)  
                    except TypeError:
                        
                        _kwargs.pop("model", None)
                        _kwargs.pop("language_code", None)
                        rt = aai.RealtimeTranscriber(**_kwargs)  
                    
                    getattr(rt, "connect", lambda: None)()  
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
                    
                    try:
                        while True:
                            msg = outbound.get_nowait()
                            
                            if msg.get("type") == "final":
                                final_text = msg.get("text") or ""
                                
                                try:
                                    if _normalize_transcript is not None and final_text:
                                        norm = _normalize_transcript(final_text)
                                        if norm != final_text:
                                            await send({"type": "websocket.send", "text": json.dumps({"type": "debug", "stage": "normalize", "raw": final_text, "normalized": norm})})
                                        final_text = norm
                                except Exception:
                                    pass
                                got_final_text = final_text or got_final_text
                                
                                if monitoring and stt_stage:
                                    try:
                                        monitoring.stage_end(stt_stage, success=True, msg=f"len={len(got_final_text)}")
                                    except Exception:
                                        pass
                            await send({"type": "websocket.send", "text": json.dumps(msg)})
                    except Empty:
                        pass

                    
                    event = None
                    try:
                        event = await receive()
                    except Exception:
                        event = None

                    if event is None:
                        continue

                    if event["type"] == "websocket.receive":
                        if event.get("bytes") is not None:
                            
                            try:
                                if t_first_byte is None:
                                    t_first_byte = time.time()
                                if fake_stt or fallback_to_fake:
                                    
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
                                        send_audio(event["bytes"]) 
                            except Exception:
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

                
                reply = ""
                if got_final_text:
                    model_stage = "Model"
                    if monitoring:
                        try:
                            monitoring.stage_start(model_stage)
                        except Exception:
                            pass
                    
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
                    
                    if monitoring:
                        try:
                            await send({"type": "websocket.send", "text": json.dumps({"type": "debug", "stage": "timings", "data": monitoring.debug_report()})})
                        except Exception:
                            pass
                    
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

        
        if path == "/ws/audio":
            await send({"type": "websocket.accept"})
            
            chunks: List[bytes] = []
            tmp_path: Optional[str] = None
            try:
                while True:
                    event = await receive()
                    if event["type"] == "websocket.receive":
                        if "bytes" in event and event["bytes"] is not None:
                            chunks.append(event["bytes"]) 
                            
                            break
                        elif "text" in event and event["text"]:
                            
                            try:
                                payload = json.loads(event["text"]) if event["text"].startswith("{") else {}
                            except Exception:
                                payload = {}
                            if payload.get("type") in ("end", "stop"):
                                break
                    elif event["type"] == "websocket.disconnect":
                        break

                
                if not chunks:
                    await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": "No audio received"})})
                    await send({"type": "websocket.close", "code": 1000})
                    return

                
                fd, tmp_path = tempfile.mkstemp(suffix=".webm")
                with os.fdopen(fd, "wb") as f:
                    for c in chunks:
                        f.write(c)

                
                transcript = ""
                if _transcribe_audio is None:
                    
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
                        
                        await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": f"transcription failed: {e}"})})
                        if monitoring:
                            try:
                                monitoring.stage_end(stt_stage, success=False, msg=str(e))
                            except Exception:
                                pass

                if transcript:
                    await send({"type": "websocket.send", "text": json.dumps({"type": "final", "text": transcript})})

                
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

        
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.send", "text": json.dumps({"type": "error", "message": "Unknown WebSocket path"})})
        await send({"type": "websocket.close", "code": 1008})
        return

    
    if scope["type"] != "http":
        await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"Not Found"})
        return

    path = scope.get("path", "/")
    method = scope.get("method", "GET").upper()

    
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

        
        reply = None
        
        cmd = os.getenv("KLARVIA_MODEL_CMD")
        if cmd:
            try:
                import subprocess
                p = subprocess.run(cmd, input=text.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, timeout=30)
                if p.returncode == 0:
                    reply = p.stdout.decode().strip()
                else:
                    
                    print("klarvia model cmd error:", p.stderr.decode())
            except Exception as e:
                print("klarvia model cmd failed:", e)

         
        if reply is None:
            ai_chat_url = os.getenv("AI_CHAT_URL") or ""
            openai_key = os.getenv("OPENAI_API_KEY") or ""
            try:
                
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
