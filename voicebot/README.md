# Klarvia Voice Bot (Python)

This Python CLI voice bot records your microphone, transcribes with AssemblyAI, gets responses from OpenAI, converts them to speech with ElevenLabs, and plays the audio back.

## Files

- `main.py` — CLI entrypoint and orchestration
- `conversation.py` — OpenAI chat conversation manager
- `voice_utils.py` — Recording and audio playback helpers
- `requirements.txt` — Python dependencies
- `.env.example` — Environment variable template

## Requirements

- Windows with a working microphone
- Python 3.10+
- API keys:
  - `OPENAI_API_KEY`
  - `ASSEMBLYAI_API_KEY`
  - `ELEVENLABS_API_KEY`

## Setup (PowerShell)

```powershell
# From repo inner root (Klarvia-AI-main/)
cd voicebot
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -r requirements.txt

Copy-Item .env.example .env
# Edit .env and fill in your keys
```

`.env` required keys:

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
ASSEMBLYAI_API_KEY=...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE=Rachel
SAMPLE_RATE=16000
CHANNELS=1
INPUT_DURATION_SECONDS=5
TTS_AUDIO_FORMAT=mp3
```

Notes:

- sounddevice uses PortAudio. Windows wheels typically bundle it, but ensure microphone access is granted.
- If `playsound` fails to play MP3s on your system, playback will fall back to `pydub`. For MP3 via `pydub`, you'll need FFmpeg installed and available on PATH. Alternatively set `TTS_AUDIO_FORMAT=wav`.

## Run

```powershell
cd voicebot
. .\.venv\Scripts\Activate.ps1
python main.py
```

When prompted, press Enter to record for a few seconds (configurable via `INPUT_DURATION_SECONDS`), then wait while it transcribes, thinks, and speaks back.
