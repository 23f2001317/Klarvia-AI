"""FastAPI microservice exposing the chatbot model via /chat.

Run locally:
  uvicorn ai.server:app --reload --host 127.0.0.1 --port 8001
"""
from __future__ import annotations

import logging
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .model import get_reply, inference_ready
from .stt import transcribe_audio
from .tts import text_to_speech
import os
import json

load_dotenv()


logger = logging.getLogger("ai.server")
logger.setLevel(logging.INFO)

app = FastAPI(title="Klarvia AI Chat Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatIn(BaseModel):
    text: str


class ChatOut(BaseModel):
    reply: str


@app.get("/health")
def health():
    return {"status": "ok", "inference_ready": inference_ready()}


@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn):
    try:
        user_text = (body.text or "").strip()
        logger.info("[chat] recv: %s", user_text)
        if not user_text:
            raise HTTPException(status_code=400, detail="text is required")
        reply = get_reply(user_text)
        logger.info("[chat] reply: %s", reply)
        return ChatOut(reply=reply)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Chat error: %s", e)
        raise HTTPException(status_code=500, detail="internal error")


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    """WebSocket pipeline: base64 audio -> STT -> model -> TTS -> audio bytes.
    
    Authentication: requires ?token=XYZ query parameter.
    Set WS_AUTH_TOKEN environment variable to enable token verification.
    If WS_AUTH_TOKEN is not set, accepts all connections (dev mode).
    """
    expected_token = os.environ.get("WS_AUTH_TOKEN")
    if expected_token:
        query_params = dict(websocket.query_params)
        provided_token = query_params.get("token")
        if not provided_token or provided_token != expected_token:
            logger.warning("/ws/audio rejected: invalid or missing token")
            await websocket.close(code=1008, reason="Unauthorized")
            return
    
    await websocket.accept()
    logger.info("/ws/audio connected")
    try:
        while True:
            b64_chunk = await websocket.receive_text()
            if not b64_chunk:
                continue

            import base64
            try:
                audio_bytes = base64.b64decode(b64_chunk)
            except Exception as e:
                logger.warning("Invalid base64 chunk: %s", e)
                await websocket.send_text("error: invalid-audio")
                continue

            logger.info("[ws] Received audio (%d bytes)", len(audio_bytes))
            
            text = await transcribe_audio(audio_bytes)
            if not text:
                await websocket.send_text("status: no-speech")
                continue
            logger.info("[ws] Transcribed text: %s", text)
            try:
                await websocket.send_text(json.dumps({
                    "type": "transcript",
                    "transcript": text,
                }))
            except Exception:
                pass

            reply_text = await asyncio.to_thread(get_reply, text)
            logger.info("[ws] Predicted reply: %s", reply_text)
            try:
                await websocket.send_text(json.dumps({
                    "type": "reply",
                    "reply": reply_text,
                }))
            except Exception:
                pass

            audio_out = await text_to_speech(reply_text)
            if not audio_out:
                await websocket.send_text("error: tts-failed")
                continue

            await websocket.send_bytes(audio_out)
            logger.info("[ws] Sent audio (%d bytes)", len(audio_out))

    except WebSocketDisconnect:
        logger.info("/ws/audio disconnected")
    except Exception as e:
        logger.exception("/ws/audio error: %s", e)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@app.get("/config")
def config():
    return {
        "stt_backend": os.environ.get("STT_BACKEND"),
        "tts_backend": os.environ.get("TTS_BACKEND"),
        "model_path": os.environ.get("MODEL_PATH"),
    }
