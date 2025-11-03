import fs from "fs";
import path from "path";
import { randomUUID } from "crypto";

// Use built-in fetch (Node 18+)

export interface VoicebotResult {
  user_transcript: string;
  bot_reply: string;
  audio_url: string;
}

const TMP_DIR = path.join(process.cwd(), "server", "tmp_audio");
export function ensureTmpDir() {
  if (!fs.existsSync(TMP_DIR)) fs.mkdirSync(TMP_DIR, { recursive: true });
  return TMP_DIR;
}

export async function transcribeAudioWithAssemblyAI(filePath: string): Promise<string> {
  const apiKey = process.env.ASSEMBLYAI_API_KEY || process.env.ASSEMBLYAI_TOKEN;
  if (!apiKey) throw new Error("ASSEMBLYAI_API_KEY is missing");

  // 1) Upload file
  const uploadUrl = "https://api.assemblyai.com/v2/upload";
  const fileBuf = await fs.promises.readFile(filePath);
  const uploadResp = await fetch(uploadUrl, {
    method: "POST",
    headers: { Authorization: apiKey },
    // Cast for TS; Node 18 fetch accepts Buffer/Uint8Array
    body: fileBuf as any,
  });
  if (!uploadResp.ok) {
    const errText = await uploadResp.text();
    throw new Error(`AssemblyAI upload failed: ${uploadResp.status} ${errText}`);
  }
  const { upload_url } = (await uploadResp.json()) as { upload_url: string };

  // 2) Request transcript
  const transcribeResp = await fetch("https://api.assemblyai.com/v2/transcript", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: apiKey },
    body: JSON.stringify({ audio_url: upload_url })
  });
  if (!transcribeResp.ok) {
    const errText = await transcribeResp.text();
    throw new Error(`AssemblyAI transcribe create failed: ${transcribeResp.status} ${errText}`);
  }
  const { id } = (await transcribeResp.json()) as { id: string };

  // 3) Poll until completed
  for (;;) {
    await new Promise(r => setTimeout(r, 1200));
    const statusResp = await fetch(`https://api.assemblyai.com/v2/transcript/${id}`, {
      headers: { Authorization: apiKey }
    });
    if (!statusResp.ok) {
      const errText = await statusResp.text();
      throw new Error(`AssemblyAI status failed: ${statusResp.status} ${errText}`);
    }
    const statusData = await statusResp.json();
    if (statusData.status === "completed") {
      return (statusData.text as string) || "";
    }
    if (statusData.status === "error") {
      throw new Error(`AssemblyAI error: ${statusData.error}`);
    }
    // statuses: queued, processing
  }
}

export async function generateOpenAIResponse(prompt: string): Promise<string> {
  const apiKey = process.env.OPENAI_API_KEY;
  const model = process.env.OPENAI_MODEL || "gpt-4o-mini";

  // If an OpenAI API key is present, call OpenAI REST API. Otherwise forward to AI_CHAT_URL (local model service).
  if (apiKey && String(apiKey).trim() !== "") {
    // Use REST to avoid SDK initialization overhead
    const resp = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: "You are Klarvia, a concise, friendly voice assistant." },
          { role: "user", content: prompt }
        ],
        temperature: 0.6,
        max_tokens: 256,
      }),
    });
    if (!resp.ok) {
      const err = await resp.text();
      throw new Error(`OpenAI error: ${resp.status} ${err}`);
    }
    const data = await resp.json();
    return data.choices?.[0]?.message?.content || "";
  }

  // Fallback to local AI chat proxy
  const aiUrl = process.env.AI_CHAT_URL;
  if (!aiUrl) throw new Error("No OpenAI API key and no AI_CHAT_URL configured");
  let r;
  try {
    r = await fetch(aiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: prompt }),
    });
  } catch (e: any) {
    // Network-level failure (connection refused, DNS, etc.)
    const code = e?.code || (e?.cause && e.cause.code) || "FETCH_ERROR";
    const msg = e?.message || String(e);
    const err = new Error(`AI proxy fetch failed (${code}): ${msg}`);
    // Attach a marker so callers can map to 502
    (err as any).upstream = true;
    throw err;
  }
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    const err = new Error(`AI proxy error: ${r.status} ${detail}`);
    (err as any).upstream = true;
    throw err;
  }
  const j = await r.json().catch(() => ({}));
  // support multiple shapes: {reply} or {reply: {text}} or {text}
  return (j.reply && (typeof j.reply === "string" ? j.reply : j.reply.text)) || j.text || "";
}

export async function synthesizeWithElevenLabs(text: string): Promise<{ filePath: string; urlPath: string; }>{
  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) throw new Error("ELEVENLABS_API_KEY is missing");
  // Prefer explicit voice id if provided, else fallback to Rachel (public demo voice)
  const voiceId = process.env.ELEVENLABS_VOICE_ID || "21m00Tcm4TlvDq8ikWAM"; // Rachel

  const outDir = ensureTmpDir();
  const id = randomUUID();
  // Map friendly format names to ElevenLabs supported output_format tokens
  const fmtEnv = (process.env.TTS_AUDIO_FORMAT || "mp3").toLowerCase();
  let outputFormat = "mp3_44100_128"; // default high-quality mp3
  let ext = "mp3";
  if (fmtEnv === "mp3") {
    outputFormat = "mp3_44100_128";
    ext = "mp3";
  } else if (fmtEnv === "wav" || fmtEnv === "pcm") {
    // request raw PCM and we'll wrap into a WAV container for compatibility
    outputFormat = "pcm_16000";
    ext = "wav";
  } else if (fmtEnv.startsWith("opus")) {
    outputFormat = "opus_48000_64";
    ext = "opus";
  } else if (fmtEnv.startsWith("pcm_")) {
    outputFormat = fmtEnv; // e.g. pcm_16000
    ext = "wav";
  } else if (fmtEnv.startsWith("mp3_")) {
    outputFormat = fmtEnv;
    ext = "mp3";
  } else {
    // fallback
    outputFormat = "mp3_44100_128";
    ext = "mp3";
  }

  const filename = `${id}.${ext}`;
  const filePath = path.join(outDir, filename);

  const url = `https://api.elevenlabs.io/v1/text-to-speech/${encodeURIComponent(voiceId)}?optimize_streaming_latency=0&output_format=${encodeURIComponent(outputFormat)}`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "xi-api-key": apiKey,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text, model_id: "eleven_multilingual_v2" })
  });
  if (!r.ok) {
    const err = await r.text();
    throw new Error(`ElevenLabs TTS failed: ${r.status} ${err}`);
  }
  const buf = Buffer.from(await r.arrayBuffer());
  // If ElevenLabs returned raw PCM (pcm_*), wrap into a WAV container so browsers can play it.
  if (outputFormat.startsWith("pcm_")) {
    // extract sample rate from token like pcm_16000
    const parts = outputFormat.split("_");
    const sampleRate = parseInt(parts[1]) || 16000;
    const wavBuf = pcmToWav(buf, sampleRate, 1, 16);
    await fs.promises.writeFile(filePath, wavBuf);
  } else {
    await fs.promises.writeFile(filePath, buf);
  }
  // Served via /media route
  const urlPath = `/media/${filename}`;
  return { filePath, urlPath };
}

function pcmToWav(pcm: Buffer, sampleRate = 16000, channels = 1, bitDepth = 16) {
  const bytesPerSample = bitDepth / 8;
  const blockAlign = channels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = pcm.length;
  const buffer = Buffer.alloc(44 + dataSize);

  // RIFF header
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVE", 8);

  // fmt subchunk
  buffer.write("fmt ", 12);
  buffer.writeUInt32LE(16, 16); // Subchunk1Size (16 for PCM)
  buffer.writeUInt16LE(1, 20); // AudioFormat PCM = 1
  buffer.writeUInt16LE(channels, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(byteRate, 28);
  buffer.writeUInt16LE(blockAlign, 32);
  buffer.writeUInt16LE(bitDepth, 34);

  // data subchunk
  buffer.write("data", 36);
  buffer.writeUInt32LE(dataSize, 40);

  // copy pcm data
  pcm.copy(buffer, 44);
  return buffer;
}

export async function runVoicePipeline(filePath: string): Promise<VoicebotResult> {
  const user_transcript = (await transcribeAudioWithAssemblyAI(filePath)).trim();
  let bot_reply = user_transcript ? (await generateOpenAIResponse(user_transcript)).trim() : "";

  // Detect simple echo fallback from the local AI proxy (e.g. "You said: <transcript>")
  // or cases where the model simply repeats the transcript. In those cases, treat
  // it as no reply so the frontend doesn't show duplicate text.
  try {
    const normalizedReply = (bot_reply || "").replace(/\s+/g, " ").trim();
    const normalizedTranscript = (user_transcript || "").replace(/\s+/g, " ").trim();
    if (
      normalizedReply === normalizedTranscript ||
      normalizedReply === `You said: ${normalizedTranscript}` ||
      normalizedReply === `You said:${normalizedTranscript}`
    ) {
      // Instead of completely hiding the reply, return a short friendly hint so the UI
      // can surface why there's no assistant response (useful in dev when no model is configured).
      bot_reply = "No assistant configured. Set OPENAI_API_KEY or AI_CHAT_URL to enable responses.";
    }
  } catch (e) {
    // non-fatal normalization error — ignore and proceed
  }

  let audio_url = "";
  if (bot_reply) {
    const tts = await synthesizeWithElevenLabs(bot_reply);
    audio_url = tts.urlPath;
  }
  // Clean temp input
  try { await fs.promises.unlink(filePath); } catch {}

  return { user_transcript, bot_reply, audio_url };
}

export async function appendConversationLog(transcript: string, reply: string) {
  try {
    const line = `${new Date().toISOString()}\tuser: ${transcript}\n${new Date().toISOString()}\tai: ${reply}\n`;
    const logPath = path.join(process.cwd(), "server", "voice_history.log");
    await fs.promises.appendFile(logPath, line, { encoding: "utf-8" });
  } catch {}
}
