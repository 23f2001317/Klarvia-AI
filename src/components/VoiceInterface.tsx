"use client";

import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Volume2, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface VoiceInterfaceProps {
  open: boolean;
  onClose: () => void;
}

export default function VoiceInterface({ open, onClose }: VoiceInterfaceProps) {
  const [isListening, setIsListening] = useState(false);
  const [userSpeech, setUserSpeech] = useState("");
  const [aiResponse, setAiResponse] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  // Initialize Speech Recognition
  useEffect(() => {
    if ("webkitSpeechRecognition" in window) {
      const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;
      const recognition = new SpeechRecognition();
      recognition.lang = "en-US";
      recognition.continuous = false;
      recognition.interimResults = false;

      recognition.onstart = () => {
        setIsListening(true);
        setUserSpeech("");
      };

      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        setUserSpeech(transcript);
      };

      recognition.onend = () => {
        setIsListening(false);
        if (userSpeech.trim() !== "") {
          handleAIResponse(userSpeech);
        }
      };

      recognitionRef.current = recognition;
    } else {
      console.warn("Speech recognition not supported in this browser.");
    }
  }, [userSpeech]);

  const handleMicClick = () => {
    if (!recognitionRef.current) return;

    if (isListening) {
      recognitionRef.current.stop();
    } else {
      recognitionRef.current.start();
      setAiResponse("");
    }
  };

  const handleAIResponse = async (text: string) => {
    setIsThinking(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await res.json().catch(() => ({}));
      const response =
        (data && (data.reply || data.message)) ||
        "Sorry, I couldn’t process that.";
      setAiResponse(response);
      speakResponse(response);
    } catch (err) {
      setAiResponse("Error connecting to AI.");
    } finally {
      setIsThinking(false);
    }
  };

  const speakResponse = (text: string) => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    speechSynthesis.speak(utterance);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.9, opacity: 0, y: 30 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.9, opacity: 0, y: 30 }}
            transition={{ type: "spring", duration: 0.5 }}
            className="bg-white rounded-3xl shadow-2xl w-full max-w-4xl p-10 mx-auto flex flex-col items-center justify-center relative"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={onClose}
              className="absolute top-4 right-4 text-gray-500 hover:text-gray-700"
            >
              <X size={24} />
            </button>

            <h2 className="text-3xl font-bold text-gray-800 mb-10 text-center">
              🎙️ Talk with Klarvia
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-10 w-full">
              {/* USER INPUT */}
              <div className="bg-indigo-50 border border-indigo-200 rounded-2xl p-8 shadow-md flex flex-col items-center justify-center text-center space-y-6">
                <h3 className="text-xl font-semibold text-indigo-700">
                  User Voice Input
                </h3>

                <Button
                  onClick={handleMicClick}
                  className={`w-16 h-16 rounded-full flex items-center justify-center ${
                    isListening
                      ? "bg-red-500 hover:bg-red-600"
                      : "bg-indigo-600 hover:bg-indigo-700"
                  } text-white shadow-lg transition-all`}
                >
                  {isListening ? (
                    <Loader2 className="animate-spin" size={26} />
                  ) : (
                    <Mic size={26} />
                  )}
                </Button>
                <p className="text-gray-600 text-base">
                  {isListening ? "Listening..." : "Tap to start speaking"}
                </p>

                {userSpeech && (
                  <p className="text-gray-700 italic mt-4 px-3 text-sm">
                    “{userSpeech}”
                  </p>
                )}
              </div>

              {/* AI RESPONSE */}
              <div className="bg-gray-50 border border-gray-200 rounded-2xl p-8 shadow-md flex flex-col items-center justify-center text-center space-y-6">
                <h3 className="text-xl font-semibold text-gray-700">
                  Klarvia’s Response
                </h3>

                <Button
                  disabled
                  className="w-16 h-16 rounded-full bg-gray-400 text-white flex items-center justify-center cursor-not-allowed"
                >
                  <Volume2 size={26} />
                </Button>

                {isThinking ? (
                  <p className="text-gray-600 text-base">Thinking...</p>
                ) : aiResponse ? (
                  <p className="text-gray-700 italic text-sm">“{aiResponse}”</p>
                ) : (
                  <p className="text-gray-600 text-base">
                    Waiting for your voice input...
                  </p>
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
