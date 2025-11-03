import { Router, Request, Response } from "express";

const router = Router();

// Returns WebSocket auth configuration.
// In development this may return the token for quick testing. In production
// it only indicates whether WS auth is enabled.
router.get("/", async (_req: Request, res: Response) => {
  try {
    let wsAuthToken = process.env.WS_AUTH_TOKEN || "";
    const nodeEnv = (process.env.NODE_ENV || "development").toLowerCase();
    const isDev = nodeEnv === "development" || nodeEnv === "dev";

    // If we don't have a token in the node process but we're running
    // in development, try to fetch it from the Python AI service's
    // /ws-token endpoint to make local dev smoother.
    if (!wsAuthToken && isDev) {
      try {
        const AI_BASE = process.env.AI_BASE_URL || "http://127.0.0.1:8001";
        const r = await fetch(`${AI_BASE}/ws-token`);
        if (r.ok) {
          const data = await r.json().catch(() => ({}));
          if (data?.token) wsAuthToken = data.token;
        }
      } catch (e) {
        // Ignore fetch errors; we'll return what we have
      }
    }

    const response: any = { wsAuthRequired: !!wsAuthToken };
    if (isDev && wsAuthToken) response.token = wsAuthToken;
    res.json(response);
  } catch (err) {
    console.error("[ws-config] error", err);
    res.status(500).json({ error: "internal error" });
  }
});

export default router;
