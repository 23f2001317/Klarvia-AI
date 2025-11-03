import express, { Request, Response } from "express";
import multer from "multer";
import path from "path";
import fs from "fs";
import {
  ensureTmpDir,
  runVoicePipeline,
  transcribeAudioWithAssemblyAI,
  generateOpenAIResponse,
  synthesizeWithElevenLabs,
  appendConversationLog,
} from "./voicebot";

const router = express.Router();

const uploadDir = ensureTmpDir();
const upload = multer({ dest: uploadDir });

function missingEnv(keys: string[]): string[] {
  return keys.filter((k) => !process.env[k] || String(process.env[k]).trim() === "");
}

function hasOpenAIProvider(): boolean {
  // Either an OpenAI API key or a local AI_CHAT_URL proxy can serve as the model backend
  const hasKey = !!process.env.OPENAI_API_KEY && String(process.env.OPENAI_API_KEY).trim() !== "";
  const hasProxy = !!process.env.AI_CHAT_URL && String(process.env.AI_CHAT_URL).trim() !== "";
  return hasKey || hasProxy;
}

// Unified pipeline endpoint
router.post("/voicebot", upload.single("audio"), async (req: Request, res: Response) => {
  try {
    const miss = missingEnv(["ASSEMBLYAI_API_KEY", "ELEVENLABS_API_KEY"]);
    if (miss.length) {
      return res.status(401).json({ error: `Missing environment variables: ${miss.join(", ")}` });
    }
    if (!hasOpenAIProvider()) {
      return res.status(401).json({ error: `Missing environment variables: OPENAI_API_KEY or AI_CHAT_URL (local model)` });
    }
  const file = (req as any).file as any;
    if (!file) return res.status(400).json({ error: "audio file is required (field: audio)" });
    let result;
    try {
      result = await runVoicePipeline(file.path);
    } catch (err: any) {
      console.error("runVoicePipeline failed", err);
      // If the underlying error was an upstream/network error, return 502
      if (err && (err.upstream || String(err.message).toLowerCase().includes("proxy") || String(err.message).toLowerCase().includes("connect ec"))) {
        return res.status(502).json({ error: "Upstream service error", detail: err.message });
      }
      return res.status(500).json({ error: err?.message || "internal error" });
    }
    if (result.user_transcript && result.bot_reply) {
      await appendConversationLog(result.user_transcript, result.bot_reply);
    }

    // Ensure audio_url is absolute so the browser (running on a different origin/port)
    // fetches the media from this backend server instead of the frontend dev server.
    if (result.audio_url && typeof result.audio_url === "string" && !result.audio_url.startsWith("http")) {
      const proto = (req.protocol as string) || (req.get("x-forwarded-proto") as string) || "http";
      const host = req.get("host");
      if (host) result.audio_url = `${proto}://${host}${result.audio_url}`;
    }

    return res.json(result);
  } catch (err: any) {
    console.error("/voicebot error", err);
    return res.status(500).json({ error: err?.message || "internal error" });
  }
});

// Separate steps if needed by frontend
router.post("/transcribe_audio", upload.single("audio"), async (req: Request, res: Response) => {
  try {
    const miss = missingEnv(["ASSEMBLYAI_API_KEY"]);
    if (miss.length) {
      return res.status(401).json({ error: `Missing environment variables: ${miss.join(", ")}` });
    }
  const file = (req as any).file as any;
    if (!file) return res.status(400).json({ error: "audio file is required (field: audio)" });
    const text = await transcribeAudioWithAssemblyAI(file.path);
    try { await fs.promises.unlink(file.path); } catch {}
    return res.json({ transcript: text });
  } catch (err: any) {
    console.error("/transcribe_audio error", err);
    return res.status(500).json({ error: err?.message || "internal error" });
  }
});

router.post("/generate_response", async (req: Request, res: Response) => {
  try {
    if (!hasOpenAIProvider()) {
      return res.status(401).json({ error: `Missing environment variables: OPENAI_API_KEY or AI_CHAT_URL (local model)` });
    }
    const { text } = req.body || {};
    if (!text || typeof text !== "string") return res.status(400).json({ error: "text is required" });
    const reply = await generateOpenAIResponse(text);
    return res.json({ reply });
  } catch (err: any) {
    console.error("/generate_response error", err);
    return res.status(500).json({ error: err?.message || "internal error" });
  }
});

router.post("/generate_voice", async (req: Request, res: Response) => {
  try {
    const miss = missingEnv(["ELEVENLABS_API_KEY"]);
    if (miss.length) {
      return res.status(401).json({ error: `Missing environment variables: ${miss.join(", ")}` });
    }
    const { text } = req.body || {};
    if (!text || typeof text !== "string") return res.status(400).json({ error: "text is required" });
    const { urlPath } = await synthesizeWithElevenLabs(text);
    let audio_url = urlPath;
    if (audio_url && !audio_url.startsWith("http")) {
      const proto = (req.protocol as string) || (req.get("x-forwarded-proto") as string) || "http";
      const host = req.get("host");
      if (host) audio_url = `${proto}://${host}${audio_url}`;
    }
    return res.json({ audio_url });
  } catch (err: any) {
    console.error("/generate_voice error", err);
    return res.status(500).json({ error: err?.message || "internal error" });
  }
});

export default router;
