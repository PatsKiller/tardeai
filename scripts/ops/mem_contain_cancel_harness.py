#!/usr/bin/env python3
"""MEM-CONTAIN 2026-11-13 cancellation proof (outside prod, synthetic build, no DB, no network beyond 127.0.0.1
on a random port of a throwaway server this script starts and stops).

A ThreadingHTTPServer subprocess serves /legacy (heavy build on the request thread, like the pre-containment
routes) and /swr (the same build through scripts/lib/shared_get_swr). The client fires N requests with a short
timeout and disconnects. The script samples the server's Threads / VmRSS / CPU from /proc after the drop.
Python threads cannot be cancelled: the measurement shows whether work keeps running after the client is gone."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = textwrap.dedent(r'''
import os, sys, time, json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, sys.argv[1])
from scripts.lib import shared_get_swr as swr
swr.cgroup_memory = lambda: (None, None)
HOLD_S, MB = float(sys.argv[2]), int(sys.argv[3])
def heavy():
    blob = bytearray(MB * 1024 * 1024)            # resident memory the build holds
    for i in range(0, len(blob), 4096): blob[i] = 1
    t = time.monotonic(); x = 0
    while time.monotonic() - t < HOLD_S: x += 1   # CPU the build burns
    return {"n": x, "mb": MB}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        q = self.path.split("?", 1)
        if self.path.startswith("/legacy"): body = heavy()
        else: body = swr.get("synthetic|principal=anon|" + (q[1] if len(q) > 1 else ""), 60, heavy, route="/swr")
        b = json.dumps(body, default=str).encode()
        try:
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        except OSError: pass
s = ThreadingHTTPServer(("127.0.0.1", 0), H); s.daemon_threads = True
print(s.server_address[1], flush=True); s.serve_forever()
''')


def proc(pid):
    st = Path(f"/proc/{pid}/status").read_text()
    f = {ln.split(":")[0]: ln.split(":", 1)[1].strip() for ln in st.splitlines()}
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    cpu_s = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    return {"threads": int(f["Threads"]), "rss_mb": round(int(f["VmRSS"].split()[0]) / 1024, 1), "cpu_s": round(cpu_s, 2)}


def scenario(path, n, hold_s, mb, timeout_s=0.5, distinct=False):
    srv = subprocess.Popen([sys.executable, "-c", SERVER, str(ROOT), str(hold_s), str(mb)], stdout=subprocess.PIPE,
                           text=True, env=dict(os.environ, SWR_SLOT_DIR="off", SWR_MAX_CONCURRENT_BUILDS="2"))
    port = int(srv.stdout.readline())
    time.sleep(0.3)
    base = proc(srv.pid)
    for i in range(n):  # client times out and disconnects mid-request
        c = socket.create_connection(("127.0.0.1", port))
        q = f"?i={i}" if distinct else ""
        c.sendall(f"GET {path}{q} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        c.settimeout(timeout_s)
        try:
            c.recv(1)
        except socket.timeout:
            pass
        c.close()
    t_drop = time.monotonic()
    samples = []
    for at in (0.0, 1.0, 2.0, hold_s + 1.0, hold_s * n + 2.0):
        time.sleep(max(0.0, t_drop + at - time.monotonic()))
        samples.append({"t_after_drop_s": at, **proc(srv.pid)})
    srv.kill()
    srv.wait()
    return {"path": path, "requests": n, "distinct_keys": distinct, "build_hold_s": hold_s, "build_mb": mb,
            "baseline": base, "samples": samples}


if __name__ == "__main__":
    hold, mb = 3.0, 150
    res = [scenario("/legacy", 4, hold, mb), scenario("/swr", 4, hold, mb),
           scenario("/swr", 4, hold, mb, distinct=True)]
    print(json.dumps(res, indent=1))
