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

dotenv.config();

const app = express();
app.use(cors());
app.use(express.json());
app.use(cookieParser());
app.use("/api", routes);
app.use("/api/auth", authRoutes);
app.use("/api/db-inspector", dbInspectorRoutes);
app.use("/api/conversations", conversationsRoutes);
app.use("/api/ws-config", wsConfigRoute);

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

const port = process.env.PORT || 4000;
app.listen(port, () => {
  console.log(`Server listening on port ${port}`);
});
