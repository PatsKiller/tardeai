#!/usr/bin/env python3
"""Minimal production server for CC v2 — serves static build + proxies API to 7777."""
import http.server
import json
import os
import urllib.request
from pathlib import Path

PORT = int(os.environ.get("CC_V2_PORT", "7778"))
DIST = Path(__file__).parent / "dist"
PROXY_TARGET = "http://127.0.0.1:7777"
PROXY_PREFIXES = ("/api/", "/data/", "/config/", "/reports/")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def do_GET(self):
        path = self.path.split("?")[0]

        # Proxy API/data requests to 7777
        if any(path.startswith(p) for p in PROXY_PREFIXES):
            self._proxy()
            return

        # SPA fallback: if file doesn't exist, serve index.html
        file_path = DIST / path.lstrip("/")
        if not file_path.exists() or file_path.is_dir():
            if not any(path.endswith(ext) for ext in (".js", ".css", ".svg", ".png", ".ico")):
                self.path = "/index.html"

        super().do_GET()

    def _proxy(self):
        url = PROXY_TARGET + self.path
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())

    def log_message(self, format, *args):
        pass  # Quiet logging


if __name__ == "__main__":
    # Build first if needed
    if not (DIST / "index.html").exists():
        print("[CC-v2] Building...")
        os.system("npx vite build")

    server = http.server.HTTPServer(("", PORT), Handler)
    print(f"[CC-v2] Serving on http://0.0.0.0:{PORT} (proxy → {PROXY_TARGET})")
    server.serve_forever()
