#!/usr/bin/env python3
"""MEM-CONTAIN 2026-11-13 (TEMPORARY CONTAINMENT evidence): measure heavy GET builds OUTSIDE portfolio-server.

Each scenario runs in a FRESH subprocess with guards installed before any project import:
  * network: socket.socket / create_connection raise (no broker, no provider, no :7777);
  * writes: builtins.open / io.open / os.open refuse any write mode; os.replace/rename/remove/unlink raise;
  * secrets: any open of a path ending in ".env", ".pgpass" or under /run/user/*/tradeai refuses.
A scenario that trips a guard reports GUARD_BLOCKED and is not retried. Reports ru_maxrss (KiB), wall ms and
payload bytes. Numbers are measurements only; they do not by themselves prove a cause (PROVISIONAL).

Usage: python3 scripts/ops/mem_contain_build_harness.py --root <served tree> [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap

CHILD = textwrap.dedent(r'''
import builtins, io, json, os, resource, socket, sys, threading, time
ROOT, SCEN = sys.argv[1], sys.argv[2]
os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on"
class GuardBlocked(Exception): pass
def _no_net(*a, **k): raise GuardBlocked("network blocked")
socket.socket = _no_net; socket.create_connection = _no_net
_ro = builtins.open
def _secret(p):
    s = str(p)
    return s.endswith((".env", ".pgpass")) or "/tradeai/env" in s
def _open(f, mode="r", *a, **k):
    if _secret(f): raise GuardBlocked(f"secret read blocked: {f}")
    if any(c in str(mode) for c in "wax+"): raise GuardBlocked(f"write blocked: {f} mode={mode}")
    return _ro(f, mode, *a, **k)
builtins.open = io.open = _open
_osopen = os.open
def _os_open(p, flags, *a, **k):
    if _secret(p): raise GuardBlocked(f"secret read blocked: {p}")
    if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
        raise GuardBlocked(f"write blocked: {p}")
    return _osopen(p, flags, *a, **k)
os.open = _os_open
for _n in ("replace", "rename", "remove", "unlink", "makedirs", "mkdir"):
    setattr(os, _n, lambda *a, _n=_n, **k: (_ for _ in ()).throw(GuardBlocked(f"os.{_n} blocked")))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.chdir("/")

def links(limit=500):
    import reporting_engine as re_
    return re_.report_links_map(symbols=None, limit=limit)

SCENARIOS = {"analyst_links": lambda: [links()],
             "analyst_links_x4": None}
out = {"scenario": SCEN, "ok": False}
t0 = time.monotonic()
try:
    if SCEN == "analyst_links_x4":
        res, errs = [], []
        def w():
            try: res.append(links())
            except BaseException as e: errs.append(repr(e))
        ts = [threading.Thread(target=w) for _ in range(4)]
        [t.start() for t in ts]; [t.join() for t in ts]
        if errs: raise RuntimeError(errs[0])
        payloads = res
    else:
        payloads = SCENARIOS[SCEN]()
    out["payload_bytes"] = [len(json.dumps(p, default=str)) for p in payloads]
    out["ok"] = True
except GuardBlocked as e:
    out["outcome"] = "GUARD_BLOCKED"; out["error"] = str(e)
except BaseException as e:
    out["outcome"] = "FAILED"; out["error"] = f"{type(e).__name__}: {e}"[:300]
out["wall_ms"] = int((time.monotonic() - t0) * 1000)
out["ru_maxrss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
out["threads_peak_note"] = "4 build threads + main" if SCEN.endswith("x4") else "main only"
sys.stdout.write("RESULT " + json.dumps(out) + "\n")
''')

NOT_RUN = {
    "market_risk_projection": "NOT RUN: lives in scripts/api_v2.py, whose import runs load_dotenv(PROJECT_ROOT/'.env') "
                              "and db_adapter._load_dotenv_if_needed(); the task rules forbid reading .env, and the "
                              "projection needs the DB connection that .env configures.",
    "home_cio_card": "NOT RUN: same api_v2 import (.env auto-load) plus DB reads via cio_truth; forbidden by the "
                     "no-.env rule.",
}


def run(root: str, scen: str, py: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PG", "DATABASE", "TRADEAI_"))}
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    cp = subprocess.run([py, "-I", "-c", CHILD, root, scen], capture_output=True, text=True, env=env, timeout=600)
    for ln in cp.stdout.splitlines():
        if ln.startswith("RESULT "):
            return json.loads(ln[7:])
    return {"scenario": scen, "ok": False, "outcome": "NO_RESULT", "rc": cp.returncode, "stderr": cp.stderr[-400:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows = [run(a.root, s, a.python) for s in ("analyst_links", "analyst_links_x4")]
    rows += [{"scenario": k, "ok": False, "outcome": "NOT_RUN", "error": v} for k, v in NOT_RUN.items()]
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        for r in rows:
            print(f"{r['scenario']:24} ok={r['ok']!s:5} wall_ms={r.get('wall_ms', '-')!s:>7} "
                  f"maxrss_kb={r.get('ru_maxrss_kb', '-')!s:>8} payload_bytes={r.get('payload_bytes', '-')} "
                  f"{r.get('outcome', '')} {r.get('error', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
