# Quick Fix: Network Error Solution

## The Problem
You're seeing **"Error: network"** because the default voice interface uses Google's Web Speech API which **requires internet connection**.

## The Solution (Choose One)

### ✅ Option 1: Use WebSocket Demo (Works Now!)

Open this URL in your browser:
```
http://localhost:8081/ws-voice-demo.html
```

**This version:**
- ✅ Works offline (no internet needed)
- ✅ Uses your local Python AI service  
- ✅ Direct audio to AI pipeline
- ✅ No Google services needed

**Steps:**
1. Make sure Python backend is running:
   ```powershell
   . .\.venv\Scripts\Activate.ps1
   uvicorn ai.server:app --host 127.0.0.1 --port 8001
   ```

2. Open: http://localhost:8081/ws-voice-demo.html

3. Click **Start** button

4. Allow microphone permission

5. **Speak your message**

6. Click **Stop** button

7. ✅ See transcript and hear AI response!

### ✅ Option 2: Check Internet Connection

If you want to use the main app's voice interface:

1. **Check internet connection**
   ```powershell
   ping google.com
   ```

2. **If you have internet:**
   - Refresh the page
   - Try again
   - The network error might be temporary

3. **If no internet or behind firewall:**
   - Use Option 1 (WebSocket demo) instead
   - It works completely offline!

### ✅ Option 3: Update Main App to Use WebSocket

I've created a new WebSocket-based voice component. To use it permanently:

**Step 1:** Open `src/pages/Index.tsx`

**Step 2:** Change line 6:
```tsx
// OLD (needs internet):
import VoiceInterface from "@/components/VoiceInterface";

// NEW (works offline):
import VoiceInterface from "@/components/VoiceInterfaceWebSocket";
```

**Step 3:** Save and reload page

That's it! Now it will use WebSocket (offline-capable) version.

## Quick Comparison

| Feature | Web Speech API | WebSocket Version |
|---------|---------------|-------------------|
| Internet Required | ✅ Yes (Google) | ❌ No (Local) |
| Latency | Higher | Lower |
| Privacy | Data to Google | Stays local |
| Setup | Simple | Need backend |
| Works Now | ❌ (Network error) | ✅ Yes |

## Recommended: Use WebSocket Version

Since you're getting network errors, I recommend using the **WebSocket version** which:
- Works offline
- Faster
- More private
- Already implemented and ready

## Test Right Now

```powershell
# 1. Start backend (if not running)
. .\.venv\Scripts\Activate.ps1
uvicorn ai.server:app --host 127.0.0.1 --port 8001

# 2. Open demo page
start http://localhost:8081/ws-voice-demo.html
```

## Troubleshooting

### "WebSocket connection failed"
**Solution:** Start Python backend (see step 1 above)

### "Authentication failed"  
**Solution:** Check `.env` has `WS_AUTH_TOKEN=test123`

### "Microphone access denied"
**Solution:** Click lock icon in browser → Allow microphone

## Why Network Error Happens

The browser's Web Speech API:
- Is built into Chrome/Edge/Safari
- Uses Google's cloud servers for speech recognition
- **Requires active internet connection**
- Fails when offline or behind strict firewall

The WebSocket version:
- Uses your local Python backend
- Runs Whisper STT model locally
- **No internet required**
- Full control and privacy

## Summary

**Fastest Solution:** Open http://localhost:8081/ws-voice-demo.html

**Permanent Fix:** Change import in `src/pages/Index.tsx` to use `VoiceInterfaceWebSocket`

Both solutions work offline and avoid the network error! 🎉
