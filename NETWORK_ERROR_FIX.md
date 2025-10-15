# Network Error Fix - Voice Interface

## Problem: "Error: network"

The "network" error occurs because the browser's Web Speech API (used by default) requires an **internet connection** to Google's speech recognition service.

## Solution: Two Options

### Option 1: Check Internet Connection (Quick Fix)

The default VoiceInterface uses browser's Web Speech API which needs internet.

**Steps:**
1. Ensure you have active internet connection
2. Refresh the page
3. Try again

**If internet is available but still fails:**
- Check if Google services are blocked (firewall, VPN, etc.)
- Try a different network
- Use Option 2 below

### Option 2: Use WebSocket Version (Recommended - Works Offline!)

I've created a **WebSocket-based voice interface** that works **completely offline** using your local AI service.

## Switch to WebSocket Version

### Method 1: Use the Demo Page (Easiest)

Open this URL:
```
http://localhost:8081/ws-voice-demo.html
```

This page:
- ✅ Works offline (no internet needed)
- ✅ Uses your local Python AI service
- ✅ Lower latency
- ✅ Better privacy (no data sent to Google)

### Method 2: Update Your App Component (Permanent Fix)

I've created a new component: `VoiceInterfaceWebSocket.tsx`

**To use it in your app:**

1. Open your component that uses VoiceInterface
2. Change the import:

```tsx
// OLD (needs internet):
import VoiceInterface from "@/components/VoiceInterface";

// NEW (works offline):
import VoiceInterface from "@/components/VoiceInterfaceWebSocket";
```

That's it! The component has the same interface, just different implementation.

## Quick Test

### Test WebSocket Demo Page

```powershell
# 1. Ensure Python backend is running
. .\.venv\Scripts\Activate.ps1
uvicorn ai.server:app --host 127.0.0.1 --port 8001

# 2. Open browser (in another terminal or manually)
start http://localhost:8081/ws-voice-demo.html
```

**Expected behavior:**
1. Click "Start" button
2. Allow microphone access
3. Speak your message
4. Click "Stop" button
5. See transcript appear
6. Hear AI response

## Comparison

### Web Speech API (Original - Needs Internet)
- ✅ Simple to use
- ✅ Built into browser
- ❌ **Requires internet connection**
- ❌ Sends audio to Google servers
- ❌ Higher latency

### WebSocket Version (New - Works Offline)
- ✅ **Works offline**
- ✅ Uses your local AI service
- ✅ Lower latency
- ✅ Better privacy
- ✅ More control
- ⚠️ Slightly more complex setup

## Detailed WebSocket Setup

### Verify Backend is Running

```powershell
# Check Python backend
curl http://127.0.0.1:8001/health

# Should return:
# {"status":"ok","inference_ready":true}
```

### Check Token Configuration

The WebSocket version uses token authentication. Verify your `.env` file:

```env
WS_AUTH_TOKEN=test123
```

The frontend uses `token=test123` by default in the WebSocket URL.

### Frontend Configuration

If you want to change the token, edit:
- `src/components/VoiceInterfaceWebSocket.tsx` line ~42
- `public/ws-voice-demo.html` in the WebSocket URL

## Troubleshooting

### Error: "WebSocket connection failed"

**Cause:** Python backend not running or wrong port

**Solution:**
```powershell
# Start backend
. .\.venv\Scripts\Activate.ps1
uvicorn ai.server:app --host 127.0.0.1 --port 8001
```

### Error: "Authentication failed"

**Cause:** Token mismatch

**Solution:**
1. Check `.env` file has: `WS_AUTH_TOKEN=test123`
2. Restart Python backend after changing .env
3. Check frontend uses same token

### Error: "Microphone access denied"

**Cause:** Browser permissions not granted

**Solution:**
1. Click lock icon in address bar
2. Set Microphone to "Allow"
3. Refresh page

### Still Getting "Network" Error

**If you want to use the browser Web Speech API:**

1. **Check Internet Connection:**
   ```powershell
   ping google.com
   ```

2. **Check Browser Console:**
   - Press F12
   - Look for detailed error messages
   - Check if it's a permission issue

3. **Try Different Browser:**
   - Chrome (recommended)
   - Edge (recommended)
   - Safari (macOS/iOS)
   - NOT Firefox (doesn't support Web Speech API)

4. **Check Firewall/VPN:**
   - Disable VPN temporarily
   - Check firewall settings
   - Some corporate networks block Google APIs

## Recommended Setup

### For Development (Best Experience)

Use **WebSocket version** because:
- Works without internet
- Faster response time
- Full control over the pipeline
- Better for testing

### For Production

Consider both options:
- **Web Speech API**: Simpler, no backend processing needed for STT
- **WebSocket**: More control, privacy, works offline

## Implementation in Your App

### Find Where VoiceInterface is Used

```powershell
# Search for VoiceInterface usage
findstr /s /i "VoiceInterface" src\*.tsx src\*.ts
```

### Update the Import

In each file that imports VoiceInterface:

```tsx
// Change this:
import VoiceInterface from "@/components/VoiceInterface";

// To this:
import VoiceInterface from "@/components/VoiceInterfaceWebSocket";
```

Or create a toggle to switch between both:

```tsx
import VoiceInterfaceBrowser from "@/components/VoiceInterface";
import VoiceInterfaceWS from "@/components/VoiceInterfaceWebSocket";

function MyComponent() {
  const [useWebSocket, setUseWebSocket] = useState(true);
  const VoiceInterface = useWebSocket ? VoiceInterfaceWS : VoiceInterfaceBrowser;
  
  return <VoiceInterface open={open} onClose={onClose} />;
}
```

## Testing Both Versions

### Test Browser Version (Needs Internet)
```
http://localhost:8081/
Click mic → Allow permissions → Speak
```

### Test WebSocket Version (No Internet Needed)
```
http://localhost:8081/ws-voice-demo.html
Click Start → Allow permissions → Speak → Click Stop
```

## Quick Decision Guide

**Choose Web Speech API (Browser) if:**
- ✅ You have reliable internet
- ✅ You want simplest setup
- ✅ You're okay with data sent to Google

**Choose WebSocket Version if:**
- ✅ You want offline capability
- ✅ You want better privacy
- ✅ You want lower latency
- ✅ You want full control

## Files Created

1. **`src/components/VoiceInterfaceWebSocket.tsx`** - New WebSocket-based component
2. **`NETWORK_ERROR_FIX.md`** - This guide
3. **`public/ws-voice-demo.html`** - Working demo page

## Next Steps

1. **Try WebSocket demo page first:**
   ```
   http://localhost:8081/ws-voice-demo.html
   ```

2. **If it works, update your app** to use `VoiceInterfaceWebSocket`

3. **If you need internet-based version**, check your connection and try again

## Summary

The "network" error is expected when offline because browser's Web Speech API needs Google's servers. The solution is to use the new **WebSocket version** which uses your local AI service and works completely offline.

**Quick test:** http://localhost:8081/ws-voice-demo.html

---

Need help? Check the console logs (F12) for detailed error messages!
