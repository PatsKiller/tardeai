"""The watchdog reports from outside n8n. The down path uses a closed port."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts.n8n_lab_watchdog import check, main, write_receipt


def test_closed_port_is_a_failure(tmp_path):
    receipt = check("http://127.0.0.1:9/healthz", timeout_s=0.5)
    assert receipt["ok"] is False
    assert receipt["sends"] is False
    assert receipt["error"]
    path = tmp_path / "watchdog.json"
    write_receipt(path, receipt)
    assert json.loads(path.read_text(encoding="utf-8"))["ok"] is False
    code = main(["--url", "http://127.0.0.1:9/healthz", "--receipt", str(tmp_path / "cli.json"), "--timeout", "0.5"])
    assert code == 2


def test_local_200_is_up_and_does_not_send(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        receipt = check(f"http://127.0.0.1:{port}/healthz", timeout_s=2)
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
    assert receipt["ok"] is True
    assert receipt["http_status"] == 200
    assert receipt["sends"] is False
    path = tmp_path / "up.json"
    write_receipt(path, receipt)
    assert json.loads(path.read_text(encoding="utf-8"))["sends"] is False
