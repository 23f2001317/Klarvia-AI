"use client";

import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Volume2, X, Loader2, Wifi, WifiOff, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

declare global {
  interface Window {
    webkitSpeechRecognition?: any;
    SpeechRecognition?: any;
  }
}

interface VoiceInterfaceProps {
  open: boolean;
  onClose: () => void;
}

export default function VoiceInterfaceWebSocket({ open, onClose }: VoiceInterfaceProps) {
  const [isListening, setIsListening] = useState(false);
  const [userSpeech, setUserSpeech] = useState("");
  const [liveTranscript, setLiveTranscript] = useState(""); // Live interim transcript
  const [aiResponse, setAiResponse] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [error, setError] = useState("");
  const [connectionStatus, setConnectionStatus] = useState<"disconnected" | "connecting" | "connected">("disconnected");
  const [srAvailable, setSrAvailable] = useState(true);
  const [useStreaming, setUseStreaming] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const speechRecognitionRef = useRef<any | null>(null); // Using 'any' for browser compatibility
  const startedAtRef = useRef<number | null>(null);
  const isConnectingRef = useRef(false);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  // Queued audio playback for streaming TTS chunks
  const audioQueueRef = useRef<string[]>([]); // queue of object URLs
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const pendingChunksRef = useRef<number>(0);

  const clearAudioQueue = () => {
    // Stop current audio and revoke all URLs
    try {
      if (currentAudioRef.current) {
        currentAudioRef.current.pause();
        currentAudioRef.current.src = "";
        currentAudioRef.current = null;
      }
    } catch {}
    try {
      while (audioQueueRef.current.length) {
        const url = audioQueueRef.current.shift();
        if (url) URL.revokeObjectURL(url);
      }
    } catch {}
    pendingChunksRef.current = 0;
  };

  const playNextFromQueue = () => {
    const nextUrl = audioQueueRef.current.shift();
    if (!nextUrl) {
      // Queue empty
      currentAudioRef.current = null;
      if (pendingChunksRef.current <= 0) {
        setIsThinking(false);
      }
      return;
    }
    const audio = new Audio(nextUrl);
    currentAudioRef.current = audio;
    audio.onended = () => {
      try { URL.revokeObjectURL(nextUrl); } catch {}
      // One chunk finished
      pendingChunksRef.current = Math.max(0, pendingChunksRef.current - 1);
      playNextFromQueue();
    };
    audio.onerror = () => {
      try { URL.revokeObjectURL(nextUrl); } catch {}
      pendingChunksRef.current = Math.max(0, pendingChunksRef.current - 1);
      // Continue with next even if this one failed
      playNextFromQueue();
    };
    // Attempt to play; on failure continue to next
    audio.play().catch(() => {
      pendingChunksRef.current = Math.max(0, pendingChunksRef.current - 1);
      playNextFromQueue();
    });
  };

  const enqueueAudioChunk = (buf: ArrayBuffer, mime: string = 'audio/mpeg') => {
    try {
      const blob = new Blob([buf], { type: mime });
      const url = URL.createObjectURL(blob);
      audioQueueRef.current.push(url);
      pendingChunksRef.current += 1;
      if (!currentAudioRef.current) {
        playNextFromQueue();
      }
    } catch (e) {
      console.error('[voice-ws] Failed to enqueue audio chunk', e);
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
      try {
        processorRef.current && (processorRef.current.disconnect(), (processorRef.current as any) = null);
        sourceRef.current && sourceRef.current.disconnect();
        audioCtxRef.current && audioCtxRef.current.close();
      } catch {}
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach(t => t.stop());
      }
      if (speechRecognitionRef.current) {
        try {
          speechRecognitionRef.current.stop();
        } catch (_) {}
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, []);

  // Initialize Speech Recognition for live transcription (disabled in streaming mode)
  useEffect(() => {
    const hasSR = typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);
    setSrAvailable(!!hasSR);
    if (hasSR && !useStreaming) {
  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      const recognition = new SpeechRecognition();
      recognition.lang = "en-US";
      recognition.continuous = true;
      recognition.interimResults = true;

  recognition.onresult = (event: any) => {
        // Combine interim and final transcripts for live display, and accumulate finals into userSpeech
        let interim = "";
        let final = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            final += transcript + " ";
          } else {
            interim += transcript;
          }
        }
        if (interim) setLiveTranscript(interim);
        if (final) {
          setUserSpeech(prev => (prev + " " + final).trim());
          setLiveTranscript("");
        }
        if (!interim && !final) {
          // still log for debugging
          console.log('[voice-ws] Live transcript: (none)');
        }
      };

  recognition.onerror = (event: any) => {
        console.error('[voice-ws] Recognition error:', event.error);
        // Do NOT stop the MediaRecorder on recognition errors; just abort recognition.
        // 'network' is common when offline or blocked; degrade gracefully.
        try {
          recognition.abort?.();
        } catch (_) {
          try { recognition.stop(); } catch (_) {}
        }
        if (event.error === 'network' || event.error === 'service-not-allowed') {
          setLiveTranscript('');
          setSrAvailable(false);
        }
      };

      speechRecognitionRef.current = recognition;
    }

    return () => {
      if (speechRecognitionRef.current) {
        try {
          speechRecognitionRef.current.stop();
        } catch (_) {}
      }
    };
  }, [useStreaming]);

  // Detect whether to use streaming route (based on localStorage or backend config)
  useEffect(() => {
    (async () => {
      try {
        const override = localStorage.getItem('STREAM_STT');
        if (override === '1') { setUseStreaming(true); return; }
        if (override === '0') { setUseStreaming(false); return; }

        // Try to inspect backend config when running locally
        const isLocal = typeof window !== 'undefined' && ["localhost", "127.0.0.1", "0.0.0.0"].includes(window.location.hostname);
        if (isLocal) {
          const cfg = await fetch('http://127.0.0.1:8001/config').then(r => r.json()).catch(() => null);
          if (cfg?.stt_backend && String(cfg.stt_backend).toLowerCase() === 'assemblyai') {
            setUseStreaming(true);
          }
        }
      } catch {}
    })();
  }, []);

  const connectWebSocket = (): Promise<WebSocket> => {
    return new Promise(async (resolve, reject) => {
      if (isConnectingRef.current) {
        reject(new Error("Connection already in progress"));
        return;
      }

      isConnectingRef.current = true;
      setConnectionStatus("connecting");
      setError("");

      try {
        // Discover token from backend or use stored token
        let resolvedToken = "";
        try {
          const cfg = await fetch('/api/ws-config').then(r => r.json()).catch(() => null);
          if (cfg?.token) {
            resolvedToken = cfg.token;
          }
        } catch (e) {
          // Backend not available, try localStorage
          console.log("[voice-ws] Backend discovery failed, using localStorage");
        }

        if (!resolvedToken) {
          resolvedToken = localStorage.getItem("WS_TOKEN") || "";
        }

        const isLocal = ["localhost", "127.0.0.1", "0.0.0.0"].includes(window.location.hostname);
        const scheme = isLocal ? "ws" : "wss";
        const hostPort = window.location.host;
        const pathPrefix = isLocal ? "" : "/ai";

  const path = useStreaming ? '/ws/audio-stream' : '/ws/audio';
        const resolvedWsUrl = isLocal
          ? `${scheme}://127.0.0.1:8001${path}${resolvedToken ? `?token=${encodeURIComponent(resolvedToken)}` : ""}`
          : `${scheme}://${hostPort}${pathPrefix}${path}${resolvedToken ? `?token=${encodeURIComponent(resolvedToken)}` : ""}`;

        console.log("[voice-ws] Connecting to:", resolvedWsUrl.replace(/token=[^&]+/, 'token=***'));

        const ws = new WebSocket(resolvedWsUrl);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;

        ws.onopen = () => {
          console.log("[voice-ws] Connected");
          setConnectionStatus("connected");
          setError("");
          isConnectingRef.current = false;
          // Reset reconnect backoff on successful connection
          reconnectAttemptsRef.current = 0;
          if (reconnectTimerRef.current) {
            clearTimeout(reconnectTimerRef.current);
            reconnectTimerRef.current = null;
          }
          resolve(ws);
        };

        ws.onerror = (event) => {
          console.error("[voice-ws] Connection error:", error);
          setConnectionStatus("disconnected");
          isConnectingRef.current = false;
          const hint = !resolvedToken 
            ? " The AI server requires authentication. Please check if the server is running and WS_AUTH_TOKEN is configured correctly."
            : "";
          setError(`Unable to connect to AI service.${hint}`);
          reject(new Error("WebSocket connection failed"));
        };

        // Updated WebSocket onmessage handler to properly process messages
        ws.onmessage = (event) => {
          if (typeof event.data === 'string') {
            let message;
            try {
              message = JSON.parse(event.data);
            } catch (e) {
              console.error('[voice-ws] Error parsing message:', e);
              return;
            }
            if (message.type === 'partial') {
              // Live partial transcript from streaming STT
              if (typeof message.text === 'string') {
                // Incremental update: attempt to append only the newly recognized suffix
                setLiveTranscript(prev => {
                  try {
                    const incoming = String(message.text || "");
                    if (!prev) return incoming;
                    // If incoming starts with what we already show, append the remainder
                    if (incoming.toLowerCase().startsWith(prev.toLowerCase())) {
                      const suffix = incoming.slice(prev.length).trimStart();
                      return (prev + (suffix ? (prev.endsWith(' ') ? '' : ' ') + suffix : '')).trimStart();
                    }
                    // Otherwise, replace (ASR restructured the phrase)
                    return incoming;
                  } catch (e) {
                    return String(message.text || "");
                  }
                });
              }
            } else if (message.type === 'final' || message.type === 'transcript') {
              const txt = (message.text || message.transcript || '').trim();
              if (txt) {
                setUserSpeech(txt);
                setLiveTranscript("");
                console.log('[voice-ws] Transcript updated:', txt);
              } else {
                console.log('[voice-ws] Received empty transcript.');
              }
            } else if (message.type === 'reply_delta') {
              const delta: string = message.text || message.delta || '';
              if (delta) {
                setAiResponse(prev => (prev + delta));
              }
            } else if (message.type === 'reply') {
              const txt = (message.text || message.reply || '').trim();
              console.log('[voice-ws] Received reply:', txt);
              setAiResponse(txt);
              // Do not force stop thinking here; wait for queued audio to finish.
            } else if (message.type === 'debug') {
              // Debug messages from server: normalization, timings, tts sizes, etc.
              console.log('[voice-ws][debug]', message);
            } else {
              console.warn('[voice-ws] Unhandled message:', message);
            }
          } else if (event.data instanceof ArrayBuffer) {
            console.log('[voice-ws] Received audio response of size:', event.data.byteLength);
            // Server currently returns ElevenLabs MP3 bytes by default
            enqueueAudioChunk(event.data, 'audio/mpeg');
          }
        };

        const scheduleReconnect = () => {
          // Do not auto-reconnect while actively recording; user action will reconnect
          if (isListening) return;
          const attempt = (reconnectAttemptsRef.current || 0) + 1;
          reconnectAttemptsRef.current = attempt;
          const delay = Math.min(30000, 1000 * Math.pow(2, attempt - 1)); // 1s,2s,4s,... up to 30s
          console.log(`[voice-ws] Scheduling reconnect (attempt ${attempt}) in ${delay}ms`);
          setConnectionStatus("connecting");
          if (reconnectTimerRef.current) {
            clearTimeout(reconnectTimerRef.current);
          }
          reconnectTimerRef.current = window.setTimeout(async () => {
            try {
              await connectWebSocket();
              setError("");
            } catch (e) {
              // Chain another attempt
              scheduleReconnect();
            }
          }, delay) as unknown as number;
        };

        ws.onclose = (event) => {
          console.log("[voice-ws] Disconnected:", event.code, event.reason);
          setConnectionStatus("disconnected");
          isConnectingRef.current = false;

          // If the server closed due to authentication (1008), attempt a
          // dev-friendly token refresh: ask the backend for ws-config and
          // retry connecting if a token is returned. This helps when the
          // AI service (which may hold the token) is started after the
          // frontend and Node proxy.
          if (event.code === 1008 || event.code === 1002) {
            setError("Authentication failed. Trying to refresh token...");
            (async () => {
              try {
                const cfg = await fetch('/api/ws-config').then(r => r.json()).catch(() => null);
                const newToken = cfg?.token || "";
                if (newToken) {
                  // persist for future attempts and retry
                  localStorage.setItem('WS_TOKEN', newToken);
                  console.log('[voice-ws] Discovered new WS token, retrying connection');
                  try {
                    await connectWebSocket();
                    setError("");
                    return;
                  } catch (e) {
                    console.warn('[voice-ws] Reconnect failed after token refresh', e);
                    scheduleReconnect();
                  }
                }
                // If we couldn't discover a token, show the authentication guidance
                setError('Authentication failed. Please verify the AI server is running and WS_AUTH_TOKEN is configured.');
                scheduleReconnect();
              } catch (e) {
                console.warn('[voice-ws] token refresh check failed', e);
                setError('Authentication failed. Please verify the AI server is running and WS_AUTH_TOKEN is configured.');
                scheduleReconnect();
              }
            })();
          } else if (event.code !== 1000) {
            setError("Connection lost. Please try again.");
            scheduleReconnect();
          }
        };
      } catch (err) {
        isConnectingRef.current = false;
        setConnectionStatus("disconnected");
        setError(err instanceof Error ? err.message : "Connection failed");
        reject(err);
      }
    });
  };

    const handleMicClick = async () => {
    if (isListening) {
      stopRecording();
    } else {
      await startRecording();
    }
  };

  const startRecording = async () => {
    try {
      setError("");
  setUserSpeech("");
  setLiveTranscript("");
  setAiResponse("");
      console.log("[voice-ws] Starting recording...");

      // Get microphone access, be less restrictive
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
        } 
      });

      // Connect WebSocket if not already connected
      let ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        ws = await connectWebSocket();
      }

      // Start speech recognition for live transcript (only if available and not using streaming)
      if (!useStreaming && speechRecognitionRef.current && srAvailable) {
        try {
          speechRecognitionRef.current.start();
          console.log("[voice-ws] Speech recognition started");
        } catch (e) {
          console.warn("[voice-ws] Could not start speech recognition:", e);
        }
      }

      // Setup audio recorder
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus'
      });
      
      audioChunksRef.current = [];

  // Prefer PCM streaming for low-latency partials when streaming is enabled.
  // Fall back to webm chunks only if Web Audio APIs are unavailable or fail.
  const pcmStreaming = useStreaming; // default: use PCM for streaming

      if (useStreaming && !pcmStreaming) {
        // Default streaming: webm chunks every ~300ms
        mediaRecorder.ondataavailable = (event) => {
          if (event.data && event.data.size > 0 && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(event.data);
          }
        };
      } else if (!useStreaming) {
        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            audioChunksRef.current.push(event.data);
          }
        };
      } else {
        // PCM streaming path via Web Audio ScriptProcessor
        try {
          const ctx = new (window.AudioContext || (window as any).webkitAudioContext)({});
          audioCtxRef.current = ctx;
          const src = ctx.createMediaStreamSource(stream);
          sourceRef.current = src;
          const bufferSize = 2048;
          const proc = ctx.createScriptProcessor(bufferSize, 1, 1);
          processorRef.current = proc as any;

          const targetRate = 16000;
          const fromRate = ctx.sampleRate || 48000;

          const resampleTo16k = (input: Float32Array): Int16Array => {
            if (fromRate === targetRate) {
              // Convert float32 [-1,1] to int16
              const out = new Int16Array(input.length);
              for (let i = 0; i < input.length; i++) {
                const s = Math.max(-1, Math.min(1, input[i]));
                out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
              }
              return out;
            }
            const ratio = fromRate / targetRate;
            const newLen = Math.round(input.length / ratio);
            const out = new Int16Array(newLen);
            let pos = 0;
            for (let i = 0; i < newLen; i++) {
              const idx = i * ratio;
              const i0 = Math.floor(idx);
              const i1 = Math.min(i0 + 1, input.length - 1);
              const t = idx - i0;
              const sample = (1 - t) * input[i0] + t * input[i1];
              const s = Math.max(-1, Math.min(1, sample));
              out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            return out;
          };

          proc.onaudioprocess = (e: AudioProcessingEvent) => {
            if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
            const input = e.inputBuffer.getChannelData(0);
            const pcm16 = resampleTo16k(input);
            wsRef.current.send(pcm16.buffer);
          };

          src.connect(proc);
          proc.connect(ctx.destination);
        } catch (err) {
          console.error('[voice-ws] PCM path failed, falling back to MediaRecorder webm', err);
          // Fallback to webm streaming
          mediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0 && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
              wsRef.current.send(event.data);
            }
          };
        }
      }

      mediaRecorder.onstop = async () => {
        console.log("[voice-ws] Recording stopped, processing...");
        setIsThinking(true);
        setLiveTranscript(""); // Clear live transcript

        // Stop speech recognition
        if (!useStreaming && speechRecognitionRef.current) {
          try {
            speechRecognitionRef.current.stop();
          } catch (_) {}
        }

        // Stop all media tracks to release the microphone
        stream.getTracks().forEach(track => track.stop());

        if (useStreaming) {
          // Tell server we're done so it can finalize transcript
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'stop' }));
          }
        } else {
          // Send the collected audio chunks (non-streaming flow)
          const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm;codecs=opus' });
          if (audioBlob.size > 0 && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            await processAndSendAudio(audioBlob, wsRef.current);
          } else {
            console.warn("[voice-ws] No audio data to send or WebSocket is not open.");
            setIsThinking(false);
          }
        }
        
        // Reset for next recording
        audioChunksRef.current = [];
      };

      mediaRecorderRef.current = mediaRecorder;
      // For streaming, request time-sliced chunks ~300ms
      // If we're not using PCM (i.e., we fell back to webm), request time-sliced chunks ~300ms
      if (useStreaming && !pcmStreaming) {
        mediaRecorder.start(300);
      } else {
        // PCM path doesn't use MediaRecorder slices; start without timeslice
        mediaRecorder.start();
      }
      setIsListening(true);
      startedAtRef.current = Date.now();
      console.log("[voice-ws] Recording started");
    } catch (err) {
      console.error("[voice-ws] Error:", err);
      setError(err instanceof Error ? err.message : "Failed to start recording");
      setIsListening(false);
      setLiveTranscript("");
    }
  };

  // New function to stop recording and speech recognition
  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    try {
      processorRef.current && (processorRef.current.disconnect(), (processorRef.current as any) = null);
      sourceRef.current && sourceRef.current.disconnect();
      audioCtxRef.current && audioCtxRef.current.close();
    } catch {}
    clearAudioQueue();
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach(t => t.stop());
    }
    if (!useStreaming && speechRecognitionRef.current) {
      speechRecognitionRef.current.stop();
    }
    setIsListening(false);
    setLiveTranscript("");
    console.log('[voice-ws] Recording stopped');
  };

  const processAndSendAudio = async (audioBlob: Blob, ws: WebSocket) => {
    try {
      if (audioBlob.size === 0) {
        console.warn("[voice-ws] Audio blob is empty, not sending.");
        setIsThinking(false);
        return;
      }
      
      console.log(`[voice-ws] Sending audio blob of size: ${audioBlob.size} bytes, type: ${audioBlob.type}`);
      
      // Directly send the blob as a binary message.
      // The backend server MUST be able to handle raw 'audio/webm;codecs=opus' blobs.
      ws.send(audioBlob);

    } catch (err) {
      console.error("[voice-ws] Error processing or sending audio:", err);
      setError("Failed to send audio for processing.");
      setIsThinking(false);
    }
  };

  const logConversation = async ({ transcript, reply, durationMs }: { transcript: string; reply: string; durationMs?: number; }) => {
    try {
      await fetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript, reply, durationMs, source: "voice" })
      });
    } catch (e) {
      console.warn("[voice-ws] failed to log conversation", e);
    }
  };

// These helper functions are no longer needed with direct blob sending.
/*
const createWavFile = (pcmData: Float32Array, sampleRate: number): ArrayBuffer => {
    const numChannels = 1;
    const bitsPerSample = 16;
    const bytesPerSample = bitsPerSample / 8;
    const blockAlign = numChannels * bytesPerSample;
    const byteRate = sampleRate * blockAlign;
    const dataLength = pcmData.length * bytesPerSample;
    
    const buffer = new ArrayBuffer(44 + dataLength);
    const view = new DataView(buffer);
    
    // RIFF header
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataLength, true);
    writeString(view, 8, 'WAVE');
    
    // fmt chunk
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitsPerSample, true);
    
    // data chunk
    writeString(view, 36, 'data');
    view.setUint32(40, dataLength, true);
    
    // Write PCM samples
    let offset = 44;
    for (let i = 0; i < pcmData.length; i++) {
      const sample = Math.max(-1, Math.min(1, pcmData[i]));
      const intSample = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
      view.setInt16(offset, intSample, true);
      offset += 2;
    }
    
    return buffer;
  };

  const writeString = (view: DataView, offset: number, string: string) => {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  };

  const arrayBufferToBase64 = (buffer: ArrayBuffer): string => {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      const chunk = bytes.subarray(i, i + chunkSize);
      binary += String.fromCharCode(...chunk);
    }
    return btoa(binary);
  };
*/

  const playAudioResponse = (audioData: ArrayBuffer) => {
    const audioBlob = new Blob([audioData], { type: 'audio/wav' });
    const audioUrl = URL.createObjectURL(audioBlob);
    const audio = new Audio(audioUrl);
    
    audio.onended = () => {
      URL.revokeObjectURL(audioUrl);
      console.log("[voice-ws] Audio playback finished");
    };
    
    audio.onerror = (err) => {
      console.error("[voice-ws] Audio playback error:", err);
      setError("Failed to play audio response");
    };
    
    audio.play().catch(err => {
      console.error("[voice-ws] Play error:", err);
      setError("Failed to play audio. Click to enable audio.");
    });
  };

  const getStatusIcon = () => {
    switch (connectionStatus) {
      case "connected":
        return <Wifi className="w-4 h-4 text-green-500" />;
      case "connecting":
        return <Loader2 className="w-4 h-4 text-yellow-500 animate-spin" />;
      default:
        return <WifiOff className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusText = () => {
    switch (connectionStatus) {
      case "connected":
        return "Connected";
      case "connecting":
        return "Connecting...";
      default:
        return "Disconnected";
    }
  };

  // Update the JSX returned by the component to ensure proper control of recording and live transcription
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-md z-50 flex items-center justify-center p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: 20 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="bg-gradient-to-br from-white to-gray-50 rounded-3xl shadow-2xl w-full max-w-2xl overflow-hidden relative"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="bg-gradient-to-r from-indigo-600 to-purple-600 px-8 py-6 text-white relative">
              <button
                onClick={onClose}
                className="absolute top-4 right-4 p-2 hover:bg-white/20 rounded-full transition-colors"
              >
                <X size={20} />
              </button>
              
              <div className="flex items-center justify-between pr-12">
                <div>
                  <h2 className="text-2xl font-bold flex items-center gap-2">
                    <span className="text-3xl">🎙️</span>
                    Talk with Klarvia
                  </h2>
                  <p className="text-indigo-100 text-sm mt-1">
                    Speak naturally and I'll respond
                  </p>
                </div>
              </div>

              {/* Connection Status */}
              <div className="flex items-center gap-2 mt-4 text-sm">
                {getStatusIcon()}
                <span className="text-indigo-100">{getStatusText()}</span>
              </div>
            </div>

            {/* Main Content */}
            <div className="p-8">
              {/* Error Message */}
              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl flex items-start gap-3"
                >
                  <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-red-800 text-sm font-medium">Connection Error</p>
                    <p className="text-red-600 text-sm mt-1">{error}</p>
                    <p className="text-red-500 text-xs mt-2">
                      Make sure the AI service is running: <code className="bg-red-100 px-2 py-0.5 rounded">uvicorn ai.server:app --reload --host 127.0.0.1 --port 8001</code>
                    </p>
                  </div>
                </motion.div>
              )}

              {/* Voice Interaction Area */}
              <div className="flex flex-col items-center justify-center py-8">
                {/* Microphone Button */}
                <motion.div
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  className="relative"
                >
                  <Button
                    onClick={isListening ? stopRecording : startRecording}
                    disabled={isThinking}
                    className={`w-28 h-28 rounded-full shadow-2xl transition-all duration-300 ${
                      isListening
                        ? "bg-gradient-to-br from-red-500 to-red-600 hover:from-red-600 hover:to-red-700 animate-pulse"
                        : isThinking
                        ? "bg-gradient-to-br from-purple-500 to-purple-600 cursor-not-allowed"
                        : "bg-gradient-to-br from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                    }`}
                  >
                    {isThinking ? (
                      <Loader2 className="w-12 h-12 animate-spin" />
                    ) : isListening ? (
                      <Mic className="w-12 h-12" />
                    ) : (
                      <Mic className="w-12 h-12" />
                    )}
                  </Button>
                  
                  {isListening && (
                    <motion.div
                      className="absolute inset-0 rounded-full border-4 border-red-400"
                      initial={{ scale: 1, opacity: 0.8 }}
                      animate={{ scale: 1.2, opacity: 0 }}
                      transition={{ repeat: Infinity, duration: 1.5 }}
                    />
                  )}
                </motion.div>

                {/* Status Text */}
                <p className="text-gray-600 mt-6 text-lg font-medium">
                  {isListening ? "Listening... Click to stop" : isThinking ? "Processing your request..." : "Click the microphone to start"}
                </p>

                {/* Transcript & Response Display */}
                <div className="w-full mt-8 space-y-4">
                  {/* User Speech */}
                  {userSpeech && (
                    <motion.div
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      className="bg-indigo-50 rounded-2xl p-5 border border-indigo-100"
                    >
                      <div className="flex items-start gap-3">
                        <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center flex-shrink-0">
                          <span className="text-white text-sm">You</span>
                        </div>
                        <div className="flex-1">
                          <p className="text-gray-700 leading-relaxed">{userSpeech}</p>
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {/* AI Response */}
                  {aiResponse && (
                    <motion.div
                      initial={{ opacity: 0, x: 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      className="bg-purple-50 rounded-2xl p-5 border border-purple-100"
                    >
                      <div className="flex items-start gap-3">
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-indigo-500 flex items-center justify-center flex-shrink-0">
                          <Volume2 className="w-4 h-4 text-white" />
                        </div>
                        <div className="flex-1">
                          <p className="text-gray-700 leading-relaxed">{aiResponse}</p>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </div>

                {/* Thinking Indicator */}
                {isThinking && <div className="text-sm text-gray-400">Klarvia is thinking...</div>}
                
                {/* Live Transcript */}
                {isListening && liveTranscript && (
                  <p className="text-lg text-gray-300">{liveTranscript}</p>
                )}

                {/* Final Transcript */}
                {userSpeech && !isListening && (
                  <div className="text-right text-white pr-4">
                    <span className="inline-block bg-blue-600 rounded-lg px-3 py-2">{userSpeech}</span>
                  </div>
                )}

                {/* AI Response */}
                {aiResponse && (
                  <div className="text-left text-white">
                    <span className="inline-block bg-gray-700 rounded-lg px-3 py-2">{aiResponse}</span>
                  </div>
                )}
              </div>

              {/* Help Text */}
              <div className="mt-6 pt-6 border-t border-gray-200">
                <p className="text-center text-sm text-gray-500">
                  <span className="font-medium">Tip:</span> Speak clearly and naturally. Klarvia will transcribe your speech, process it, and respond with voice.
                </p>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
