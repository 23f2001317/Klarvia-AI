"use client";

import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import { Button } from "@/components/ui/button";
import VoiceInterface from "@/components/home/VoiceInterface";
import { motion } from "framer-motion";
import { useAuth } from "@/contexts/AuthContext";
import { useState } from "react";

export default function Klarvia() {
  const { user, loading } = useAuth();
  const [isVoiceOpen, setIsVoiceOpen] = useState(false);

  return (
    <div className="min-h-screen relative overflow-hidden flex flex-col">
      {/* Background Video */}
      <div className="fixed inset-0 z-0">
        <video
          autoPlay
          loop
          muted
          playsInline
          className="w-full h-full object-cover opacity-20"
        >
          <source src="/background-video.mp4" type="video/mp4" />
        </video>
        <div className="absolute inset-0 bg-gradient-to-b from-background/80 via-background/60 to-background/80" />
      </div>

      <div className="relative z-10 flex flex-col min-h-screen">
        <Navbar />

        <div className="flex-grow flex items-center justify-center px-4">
          {!loading && (
            <div className="text-center max-w-5xl mx-auto px-6 py-12">
              <motion.h2
                className="text-5xl md:text-6xl font-bold mb-6 text-primary"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6 }}
              >
                Meet Klarvia
              </motion.h2>

              <motion.p
                className="text-muted-foreground mb-10 max-w-2xl mx-auto text-lg md:text-xl"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.15 }}
              >
                Have a natural voice conversation with Klarvia — your AI
                companion for workplace wellbeing.
              </motion.p>

              <Button
                onClick={() => setIsVoiceOpen(true)}
                size="lg"
                className="px-10 py-5 text-lg bg-primary hover:bg-primary/90 rounded-full shadow-lg"
              >
                Start Conversation
              </Button>

              <p className="text-sm text-gray-500 mt-3">
                Click Start to open Klarvia’s voice interface.
              </p>
            </div>
          )}
        </div>

        <Footer />
      </div>

      {/* Voice Modal */}
      <VoiceInterface open={isVoiceOpen} onClose={() => setIsVoiceOpen(false)} />
    </div>
  );
}
