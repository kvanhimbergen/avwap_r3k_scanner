from __future__ import annotations

import os

import uvicorn

from analytics_platform.backend.app import create_app


app = create_app()


def main() -> int:
    host = os.environ.get("AP_HOST", "0.0.0.0")
    port = int(os.environ.get("AP_PORT", "8787"))
    uvicorn.run(
        "analytics_platform.backend.main:app",
        host=host,
        port=port,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
