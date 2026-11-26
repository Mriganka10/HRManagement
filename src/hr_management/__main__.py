"""Run the web server:  python -m hr_management  [--host 127.0.0.1] [--port 8000] [--reload]"""
from __future__ import annotations

import argparse
import logging
import os


def main() -> None:
    parser = argparse.ArgumentParser(prog="hr_management", description="Run the HR Management web app.")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--reload", action="store_true", help="Auto-restart when code changes (development).")
    args = parser.parse_args()

    import uvicorn

    logging.basicConfig(level=os.getenv("HRM_LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"\n  HR Management running →  http://{args.host}:{args.port}\n")
    uvicorn.run("hr_management.web:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
