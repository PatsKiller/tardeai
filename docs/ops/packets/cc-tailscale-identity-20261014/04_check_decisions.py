#!/usr/bin/env python3
"""04 — summarise cc_auth decisions (deny / would_deny / step-up) from the decision log.

Usage: python3 04_check_decisions.py [--hours 24] [--log ~/.local/state/tradeai/cc_auth_decisions.jsonl]

GO for step 6 (enforce) when, over a window that includes a weekday market session and the nightly
run:
  * no `service` would_deny rows except callers you have decided to accept breaking;
  * no `serve_proxy` would_deny rows with reason "no tailnet identity" from your own devices (that
    would mean tailscale serve is not setting Tailscale-User-Login on the unix target);
  * no `service` rows with ident_on_7777=True (browser traffic still aimed at :7777).
The log never contains token values.
"""
import argparse
import collections
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--hours", type=float, default=24)
ap.add_argument("--log", default="~/.local/state/tradeai/cc_auth_decisions.jsonl")
a = ap.parse_args()
p = Path(a.log).expanduser()
if not p.exists():
    raise SystemExit(f"no decision log yet at {p} (nothing denied/would-deny, or the release is not serving)")
since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
rows = []
for line in p.read_text(encoding="utf-8").splitlines():
    try:
        r = json.loads(line)
        if datetime.fromisoformat(r["ts"]) >= since:
            rows.append(r)
    except Exception:
        continue
print(f"{len(rows)} rows in last {a.hours}h from {p}")
c = collections.Counter((r["outcome"], r["kind"], r["listener"], r["status"], r["method"], r["path"],
                         (r.get("reason") or "")[:60], (r.get("user_agent") or "")[:40],
                         bool(r.get("ignored_identity_header"))) for r in rows)
for k, n in c.most_common(80):
    print(f"{n:6d}  {k[0]:10s} {k[1]:7s} {k[2]:11s} {k[3]} {k[4]:5s} {k[5]:55s} | {k[6]} | ua={k[7]} | ident_on_7777={k[8]}")
svc = [r for r in rows if r["listener"] == "service" and r["kind"] == "auth"]
sp = [r for r in rows if r["listener"] == "serve_proxy" and r["kind"] == "auth"]
print("\nSUMMARY")
print(f"  service would_deny/deny (unmigrated loopback callers): {len(svc)}")
print(f"    of which carried Tailscale-User-Login (browser still via :7777): {sum(1 for r in svc if r.get('ignored_identity_header'))}")
print(f"  serve_proxy would_deny/deny (identity missing / not allowed): {len(sp)}")
print(f"  step-up refusals: {sum(1 for r in rows if r['kind'] == 'step_up')}")
print(f"  csrf deny/would_deny (cross-site or non-JSON writes; any from your own UI = a bug to fix first): "
      f"{sum(1 for r in rows if r['kind'] == 'csrf')}")
print(f"  secret-write refusals (WS4-02): {sum(1 for r in rows if r['kind'] == 'refused')}")
