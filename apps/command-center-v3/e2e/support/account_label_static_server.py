"""Static fixture server: serves the built SPA, rejects APIs, and has no proxy."""
from __future__ import annotations

import argparse
import http.server
from pathlib import Path
from urllib.parse import unquote, urlsplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file", type=Path, required=True)
    args = parser.parse_args()
    root = args.dist.resolve()
    if not (root / "index.html").is_file():
        raise SystemExit("built dist/index.html required")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path.startswith("/api/"):
                self.send_error(410, "API must be fulfilled by the browser fixture")
                return
            path = path.removeprefix("/v3")
            target = (root / path.lstrip("/")).resolve()
            if not target.is_relative_to(root):
                self.send_error(403)
                return
            self.path = "/" + str(target.relative_to(root)) if target.is_file() else "/index.html"
            super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    args.port_file.parent.mkdir(parents=True, exist_ok=True)
    args.port_file.write_text(str(server.server_port))
    print(f"fixture server http://127.0.0.1:{server.server_port}; no API proxy", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
