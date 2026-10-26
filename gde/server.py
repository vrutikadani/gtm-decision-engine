"""`make demo`: API + demo UI on one port, no API keys needed."""
from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

from .api import app, svc

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PORT", "8000"))

# Same layout as GitHub Pages: repo root is the site root, the app lives in /web/.
# API routes and /docs are registered first, so they win over static files.
app.mount("/", StaticFiles(directory=ROOT, html=True), name="site")


def main():
    from .demo.scenarios import SCENARIOS
    print(f"""
GTM Decision Engine running

Demo UI:
http://localhost:{PORT}

API docs:
http://localhost:{PORT}/docs

Demo scenarios loaded:
{len(SCENARIOS)}

LLM provider: {svc.llm.name}{'' if svc.llm.name != 'mock' else ' (deterministic)'}
No external API keys required.
""", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
