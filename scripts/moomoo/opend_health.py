#!/usr/bin/env python3
"""opend_health.py — moomoo OpenD data-plane health probe.

Three escalating checks, each reported honestly rather than collapsed into one bool:
  1. unit      — is the systemd user unit active?
  2. port      — is OpenD listening on 127.0.0.1:11111?
  3. quote     — does a real futu query round-trip? (proves LOGIN succeeded, which
                 the port alone does not: OpenD binds the API port BEFORE logging in,
                 then exits on auth failure. On 2026-07-23 it listened and died
                 seconds later with "Password does not match".)

Writes data/runtime/moomoo_opend_health.json for the Health desk and alerts on a
sustained outage. Read-only: no orders, no trade unlock, no subscriptions kept.

  .venv/bin/python scripts/moomoo/opend_health.py
  .venv/bin/python scripts/moomoo/opend_health.py --alert
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "data" / "runtime" / "moomoo_opend_health.json"
FAIL_STREAK = ROOT / "data" / "runtime" / "moomoo_opend_fail_streak.json"
UNIT = "trade-ai-lab-moomoo-opend.service"
HOST, PORT = "127.0.0.1", 11111
ALERT_AFTER = 3  # consecutive failures before shouting (probe runs every 5 min)


def _unit_active() -> tuple[bool, str]:
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", UNIT],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "active", r.stdout.strip() or "unknown"
    except Exception as e:
        return False, f"error: {str(e)[:60]}"


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=4):
            return True
    except Exception:
        return False


def _quote_ok() -> tuple[bool, str]:
    """Round-trip a real query. This is the only check that proves login worked."""
    try:
        from futu import OpenQuoteContext, RET_OK
    except ImportError:
        return False, "futu SDK not installed"
    ctx = None
    try:
        ctx = OpenQuoteContext(host=HOST, port=PORT)
        ret, data = ctx.get_market_snapshot(["US.AAPL"])
        if ret != RET_OK:
            return False, f"query rejected: {str(data)[:100]}"
        return True, f"snapshot ok ({len(data)} row)"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass


def _bump(ok: bool) -> int:
    try:
        d = json.loads(FAIL_STREAK.read_text()) if FAIL_STREAK.exists() else {}
    except Exception:
        d = {}
    n = 0 if ok else int(d.get("streak") or 0) + 1
    FAIL_STREAK.parent.mkdir(parents=True, exist_ok=True)
    FAIL_STREAK.write_text(json.dumps({"streak": n}))
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true", help="telegram on sustained failure")
    args = ap.parse_args()

    active, unit_state = _unit_active()
    port = _port_open()
    quote, quote_detail = (_quote_ok() if port else (False, "port closed — not probed"))
    ok = active and port and quote

    streak = _bump(ok)
    out = {
        "ok": ok,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "unit": {"name": UNIT, "active": active, "state": unit_state},
        "port": {"host": HOST, "port": PORT, "open": port},
        "quote": {"ok": quote, "detail": quote_detail},
        "fail_streak": streak,
        "note": "Data plane only — no order path, no trade unlock. A listening port "
                "does NOT imply a successful login; the quote round-trip is the real gate.",
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))

    if args.alert and streak == ALERT_AFTER:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from telegram_alert import send_telegram
            reason = unit_state if not active else ("port closed" if not port else quote_detail)
            send_telegram(f"⚠️ moomoo OpenD data plane DOWN ×{streak} — {reason}",
                          bypass_router=True)
        except Exception as e:
            print(f"[warn] alert failed: {e}", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
