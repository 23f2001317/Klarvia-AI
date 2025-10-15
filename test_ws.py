import asyncio
import base64
import sys
from pathlib import Path

try:
    import websockets  # type: ignore
except ImportError:
    print("websockets package is required. Install with: pip install websockets", file=sys.stderr)
    raise


def ensure_test_wav(path: Path, duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    """Create a tiny silent WAV file if it doesn't exist."""
    if path.exists():
        return
    print(f"[info] '{path.name}' not found; creating a {duration_s:.1f}s silent WAV for testing.")
    import wave
    import struct

    n_frames = int(duration_s * sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        silence_frame = struct.pack('<h', 0)
        for _ in range(n_frames):
            wf.writeframes(silence_frame)


async def run(url: str, in_wav: Path, out_wav: Path) -> None:
    print(f"[info] connecting to {url} …")
    async with websockets.connect(url) as ws:
        print("[ok] connected")

        # Read input WAV and send as base64 text
        wav_bytes = in_wav.read_bytes()
        b64 = base64.b64encode(wav_bytes).decode('ascii')
        await ws.send(b64)
        print(f"[ok] sent {in_wav} ({len(wav_bytes)} bytes, base64 length {len(b64)})")

        # Receive messages until we get binary audio, then save and exit
        print("[info] waiting for response audio …")
        while True:
            msg = await ws.recv()
            if isinstance(msg, (bytes, bytearray)):
                out_wav.write_bytes(msg)
                print(f"[ok] received audio -> saved to {out_wav} ({len(msg)} bytes)")
                break
            else:
                text = str(msg)
                print(f"[info] server text: {text}")
                # If the server indicates no speech was detected, we can exit
                if "no-speech" in text:
                    print("[warn] Server reported no speech detected in input.")
                    break


if __name__ == "__main__":
    # Defaults
    url = "ws://localhost:8001/ws/audio?token=test123"
    in_wav = Path("test.wav")
    out_wav = Path("output.wav")

    # Allow optional args: url in_wav out_wav
    if len(sys.argv) > 1:
        url = sys.argv[1]
    if len(sys.argv) > 2:
        in_wav = Path(sys.argv[2])
    if len(sys.argv) > 3:
        out_wav = Path(sys.argv[3])

    ensure_test_wav(in_wav)
    try:
        asyncio.run(run(url, in_wav, out_wav))
    except KeyboardInterrupt:
        print("[info] canceled by user")
