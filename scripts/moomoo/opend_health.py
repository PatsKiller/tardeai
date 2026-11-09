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

LQ-20261107-1509: a quote rate-limit rejection ("Maximum 60 times per 30 seconds" /
"high frequency") proves the data plane is up and logged in — it is not SERVICE_DOWN.
Keep the last-good receipt, mark ``throttled``, and skip further quote calls for
``QUOTE_COOLDOWN_S`` so this probe stays under the shared OpenD quota.

  .venv/bin/python scripts/moomoo/opend_health.py
  .venv/bin/python scripts/moomoo/opend_health.py --alert

Exit codes: 0 data plane up (including throttled last-good); 3 (EXIT_FINDING) data
plane down — a finding, not a crash. 1 is left to Python's uncaught-exception exit
so health_tick.py can tell the two apart (n8n maturity B3.1, 2026-10-09; was 1 for
"down" before).
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.lib.monitor_exit_codes import EXIT_FINDING  # noqa: E402
STATE = ROOT / "data" / "runtime" / "moomoo_opend_health.json"
FAIL_STREAK = ROOT / "data" / "runtime" / "moomoo_opend_fail_streak.json"
UNIT = "trade-ai-lab-moomoo-opend.service"
HOST, PORT = "127.0.0.1", 11111
ALERT_AFTER = 3  # consecutive failures before shouting (probe runs every 5 min)
# Shared OpenD quote quota is 60 / 30s across every client. This probe must not
# burn a snapshot on every */5 tick when the last good (or last throttle) is fresh.
QUOTE_COOLDOWN_S = 120


def _is_throttle_detail(detail: object) -> bool:
    """True when OpenD rejected the quote for rate limit, not auth or connectivity."""
    text = str(detail or "").lower()
    return "high frequency" in text or "maximum 60 times" in text or "60 times per 30" in text


def _read_prior() -> dict:
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _parse_checked_at(value: object) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _within_cooldown(prior: dict, *, now: datetime) -> tuple[bool, str]:
    """Skip a new quote when the prior receipt is recent enough to spare the quota."""
    checked = _parse_checked_at(prior.get("checked_at"))
    if checked is None:
        return False, ""
    age = (now - checked).total_seconds()
    if age < 0 or age > QUOTE_COOLDOWN_S:
        return False, ""
    quote = prior.get("quote") if isinstance(prior.get("quote"), dict) else {}
    if prior.get("ok") is True or prior.get("throttled") is True or _is_throttle_detail(quote.get("detail")):
        return True, f"skipped quote; last receipt {age:.0f}s ago (cooldown {QUOTE_COOLDOWN_S}s)"
    return False, ""


def _unit_active() -> tuple[bool, str]:
    """systemctl --user state. Informational — see main() for why it is not the gate.

    cron runs with a bare environment, so `systemctl --user` cannot reach the user
    bus ("$DBUS_SESSION_BUS_ADDRESS and $XDG_RUNTIME_DIR not defined") and returns
    unknown. Supply XDG_RUNTIME_DIR/DBUS ourselves so the probe works under cron.
    """
    import os
    env = dict(os.environ)
    uid = os.getuid()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", UNIT],
                           capture_output=True, text=True, timeout=10, env=env)
        state = r.stdout.strip() or "unknown"
        return state == "active", state
    except Exception as e:
        return False, f"error: {str(e)[:60]}"


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=4):
            return True
    except Exception:
        return False


def _quote_ok() -> tuple[bool, str]:
    """Round-trip a real query. This is the only check that proves login worked.

    The futu SDK logs verbosely to stdout on every connect; left alone it interleaves
    with our JSON and makes this script's output unparseable for anything downstream
    (and floods the 5-minute cron log). Silence its logger and swallow its stdout —
    ours is the only thing that should reach the caller.
    """
    import contextlib

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from moomoo.client import quiet_futu_logging
    except Exception:
        return False, "moomoo client module unavailable"

    ctx = None
    try:
        with quiet_futu_logging():
            from futu import OpenQuoteContext, RET_OK
            ctx = OpenQuoteContext(host=HOST, port=PORT)
            ret, data = ctx.get_market_snapshot(["US.AAPL"])
        if ret != RET_OK:
            return False, f"query rejected: {str(data)[:100]}"
        return True, f"snapshot ok ({len(data)} row)"
    except ImportError:
        return False, "futu SDK not installed"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"
    finally:
        if ctx is not None:
            with contextlib.suppress(Exception), quiet_futu_logging():
                ctx.close()


def _keep_last_good(prior: dict, *, detail: str, now: datetime) -> dict:
    """Throttle / cooldown: data plane is up; carry the last successful receipt forward."""
    prior_quote = prior.get("quote") if isinstance(prior.get("quote"), dict) else {}
    last_good_at = prior.get("last_good_at") or (
        prior.get("checked_at") if prior.get("ok") is True else None
    )
    return {
        "ok": True,
        "throttled": True,
        "checked_at": now.isoformat(),
        "unit": prior.get("unit") if isinstance(prior.get("unit"), dict) else {"name": UNIT},
        "port": prior.get("port") if isinstance(prior.get("port"), dict) else {"host": HOST, "port": PORT, "open": True},
        "quote": {
            "ok": True,
            "throttled": True,
            "detail": detail,
            "last_good_detail": prior_quote.get("detail"),
        },
        "last_good_at": last_good_at,
        "fail_streak": 0,
        "note": "Data plane only — no order path, no trade unlock. Rate-limit is not SERVICE_DOWN; "
                "last-good kept (LQ-20261107-1509).",
    }


def _bump(ok: bool) -> int:
    try:
        d = json.loads(FAIL_STREAK.read_text()) if FAIL_STREAK.exists() else {}
    except Exception:
        d = {}
    n = 0 if ok else int(d.get("streak") or 0) + 1
    FAIL_STREAK.parent.mkdir(parents=True, exist_ok=True)
    FAIL_STREAK.write_text(json.dumps({"streak": n}))
    return n


def probe(*, now: datetime | None = None, prior: dict | None = None,
          quote_fn=None, port_fn=None, unit_fn=None) -> dict:
    """One probe. Injectable clocks/I/O for tests — never talks to a broker order path."""
    now = now or datetime.now(timezone.utc)
    prior = prior if prior is not None else _read_prior()
    active, unit_state = (unit_fn or _unit_active)()
    port = (port_fn or _port_open)()
    unit_block = {"name": UNIT, "active": active, "state": unit_state}
    port_block = {"host": HOST, "port": PORT, "open": port}

    if not port:
        ok = False
        quote, quote_detail = False, "port closed — not probed"
        throttled = False
    else:
        cool, cool_detail = _within_cooldown(prior, now=now)
        if cool:
            kept = _keep_last_good(prior, detail=cool_detail, now=now)
            kept["unit"] = unit_block
            kept["port"] = port_block
            kept["fail_streak"] = _bump(True)
            return kept
        quote, quote_detail = (quote_fn or _quote_ok)()
        if (not quote) and _is_throttle_detail(quote_detail):
            # A rate-limit rejection proves login + serving; keep last-good when we have it.
            detail = f"throttled; keeping last-good ({quote_detail})"
            if prior.get("ok") is True or (isinstance(prior.get("quote"), dict) and prior["quote"].get("ok") is True):
                kept = _keep_last_good(prior, detail=detail, now=now)
                kept["unit"] = unit_block
                kept["port"] = port_block
                kept["fail_streak"] = _bump(True)
                return kept
            # No last-good yet: still not SERVICE_DOWN — the throttle itself is the proof.
            ok, throttled = True, True
            quote = True
            quote_detail = f"throttled; data plane responding ({quote_detail})"
        else:
            ok, throttled = bool(port and quote), False

    streak = _bump(ok)
    out = {
        "ok": ok,
        "throttled": throttled,
        "checked_at": now.isoformat(),
        "unit": unit_block,
        "port": port_block,
        "quote": {"ok": quote, "detail": quote_detail, **({"throttled": True} if throttled else {})},
        "fail_streak": streak,
        "note": "Data plane only — no order path, no trade unlock. A listening port "
                "does NOT imply a successful login; the quote round-trip is the real gate. "
                "A rate-limit rejection is not down (LQ-20261107-1509).",
    }
    if ok:
        out["last_good_at"] = now.isoformat()
    elif prior.get("last_good_at"):
        out["last_good_at"] = prior.get("last_good_at")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true", help="telegram on sustained failure")
    args = ap.parse_args()

    out = probe()
    ok = bool(out.get("ok"))
    raw_streak = out.get("fail_streak")
    try:
        streak = int(raw_streak) if raw_streak is not None else None
    except (TypeError, ValueError):
        streak = None
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))

    if args.alert and streak == ALERT_AFTER and not out.get("throttled"):
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from telegram_alert import send_telegram
            unit = out.get("unit") if isinstance(out.get("unit"), dict) else {}
            port = out.get("port") if isinstance(out.get("port"), dict) else {}
            quote = out.get("quote") if isinstance(out.get("quote"), dict) else {}
            reason = (unit.get("state") if not unit.get("active")
                      else ("port closed" if not port.get("open") else quote.get("detail")))
            send_telegram(f"⚠️ moomoo OpenD data plane DOWN ×{streak} — {reason}",
                          bypass_router=True)
        except Exception as e:
            print(f"[warn] alert failed: {e}", file=sys.stderr)

    return 0 if ok else EXIT_FINDING


if __name__ == "__main__":
    raise SystemExit(main())
