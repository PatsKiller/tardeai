#!/usr/bin/env python3
"""MEM-CONTAIN v2 (2026-11-13) overlap / RSS / disconnect harness — LOCAL ONLY, SYNTHETIC DATA.

Starts a throwaway HTTP server on 127.0.0.1:<free port> (never 7777) in a child process. The child imports the real
scripts/api_v2.py SWR request functions for the four contained routes (market-risk/latest, risk, home/cio-card,
reports/analyst/links) and replaces only their heavy builders with a synthetic builder that allocates and touches
--build-mb MiB, holds it for --build-s seconds and returns a small synthetic payload. Nothing reads a DB, a broker, a
provider or a secret: outbound connects other than to the harness's own loopback port raise in the child, and every
data path env var points into a scratch dir.

Two server modes, measured with the same client load:
  swr    — the contained path (request thread never builds; one background build per key, capped, leased)
  inline — the pre-containment shape (each request runs the builder on its own thread)

Reports, per mode: request latency p50/p95/max, builder calls, peak concurrent builders, server VmHWM / VmRSS, the
per-request RSS delta (process VmRSS after - before, read on the request thread; concurrent requests AND background
builds overlap, so a delta is an upper bound on what that request added, not its own allocation), and whether a request whose client disconnected left a build
running (and on which thread).

Usage: python3 scripts/ops/mem_contain_overlap_harness.py [--json] [--clients 8] [--requests 64] [--build-mb 64]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROUTES = ("market-risk", "risk", "cio-card", "links")
PROD_PORT = 7777

CHILD = r'''
import json, os, socket, sys, threading, time
port, build_mb, build_s, root = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
assert port != 7777
_real_connect = socket.socket.connect
def _guard_connect(self, addr):
    if not (isinstance(addr, tuple) and addr[0] in ("127.0.0.1", "localhost") and addr[1] == port):
        raise ConnectionRefusedError(f"harness: outbound connect blocked {addr!r}")
    return _real_connect(self, addr)
socket.socket.connect = _guard_connect
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError("harness: blocked"))
sys.path[:0] = [root, os.path.join(root, "scripts")]
import api_v2
from scripts.lib import shared_get_swr as swr

LOCK = threading.Lock()
ACTIVE = [0]; PEAK = [0]; CALLS = []
def rss_kb(field="VmRSS"):
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith(field + ":"):
                return int(line.split()[1])
    return None
def heavy(tag):
    t0 = time.monotonic()
    with LOCK:
        ACTIVE[0] += 1; PEAK[0] = max(PEAK[0], ACTIVE[0])
    try:
        buf = bytearray(build_mb * 1024 * 1024)
        for i in range(0, len(buf), 4096):
            buf[i] = 1
        time.sleep(build_s)
        del buf
        return {"state": "evaluated", "tier": "RED", "as_of": "2031-01-02T15:00:00+00:00", "stale": False,
                "positions": [], "links": {}, "synthetic": tag}
    finally:
        with LOCK:
            ACTIVE[0] -= 1
            CALLS.append({"tag": tag, "thread": threading.current_thread().name,
                          "ms": int((time.monotonic() - t0) * 1000), "end": time.time()})
class R:
    def risk_payload(self, db_query=None):
        return heavy("risk")
api_v2._market_risk_latest_projection = lambda: heavy("market-risk")
api_v2._cio_truth_readers = lambda: R()
api_v2._home_cio_card_build = lambda *a, **k: heavy("cio-card")
api_v2._reports_analyst_links = lambda *a, **k: heavy("links")
SWR = {"market-risk": api_v2._market_risk_latest_swr, "risk": api_v2._risk_payload_cached,
       "cio-card": api_v2._home_cio_card, "links": lambda: api_v2._reports_analyst_links_swr({"limit": "500"})}

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        parts = self.path.strip("/").split("/")
        if parts[0] == "stats":
            body = {"swr": swr.stats(), "active": ACTIVE[0], "peak": PEAK[0], "calls": list(CALLS),
                    "vmrss_kb": rss_kb(), "vmhwm_kb": rss_kb("VmHWM"), "threads": threading.active_count()}
        elif parts[0] == "reset":
            swr.clear(); CALLS.clear(); PEAK[0] = 0; body = {"ok": True}
        else:
            mode, route = parts[0], parts[1]
            r0, t0 = rss_kb(), time.monotonic()
            if mode == "swr":
                out = SWR[route]()
            else:
                out = heavy(route)
            out = out[1] if isinstance(out, tuple) else out
            body = {"route": route, "mode": mode, "status": out.get("status"), "rss_delta_kb": rss_kb() - r0,
                    "handler_ms": int((time.monotonic() - t0) * 1000), "thread": threading.current_thread().name}
        data = json.dumps(body, default=str).encode()
        try:
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
ThreadingHTTPServer.daemon_threads = True
srv = ThreadingHTTPServer(("127.0.0.1", port), H)
print("READY", flush=True)
srv.serve_forever()
'''


def _free_port() -> int:
    while True:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        if p != PROD_PORT:
            return p


def _get(port: int, path: str, timeout: float = 60.0) -> dict:
    assert port != PROD_PORT
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read())


def _pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def run(args) -> dict:
    scratch = tempfile.mkdtemp(prefix="mem_contain_overlap_", dir=os.environ.get("TMPDIR"))
    env = dict(os.environ)
    for k, sub in (("TRADEAI_AUDIT_LEDGER_DIR", "ledger"), ("TRADEAI_PORTFOLIO_REPORTS_ROOT", "reports")):
        env[k] = os.path.join(scratch, sub)
    env.update({"TRADEAI_AUDIT_LEDGER_DB": "0", "TRADEAI_ALERT_EVENT_DB": "0",
                "TRADEAI_CC_SERVICE_TOKEN_FILE": os.path.join(scratch, "absent_token"),
                "SWR_SLOT_DIR": os.path.join(scratch, "slots"), "SWR_MAX_CONCURRENT_BUILDS": str(args.cap),
                "SWR_BUILD_LEASE_S": str(args.lease_s), "SWR_STATS_LOG_INTERVAL_S": "0",
                "PYTHONDONTWRITEBYTECODE": "1"})
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-c", CHILD, str(port), str(args.build_mb), str(args.build_s), ROOT],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=scratch)
    try:
        if proc.stdout.readline().strip() != "READY":
            raise RuntimeError("harness server did not start")
        base = _get(port, "/stats")
        report = {"port": port, "build_mb": args.build_mb, "build_s": args.build_s, "cap": args.cap,
                  "lease_s": args.lease_s, "clients": args.clients, "requests": args.requests, "rounds": args.rounds,
                  "server_vmrss_kb_idle": base["vmrss_kb"], "modes": {}}
        for mode in ("swr", "inline"):
            _get(port, "/reset")
            paths = [f"/{mode}/{ROUTES[i % len(ROUTES)]}" for i in range(args.requests)]
            t0 = time.monotonic()
            res, per_round = [], []
            for _ in range(args.rounds):  # bursts separated by one build time: cold, then warming, then warm
                with ThreadPoolExecutor(max_workers=args.clients) as ex:
                    rr = list(ex.map(lambda p: (time.monotonic(), _get(port, p), time.monotonic()), paths))
                res += rr
                per_round.append({"unknown": sum(1 for _, r, _ in rr if r.get("status") == "UNKNOWN"),
                                  "latency_ms_max": max(int((e - s0) * 1000) for s0, _, e in rr)})
                time.sleep(args.build_s + 0.5)  # let background builds land
            wall = time.monotonic() - t0
            st = _get(port, "/stats")
            lat = [int((e - s) * 1000) for s, _, e in res]
            deltas = [r["rss_delta_kb"] for _, r, _ in res]
            report["modes"][mode] = {
                "wall_s": round(wall, 2), "latency_ms_p50": _pct(lat, .5), "latency_ms_p95": _pct(lat, .95),
                "latency_ms_max": max(lat), "builder_calls": len(st["calls"]), "peak_concurrent_builders": st["peak"],
                "builder_threads_on_request_thread": sum(1 for c in st["calls"] if not c["thread"].startswith("swr-build-")),
                "unknown_responses": sum(1 for _, r, _ in res if r.get("status") == "UNKNOWN"), "rounds": per_round,
                "abandoned_total": st["swr"]["abandoned_total"],
                "rss_delta_kb_p50": _pct(deltas, .5), "rss_delta_kb_max": max(deltas),
                "server_vmhwm_kb": st["vmhwm_kb"], "server_vmrss_kb_after": st["vmrss_kb"],
                "swr_counters": st["swr"]["routes"] if mode == "swr" else None}
        # disconnect: client gives up after 50 ms on a cold key; does compute keep running, and where?
        disc = {}
        for mode in ("swr", "inline"):
            _get(port, "/reset")
            t_gone = time.time()
            try:
                _get(port, f"/{mode}/risk", timeout=0.05)
                client = "answered"
            except Exception as e:  # noqa: BLE001
                client = f"gave up ({type(e).__name__})"
            time.sleep(args.build_s + 0.5)
            st = _get(port, "/stats")
            calls = [c for c in st["calls"] if c["tag"] == "risk"]
            disc[mode] = {"client": client, "builds_after_disconnect": len(calls),
                          "build_thread": calls[0]["thread"] if calls else None,
                          "build_finished_s_after_client_left": round(calls[0]["end"] - t_gone, 2) if calls else None}
        report["disconnect"] = disc
        _get(port, "/reset")
        report["note"] = ("swr: request threads return immediately (UNKNOWN or last-good); builds run on swr-build-* "
                          "threads, one per key, at most cap at once; a client disconnect does NOT cancel a started "
                          "build (by design: it completes and is stored), bounded by the cap and the build lease. "
                          "inline: every request computes on its own thread and keeps computing after the client left.")
        return report
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clients", type=int, default=8)
    ap.add_argument("--requests", type=int, default=64)
    ap.add_argument("--build-mb", type=int, default=64)
    ap.add_argument("--build-s", type=float, default=2.0)
    ap.add_argument("--cap", type=int, default=2)
    ap.add_argument("--lease-s", type=float, default=300.0)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = run(args)
    print(json.dumps(rep, indent=None if args.json else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
