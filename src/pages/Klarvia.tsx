"use client";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import VoiceInterface from "./VoiceInterface";

export default function Klarvia() {
  const [isVoiceOpen, setIsVoiceOpen] = useState(false);

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center text-white">
      {/* Background Video */}
      <video
        autoPlay
        muted
        loop
        playsInline
        className="absolute inset-0 w-full h-full object-cover -z-10"
      >
        <source src="/videos/bg.mp4" type="video/mp4" />
      </video>

      {/* Overlay Gradient */}
      <div className="absolute inset-0 bg-gradient-to-b from-black/70 via-black/60 to-black/90 -z-10"></div>

      {/* Content */}
      <motion.div
        className="text-center space-y-6 z-10"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 1 }}
      >
        <h1 className="text-5xl font-bold tracking-tight">
          Meet <span className="text-blue-400">Klarvia</span>
        </h1>
        <p className="text-lg text-gray-300 max-w-2xl mx-auto">
          Your intelligent voice assistant — always ready to listen, understand, and help you.
        </p>
        <Button
          size="lg"
          onClick={() => setIsVoiceOpen(true)}
          className="bg-blue-500 hover:bg-blue-600 text-white rounded-full px-6 py-3"
        >
          Start Conversation
        </Button>
      </motion.div>

      {/* Voice Modal */}
      {isVoiceOpen && (
        <VoiceInterface onClose={() => setIsVoiceOpen(false)} />
      )}
    </div>
  );
}
