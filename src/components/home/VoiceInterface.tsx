// Re-export the WebSocket-based VoiceInterface to avoid Web Speech API dependency
// and ensure offline/local operation for Klarvia voice interactions.
export { default } from "@/components/VoiceInterfaceWebSocket";
