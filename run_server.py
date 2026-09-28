from __future__ import annotations

import os
import uvicorn


def _port() -> int:
    raw = os.getenv("PORT", "8000").strip()
    try:
        port = int(raw)
    except (TypeError, ValueError):
        port = 8000
    if port <= 0 or port > 65535:
        port = 8000
    return port


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=_port(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
