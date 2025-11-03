"""
Simple mock STT WebSocket server to emulate `/ws/audio-stream` behavior for dev testing.
Accepts binary PCM frames and emits `partial` messages every 150-250ms revealing words from a sample sentence,
then emits `final` and `reply` messages.

Run: python scripts/mock_stt_server.py --port 8002
"""
import asyncio
import json
import argparse
import websockets

SAMPLE_TRANSCRIPT = "Hello Klarvia I have a headache"

async def handler(ws, path):
    print('[mock-stt] connection from', ws.remote_address, 'path', path)
    # Wait for first binary to consider start
    got_audio = False
    buf_count = 0
    try:
        async for message in ws:
            if isinstance(message, bytes):
                buf_count += 1
                if not got_audio:
                    got_audio = True
                    # Start emitting partials in background
                    asyncio.create_task(emit_partials(ws))
            else:
                try:
                    data = json.loads(message)
                    if data.get('type') in ('stop', 'end'):
                        # emit final and reply then close
                        await ws.send(json.dumps({"type":"final", "text": SAMPLE_TRANSCRIPT}))
                        await ws.send(json.dumps({"type":"reply", "text": "I hear that you're in pain; try resting and hydrating."}))
                        await asyncio.sleep(0.1)
                        await ws.close()
                        return
                except Exception:
                    pass
    except websockets.ConnectionClosed:
        print('[mock-stt] connection closed')

async def emit_partials(ws):
    words = SAMPLE_TRANSCRIPT.split()
    built = []
    for w in words:
        # simulate processing delay
        await asyncio.sleep(0.18)
        built.append(w)
        text = ' '.join(built)
        msg = {"type": "partial", "text": text}
        try:
            await ws.send(json.dumps(msg))
            print('[mock-stt] sent partial:', text)
        except Exception as e:
            print('[mock-stt] send failed:', e)
            return
    # after all, send final
    await asyncio.sleep(0.05)
    try:
        await ws.send(json.dumps({"type":"final", "text": SAMPLE_TRANSCRIPT}))
        print('[mock-stt] sent final')
    except Exception as e:
        print('[mock-stt] send final failed:', e)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8002)
    args = p.parse_args()

    print(f'[mock-stt] starting on {args.host}:{args.port}')
    async def _main():
        async with websockets.serve(handler, args.host, args.port):
            print(f'[mock-stt] serving, press Ctrl-C to stop')
            await asyncio.Future()  # run forever

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print('[mock-stt] stopped')
