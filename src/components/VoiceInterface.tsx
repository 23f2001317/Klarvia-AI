"use client";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useEffect, useRef } from "react";
import { Mic, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function VoiceInterface({ onClose }: { onClose: () => void }) {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [aiResponse, setAiResponse] = useState("");
  const recognitionRef = useRef<any>(null);

  // --- Voice recognition setup ---
  useEffect(() => {
    if (typeof window !== "undefined") {
      const SpeechRecognition =
        (window as any).SpeechRecognition ||
        (window as any).webkitSpeechRecognition;

      if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.lang = "en-US";
        recognition.interimResults = false;
        recognition.continuous = false;

        recognition.onresult = (event: any) => {
          const text = event.results[0][0].transcript;
          setTranscript(text);
          handleSendToAI(text);
        };

        recognition.onerror = (err: any) => {
          console.error("Speech recognition error:", err);
          setIsListening(false);
        };

        recognitionRef.current = recognition;
      }
    }
  }, []);

  // --- Start / Stop Listening ---
  const handleMicClick = () => {
    if (!recognitionRef.current) return alert("Speech recognition not supported");
    if (isListening) {
      recognitionRef.current.stop();
      setIsListening(false);
    } else {
      setTranscript("");
      setAiResponse("");
      setIsListening(true);
      recognitionRef.current.start();
    }
  };

  // --- Send text to AI endpoint ---
  const handleSendToAI = async (text: string) => {
    setIsListening(false);
    setAiResponse("Thinking...");
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      setAiResponse(data.reply || "No response received.");
    } catch (err) {
      console.error("AI error:", err);
      setAiResponse("Sorry, something went wrong.");
    }
  };

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 bg-black/70 backdrop-blur-md flex items-center justify-center z-50"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <motion.div
          className="bg-gradient-to-b from-gray-900 to-gray-800 p-8 rounded-2xl shadow-2xl max-w-md w-full text-center border border-gray-700"
          initial={{ scale: 0.9, opacity: 0, y: 30 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.9, opacity: 0 }}
          transition={{ type: "spring", stiffness: 120, damping: 12 }}
        >
          {/* Close Button */}
          <button
            onClick={onClose}
            className="absolute top-4 right-4 text-gray-400 hover:text-white"
          >
            <X size={22} />
          </button>

          <h2 className="text-2xl font-semibold mb-4">Talk to Klarvia</h2>

          {/* Mic Button */}
          <div className="flex justify-center my-6">
            <Button
              onClick={handleMicClick}
              className={`rounded-full p-6 transition-all ${
                isListening ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"
              }`}
            >
              {isListening ? <Loader2 className="animate-spin" /> : <Mic size={32} />}
            </Button>
          </div>

          {/* Transcript */}
          {transcript && (
            <p className="text-gray-300 mt-3 italic">You said: “{transcript}”</p>
          )}

          {/* AI Response */}
          {aiResponse && (
            <motion.div
              className="mt-4 bg-gray-900/60 p-4 rounded-xl text-gray-200"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <p>{aiResponse}</p>
            </motion.div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
