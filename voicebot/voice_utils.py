import io
import os
import tempfile
import time
from typing import Optional, Tuple, Union

import numpy as np

try:
    import sounddevice as sd
except Exception as e:  # pragma: no cover - informative import failure
    sd = None  # type: ignore

# Playback: prefer playsound (simple), else pydub + simpleaudio
try:
    from playsound import playsound  # type: ignore
except Exception:
    playsound = None  # type: ignore

try:
    from pydub import AudioSegment  # type: ignore
    from pydub.playback import play as pydub_play  # type: ignore
except Exception:
    AudioSegment = None  # type: ignore
    pydub_play = None  # type: ignore

import wave


def get_audio_config() -> Tuple[int, int]:
    """Read audio config from env with safe defaults.

    Returns: (sample_rate, channels)
    """
    sample_rate = int(os.getenv("SAMPLE_RATE", "16000"))
    channels = int(os.getenv("CHANNELS", "1"))
    return sample_rate, channels


def record_blocking(duration_seconds: float) -> Tuple[np.ndarray, int]:
    """Record audio from the default microphone for a fixed duration.

    Returns: (audio_float32_mono_or_stereo, sample_rate)
    """
    if sd is None:
        raise RuntimeError(
            "sounddevice is not available. Please install PortAudio-enabled wheel and ensure microphone access is granted."
        )

    sample_rate, channels = get_audio_config()
    dtype = "float32"
    # Start recording
    audio = sd.rec(
        int(duration_seconds * sample_rate), samplerate=sample_rate, channels=channels, dtype=dtype
    )
    sd.wait()  # Wait until recording is finished
    return audio, sample_rate


def float_to_int16(audio: np.ndarray) -> np.ndarray:
    """Convert float32 [-1,1] audio to int16."""
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    return np.clip(audio, -1.0, 1.0)


def write_wav_bytes(audio_float: np.ndarray, sample_rate: int) -> bytes:
    """Encode float32 audio to 16-bit PCM WAV bytes."""
    # Ensure 2D array shape (frames, channels)
    if audio_float.ndim == 1:
        audio_float = audio_float[:, None]
    # Convert to int16 PCM
    audio_int16 = (audio_float * 32767.0).astype(np.int16)

    with io.BytesIO() as buf:
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(audio_int16.shape[1])
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())
        return buf.getvalue()


def save_temp_audio(data: bytes, suffix: str = ".wav") -> str:
    """Save bytes to a temporary audio file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def playback_audio(audio: Union[bytes, str], fmt: Optional[str] = None) -> None:
    """Play audio from bytes or file path.

    - If bytes are provided and playsound is available, write to temp file and play.
    - If pydub is available, decode and play via simpleaudio backend.
    - If a string path is provided, use playsound when possible, else pydub based on extension.
    """
    # Determine format if given bytes
    ext = ".mp3" if (fmt or "mp3").lower() == "mp3" else ".wav"

    if isinstance(audio, bytes):
        # Try playsound path
        if playsound is not None:
            tmp = save_temp_audio(audio, suffix=ext)
            try:
                playsound(tmp)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return
        # Try pydub
        if AudioSegment is not None and pydub_play is not None:
            if ext == ".mp3":
                seg = AudioSegment.from_file(io.BytesIO(audio), format="mp3")
            else:
                seg = AudioSegment.from_file(io.BytesIO(audio), format="wav")
            pydub_play(seg)
            return
        raise RuntimeError("No audio playback backend available. Install playsound or pydub+simpleaudio.")

    # audio is a path
    if isinstance(audio, str):
        if playsound is not None:
            playsound(audio)
            return
        if AudioSegment is not None and pydub_play is not None:
            seg = AudioSegment.from_file(audio)
            pydub_play(seg)
            return
        raise RuntimeError("No audio playback backend available. Install playsound or pydub+simpleaudio.")


def ensure_ffmpeg_note():  # pragma: no cover - note helper for users
    """Warn users if trying to play mp3 via pydub without ffmpeg.

    On Windows, pydub requires ffmpeg for mp3 decode unless using wavs.
    """
    if AudioSegment is not None:
        pass


def _ensure_temp_dir() -> str:
    """Create and return a stable temp folder for the voice bot."""
    root = os.path.join(tempfile.gettempdir(), "klarvia_voicebot")
    os.makedirs(root, exist_ok=True)
    return root


def record_audio(
    duration_seconds: Optional[float] = None,
    detect_silence: bool = True,
    silence_threshold: float = 0.015,
    silence_duration: float = 1.2,
) -> str:
    """Record audio from the microphone and save as temp/input.wav.

    Behavior:
    - If duration_seconds is provided (default from env or 10s), record up to that length.
    - If detect_silence is True, stop early once continuous silence is detected for `silence_duration` seconds.

    Returns the absolute path to the recorded WAV filename.
    """
    if sd is None:
        raise RuntimeError(
            "sounddevice is not available. Please install it and ensure microphone access is granted."
        )

    # Defaults
    if duration_seconds is None:
        # Prefer env setting if present, else 10s default
        duration_seconds = float(os.getenv("INPUT_DURATION_SECONDS", "10"))

    sample_rate, channels = get_audio_config()

    # Stream and accumulate until duration or silence
    blocksize = 1024
    frames: list[np.ndarray] = []

    silence_run = 0.0
    start = time.time()

    with sd.InputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        blocksize=blocksize,
    ) as stream:
        while True:
            buf, _ = stream.read(blocksize)
            # Defensive copy
            frames.append(buf.copy())

            # Update silence window
            if detect_silence:
                amp = float(np.max(np.abs(buf))) if buf.size else 0.0
                if amp < silence_threshold:
                    silence_run += blocksize / sample_rate
                else:
                    silence_run = 0.0

            # Stop conditions
            elapsed = time.time() - start
            if elapsed >= duration_seconds:
                break
            if detect_silence and elapsed > 0.5 and silence_run >= silence_duration:
                # Allow at least 0.5s to avoid cutting off too soon on startup
                break

    if not frames:
        # Ensure at least a tiny buffer to produce a valid wav
        frames = [np.zeros((1, channels), dtype=np.float32)]

    audio_float = np.concatenate(frames, axis=0)

    # Ensure 2D shape
    if audio_float.ndim == 1:
        audio_float = audio_float[:, None]

    # Write to temp/input.wav
    tmp_dir = _ensure_temp_dir()
    path = os.path.join(tmp_dir, "input.wav")

    # Prefer wavio if available
    try:
        import wavio  # type: ignore

        audio_int16 = (np.clip(audio_float, -1.0, 1.0) * 32767.0).astype(np.int16)
        # wavio expects shape (n, channels)
        wavio.write(path, audio_int16, sample_rate, sampwidth=2)
    except Exception:
        # Fallback to built-in wave writer
        wav_bytes = write_wav_bytes(audio_float, sample_rate)
        with open(path, "wb") as f:
            f.write(wav_bytes)

    return path


def generate_voice(text: str) -> str:
    """Generate speech from text using ElevenLabs and save as output.mp3 in the temp folder.

    Returns the absolute path to the saved mp3 file.
    """
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()
    if not text:
        raise ValueError("Text is empty; cannot synthesize.")

    # Lazy import to avoid hard dependency for modules not using TTS
    try:
        from elevenlabs import ElevenLabs  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("elevenlabs package not available. Install dependencies from requirements.txt") from exc

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is missing in environment.")
    voice = os.getenv("ELEVENLABS_VOICE", "Rachel")

    client = ElevenLabs(api_key=api_key)

    # Model choice; v2 supports multiple languages well
    model = "eleven_multilingual_v2"

    # Request MP3 output
    try:
        audio = client.generate(text=text, voice=voice, model=model, output_format="mp3")
    except Exception as exc:
        raise RuntimeError(f"ElevenLabs generate() failed: {exc}")

    # Normalize to bytes
    if isinstance(audio, (bytes, bytearray)):
        audio_bytes = bytes(audio)
    else:
        try:
            audio_bytes = b"".join(audio)  # type: ignore[assignment]
        except TypeError as exc:
            raise RuntimeError("Unexpected ElevenLabs generate() return type; expected bytes or iterable of bytes.") from exc

    tmp_dir = _ensure_temp_dir()
    out_path = os.path.join(tmp_dir, "output.mp3")
    with open(out_path, "wb") as f:
        f.write(audio_bytes)

    return out_path
