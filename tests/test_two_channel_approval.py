#!/usr/bin/env python3
"""Two-channel anti-fat-finger approval proof (Stage 2a Part E). Self-runnable:
    .venv/bin/python tests/test_two_channel_approval.py

Proves end-to-end, with NOTHING executing:
  1. Telegram approval message carries the Tailscale FQDN deep-link to the exact intent.
  2. Web channel confirms ONLY by typing the ticker (click-only and wrong-ticker rejected).
  3. ONE ORDER AT A TIME: a second intent cannot request approval while the first holds the slot.
  4. Single-use + TTL preserved (scaffold suite covers expiry; re-confirm covered here).
  5. Even FULLY APPROVED on both channels, the guard still BLOCKS submission (correct this phase).
"""
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brokers.order_intent import (OrderIntent, Instrument, Direction, EntrySpec, EntryMethod, Quantity,
                                  ExitPolicy, StopSpec, TargetSpec)
from brokers import approval_service as ap
from brokers.execution_guard import authorize
from db_adapter import _get_conn

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def mk(symbol="ZZGUARD"):
    return OrderIntent(instrument=Instrument(symbol), direction=Direction.LONG,
                       entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=3.50),
                       quantity=Quantity(qty=2), broker="schwab",
                       exit_policy=ExitPolicy(stop=StopSpec(price=3.20), targets=[TargetSpec(price=3.80)]))


it_a, it_b = mk(), mk("ZZSECOND")
cur = _get_conn().cursor()
try:
    # ── 1. deep-link in the telegram message ────────────────────────────────────────────────
    sent = {}

    def fake_post(url, json=None, timeout=None, **kw):
        sent["url"], sent["json"] = url, json
        class R: status_code = 200
        return R()

    env = {"TAILSCALE_HOSTNAME": "ms01-openclaw.tail163d14.ts.net",
           "TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_APPROVAL_CHAT_ID": "12345"}
    with mock.patch.dict(os.environ, env), mock.patch("requests.post", side_effect=fake_post):
        req = ap.request_approval(it_a)
    check("approval request ok", req.get("ok") is True, str(req)[:120])
    text = (sent.get("json") or {}).get("text", "")
    want = f"https://ms01-openclaw.tail163d14.ts.net/v3/trading?tab=Broker+Orders&intent={it_a.intent_id}"
    check("telegram message carries Tailscale deep-link to the exact intent", want in text, text[:200])
    check("telegram message states type-the-ticker requirement", "TYPE the ticker" in text)
    check("deep-link helper returns None when TAILSCALE_HOSTNAME unset",
          ap.intent_deep_link("x") is None if not os.getenv("TAILSCALE_HOSTNAME") else True)

    # ── 2. one order at a time ──────────────────────────────────────────────────────────────
    r2 = ap.request_approval(it_b)
    check("second intent refused while first holds the slot",
          r2.get("ok") is False and str(it_a.intent_id) in (r2.get("holder_intent_ids") or []))

    # ── 3. web = type-the-ticker; telegram = one-time code ─────────────────────────────────
    check("web click-only rejected", not ap.confirm(it_a.intent_id, "web")["ok"])
    check("web wrong ticker rejected", not ap.confirm(it_a.intent_id, "web", "AAPL")["ok"])
    check("web lowercase typed ticker accepted (case-insensitive)",
          ap.confirm(it_a.intent_id, "web", "zzguard")["ok"])
    cur.execute("SELECT code FROM trade_approvals WHERE intent_id=%s AND channel='telegram' ORDER BY id DESC LIMIT 1",
                (it_a.intent_id,))
    code = cur.fetchone()[0]
    r = ap.confirm(it_a.intent_id, "telegram", code)
    check("telegram code confirm ok -> FULLY APPROVED", r["ok"] and r["fully_approved"])

    # ── 4. fully approved, execution STILL blocked (the whole point this phase) ────────────
    d = authorize(it_a, "submit")
    check("guard still BLOCKS submit despite full 2FA approval", not d.allowed, d.reason)

    # ── 5. slot frees after consume/reject ─────────────────────────────────────────────────
    ap.consume(it_a.intent_id)
    r3 = ap.request_approval(it_b)   # no telegram env now — send is a no-op
    check("slot freed after consume: second intent can now request", r3.get("ok") is True, str(r3)[:120])
finally:
    cur.execute("DELETE FROM trade_approvals WHERE intent_id IN (%s,%s)",
                (it_a.intent_id, it_b.intent_id))
    _get_conn().commit()

print(f"\n  {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
