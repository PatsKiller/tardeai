#!/usr/bin/env python3
"""schwab_stop_batch_request — request advisory protective stops on ALL Schwab holdings.

Operator instruction 2026-07-14: "set stops on all schwab holdings with 2fa".

For every stoppable Schwab holding (whole shares ≥1, not a fund, has a current
advisory), this: (1) refreshes the quote, (2) REQUESTS the advisor's fixed stop
through /api/v2/holdings/protective-stop. Each request that passes the gates
returns awaiting_approval and fires the per-order 2FA (Telegram + email code;
EITHER channel confirms). NOTHING is placed by this script — every placement
still needs the operator's individual 2FA confirmation, and the stale-quote /
whole-share / protective-envelope gates all apply unchanged. Fail-closed: any
blocked symbol is reported, never forced.

Run during market hours (quotes must be <60m fresh):
  .venv/bin/python scripts/schwab_stop_batch_request.py            # dry list only
  .venv/bin/python scripts/schwab_stop_batch_request.py --request  # fire the 2FA requests
Then confirm each order in Telegram (or the web drawer) one by one.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
BASE = "http://127.0.0.1:7777"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def get(path: str) -> dict:
    return json.loads(urllib.request.urlopen(BASE + path, timeout=120).read())


def candidates() -> list[dict]:
    import holding_family as hf
    hold = json.loads((ROOT / "data/portfolios/state/holdings.json").read_text())["holdings"]
    cov = get("/api/v2/portfolio/llm-coverage")["data"]["protection"]
    out = []
    for h in hold:
        sym = str(h.get("symbol") or "").upper()
        acct = str(h.get("account") or "")
        if not acct.startswith("schwab") or sym == "CASH":
            continue
        sh = float(h.get("shares") or 0)
        if float(h.get("market_value") or 0) < 500 or int(sh) < 1:
            continue
        if hf.is_unstoppable_fund(sym):
            continue
        stop = (cov.get(sym) or {}).get("stop_price")
        if not stop:
            continue
        out.append({"symbol": sym, "account": acct, "qty": int(sh),
                    "stop_price": float(stop), "value": float(h.get("market_value") or 0)})
    return out


def _orders_lane_healthy(accounts: set[str]) -> tuple[bool, str]:
    """The Schwab open-orders read MUST succeed before we request any stop: if the lane is
    degraded, stops the operator placed directly at Schwab are invisible, and requesting a
    second stop against an invisible first one can OVER-SELL. Fail closed."""
    import schwab_transport as st
    bad = []
    for acct in sorted(accounts):
        raw = st.get_orders_raw(acct)
        if not isinstance(raw, list):
            alias = acct[:-4] if acct.endswith("_ira") else f"{acct}_ira"
            raw = st.get_orders_raw(alias)
        if not isinstance(raw, list):
            bad.append(f"{acct}: {raw.get('reason') or raw.get('status') if isinstance(raw, dict) else 'unreadable'}")
    return (not bad), "; ".join(bad)


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))
    fire = "--request" in sys.argv
    rows = candidates()
    if fire:
        ok, why = _orders_lane_healthy({r["account"] for r in rows})
        if not ok:
            print("REFUSING to request any stop — Schwab orders lane degraded (existing stops"
                  " would be invisible; double-stop/over-sell risk):")
            print("  " + why)
            print("Retry when the token manager's login-token lane recovers (auto-managed; do not touch).")
            return 1
    print(f"{len(rows)} Schwab stop candidates (advisory fixed stops):")
    fired, blocked = [], []
    for r in rows:
        line = f"  {r['symbol']:6} {r['account']:20} SELL {r['qty']:5d} STOP ${r['stop_price']}"
        if not fire:
            print(line)
            continue
        q = post("/api/v2/holdings/protective-stop/refresh-quote",
                 {"symbol": r["symbol"], "account": r["account"]})
        if q.get("operator_readiness") == "BLOCKED" or not q.get("quote_fresh"):
            blocked.append((r["symbol"], "; ".join(q.get("blockers") or ["quote not fresh"])))
            print(line, "→ BLOCKED:", (q.get("blockers") or ["stale quote"])[0])
            continue
        res = post("/api/v2/holdings/protective-stop", {
            "symbol": r["symbol"], "account": r["account"], "qty": r["qty"],
            "order_kind": "STOP", "stop_price": r["stop_price"],
            "advised_stop": r["stop_price"],
            "current_price": q.get("quote_price"),
            "quote_at": q.get("quote_time_normalized"),
            "whole_share_confirmed": True,
        })
        mode = res.get("mode")
        if mode == "awaiting_approval":
            fired.append((r["symbol"], res.get("intent_id")))
            print(line, f"→ 2FA REQUESTED (intent {res.get('intent_id')})")
        else:
            blocked.append((r["symbol"], str(res.get("error") or res.get("reason") or mode)[:100]))
            print(line, "→", mode, str(res.get("error") or "")[:90])
    if fire:
        print(f"\n{len(fired)} awaiting your per-order 2FA (Telegram or web drawer) · "
              f"{len(blocked)} blocked")
        for s, why in blocked:
            print(f"  blocked {s}: {why}")
    else:
        print("\nDry list only. Add --request during market hours to fire the 2FA requests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
