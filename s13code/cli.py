from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="s13code")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default=os.getenv("S13_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.getenv("S13_PORT", "8113")))
    args = parser.parse_args()
    if args.command == "serve":
        if not os.getenv("GLC_BASE_URL"):
            print("s13code error: GLC_BASE_URL is not set. Startup aborted.", file=sys.stderr)
            sys.exit(1)

        import uvicorn
        uvicorn.run("s13code.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
