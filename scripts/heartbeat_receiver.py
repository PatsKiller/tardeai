#!/usr/bin/env python3
"""In-network heartbeat receiver (2026-06-04) — partial watchdog layer 3.

Receives the freshness monitor's off-host ping (FRESHNESS_HEARTBEAT_PING_URL) and records the
last-ping timestamp to logs/.offhost_ping.txt. An INDEPENDENT staleness check (in
freshness_watchdog_heartbeat.py) pages if that file goes stale — i.e. if the monitor stops
pinging. Listens on 0.0.0.0 so other in-network hosts could also point at it.

HONEST SCOPE: this is the in-network stopgap. It is the SAME HOST as the monitor, so it covers
monitor/process death but NOT total-box death (if the box dies, this receiver dies too). The
box-death case needs an OFF-HOST service (healthchecks.io). It also overlaps layer 2
(freshness_watchdog_heartbeat's file check); the unique add here is a push-based (HTTP) signal
independent of the monitor's own heartbeat file. Kept alive by a */5 respawn cron.

Run: python3 scripts/heartbeat_receiver.py   (binds 0.0.0.0:18798)
"""
import os, http.server, socketserver
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PING_FILE = os.path.join(ROOT, "logs", ".offhost_ping.txt")
PORT = int(os.environ.get("HEARTBEAT_RECEIVER_PORT", "18798"))


class Handler(http.server.BaseHTTPRequestHandler):
    def _record(self):
        try:
            os.makedirs(os.path.dirname(PING_FILE), exist_ok=True)
            with open(PING_FILE, "w") as f:
                f.write(datetime.now(timezone.utc).isoformat())
        except Exception:
            pass
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self._record()

    def do_POST(self):
        self._record()

    def log_message(self, *a):
        pass  # quiet


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"[heartbeat_receiver] listening on 0.0.0.0:{PORT}, recording to {PING_FILE}")
        httpd.serve_forever()
