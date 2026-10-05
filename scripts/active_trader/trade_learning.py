"""Active Trader learning memory (operator 2026-10-05: "is anything persisted in memory when it
works so we learn?"). Deterministic, no LLM.

Two kinds of append-only records in <journal dir>/learning/trade_learning.jsonl:
  decision — every scored alert/veto: what the book, tape and signals said, and what happened
             (outcome from the price you could pay, best and rule exits).
  trip     — every closed round trip of yours: alert it followed, book/tape/volume at the buy and
             the sell (from trade_replay), P&L and hold time.
Records are keyed by id and written once. signal_calibration.py reads them to measure which
signals separated trades that worked from trades that were stopped, and PROPOSES threshold
changes; nothing here edits config.

Closed trips tagged to an alert also get one trade_lesson_memory row (human_review_only, pending
review) so the platform's lesson surfaces see them — only with apply=True; otherwise the rows are
returned for a dry run.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

try:
    from active_trader import momentum_alerts as ma
except ModuleNotFoundError:  # pragma: no cover
    from scripts.active_trader import momentum_alerts as ma

CONTRACT = "active-trader-learning-v1"
LESSON_CATEGORY = "active_trader_scalp"


def learning_path(base: Optional[Path] = None) -> Path:
    return (base or ma.journal_dir()) / "learning" / "trade_learning.jsonl"


def read_records(base: Optional[Path] = None) -> list[dict]:
    p = learning_path(base)
    if not p.exists():
        return []
    out = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def append_new(records: Iterable[Mapping[str, Any]], *, base: Optional[Path] = None) -> int:
    p = learning_path(base)
    have = {r.get("id") for r in read_records(base)}
    new = [r for r in records if r.get("id") and r["id"] not in have]
    if not new:
        return 0
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in new:
            fh.write(json.dumps(r, default=str, sort_keys=True) + "\n")
    return len(new)


def _signal_flags(signals: Optional[Mapping[str, Any]]) -> dict:
    """{name: True/False/None} — the compact form calibration buckets on."""
    return {k: (v.get("on") if isinstance(v, Mapping) else None) for k, v in (signals or {}).items()
            if isinstance(v, Mapping)}


def decision_record(row: Mapping[str, Any], scored: Mapping[str, Any]) -> Optional[dict]:
    o = scored.get("outcome") or {}
    if scored.get("status") != "SCORED" or not o.get("result"):
        return None
    c = row.get("candidate") or {}
    l2, tape = row.get("l2") or {}, row.get("tape") or {}
    sig = row.get("signals") or {}
    return {
        "contract": CONTRACT, "type": "decision", "id": f"decision:{scored.get('decision_id')}",
        "session_date": c.get("session_date"), "symbol": c.get("symbol"), "ts_epoch": row.get("ts_epoch"),
        "kind": row.get("kind"), "verdict": row.get("verdict"), "veto_reasons": row.get("veto_reasons") or [],
        "sent": bool(row.get("sent")),
        "features": {"depth_ratio": l2.get("depth_ratio"), "spread_bps": l2.get("spread_bps"),
                     "buy_ratio": tape.get("buy_ratio"), "rvol": c.get("rvol"), "float_mm": c.get("float_mm"),
                     "ign": c.get("ign"), "risk_pct": o.get("risk_pct"),
                     "ask_inside": (l2.get("supply") or {}).get("ask_size_inside"),
                     "ask_near": (l2.get("supply") or {}).get("ask_shares_near")},
        "signals": _signal_flags(sig if isinstance(sig, Mapping) else {}),
        "outcome": {"result": "STOPPED" if o.get("result") == "SAME_BAR" else o.get("result"),
                    "best_exit_pct": (o.get("best_exit") or {}).get("pct"),
                    "rule_exit_pct": (o.get("rule_exit") or {}).get("pct")},
    }


def trip_record(trip: Mapping[str, Any], replay: Optional[Mapping[str, Any]], day: str) -> Optional[dict]:
    if trip.get("sell_at") is None:
        return None
    buy = (replay or {}).get("buy") or {}
    return {
        "contract": CONTRACT, "type": "trip",
        "id": f"trip:{day}:{trip.get('symbol')}:{trip.get('buy_ts')}:{trip.get('qty')}",
        "session_date": day, "symbol": trip.get("symbol"), "source": trip.get("source"),
        "alert": trip.get("alert"), "qty": trip.get("qty"), "buy_price": trip.get("buy_price"),
        "sell_price": trip.get("sell_price"), "pnl": trip.get("pnl"), "pnl_pct": trip.get("pnl_pct"),
        "held_s": trip.get("held_s"),
        "at_buy": {k: buy.get(k) for k in ("evidence", "book", "tape", "volume", "schwab")},
        "signals": _signal_flags(buy.get("signals")),
        "at_sell": {k: ((replay or {}).get("sell") or {}).get(k) for k in ("evidence", "book", "tape", "volume")},
    }


def _g(v: Any) -> str:
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return "n/a"


def lesson_row(trip: Mapping[str, Any], replay: Optional[Mapping[str, Any]], *, trade_id: Optional[int]) -> dict:
    """One deterministic lesson for a closed trip that followed an alert."""
    buy = (replay or {}).get("buy") or {}
    book, vol = buy.get("book") or {}, buy.get("volume") or {}
    a = trip.get("alert") or {}
    facts = [
        f"{trip.get('symbol')} {trip.get('qty'):g} sh bought {trip.get('buy_price')} {a.get('lag_s')}s after the "
        f"{(a.get('kind') or '').lower()} alert (ask then {a.get('ask_at_alert')}), sold {trip.get('sell_price')} "
        f"after {trip.get('held_s')}s: P&L {trip.get('pnl')} before fees.",
    ]
    if book:
        inside = f", inside ask {_g(book.get('ask_inside'))} sh" if book.get("ask_inside") is not None else ""
        facts.append(f"Book at buy ({buy.get('evidence')}): bid depth {_g(book.get('bid_depth'))} / ask depth "
                     f"{_g(book.get('ask_depth'))}{inside}.")
    ch = buy.get("bracket_change") or {}
    if ch.get("bid_depth_pct") is not None:
        facts.append(f"Between the snapshots around the buy, bid depth changed {ch['bid_depth_pct']:+.0f}% and "
                     f"ask depth {ch['ask_depth_pct']:+.0f}%.")
    if vol:
        facts.append(f"Buy-minute volume {_g(vol.get('minute_volume'))} vs prior-5 avg {vol.get('prior5_avg')} "
                     f"({vol.get('source')}).")
    fired = [k for k, v in (buy.get("signals") or {}).items() if isinstance(v, Mapping) and v.get("on")]
    if fired:
        facts.append("Signals on at buy: " + ", ".join(fired) + ".")
    text = " ".join(facts)
    payload = json.dumps({"trip": dict(trip), "buy": buy}, sort_keys=True, default=str)
    pnl = trip.get("pnl")
    return {
        "trade_id": trade_id, "symbol": trip.get("symbol"), "strategy_id": "momentum_scalp",
        "close_date": (trip.get("sell_at") or "")[:10] or None,
        "exit_reason": "operator_manual", "dashboard_verdict": "deterministic:active_trader",
        "exit_quality": None, "mistake_type": None, "lesson_category": LESSON_CATEGORY,
        "improved_lesson": text, "rule_feedback": None,
        "next_operator_action": "Review in Active Trader → Alerts → Your trades.",
        "action_priority": "low", "action_owner": "active_trader_learning",
        "confidence_delta": "win" if (pnl or 0) > 0 else ("loss" if (pnl or 0) < 0 else "flat"),
        "repeated_pattern_key": f"at_scalp:{a.get('kind') or 'untagged'}:{'+'.join(sorted(fired)) or 'no_signals'}",
        "pnl": pnl, "r_multiple": None,
        "source_payload_hash": hashlib.md5(payload.encode()).hexdigest(),
    }


LESSON_COLUMNS = ("trade_id", "symbol", "strategy_id", "close_date", "exit_reason", "dashboard_verdict",
                  "exit_quality", "mistake_type", "lesson_category", "improved_lesson", "rule_feedback",
                  "next_operator_action", "action_priority", "action_owner", "confidence_delta",
                  "repeated_pattern_key", "pnl", "r_multiple", "source_payload_hash")


def insert_lessons(conn, rows: list[dict], *, apply: bool) -> dict:
    if not apply or not rows:
        return {"applied": False, "would_write": rows}
    cols = ", ".join(LESSON_COLUMNS)
    ph = ", ".join(["%s"] * len(LESSON_COLUMNS))
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(f"""INSERT INTO trade_lesson_memory ({cols}) VALUES ({ph})
                            ON CONFLICT (trade_id, lesson_category, source_payload_hash) DO NOTHING""",
                        [r.get(c) for c in LESSON_COLUMNS])
            n += cur.rowcount or 0
    conn.commit()
    return {"applied": True, "inserted": n}


def closed_trade_id(conn, trip: Mapping[str, Any]) -> Optional[int]:
    """trade_closed.id for this round trip (same symbol, day, shares, prices), SELECT only."""
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id FROM trade_closed WHERE symbol=%s AND close_date=%s
                           AND abs(buy_price-%s) < 0.005 AND abs(sell_price-%s) < 0.005 AND abs(shares-%s) < 0.001
                           ORDER BY id LIMIT 1""",
                        (trip.get("symbol"), (trip.get("sell_at") or "")[:10], trip.get("buy_price"),
                         trip.get("sell_price"), trip.get("qty")))
            row = cur.fetchone()
        return int(row[0]) if row else None
    except Exception:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


def summary(records: list[dict], *, min_sample: int) -> dict:
    dec = [r for r in records if r.get("type") == "decision"]
    trips = [r for r in records if r.get("type") == "trip"]
    sessions = sorted({r.get("session_date") for r in records if r.get("session_date")})
    return {"decisions": len(dec), "trips": len(trips), "sessions": len(sessions),
            "first_session": sessions[0] if sessions else None, "last_session": sessions[-1] if sessions else None,
            "min_sample": min_sample,
            "status": "learning" if len(dec) >= min_sample else "insufficient sample",
            "trip_pnl": round(sum(r.get("pnl") or 0 for r in trips), 2)}
