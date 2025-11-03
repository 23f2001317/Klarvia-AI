import os
import threading
from queue import Queue

from dotenv import load_dotenv

from voice_utils import (
    record_audio,
    playback_audio,
)
from conversation import ConversationManager, transcribe_audio

# Text-to-Speech: ElevenLabs
try:
    from elevenlabs import ElevenLabs
except Exception:  # pragma: no cover
    ElevenLabs = None  # type: ignore


def ensure_env():
    load_dotenv()
    missing = []
    for key in ["OPENAI_API_KEY", "ASSEMBLYAI_API_KEY", "ELEVENLABS_API_KEY"]:
        if not os.getenv(key):
            missing.append(key)
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def tts_elevenlabs(text: str) -> bytes:
    if ElevenLabs is None:
        raise RuntimeError("elevenlabs package not available. Install dependencies from requirements.txt")
    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice = os.getenv("ELEVENLABS_VOICE", "Rachel")
    fmt = (os.getenv("TTS_AUDIO_FORMAT", "mp3") or "mp3").lower()

    client = ElevenLabs(api_key=api_key)

    # Model choice; v2 supports many languages
    model = "eleven_multilingual_v2"

    # Some SDK versions return an iterator; normalize to bytes
    audio = client.generate(text=text, voice=voice, model=model, output_format=fmt)
    if isinstance(audio, (bytes, bytearray)):
        return bytes(audio)
    try:
        # try iterable/generator
        return b"".join(audio)  # type: ignore
    except TypeError:
        raise RuntimeError("Unexpected ElevenLabs generate() return type.")


def playback_worker(q: Queue, fmt: str):
    while True:
        data = q.get()
        if data is None:
            break
        try:
            playback_audio(data, fmt=fmt)
        except Exception as e:
            print(f"[Playback error] {e}")
        finally:
            q.task_done()


def main():
    ensure_env()
    input_seconds = float(os.getenv("INPUT_DURATION_SECONDS", "5"))
    fmt = (os.getenv("TTS_AUDIO_FORMAT", "mp3") or "mp3").lower()

    convo = ConversationManager()

    # Start playback thread
    q: Queue = Queue(maxsize=4)
    t = threading.Thread(target=playback_worker, args=(q, fmt), daemon=True)
    t.start()

    print("Klarvia Voice Bot — Press Enter to record, or type 'q' then Enter to quit.")
    try:
        while True:
            cmd = input("\n[Enter] to speak, 'q' to quit: ")
            if cmd.strip().lower() == 'q':
                break

            print(f"Recording for up to {input_seconds:.1f}s (early stop on silence)…")
            wav_path = record_audio(duration_seconds=input_seconds, detect_silence=True)

            print("Transcribing…")
            text = transcribe_audio(wav_path)
            if not text.strip():
                print("(No speech detected)")
                continue

            print(f"You: {text}")
            print("Assistant thinking…")
            reply = convo.get_response(text)
            print(f"Assistant: {reply}")

            print("Generating speech…")
            speech = tts_elevenlabs(reply)
            q.put(speech)
            print("(Speaking…)")

    finally:
        q.put(None)


if __name__ == "__main__":
    main()
