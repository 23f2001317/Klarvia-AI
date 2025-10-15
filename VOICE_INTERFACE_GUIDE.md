# Klarvia Voice Interface - Quick Start Guide

## 🎙️ What's New

You now have a beautiful, modern voice interface that:
- ✅ Clean, polished UI with gradient design
- ✅ Real-time connection status indicator (Connected/Connecting/Disconnected)
- ✅ Clear error messages with helpful troubleshooting tips
- ✅ Smooth animations and visual feedback
- ✅ Shows both your transcript and AI response in chat bubbles
- ✅ Automatic WebSocket connection management
- ✅ Works with or without authentication

## 🚀 Quick Start (No Authentication - Easiest)

### 1. Start the AI Server (No Token Required)

In PowerShell:

```powershell
# Make sure WS_AUTH_TOKEN is NOT set
Remove-Item Env:WS_AUTH_TOKEN -ErrorAction SilentlyContinue

# Start the AI server
uvicorn ai.server:app --reload --host 127.0.0.1 --port 8001
```

### 2. Start the Frontend

In a new PowerShell window:

```powershell
npm run dev
```

### 3. Test It!

1. Open your browser to http://localhost:5173
2. Click "Start Conversation" button
3. Click the big purple microphone button
4. Allow microphone access when prompted
5. Speak naturally (e.g., "Hello, how are you?")
6. Click the mic again to stop recording
7. Watch as Klarvia transcribes, processes, and responds with voice!

## 🔐 With Authentication (Recommended for Production)

### 1. Start the AI Server with Token

```powershell
$env:WS_AUTH_TOKEN = "your-secret-token"
uvicorn ai.server:app --reload --host 127.0.0.1 --port 8001
```

### 2. The Frontend Handles Token Automatically

The voice interface will:
- First try to get the token from `/api/ws-config` (if Node backend is running)
- Fall back to `localStorage.getItem("WS_TOKEN")` if backend is unavailable
- Show clear error if connection fails

### 3. Optional: Start Node Backend (for token discovery + conversation logging)

```powershell
# Set database URL (required)
$env:DATABASE_URL = "postgresql://user:password@localhost:5432/klarvia"
$env:DATABASE_SSL = "false"  # For local dev
$env:WS_AUTH_TOKEN = "your-secret-token"  # Same as AI server

# Start Node server
npm --prefix ".\server" run dev

# Run migrations (first time only)
npm --prefix ".\server" run migrate
```

## 📋 What to Expect

### When it works:
1. Connection status shows "Connected" with green wifi icon
2. Microphone button is purple/indigo gradient
3. While recording: button turns red and pulses
4. While processing: button shows spinning loader
5. Your transcript appears in an indigo bubble
6. AI response appears in a purple bubble
7. Audio plays automatically

### If there's an error:
- Red error box appears with clear message
- Shows the exact command to start the AI server
- Connection status shows "Disconnected" with gray icon
- You'll see helpful hints about authentication

## 🎨 UI Features

- **Header**: Beautiful gradient header with emoji icon and connection status
- **Microphone Button**: Large, animated button with hover effects
- **Status Indicator**: Real-time connection status (Connected/Connecting/Disconnected)
- **Transcript Bubbles**: Chat-style bubbles for you and Klarvia
- **Error Messages**: Clear, actionable error messages with troubleshooting tips
- **Help Text**: Inline tips at the bottom
- **Smooth Animations**: Framer Motion animations for all state changes

## 🔧 Troubleshooting

### "Unable to connect to AI service"
- Make sure AI server is running: `uvicorn ai.server:app --reload --host 127.0.0.1 --port 8001`
- Check that port 8001 is not in use by another process
- Look at AI server console for connection logs

### "Authentication failed"
- If using `WS_AUTH_TOKEN`, make sure it's set on AI server
- Either remove the token (for dev) or ensure frontend has access to it

### "Failed to start recording"
- Click the browser permission dialog to allow microphone access
- Check browser console for specific MediaRecorder errors
- Try in Chrome/Edge (best browser support)

### No audio playback
- Check browser audio isn't muted
- Look for autoplay policy warnings in console
- Try clicking something in the page first (user gesture requirement)

## 📊 What Happens During a Conversation

1. **Click mic** → Opens WebSocket connection (if not connected)
2. **Record audio** → Captures via MediaRecorder (WebM/Opus)
3. **Stop recording** → Converts to 16kHz mono WAV
4. **Send to AI** → Base64-encoded WAV over WebSocket
5. **AI processes**:
   - Whisper STT → text transcript
   - Model inference → reply text
   - pyttsx3 TTS → audio bytes
6. **Receive response**:
   - JSON with transcript (displayed in UI)
   - JSON with reply (displayed in UI)
   - Binary audio data (auto-played)
7. **Optional**: Log to database (if Node backend is running)

## 🎯 Next Steps

- **No changes needed!** The voice interface is production-ready
- Optional: Set up Node backend for conversation logging
- Optional: Deploy with reverse proxy (Nginx) for wss:// in production

## 💡 Tips

- Speak clearly and at normal pace
- Keep sentences reasonably short (5-10 seconds)
- Wait for the "thinking" state before speaking again
- The connection persists between recordings (efficient!)
- Check console logs (F12) for detailed debugging info

---

Enjoy your beautiful new voice interface! 🎉
