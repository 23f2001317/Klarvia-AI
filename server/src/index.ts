import express, { Request, Response, NextFunction } from "express";
import cors from "cors";
import dotenv from "dotenv";
import { pool } from "./db";
import routes from "./routes";
import authRoutes from "./authRoutes";
import dbInspectorRoutes from "./dbInspectorRoutes";
import conversationsRoutes from "./conversationsRoutes";
import wsConfigRoute from "./wsConfigRoute";
import cookieParser from "cookie-parser";
import voicebotRoutes from "./voicebotRoutes";
import path from "path";

// Load env from multiple locations to support different setups
// 1) server/.env (default)
dotenv.config();
// 2) project root .env
dotenv.config({ path: path.resolve(__dirname, "..", "..", ".env") });
// 3) voicebot/.env (Python service keys)
dotenv.config({ path: path.resolve(__dirname, "..", "..", "voicebot", ".env") });

const app = express();
app.use(cors());
app.use(express.json());
// Return clearer errors for malformed JSON bodies (body-parser SyntaxError)
app.use((err: any, _req: Request, res: Response, next: NextFunction) => {
  if (err && err.type === 'entity.parse.failed') {
    console.error('JSON parse error:', err.message);
    return res.status(400).json({ error: 'Invalid JSON payload', detail: err.message });
  }
  next(err);
});
app.use(cookieParser());
app.use("/api", routes);
app.use("/api/auth", authRoutes);
app.use("/api/db-inspector", dbInspectorRoutes);
app.use("/api/conversations", conversationsRoutes);
app.use("/api/ws-config", wsConfigRoute);
app.use("/api", voicebotRoutes);

// Serve generated TTS audio files
const mediaDir = path.join(process.cwd(), "server", "tmp_audio");
app.use("/media", express.static(mediaDir, { maxAge: 0 }));

// Proxy /api/chat to the Python AI service to keep a single API surface
const AI_CHAT_URL = process.env.AI_CHAT_URL || "http://127.0.0.1:8001/chat";
app.post("/api/chat", async (req: Request, res: Response) => {
  try {
    const text = (req.body?.text || "").trim();
    if (!text) {
      return res.status(400).json({ error: "text is required" });
    }
    // Forward to Python service
    const r = await fetch(AI_CHAT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      console.error("/api/chat upstream error", r.status, data);
      return res.status(502).json({ error: "upstream error", detail: data });
    }
    return res.json(data);
  } catch (err) {
    console.error("/api/chat error", err);
    return res.status(500).json({ error: "internal error" });
  }
});

app.get("/health", async (req: Request, res: Response) => {
  try {
    const client = await pool.connect();
    await client.query('SELECT 1');
    client.release();
    res.json({ status: "ok" });
  } catch (err) {
    console.error("/health check failed:", err);
    res.status(500).json({ status: "error", error: String(err) });
  }
});

// Basic error handler
app.use((err: any, _req: Request, res: Response, _next: NextFunction) => {
  console.error(err);
  res.status(500).json({ error: "Internal Server Error" });
});

// Prefer explicit server-specific port variables to avoid conflicts with root .env PORT
const chosenPort = Number(process.env.SERVER_PORT || process.env.API_PORT || 4000);
if (process.env.PORT && Number(process.env.PORT) !== chosenPort) {
  console.warn(
    `Ignoring PORT=${process.env.PORT} in favor of SERVER_PORT/API_PORT=${chosenPort} to avoid conflicts with other services.`
  );
}
app.listen(chosenPort, () => {
  console.log(`Server listening on port ${chosenPort}`);
});
