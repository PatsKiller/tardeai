#!/usr/bin/env python3
"""rotation_round_trips.py — Defense v4 WS-RT: the round-trip ledger.

"Temporarily step out" finally has a memory: every move-out advisory registers here;
exits are detected (Schwab trade_transactions ingest, 12h lag) OR one-tap confirmed;
re-entry conditions are stored AT exit time from the advisory's own invalidation
logic; the nightly engine flips satisfied rows to rollback_open; closes score the
step-out against having held. Wash-sale is a WARNING system with deterministic dates,
never tax advice — and it NEVER suppresses a rollback alert (both facts render).

Statuses: advised → stepped_out → rollback_open → rolled_back | expired | cancelled
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WASH_DAYS = 31
EXPIRE_DAYS = 60


def ensure_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS rotation_round_trips (
        id serial PRIMARY KEY, advisory_id text NOT NULL, symbol text NOT NULL,
        account text NOT NULL, status text NOT NULL DEFAULT 'advised',
        exit_advised_at timestamptz DEFAULT now(),
        exit_detected_at timestamptz, exit_source text, exit_qty numeric, exit_price numeric,
        exit_loss_known boolean, exit_is_loss boolean,
        re_entry_conditions jsonb NOT NULL,
        rollback_opened_at timestamptz, closed_at timestamptz, close_reason text,
        created_at timestamptz DEFAULT now(),
        UNIQUE (advisory_id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS round_trip_outcomes (
        id serial PRIMARY KEY, round_trip_id int REFERENCES rotation_round_trips(id),
        symbol text, account text, out_days int,
        exit_price numeric, close_price numeric, symbol_return_pct numeric,
        verdict text, source_type text DEFAULT 'rotation_round_trip',
        created_at timestamptz DEFAULT now())""")


def conditions_from_card(card: dict, sector: str | None, state: str | None,
                         is_core: bool = False) -> list:
    """Structured re-entry conditions derived from the advisory's invalidation —
    whichever satisfies first opens the rollback window. Core positions get the
    PATIENT window (v6 C3) — the desk expects them back."""
    try:
        core_cfg = json.loads((ROOT / "config" / "defense_recommendations.json").read_text()).get("core", {})
        window = core_cfg.get("reentry_window_days", 90) if is_core else \
            core_cfg.get("noncore_reentry_window_days", EXPIRE_DAYS)
    except Exception:
        window = EXPIRE_DAYS
    conds = []
    if sector and state:
        conds.append({"type": "sector_state_exit", "sector": sector, "from_state": state,
                      "label": f"{sector} exits {state} (2-close confirmed)"})
    sym = card["instruments"][0]["symbol"]
    conds.append({"type": "price_reclaim_dma", "symbol": sym, "dma": 50,
                  "label": f"{sym} reclaims its 50DMA"})
    conds.append({"type": "elapsed_days", "days": window,
                  "label": f"{window} sessions elapsed ({'patient core window' if is_core else 'auto-expire review'})"})
    return conds


def register_advisories(cur, cards: list, sector_states: dict):
    """Move-out cards → 'advised' rows (idempotent per advisory day)."""
    n = 0
    for card in cards:
        if card.get("group") != "protect" or not card["id"].startswith("moveout-"):
            continue
        sym = card["instruments"][0]["symbol"]
        acct = card["accounts"][0]
        sec = None
        for f in card.get("factors", []):
            if f["name"] == "sector state":
                sec = str(f["value"]).split(" ")[0]
        state = sector_states.get(sec)
        cur.execute("""SELECT 1 FROM rotation_round_trips WHERE symbol=%s AND account=%s
                       AND status IN ('advised','stepped_out','rollback_open') LIMIT 1""",
                    (sym, acct))
        if cur.fetchone():
            continue
        cur.execute("""INSERT INTO rotation_round_trips
                       (advisory_id, symbol, account, re_entry_conditions)
                       VALUES (%s,%s,%s,%s) ON CONFLICT (advisory_id) DO NOTHING""",
                    (card["id"], sym, acct,
                     json.dumps(conditions_from_card(card, sec, state,
                                                     is_core=bool(card.get("is_core"))))))
        n += cur.rowcount
    return n


def detect_fills(cur):
    """Reconcile 'advised' rows against Schwab trade_transactions (Sell after advised_at).
    12h ingest lag is known — one-tap confirm is the primary same-day signal."""
    cur.execute("""SELECT id, symbol, account, exit_advised_at FROM rotation_round_trips
                   WHERE status='advised'""")
    n = 0
    for rid, sym, acct, advised_at in cur.fetchall():
        cur.execute("""SELECT trade_date, quantity, price FROM trade_transactions
                       WHERE symbol=%s AND account=%s AND action='Sell'
                         AND trade_date >= %s ORDER BY trade_date LIMIT 1""",
                    (sym, acct, advised_at.date()))
        f = cur.fetchone()
        if f:
            cur.execute("""UPDATE rotation_round_trips SET status='stepped_out',
                           exit_detected_at=%s, exit_source='ingest',
                           exit_qty=%s, exit_price=%s, exit_loss_known=false
                           WHERE id=%s""",
                        (f[0], f[1], f[2], rid))
            n += 1
    return n


def confirm_exit(cur, round_trip_id: int, qty=None, price=None):
    """One-tap 'I executed this' from the card. Reconciles against ingest later."""
    cur.execute("""UPDATE rotation_round_trips SET status='stepped_out',
                   exit_detected_at=now(), exit_source='operator_confirm',
                   exit_qty=COALESCE(%s, exit_qty), exit_price=COALESCE(%s, exit_price),
                   exit_loss_known=false
                   WHERE id=%s AND status IN ('advised','stepped_out') RETURNING id""",
                (qty, price, round_trip_id))
    return cur.fetchone() is not None


def _price_and_sma50(symbol: str, prices: dict, enrich: dict):
    px = prices.get(symbol)
    e = enrich.get(symbol) or {}
    above50 = (e.get("sma50_pct") or -1) > 0
    return px, above50


def evaluate(cur, sector_states: dict, prices: dict, enrich: dict) -> list:
    """Nightly: open round-trips → rollback_open when any condition is met.
    Returns render rows for the 'Stepped out — watching' panel."""
    cur.execute("""SELECT id, symbol, account, status, exit_advised_at, exit_detected_at,
                   exit_source, exit_price, exit_is_loss, exit_loss_known,
                   re_entry_conditions, rollback_opened_at
                   FROM rotation_round_trips
                   WHERE status IN ('advised','stepped_out','rollback_open')
                   ORDER BY exit_advised_at DESC""")
    out = []
    now = datetime.now(timezone.utc)
    for (rid, sym, acct, status, advised_at, detected_at, source, exit_px,
         is_loss, loss_known, conds, opened_at) in cur.fetchall():
        conds = conds if isinstance(conds, list) else json.loads(conds)
        px, above50 = _price_and_sma50(sym, prices, enrich)
        met, checks = [], []
        for c in conds:
            ok = False
            if c["type"] == "sector_state_exit":
                ok = sector_states.get(c["sector"]) not in (c["from_state"], None)
            elif c["type"] == "price_reclaim_dma":
                ok = above50
            elif c["type"] == "elapsed_days":
                base = detected_at or advised_at
                ok = (now - base).days >= c["days"]
            checks.append({**c, "met": ok})
            if ok:
                met.append(c["label"])
        if status == "stepped_out" and met:
            cur.execute("""UPDATE rotation_round_trips SET status='rollback_open',
                           rollback_opened_at=now() WHERE id=%s""", (rid,))
            status = "rollback_open"
        wash = None
        if acct == "schwab_taxable" and status in ("stepped_out", "rollback_open") and detected_at:
            days_left = WASH_DAYS - (now - detected_at).days
            if days_left > 0:
                wash = {"days_left": days_left,
                        "loss_known": bool(loss_known), "is_loss": bool(is_loss),
                        "line": (f"wash-sale window: {days_left}d remain — repurchase in ANY account "
                                 f"(incl. IRAs — permanently) before day {WASH_DAYS} disallows a loss"
                                 + ("" if loss_known else " · basis n/a (Cost Basis export pending) — treat as potential loss")
                                 + " · verify with your tax context (route: Alex)")}
        vs_exit = (round((px - float(exit_px)) / float(exit_px) * 100, 1)
                   if px and exit_px else None)
        out.append({"id": rid, "symbol": sym, "account": acct, "status": status,
                    "advised_at": str(advised_at)[:10],
                    "exit": {"detected_at": str(detected_at)[:10] if detected_at else None,
                             "source": source, "price": float(exit_px) if exit_px else None},
                    "now_price": px, "now_vs_exit_pct": vs_exit,
                    "conditions": checks, "wash_sale": wash})
    return out


def close_round_trip(cur, round_trip_id: int, reason: str, prices: dict):
    """rolled_back | expired → outcome row (step-out scored vs having held)."""
    cur.execute("""SELECT symbol, account, exit_detected_at, exit_price
                   FROM rotation_round_trips WHERE id=%s""", (round_trip_id,))
    row = cur.fetchone()
    if not row:
        return None
    sym, acct, detected_at, exit_px = row
    px = prices.get(sym)
    ret = round((px - float(exit_px)) / float(exit_px) * 100, 2) if px and exit_px else None
    verdict = None
    if ret is not None:
        # symbol fell while out → stepping out saved money
        verdict = "good_exit" if ret < 0 else "would_have_been_better_to_hold"
    out_days = None
    if detected_at and hasattr(detected_at, "tzinfo"):
        base = detected_at if detected_at.tzinfo else detected_at.replace(tzinfo=timezone.utc)
        out_days = (datetime.now(timezone.utc) - base).days
    cur.execute("""UPDATE rotation_round_trips SET status=%s, closed_at=now(),
                   close_reason=%s WHERE id=%s""", (reason, reason, round_trip_id))
    cur.execute("""INSERT INTO round_trip_outcomes
                   (round_trip_id, symbol, account, out_days, exit_price, close_price,
                    symbol_return_pct, verdict) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (round_trip_id, sym, acct, out_days, exit_px, px, ret, verdict))
    return {"symbol": sym, "return_while_out": ret, "verdict": verdict}
