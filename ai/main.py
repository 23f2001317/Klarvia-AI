"""
FastAPI entrypoint for Klarvia AI service.

Development usage:
  - Run locally with auto-reload:
      uvicorn ai.main:app --reload --host 127.0.0.1 --port 8001

  - CORS policy:
      If ENV=development (or ALLOW_ALL_CORS=true), we add a permissive CORS
      middleware allowing all origins to simplify local dev across ports.

Production deployment:
  - Use Gunicorn with UvicornWorker (supports WebSocket):
      gunicorn -k uvicorn.workers.UvicornWorker \
               -w 2 \
               -b 0.0.0.0:8000 \
               ai.main:app

  - Behind a reverse proxy (e.g., Nginx), ensure WebSocket upgrade headers are forwarded:
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_http_version 1.1;

  - Environment hardening tips:
      - Set ENV=production (disables dev CORS behavior below)
      - Configure proper CORS allowlist in the application or proxy
"""

from __future__ import annotations

import os
from fastapi.middleware.cors import CORSMiddleware

# Import the existing FastAPI app with routes, models, and WebSocket handlers
from .server import app as _app

# Expose as module-level `app` for ASGI servers (uvicorn/gunicorn)
app = _app

# Development CORS: allow all origins when explicitly enabled
env = os.getenv("ENV", "").lower()
allow_all = env in ("dev", "development") or os.getenv("ALLOW_ALL_CORS", "0").lower() in ("1", "true", "yes")
if allow_all:
    # Note: This adds an outer CORS middleware layer that permits all origins.
    # The app also configures CORS in server.py for common dev ports; this layer
    # ensures permissive behavior if you run from alternative ports during dev.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    uvicorn.run("ai.main:app", host="127.0.0.1", port=port, reload=True)
