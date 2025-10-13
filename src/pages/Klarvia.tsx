"use client";

import VoiceInterface from "@/components/VoiceInterface";

export default function Klarvia() {
  return (
    <section className="flex flex-col items-center justify-center min-h-screen bg-gradient-to-b from-blue-50 to-white px-6 py-12">
      <div className="max-w-4xl text-center">
        {/* Heading Section */}
        <h1 className="text-4xl md:text-5xl font-bold text-gray-800 mb-4">
          Meet <span className="text-indigo-600">Klarvia</span>
        </h1>
        <p className="text-gray-600 text-lg mb-8">
          Have a natural voice conversation with Klarvia — your AI companion for workplace wellbeing.
        </p>

        {/* Embedded Voice Interface */}
        <VoiceInterface />

        {/* Footer note */}
        <p className="text-sm text-gray-400 mt-8">
          Click the mic to start talking with Klarvia.
        </p>
      </div>
    </section>
  );
}
