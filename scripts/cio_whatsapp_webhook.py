#!/usr/bin/env python3
"""cio_whatsapp_webhook.py — Meta Cloud API webhook for CIO WhatsApp converse (P4).

READ_ONLY_ADVISORY. Transport only → shared converse core.

Usage:
  .venv/bin/python scripts/cio_whatsapp_webhook.py --port 8787
  # Meta webhook URL: https://<host>/cio/whatsapp/webhook

Env: see docs/cio/CIO_WHATSAPP_CONVERSE_RUNBOOK.md
  CIO_WHATSAPP_CONVERSE=0|1 (default 0)
  WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET
  WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_WA_IDS
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)


class WhatsAppWebhookHandler(BaseHTTPRequestHandler):
    dry_run: bool = False

    def log_message(self, fmt: str, *args) -> None:  # quieter
        sys.stderr.write("[cio-wa] " + (fmt % args) + "\n")

    def _path_ok(self) -> bool:
        p = urlparse(self.path).path.rstrip("/")
        return p in (
            "/cio/whatsapp/webhook",
            "/webhook",
            "/whatsapp/webhook",
        )

    def do_GET(self) -> None:  # noqa: N802
        if not self._path_ok():
            self.send_error(404)
            return
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("hub.mode") or qs.get("hub_mode") or [""])[0]
        token = (qs.get("hub.verify_token") or qs.get("hub_verify_token") or [""])[0]
        challenge = (qs.get("hub.challenge") or qs.get("hub_challenge") or [""])[0]
        from scripts.lib.cio_whatsapp_ingress import verify_webhook_challenge
        ch = verify_webhook_challenge(mode, token, challenge)
        if ch is None:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(str(ch).encode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        if not self._path_ok():
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        sig = self.headers.get("X-Hub-Signature-256") or self.headers.get("x-hub-signature-256")
        from scripts.lib.cio_whatsapp_ingress import (
            process_webhook_payload,
            verify_signature,
        )
        if not verify_signature(raw, sig):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"invalid signature")
            return
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
        # Always 200 quickly to Meta; process inline (small volume allowlist)
        try:
            result = process_webhook_payload(payload, dry_run=self.dry_run)
        except Exception as exc:
            result = {"errors": [f"{type(exc).__name__}:{exc}"], "processed": 0}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "result": {
            "processed": result.get("processed"),
            "errors": result.get("errors"),
        }}, default=str).encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="CIO WhatsApp Meta webhook (P4)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    WhatsAppWebhookHandler.dry_run = args.dry_run
    server = HTTPServer((args.host, args.port), WhatsAppWebhookHandler)
    print(
        f"[cio-wa] listening http://{args.host}:{args.port}/cio/whatsapp/webhook "
        f"dry_run={args.dry_run} flag={os.environ.get('CIO_WHATSAPP_CONVERSE', '0')}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[cio-wa] stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
