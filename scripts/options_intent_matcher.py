#!/usr/bin/env python3
"""Proactive contract matcher for operator options intents (operator 2026-10-05, SPCX).

For every active intent (spec.options_intent on a ticker watch directive): pull Schwab's live
option chain (read-only market data), rank the contracts that fit the plan, and record them.

  options_intent_matcher.py              dry run: print the matches, write nothing, send nothing
  options_intent_matcher.py --apply      write the snapshot (data/options_intent/latest.json +
                                         matches.jsonl); Telegram digest only when config mode=send
                                         and something changed materially (throttled)

No proposal is staged and no order path exists (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib.options_intent import matcher as mt  # noqa: E402
from lib.options_intent import store  # noqa: E402

MESSAGE_CLASS = "options_intent_digest"


CC_BASE = "http://127.0.0.1:7777/api/v2"


def schwab_chain(sym: str, side: str) -> dict:
    """Schwab's live chain through the Command Center's read-only GET (the one Schwab access
    point the desk already uses; this process opens no broker client)."""
    import os
    import urllib.parse
    import urllib.request
    base = os.environ.get("TRADEAI_CC_API_BASE", CC_BASE).rstrip("/")
    url = f"{base}/schwab/option-chain?" + urllib.parse.urlencode({"symbol": sym, "strikes": 40, "side": side})
    with urllib.request.urlopen(url, timeout=45) as r:
        d = json.loads(r.read().decode())
    return d.get("data", d) if isinstance(d, dict) else {}


def desk_earnings(sym: str) -> dict:
    try:
        from options_desk_enterprise import earnings_blackout_check
        r = earnings_blackout_check(sym, dte=30, strategy="cash_secured_put") or {}
        return {"date": r.get("next_earnings") or r.get("event_date"), "source": "options desk earnings gate"}
    except Exception:  # noqa: BLE001
        return {}


def holdings() -> list:
    try:
        import options_engine as oe
        items, _ = oe._load_holdings()
        return items or []
    except Exception:  # noqa: BLE001
        return []


def telegram_send(text: str) -> bool:
    """The operator asked for this standing watch himself and the digest is throttled per intent
    (digest.min_interval_min), so it goes out now instead of waiting in the router's P1 batch —
    same reasoning as the Active Trader scalp alerts. Still through the one chokepoint + editor."""
    from telegram_alert import send_telegram
    return bool(send_telegram(text, bypass_router=True, message_class=MESSAGE_CLASS))


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def run(intents: list, *, cfg: dict, apply: bool, chain_fn=schwab_chain, earnings_fn=desk_earnings,
        holdings_list=None, send_fn=telegram_send, now: float | None = None, out=print) -> dict:
    now = time.time() if now is None else now
    d = mt.state_dir()
    latest_p, state_p = d / "latest.json", d / "digest_state.json"
    latest = _read_json(latest_p, {})
    dstate = _read_json(state_p, {})
    hl = holdings() if holdings_list is None else holdings_list
    summary = {"intents": len(intents), "matched": 0, "digests_sent": 0, "mode": cfg["mode"], "apply": apply}
    new_latest = dict(latest)
    for it in intents:
        m = mt.match_intent(it, chain_fn=chain_fn, holdings=hl, earnings_fn=earnings_fn,
                            liq=cfg.get("liquidity"), top=int(cfg.get("top_per_play", 5)))
        summary["matched"] += 1
        key = it["symbol"]
        reasons = mt.material_changes(latest.get(key), m,
                                      min_improvement_pct=float(cfg["digest"]["min_improvement_pct"]))
        text = mt.digest_text(m, reasons or ["no material change"], per_play=int(cfg["digest"]["per_play"]))
        out(text)
        m["material_changes"] = reasons
        new_latest[key] = m
        last_sent = float((dstate.get(key) or {}).get("ts") or 0)
        due = now - last_sent >= float(cfg["digest"]["min_interval_min"]) * 60
        if apply and reasons and due and cfg["mode"] == "send":
            ok = send_fn(text)
            m["digest_sent"] = ok
            if ok:
                summary["digests_sent"] += 1
                dstate[key] = {"ts": now, "reasons": reasons}
    if apply:
        d.mkdir(parents=True, exist_ok=True)
        with (d / "matches.jsonl").open("a", encoding="utf-8") as fh:
            for k, v in new_latest.items():
                if k in {i["symbol"] for i in intents}:
                    fh.write(json.dumps(v, default=str, sort_keys=True) + "\n")
        latest_p.write_text(json.dumps(new_latest, default=str, indent=1), encoding="utf-8")
        state_p.write_text(json.dumps(dstate, default=str), encoding="utf-8")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--symbol", help="only this intent")
    a = ap.parse_args(argv)
    cfg = mt.load_config()
    from db_adapter import get_connection  # type: ignore
    conn = get_connection()
    try:
        cur = conn.cursor()
        intents = store.load_intents(cur)
        conn.rollback()
    finally:
        conn.close()
    if a.symbol:
        intents = [i for i in intents if i["symbol"] == a.symbol.upper()]
    res = run(intents, cfg=cfg, apply=a.apply)
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
