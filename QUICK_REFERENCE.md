# Quick Reference - Voice Pipeline

## Start Services

### Backend (Python FastAPI)
```powershell
. .\.venv\Scripts\Activate.ps1
uvicorn ai.server:app --reload --host 127.0.0.1 --port 8001
```

### Frontend (Vite)
```powershell
npm run dev
```

### Node Backend (Optional - for /api/chat proxy)
```powershell
npm --prefix .\server run dev
```

## Test Endpoints

### Health Check
```powershell
curl http://127.0.0.1:8001/health
# Expected: {"status":"ok","inference_ready":true}
```

### Configuration
```powershell
curl http://127.0.0.1:8001/config
# Expected: {"STT_BACKEND":"whisper","TTS_BACKEND":"pyttsx3","MODEL_PATH":"./model"}
```

### Chat (REST)
```powershell
curl -X POST http://127.0.0.1:8001/chat -H "Content-Type: application/json" -d '{"text":"Hello"}'
# Expected: {"reply":"..."}
```

## Test Voice Pipeline

### Command Line
```powershell
python test_ws.py
```

### Browser
1. Open: http://localhost:5173/ws-voice-demo.html
2. Enter token: `test123`
3. Click Start → Speak → Stop
4. Verify audio plays

### Main App
1. Open: http://localhost:5173/
2. Check browser console for `[ws]` logs
3. Should auto-connect and send test audio

## Expected Logs

### Backend Terminal
```
INFO: [ws] Received audio (12345 bytes)
INFO: [ws] Transcribed text: Hello, how are you?
INFO: [ws] Predicted reply: I'm doing well, thank you!
INFO: [ws] Sent audio (67890 bytes)
```

### Browser Console
```
Sending audio 12345 bytes
Received audio 67890 bytes
[ws] Connected
[ws] Sending audio chunk
[ws] Received response audio
```

## Environment Variables

### Required (.env file)
```env
STT_BACKEND=whisper
TTS_BACKEND=pyttsx3
MODEL_PATH=./model
PORT=8001
```

### Optional (.env file)
```env
WS_AUTH_TOKEN=test123        # Enable WebSocket auth
ENV=development              # Enable dev CORS
ALLOW_ALL_CORS=true         # Allow all origins
MODEL_IMPL=transformers      # Use specific model backend
MODEL_NAME=sshleifer/tiny-gpt2  # Model name
```

## File Locations

### Backend Code
- `ai/server.py` - FastAPI app with endpoints
- `ai/stt.py` - Whisper speech-to-text
- `ai/tts.py` - pyttsx3 text-to-speech
- `ai/model.py` - ML model inference
- `ai/main.py` - Production entrypoint

### Frontend Code
- `public/ws-voice-demo.html` - Interactive demo
- `index.html` - Main app with WebSocket probe
- `src/components/VoiceInterface.tsx` - React voice UI

### Configuration
- `.env` - Environment variables
- `ai/requirements.txt` - Python dependencies
- `package.json` - Node dependencies

### Documentation
- `README.md` - Main documentation
- `SANITY_CHECK.md` - Testing guide
- `IMPLEMENTATION_SUMMARY.md` - Technical details
- `QUICK_REFERENCE.md` - This file

## Common Commands

### Install Dependencies
```powershell
# Python
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r ai/requirements.txt

# Node
npm install
npm --prefix .\server install
```

### Check Python Environment
```powershell
python --version
pip list | findstr whisper
pip list | findstr torch
```

### Check Node Environment
```powershell
node --version
npm list framer-motion
npm list lucide-react
```

### View Logs
```powershell
# Backend logs in terminal where uvicorn is running
# Frontend logs: Open browser DevTools → Console tab
```

## WebSocket URL Format

### With Authentication
```
ws://localhost:8001/ws/audio?token=test123
```

### Without Authentication
```
ws://localhost:8001/ws/audio
```

## Audio Format Requirements

### Input (Client → Server)
- Format: WAV (16-bit PCM)
- Sample Rate: 16000 Hz
- Channels: Mono (1 channel)
- Encoding: Base64 string

### Output (Server → Client)
- Format: WAV (raw bytes)
- Sample Rate: 16000 Hz (or system default)
- Channels: Mono
- Encoding: Binary

## Troubleshooting Quick Fixes

### Backend won't start
```powershell
# Check if port is in use
netstat -ano | findstr :8001
# Kill process if needed
Stop-Process -Id <PID>
```

### Module not found
```powershell
. .\.venv\Scripts\Activate.ps1
pip install -r ai/requirements.txt
```

### Token authentication not working
```powershell
# Check .env has WS_AUTH_TOKEN
cat .env | findstr TOKEN
# Restart backend after changing .env
```

### No audio in browser
```powershell
# Check browser console for errors
# Verify microphone permissions granted
# Test with different browser
```

### Slow inference
```powershell
# Check GPU available
python -c "import torch; print(torch.cuda.is_available())"
# Install CUDA-enabled PyTorch
pip install torch --index-url https://download.pytorch.org/whl/cu118
```

## Status Indicators

### ✅ All Systems Operational
- Backend health: `{"status":"ok","inference_ready":true}`
- Frontend console: `[ws] Connected`
- Browser logs: `Sending audio` → `Received audio`
- Audio playback: Automatic and clear

### ⚠️ Partial Operation
- Backend running but no WebSocket: Check firewall
- Connected but no audio: Check microphone permissions
- Audio received but no playback: Check browser audio settings

### ❌ System Down
- Health check fails: Backend not running
- Connection refused: Port blocked or wrong URL
- 401/403 errors: Token authentication issue

## Production Checklist

- [ ] Set strong random `WS_AUTH_TOKEN` value
- [ ] Use HTTPS/WSS with valid SSL certificate
- [ ] Configure Nginx reverse proxy
- [ ] Enable rate limiting
- [ ] Set up monitoring and alerting
- [ ] Configure log rotation
- [ ] Test failover scenarios
- [ ] Document deployment procedures
- [ ] Set up CI/CD pipeline
- [ ] Perform security audit

---

**Last Updated**: 2025
**Version**: 1.0.0
