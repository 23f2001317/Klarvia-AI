import wave, struct, math
out = r'D:/Klarvia-AI-main/Klarvia-AI-main/server/tmp_test_input.wav'
framerate=16000
duration=1.0
amplitude=16000
freq=440.0
nframes=int(framerate*duration)
with wave.open(out,'w') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(framerate)
    for i in range(nframes):
        val = int(amplitude*math.sin(2*math.pi*freq*(i/framerate)))
        data = struct.pack('<h', val)
        wf.writeframesraw(data)
print('WAV written', out)
