import { useState } from "react";

interface VoiceInterfaceProps {
  onSendMessage?: (message: string) => void;
}

const VoiceInterface: React.FC<VoiceInterfaceProps> = ({ onSendMessage }) => {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [aiResponse, setAiResponse] = useState("");

  // Start voice recognition
  const startListening = () => {
    if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
      alert("Your browser does not support Speech Recognition");
      return;
    }

    setListening(true);
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event: any) => {
      const speech = event.results[0][0].transcript;
      setTranscript(speech);
      sendToAI(speech);
      if (onSendMessage) onSendMessage(speech);
    };

    recognition.onerror = (err: any) => {
      console.error(err);
      setListening(false);
    };

    recognition.onend = () => setListening(false);

    recognition.start();
  };

  // Send text to AI backend and get voice response
  const sendToAI = async (text: string) => {
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      setAiResponse(data.reply);
      speak(data.reply);
    } catch (err) {
      console.error(err);
    }
  };

  // Play AI response as audio
  const speak = (text: string) => {
    const utterance = new SpeechSynthesisUtterance(text);
    window.speechSynthesis.speak(utterance);
  };

  return (
    <div className="voice-interface">
      <button onClick={startListening} className="voice-btn">
        {listening ? "Listening..." : "Talk to Klarvia"}
      </button>
      <p className="user-text">You: {transcript}</p>
      <p className="ai-text">Klarvia: {aiResponse}</p>
    </div>
  );
};

export default VoiceInterface;
