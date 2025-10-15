# Voice Pipeline Sanity Check

This document provides step-by-step instructions to validate the complete voice→model→voice pipeline.

## Prerequisites

1. **Python Environment**
   - Python 3.9+ with virtual environment activated
   - All dependencies installed: `pip install -r ai/requirements.txt`

2. **Environment Configuration**
   - Create/update `.env` file in project root:
     ```env
     STT_BACKEND=whisper
     TTS_BACKEND=pyttsx3
     MODEL_PATH=./model
     PORT=8001
     WS_AUTH_TOKEN=test123
     ```

3. **Node Environment**
   - Node 18+ installed
   - Dependencies installed: `npm install`

## Step 1: Start the Backend

Open a terminal in the project root and run:

```powershell
# Activate virtual environment (if not already active)
.\.venv\Scripts\Activate.ps1

# Start FastAPI backend
uvicorn ai.server:app --reload --host 127.0.0.1 --port 8001
```

**Expected Output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8001
INFO:     Application startup complete.
```

## Step 2: Start the Frontend (Optional)

Open a new terminal and run:

```powershell
npm run dev
```

**Expected Output:**
```
VITE v... ready in ...ms
  ➜  Local:   http://localhost:5173/
```

## Step 3: Open the WebSocket Demo Page

1. Navigate to: `http://localhost:5173/ws-voice-demo.html` (or open `public/ws-voice-demo.html` directly in your browser)
2. Verify the token field shows: `test123`

## Step 4: Perform Voice Test

1. Click **"Start"** button
2. Allow microphone access when prompted
3. Speak a short phrase (e.g., "Hello, how are you?")
4. Click **"Stop"** button
5. Wait for the AI response audio to play

## Step 5: Verify Backend Logs

Check the backend terminal for these **exact log messages** in sequence:

```
INFO: [ws] Received audio (XXXXX bytes)
INFO: [ws] Transcribed text: <your speech text>
INFO: [ws] Predicted reply: <AI response>
INFO: [ws] Sent audio (XXXXX bytes)
```

**✅ PASS**: All 4 log messages appear with correct content  
**❌ FAIL**: Any message missing or errors appear

## Step 6: Verify Frontend Console Logs

1. Open browser DevTools (F12)
2. Go to Console tab
3. Look for these messages:

```
Sending audio XXXXX bytes
Received audio XXXXX bytes
```

**✅ PASS**: Both messages appear after recording stops  
**❌ FAIL**: Messages missing or WebSocket errors shown

## Step 7: Verify Audio Playback

1. Check that the audio player control appears
2. Confirm that audio plays automatically
3. Listen to verify the AI response is audible and clear

**✅ PASS**: Audio plays with clear AI voice response  
**❌ FAIL**: No audio, distorted audio, or playback errors

## Step 8: Test Token Authentication

1. Change the token in the input field to: `invalid_token`
2. Click **"Start"** → Speak → Click **"Stop"**
3. Check browser console for:
   ```
   WebSocket closed: Unauthorized (invalid or missing token)
   ```
4. Change token back to: `test123`
5. Repeat the test - should work normally

**✅ PASS**: Invalid token rejected, valid token accepted  
**❌ FAIL**: Authentication not enforced

## Final Checklist

- [ ] Backend starts without errors
- [ ] Backend logs show all 4 pipeline stages
- [ ] Frontend console shows "Sending audio" and "Received audio"
- [ ] Audio plays automatically and is clearly audible
- [ ] Token authentication properly rejects invalid tokens
- [ ] Token authentication accepts valid tokens

## If All Checks Pass ✅

The voice-based ML model integration is **fully operational**! Update the README with:

```markdown
✅ Voice-based ML model integration fully operational.
```

## Troubleshooting

### Backend Issues

**Model loading errors:**
- Check MODEL_PATH in .env
- Ensure sufficient disk space for Whisper model download

**WebSocket connection refused:**
- Verify backend is running on port 8001
- Check firewall settings

**Audio processing errors:**
- Ensure ffmpeg is not required (we use soundfile)
- Check Python package versions

### Frontend Issues

**Microphone access denied:**
- Grant browser microphone permissions
- Use HTTPS or localhost (required for getUserMedia)

**No audio playback:**
- Check browser audio permissions
- Verify audio element has content
- Check browser console for errors

**WebSocket connection failed:**
- Verify backend URL in demo page
- Check CORS configuration
- Ensure WS_URL includes correct token

### Performance Issues

**Slow transcription:**
- Enable GPU: Install CUDA-enabled PyTorch
- Use fp16: Model automatically uses fp16 if GPU available

**Large audio files:**
- Audio is compressed to OGG/Vorbis before sending
- Check network bandwidth

**High latency:**
- Reduce audio chunk size in recorder
- Use asyncio.Queue for streaming (already implemented)

## Advanced Testing

### Test with Python Script

```powershell
python test_ws.py
```

Expected output:
```
[test] Connecting to ws://localhost:8001/ws/audio?token=test123...
[test] WebSocket connected
[test] Sending audio (X bytes)...
[test] Sent audio chunk
[test] Received reply audio, saving to output.wav...
[test] Saved X bytes to output.wav
```

### Check Health Endpoint

```powershell
curl http://127.0.0.1:8001/health
```

Expected response:
```json
{"status": "ok", "inference_ready": true}
```

### Check Config Endpoint

```powershell
curl http://127.0.0.1:8001/config
```

Expected response:
```json
{
  "STT_BACKEND": "whisper",
  "TTS_BACKEND": "pyttsx3",
  "MODEL_PATH": "./model"
}
```

## Notes

- First run will download Whisper model (~140MB) - this is normal
- Model loading takes 5-10 seconds on first inference
- Subsequent requests are much faster due to model caching
- Token authentication is optional - remove WS_AUTH_TOKEN from .env to disable
