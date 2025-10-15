import { Router, Request, Response } from "express";

const router = Router();

// Returns WebSocket auth configuration.
// In development this may return the token for quick testing. In production
// it only indicates whether WS auth is enabled.
router.get("/", async (_req: Request, res: Response) => {
  try {
    const wsAuthToken = process.env.WS_AUTH_TOKEN || "";
    const nodeEnv = (process.env.NODE_ENV || "development").toLowerCase();
    const isDev = nodeEnv === "development" || nodeEnv === "dev";
    const response: any = { wsAuthRequired: !!wsAuthToken };
    if (isDev && wsAuthToken) response.token = wsAuthToken;
    res.json(response);
  } catch (err) {
    console.error("[ws-config] error", err);
    res.status(500).json({ error: "internal error" });
  }
});

export default router;
