"""
Stream a WAV file as raw PCM int16 frames to the server's /ws/audio-stream WebSocket
and measure partial/final transcript latencies.

Usage:
  python scripts/ws_pcm_tester.py --file ../test_claudia.wav --chunk-ms 160 --host 127.0.0.1 --port 8001

If websocket-client isn't installed, install via: pip install websocket-client
"""

import argparse
import wave
import time
import json
import threading
import os
import sys

try:
    import websocket
except Exception:
    websocket = None

try:
    import audioop
    _HAS_AUDIOOP = True
except Exception:
    audioop = None
    _HAS_AUDIOOP = False

from array import array

def _py_resample(frames_bytes, sampwidth, src_rate, tgt_rate):
    """Simple linear interpolation resampler from src_rate to tgt_rate for 16-bit mono data.
    Returns resampled bytes (16-bit little-endian).
    """
    if sampwidth != 2:
        raise RuntimeError('py_resample only supports 16-bit samples')
    # Convert bytes to array('h')
    arr = array('h')
    arr.frombytes(frames_bytes)
    src_len = len(arr)
    if src_len == 0:
        return b''
    ratio = float(tgt_rate) / float(src_rate)
    new_len = int(round(src_len * ratio))
    out = array('h', [0]) * new_len
    for i in range(new_len):
        src_pos = i / ratio
        i0 = int(src_pos)
        i1 = min(i0 + 1, src_len - 1)
        t = src_pos - i0
        v = int((1.0 - t) * arr[i0] + t * arr[i1])
        out[i] = max(-32768, min(32767, v))
    return out.tobytes()


def prepare_pcm(path, target_rate=16000):
    # Read wave
    wf = wave.open(path, 'rb')
    nch = wf.getnchannels()
    sampwidth = wf.getsampwidth()
    sr = wf.getframerate()
    frames = wf.readframes(wf.getnframes())
    wf.close()

    # Convert to mono if needed
    if nch > 1:
        if _HAS_AUDIOOP:
            try:
                frames = audioop.tomono(frames, sampwidth, 1, 1)
                nch = 1
            except Exception:
                frames = audioop.tomono(frames, sampwidth, 1.0, 0.0)
                nch = 1
        else:
            # naive fallback: take left channel from interleaved data
            if sampwidth != 2:
                raise RuntimeError('Unsupported sample width for mono fallback')
            arr = array('h')
            arr.frombytes(frames)
            left = array('h')
            left.extend(arr[0::nch])
            frames = left.tobytes()
            nch = 1

    # Convert to 16-bit samples if needed
    if sampwidth != 2:
        if _HAS_AUDIOOP:
            try:
                frames = audioop.lin2lin(frames, sampwidth, 2)
                sampwidth = 2
            except Exception:
                raise RuntimeError('Failed to convert sample width to 16-bit')
        else:
            raise RuntimeError('audioop required to change sample width')

    # Resample to target_rate if needed
    if sr != target_rate:
        if _HAS_AUDIOOP:
            try:
                frames, _ = audioop.ratecv(frames, 2, 1, sr, target_rate, None)
                sr = target_rate
            except Exception as e:
                raise RuntimeError(f'Failed to resample audio: {e}')
        else:
            try:
                frames = _py_resample(frames, 2, sr, target_rate)
                sr = target_rate
            except Exception as e:
                raise RuntimeError(f'Fallback resample failed: {e}')

    return frames, sr


class PCMTester:
    def __init__(self, ws_url, wav_path, chunk_ms=160):
        self.ws_url = ws_url
        self.wav_path = wav_path
        self.chunk_ms = int(chunk_ms)

        self.sent_times = []
        self.partial_times = []
        self.final_time = None
        self.partials = []
        self.reply = None

        self.ws = None
        self.start_sending_at = None

    def on_open(self, ws):
        print('[tester] WebSocket opened, starting send thread')
        t = threading.Thread(target=self._send_loop, args=(ws,), daemon=True)
        t.start()

    def on_message(self, ws, message):
        # message may be bytes or text
        if isinstance(message, bytes):
            print('[tester] Received binary data (audio) of length', len(message))
            return
        try:
            msg = json.loads(message)
        except Exception:
            print('[tester] Non-JSON message:', message)
            return
        t = time.time()
        typ = msg.get('type')
        if typ == 'partial':
            self.partial_times.append((t, msg.get('text')))
            self.partials.append(msg.get('text'))
            print(f"[tester] PARTIAL @ {t:.3f}: {msg.get('text')}")
        elif typ in ('final', 'transcript'):
            self.final_time = t
            print(f"[tester] FINAL @ {t:.3f}: {msg.get('text')}")
        elif typ == 'reply':
            self.reply = msg.get('text')
            print(f"[tester] REPLY @ {t:.3f}: {self.reply}")
        elif typ == 'debug':
            print('[tester] DEBUG', msg)
        else:
            print('[tester] MSG', msg)

    def on_error(self, ws, err):
        print('[tester] WebSocket error:', err)

    def on_close(self, ws, code, reason):
        print(f'[tester] WebSocket closed: code={code} reason={reason}')

    def _send_loop(self, ws):
        try:
            frames, sr = prepare_pcm(self.wav_path, target_rate=16000)
        except Exception as e:
            print('[tester] Failed to prepare PCM:', e)
            ws.close()
            return

        bytes_per_sample = 2
        samples_per_ms = sr / 1000.0
        samples_per_chunk = int(round(samples_per_ms * self.chunk_ms))
        bytes_per_chunk = samples_per_chunk * bytes_per_sample

        total = len(frames)
        pos = 0
        self.start_sending_at = time.time()
        print(f'[tester] Starting send of audio (bytes={total}) chunk_ms={self.chunk_ms} bytes_per_chunk={bytes_per_chunk}')
        while pos < total:
            end = min(pos + bytes_per_chunk, total)
            chunk = frames[pos:end]
            try:
                ws.send(chunk, opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception as e:
                print('[tester] send failed:', e)
                break
            sent_at = time.time()
            self.sent_times.append(sent_at)
            pos = end
            # Sleep to emulate real-time capture
            time.sleep(self.chunk_ms / 1000.0)
        # After sending all audio, send stop marker
        time.sleep(0.05)
        try:
            ws.send(json.dumps({"type": "stop"}))
        except Exception:
            pass
        print('[tester] Finished sending audio, waiting for final reply...')

    def run(self):
        if websocket is None:
            raise RuntimeError('websocket-client module not available')
        self.ws = websocket.WebSocketApp(self.ws_url,
                                        on_open=self.on_open,
                                        on_message=self.on_message,
                                        on_error=self.on_error,
                                        on_close=self.on_close)
        self.ws.run_forever()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--file', default=os.path.join(os.path.dirname(__file__), '..', 'test_claudia.wav'))
    p.add_argument('--chunk-ms', type=int, default=160)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8001)
    p.add_argument('--token', default='')
    args = p.parse_args()

    # Try ports 8001 then 8000 if not reachable (the frontend sometimes uses 8001)
    host = args.host
    port = args.port
    token = args.token
    if token:
        ws_url = f"ws://{host}:{port}/ws/audio-stream?token={token}"
    else:
        ws_url = f"ws://{host}:{port}/ws/audio-stream"

    print('[tester] Connecting to', ws_url)
    t = PCMTester(ws_url, os.path.abspath(args.file), chunk_ms=args.chunk_ms)
    try:
        t.run()
    except Exception as e:
        print('Error running tester:', e)
        sys.exit(2)

    # After run, print summary (if any partials recorded)
    if t.sent_times and t.partial_times:
        first_sent = t.sent_times[0]
        first_partial = t.partial_times[0][0]
        print('\n--- SUMMARY ---')
        print(f'First send @ {first_sent:.3f}')
        print(f'First partial @ {first_partial:.3f}  latency={(first_partial - first_sent)*1000:.1f} ms')
        if t.final_time:
            last_sent = t.sent_times[-1]
            print(f'Last send @ {last_sent:.3f}')
            print(f'Final transcript @ {t.final_time:.3f}  latency_from_last_send={(t.final_time - last_sent)*1000:.1f} ms')
    else:
        print('\nNo partials recorded during the test. Check server logs and connectivity.')
