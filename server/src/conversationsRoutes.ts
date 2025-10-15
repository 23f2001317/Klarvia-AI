import { Router, Request, Response } from "express";
import { pool } from "./db";

const router = Router();

// Create a new conversation log
router.post("/", async (req: Request, res: Response) => {
  try {
    const { userId, source = "voice", transcript, reply, durationMs } = req.body || {};
    if (!transcript || !reply) {
      return res.status(400).json({ error: "transcript and reply are required" });
    }
    const result = await pool.query(
      `INSERT INTO conversations (user_id, source, transcript, reply, duration_ms)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, created_at`,
      [userId ?? null, source, transcript, reply, durationMs ?? null]
    );
    res.json({ id: result.rows[0].id, created_at: result.rows[0].created_at });
  } catch (err) {
    console.error("[conversations] create error", err);
    res.status(500).json({ error: "internal error" });
  }
});

// List recent conversations (optional filters later)
router.get("/", async (_req: Request, res: Response) => {
  try {
    const result = await pool.query(
      `SELECT id, user_id, source, transcript, reply, duration_ms, created_at
       FROM conversations
       ORDER BY created_at DESC
       LIMIT 100`
    );
    res.json(result.rows);
  } catch (err) {
    console.error("[conversations] list error", err);
    res.status(500).json({ error: "internal error" });
  }
});

export default router;
