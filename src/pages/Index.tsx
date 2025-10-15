import { useState } from "react";
import { Mic } from "lucide-react";
import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import HeroSection from "@/components/home/HeroSection";
import FeaturesSection from "@/components/home/FeaturesSection";
import SecurityPrivacySection from "@/components/home/SecurityPrivacySection";
import VoiceInterface from "@/components/VoiceInterfaceWebSocket";
import { Button } from "@/components/ui/button";

const Index = () => {
  const [isVoiceOpen, setIsVoiceOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <Navbar />
      <HeroSection />
      <FeaturesSection />
      <SecurityPrivacySection />
      <Footer />

      {/* Floating Action Button for Voice */}
      <div className="fixed bottom-8 right-8 z-40">
        <Button
          onClick={() => setIsVoiceOpen(true)}
          className="w-16 h-16 rounded-full bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg flex items-center justify-center"
        >
          <Mic size={28} />
        </Button>
      </div>

      <VoiceInterface open={isVoiceOpen} onClose={() => setIsVoiceOpen(false)} />
    </div>
  );
};

export default Index;
