"use client";

import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Volume2, X, Loader2, Wifi, WifiOff, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface VoiceInterfaceProps {
  open: boolean;
  onClose: () => void;
}

export default function VoiceInterfaceWebSocket({ open, onClose }: VoiceInterfaceProps) {
  const [isListening, setIsListening] = useState(false);
  const [userSpeech, setUserSpeech] = useState("");
  const [aiResponse, setAiResponse] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [error, setError] = useState("");
  const [connectionStatus, setConnectionStatus] = useState<"disconnected" | "connecting" | "connected">("disconnected");
  
  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const isConnectingRef = useRef(false);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
    };
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

        const resolvedWsUrl = isLocal
          ? `${scheme}://127.0.0.1:8001/ws/audio${resolvedToken ? `?token=${encodeURIComponent(resolvedToken)}` : ""}`
          : `${scheme}://${hostPort}${pathPrefix}/ws/audio${resolvedToken ? `?token=${encodeURIComponent(resolvedToken)}` : ""}`;

        console.log("[voice-ws] Connecting to:", resolvedWsUrl.replace(/token=[^&]+/, 'token=***'));

        const ws = new WebSocket(resolvedWsUrl);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;

        ws.onopen = () => {
          console.log("[voice-ws] Connected");
          setConnectionStatus("connected");
          setError("");
          isConnectingRef.current = false;
          resolve(ws);
        };

        ws.onerror = (error) => {
          console.error("[voice-ws] Connection error:", error);
          setConnectionStatus("disconnected");
          isConnectingRef.current = false;
          
          const hint = !resolvedToken 
            ? " The AI server requires authentication. Please check if the server is running and WS_AUTH_TOKEN is configured correctly."
            : "";
          
          setError(`Unable to connect to AI service.${hint}`);
          reject(new Error("WebSocket connection failed"));
        };

        ws.onmessage = (event) => {
          if (typeof event.data === "string") {
            console.log("[voice-ws] Text message:", event.data);
            try {
              const data = JSON.parse(event.data);
              if (data.type === "transcript" && data.transcript) {
                setUserSpeech(data.transcript);
              }
              if (data.type === "reply" && data.reply) {
                setAiResponse(data.reply);
                
                // Log conversation to backend
                if (startedAtRef.current) {
                  const durationMs = Date.now() - startedAtRef.current;
                  logConversation({
                    transcript: data.transcript || userSpeech,
                    reply: data.reply,
                    durationMs
                  }).catch(err => console.warn("[voice-ws] Log failed:", err));
                }
              }
            } catch (e) {
              // Not JSON, might be status message
              if (event.data.includes("error")) {
                setError(event.data);
              }
            }
          } else {
            // Binary audio response
            console.log("[voice-ws] Received audio response");
            setIsThinking(false);
            playAudioResponse(event.data as ArrayBuffer);
          }
        };

        ws.onclose = (event) => {
          console.log("[voice-ws] Disconnected:", event.code, event.reason);
          setConnectionStatus("disconnected");
          isConnectingRef.current = false;
          
          if (event.code === 1008 || event.code === 1002) {
            setError("Authentication failed. Please verify the AI server configuration.");
          } else if (event.code !== 1000) {
            setError("Connection lost. Please try again.");
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
      setAiResponse("");
      console.log("[voice-ws] Starting recording...");

      // Get microphone access
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        } 
      });

      // Connect WebSocket if not already connected
      let ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        ws = await connectWebSocket();
      }

      // Setup audio recorder
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus'
      });
      
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        console.log("[voice-ws] Recording stopped, processing...");
        setIsListening(false);
        setIsThinking(true);

        // Stop all tracks
        stream.getTracks().forEach(track => track.stop());

        // Convert to WAV and send
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await processAndSendAudio(audioBlob, ws!);
      };

      mediaRecorderRef.current = mediaRecorder;
      mediaRecorder.start();
      setIsListening(true);
      startedAtRef.current = Date.now();
      console.log("[voice-ws] Recording started");
    } catch (err) {
      console.error("[voice-ws] Error:", err);
      setError(err instanceof Error ? err.message : "Failed to start recording");
      setIsListening(false);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
      console.log("[voice-ws] Stopping recording...");
    }
  };

  const processAndSendAudio = async (audioBlob: Blob, ws: WebSocket) => {
    try {
      // Decode audio to PCM
      const arrayBuffer = await audioBlob.arrayBuffer();
      const audioContext = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioContext;
      
      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
      
      // Resample to 16kHz mono
      const offlineContext = new OfflineAudioContext(
        1, // mono
        Math.ceil(audioBuffer.duration * 16000),
        16000
      );
      
      const source = offlineContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(offlineContext.destination);
      source.start();
      
      const resampled = await offlineContext.startRendering();
      const pcmData = resampled.getChannelData(0);
      
      // Create WAV file
      const wavBuffer = createWavFile(pcmData, 16000);
      
      // Encode to base64
      const base64 = arrayBufferToBase64(wavBuffer);
      
      console.log("[voice-ws] Sending audio:", wavBuffer.byteLength, "bytes");
      ws.send(base64);
    } catch (err) {
      console.error("[voice-ws] Error processing audio:", err);
      setError("Failed to process audio");
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
                    onClick={handleMicClick}
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
