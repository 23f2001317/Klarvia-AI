import { useState } from "react";
import VoiceInterface from "../components/VoiceInterface"; // Correct path
import { Button } from "@/components/ui/button";

export default function Klarvia() {
  const [messages, setMessages] = useState<{ user: string; ai: string }[]>([]);

  const handleSendMessage = (userMessage: string) => {
    setMessages([...messages, { user: userMessage, ai: "" }]);
  };

  return (
    <div className="klarvia-page">
      {/* Background video */}
      <video autoPlay loop muted className="background-video">
        <source src="/video.mp4" type="video/mp4" />
      </video>

      <div className="klarvia-container">
        <VoiceInterface onSendMessage={handleSendMessage} />
        <div className="chat-history">
          {messages.map((msg, idx) => (
            <div key={idx} className="chat-msg">
              <p className="user">You: {msg.user}</p>
              <p className="ai">Klarvia: {msg.ai}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
