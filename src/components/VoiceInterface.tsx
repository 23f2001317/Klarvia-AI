"use client";

import { useState, useRef } from "react";
import { Mic, Loader2, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function VoiceInterface() {
  const [isListening, setIsListening] = useState(false);
  const [userTranscript, setUserTranscript] = useState("");
  const [klarviaResponse, setKlarviaResponse] = useState("");
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  const handleStartListening = () => {
    if (!("webkitSpeechRecognition" in window)) {
      alert("Speech recognition not supported in this browser.");
      return;
    }

    const SpeechRecognition =
      window.SpeechRecognition || (window as any).webkitSpeechRecognition;
    const recognition = new SpeechRecognition();

    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    recognition.onstart = () => setIsListening(true);
    recognition.onerror = (e) => {
      console.error("Speech recognition error:", e);
      setIsListening(false);
    };
    recognition.onend = () => setIsListening(false);

    recognition.onresult = async (event: SpeechRecognitionEvent) => {
      const transcript = event.results[0][0].transcript;
      setUserTranscript(transcript);
      setIsListening(false);
      await sendToKlarvia(transcript);
    };

    recognitionRef.current = recognition;
    recognition.start();
  };

  const sendToKlarvia = async (message: string) => {
    setKlarviaResponse("...");
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });

      const data = await response.json();
      const reply = data.reply || "Klarvia couldn’t understand that.";
      setKlarviaResponse(reply);
      speakResponse(reply);
    } catch (error) {
      console.error("Error communicating with Klarvia:", error);
      setKlarviaResponse("Error communicating with Klarvia.");
    }
  };

  const speakResponse = (text: string) => {
    const synth = window.speechSynthesis;
    if (!synth) return;
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "en-US";
    synth.speak(utter);
  };

  return (
    <div className="flex flex-col items-center justify-center mt-8 space-y-8">
      <h2 className="text-3xl font-semibold text-gray-800 flex items-center space-x-2">
        <Mic className="text-indigo-600" />
        <span>Talk with Klarvia</span>
      </h2>

      <div className="flex flex-col md:flex-row items-center justify-center gap-8">
        {/* User Voice Input */}
        <div className="bg-indigo-50 border border-indigo-100 rounded-2xl p-6 w-72 text-center shadow-md">
          <h3 className="font-semibold text-indigo-700 mb-3">User Voice Input</h3>

          <Button
            onClick={handleStartListening}
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-full p-4 w-14 h-14 flex items-center justify-center mx-auto"
          >
            {isListening ? (
              <Loader2 className="h-6 w-6 animate-spin" />
            ) : (
              <Mic className="h-6 w-6" />
            )}
          </Button>

          <p className="mt-4 text-sm text-gray-600">
            {isListening
              ? "Listening..."
              : userTranscript
              ? `"${userTranscript}"`
              : "Tap to start speaking"}
          </p>
        </div>

        {/* Klarvia's Response */}
        <div className="bg-gray-50 border border-gray-200 rounded-2xl p-6 w-72 text-center shadow-md">
          <h3 className="font-semibold text-gray-700 mb-3">Klarvia’s Response</h3>

          <div className="flex justify-center mb-3">
            <Volume2 className="text-gray-500 h-6 w-6" />
          </div>

          <p className="text-sm text-gray-600 min-h-[48px] transition-all">
            {klarviaResponse
              ? klarviaResponse
              : "Waiting for your voice input..."}
          </p>
        </div>
      </div>
    </div>
  );
}
