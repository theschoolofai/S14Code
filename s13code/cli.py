from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(prog="s13code")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    # Loopback stays the default: a dev machine should not expose the runtime to
    # its whole network by accident. A container has no such default — nothing
    # outside it can ever reach 127.0.0.1 — so S13_HOST lets the image bind
    # 0.0.0.0 without baking that choice into local use. PORT is read too, since
    # most hosts inject it rather than letting you pick.
    serve.add_argument("--host", default=os.getenv("S13_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int,
                       default=int(os.getenv("PORT") or os.getenv("S13_PORT", "8113")))
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("s13code.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
