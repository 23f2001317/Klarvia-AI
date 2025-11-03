"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Volume2, X, Loader2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface VoiceInterfaceProps { open: boolean; onClose: () => void; }

export default function VoiceInterfaceHttp({ open, onClose }: VoiceInterfaceProps) {
  const [isListening, setIsListening] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [userSpeech, setUserSpeech] = useState("");
  const [aiResponse, setAiResponse] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const srRef = useRef<any | null>(null);

  // Setup Web Speech interim recognition (optional)
  useEffect(() => {
    const hasSR = typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);
    if (!hasSR) return;
    const SpeechRecognition: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event: any) => {
      let interim = ""; let final = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) final += t + " "; else interim += t;
      }
      if (interim) setLiveTranscript(interim);
      if (final) { setUserSpeech(prev => (prev + " " + final).trim()); setLiveTranscript(""); }
    };
    recognition.onerror = () => { try { recognition.abort?.(); } catch {} };
    srRef.current = recognition;
    return () => { try { srRef.current?.stop(); } catch {} };
  }, []);

  const startRecording = async () => {
    try {
      setError(""); setInfo(""); setUserSpeech(""); setAiResponse(""); setLiveTranscript("");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        setIsThinking(true);
        try { srRef.current?.stop?.(); } catch {}
        stream.getTracks().forEach(t => t.stop());

        try {
          const blob = new Blob(chunksRef.current, { type: 'audio/webm;codecs=opus' });
          if (blob.size === 0) { setIsThinking(false); return; }
          const fd = new FormData();
          fd.append('audio', blob, 'input.webm');
          const r = await fetch('/api/voicebot', { method: 'POST', body: fd });
          const data = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(data?.error || 'processing failed');
          const { user_transcript, bot_reply, audio_url } = data;
          setUserSpeech(user_transcript || "");
          if (bot_reply) {
            setAiResponse(bot_reply);
            setInfo("");
          } else {
            // No assistant reply — surface an informational notification to the user
            setAiResponse("");
            setInfo("No assistant response — the model may not be configured.");
          }

          if (audio_url) {
            try {
              const audio = new Audio(audio_url);
              // Wait for the audio to be ready before attempting to play to avoid race conditions
              const onCanPlay = () => {
                audio.play().catch(err => console.warn('playback error', err));
                audio.removeEventListener('canplay', onCanPlay);
              };
              audio.addEventListener('canplay', onCanPlay);
              audio.addEventListener('error', (e) => { console.warn('playback error', e); });
              // Trigger load
              audio.load();
            } catch (e: any) {
              console.warn('playback setup failed', e);
            }
          }
        } catch (err: any) {
          setError(err?.message || 'Failed to process audio');
        } finally {
          setIsThinking(false);
        }
      };
      mediaRecorderRef.current = rec;
      rec.start();
      try { srRef.current?.start?.(); } catch {}
      setIsListening(true);
    } catch (e: any) {
      setError(e?.message || 'Failed to start recording');
      setIsListening(false);
    }
  };

  const stopRecording = () => {
    const rec = mediaRecorderRef.current;
    if (rec && rec.state !== 'inactive') rec.stop();
    setIsListening(false);
    setTimeout(() => setIsThinking(false), 300); // will be reset on response
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 bg-black/60 backdrop-blur-md z-50 flex items-center justify-center p-4" onClick={onClose}>
          <motion.div initial={{ scale: 0.95, opacity: 0, y: 20 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: 0.95, opacity: 0, y: 20 }} transition={{ type: "spring", damping: 25, stiffness: 300 }} className="bg-gradient-to-br from-white to-gray-50 rounded-3xl shadow-2xl w-full max-w-2xl overflow-hidden relative" onClick={(e) => e.stopPropagation()}>
            <div className="bg-gradient-to-r from-indigo-600 to-purple-600 px-8 py-6 text-white relative">
              <button onClick={onClose} className="absolute top-4 right-4 p-2 hover:bg-white/20 rounded-full transition-colors"><X size={20} /></button>
              <h2 className="text-2xl font-bold flex items-center gap-2"><span className="text-3xl">🎙️</span>Talk with Klarvia</h2>
              {error && (
                <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-xl flex gap-2 text-sm text-red-700"><AlertCircle className="w-4 h-4" />{error}</div>
              )}
              {info && (
                <div className="mt-3 p-3 bg-blue-50 border border-blue-100 rounded-xl flex gap-2 text-sm text-blue-700"><AlertCircle className="w-4 h-4" />{info}</div>
              )}
            </div>
            <div className="p-8 flex flex-col items-center">
              <motion.div whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}>
                <Button onClick={isListening ? stopRecording : startRecording} disabled={isThinking} className={`w-28 h-28 rounded-full ${isListening ? 'bg-red-600 animate-pulse' : isThinking ? 'bg-purple-600' : 'bg-indigo-600'}`}>
                  {isThinking ? <Loader2 className="w-12 h-12 animate-spin"/> : <Mic className="w-12 h-12"/>}
                </Button>
              </motion.div>
              <p className="text-gray-600 mt-6 text-lg font-medium">{isListening ? 'Listening... Click to stop' : isThinking ? 'Processing your request...' : 'Click the microphone to start'}</p>
              <div className="w-full mt-8 space-y-4">
                {userSpeech && (
                  <div className="bg-indigo-50 rounded-2xl p-5 border border-indigo-100"><div className="flex items-start gap-3"><div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center flex-shrink-0"><span className="text-white text-sm">You</span></div><div className="flex-1"><p className="text-gray-700 leading-relaxed">{userSpeech}</p></div></div></div>
                )}
                {aiResponse && (
                  <div className="bg-purple-50 rounded-2xl p-5 border border-purple-100"><div className="flex items-start gap-3"><div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-indigo-500 flex items-center justify-center flex-shrink-0"><Volume2 className="w-4 h-4 text-white"/></div><div className="flex-1"><p className="text-gray-700 leading-relaxed">{aiResponse}</p></div></div></div>
                )}
                {isListening && liveTranscript && (
                  <p className="text-lg text-gray-400">{liveTranscript}</p>
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
