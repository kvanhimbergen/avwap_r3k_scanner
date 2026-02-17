from __future__ import annotations

import uvicorn

from analytics_platform.backend.app import create_app


app = create_app()


def main() -> int:
    uvicorn.run(
        "analytics_platform.backend.main:app",
        host="127.0.0.1",
        port=8787,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
