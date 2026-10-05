"""GET /api/v3/active-trader/alerts — Phase 1 L2-confirmed scalp alert feed (read-only).

Reads the append-only decision journal, the scored ledger and the engine heartbeat that
scripts/active_trader/momentum_alert_pass writes into persistent state, plus the alert mode
from config/scalp_signal_engine.yaml. Pure read: never writes, never sends, no broker, no LLM.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    from active_trader import momentum_alerts as ma
    from active_trader import momentum_alert_scoring as ms
except ModuleNotFoundError:
    from scripts.active_trader import momentum_alerts as ma
    from scripts.active_trader import momentum_alert_scoring as ms

CONTRACT = "active-trader-alerts-feed-v1"   # additive fields only (2026-10-05)
FILL_MATCH_WINDOW_S = 20 * 60      # a fill up to 20 min after a sent alert on the same symbol is "after the alert"
ET = ZoneInfo("America/New_York")
REPO = Path(__file__).resolve().parents[2]
TAIL_BYTES = 4_000_000          # journal tail read; a full session is far smaller
ENGINE_WINDOW_ET = ("09:30", "11:55")
L2_PROOF = {"source": "moomoo OpenD (quote context)", "levels_proven": 60,
            "proven_at": "2026-10-04", "compare": "Schwab NASDAQ_BOOK (5 levels, comparison only)"}


def _tail_lines(path: Path, max_bytes: int = TAIL_BYTES) -> list[str]:
    if not path.exists():
        return []
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()                      # drop the partial first line
        return fh.read().decode("utf-8", "replace").splitlines()


def _rows(path: Path) -> list[dict]:
    out = []
    for line in _tail_lines(path):
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


def _alert_config() -> ma.AlertConfig:
    try:
        import yaml
        raw = yaml.safe_load((REPO / "config" / "scalp_signal_engine.yaml").read_text(encoding="utf-8")) or {}
        return ma.AlertConfig.from_mapping(raw.get("active_trader_alerts"))
    except Exception:  # noqa: BLE001 — unreadable config falls back to the code defaults (shadow)
        return ma.AlertConfig()


def _et(ts: Optional[float]) -> Optional[str]:
    return None if ts is None else datetime.fromtimestamp(ts, ET).isoformat(timespec="seconds")


def _compact(row: dict, score: Optional[dict]) -> dict:
    c = row.get("candidate") or {}
    l2, tape, cmp_ = row.get("l2") or {}, row.get("tape") or {}, row.get("l2_compare") or {}
    windows = (score or {}).get("windows") or {}
    return {
        "id": ms.decision_id(row), "at": _et(row.get("ts_epoch")), "ts_epoch": row.get("ts_epoch"),
        "symbol": c.get("symbol"), "kind": row.get("kind"), "verdict": row.get("verdict"),
        "veto_reasons": row.get("veto_reasons") or [], "sent": bool(row.get("sent")),
        "mode": row.get("mode"), "last": c.get("last"), "entry": c.get("entry_ref"), "stop": c.get("stop_ref"),
        "r": row.get("r_dollars"), "float_mm": c.get("float_mm"), "rvol": c.get("rvol"),
        "ign": c.get("ign"), "lane": c.get("lane"), "setup": c.get("setup_label") or c.get("setup_id"),
        "quote_age_s": row.get("quote_age_s"),
        "l2": {k: l2.get(k) for k in ("source", "levels", "depth_ratio", "spread_bps", "age_s", "ts_source",
                                       "best_bid", "best_ask", "bid_depth", "ask_depth")},
        "tape": {k: tape.get(k) for k in ("source", "prints", "buy_ratio", "age_s")} if tape else None,
        "l2_compare": {k: cmp_.get(k) for k in ("source", "levels", "depth_ratio", "spread_bps", "age_s")} if cmp_ else None,
        "score": {w: {k: v.get(k) for k in ("mfe_r", "mae_r", "mfe_pct", "mae_pct")} for w, v in windows.items()
                  if isinstance(v, dict) and v.get("mfe") is not None} or None,
        "supply": l2.get("supply") or None,
        "signals": _signals_view(row.get("signals")),
        "outcome": _outcome_view((score or {}).get("outcome")),
        # alert sync (2026-10-05): which loop decided, the market event it reacted to, and how late
        "source": row.get("source") or "pass5",
        "intrabar": bool(c.get("intrabar")),
        "break_level": c.get("break_level"),
        "zone": ({"low": c.get("zone_low"), "high": c.get("zone_high")} if c.get("zone_low") is not None else None),
        "latency": ({**(row.get("latency") or {}), "event_at": _et((row.get("latency") or {}).get("event_ts_epoch"))}
                    if row.get("latency") else None),
    }


def latency_summary(rows: list[dict]) -> dict:
    """p50 / p90 seconds from the market event (break print, zone entry, extension, bar close) to the
    alert, for ALERT rows — the proof that alerts are in sync with the tape."""
    def pct(xs: list[float], q: float):
        if not xs:
            return None
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 1)
    out: dict[str, Any] = {}
    groups: dict[str, list[float]] = {}
    for r in rows:
        lat = r.get("latency") or {}
        if r.get("verdict") != ma.ALERT or lat.get("latency_s") is None:
            continue
        groups.setdefault("all", []).append(float(lat["latency_s"]))
        groups.setdefault(f"source:{r.get('source') or 'pass5'}", []).append(float(lat["latency_s"]))
        groups.setdefault(f"event:{lat.get('event')}", []).append(float(lat["latency_s"]))
    for k, xs in groups.items():
        out[k] = {"n": len(xs), "p50_s": pct(xs, 0.5), "p90_s": pct(xs, 0.9)}
    return out


def _signals_view(sig: Any) -> Optional[dict]:
    if not isinstance(sig, dict):
        return None
    detail = {k: v for k, v in sig.items() if isinstance(v, dict)}
    return {"status": sig.get("status"), "snapshots": sig.get("snapshots"),
            "fired": [k for k, v in detail.items() if v.get("on") is True], "detail": detail}


def _learning_block(day: str) -> dict:
    """Replays, exit watch and learning summary — each part fails soft on its own."""
    out: dict[str, Any] = {"replays": [], "exit_watch": [], "learning": None}
    try:
        from active_trader import trade_replay as tr
    except ModuleNotFoundError:  # pragma: no cover
        from scripts.active_trader import trade_replay as tr
    try:
        out["replays"] = tr.read_replays(day)
    except Exception:  # noqa: BLE001
        pass
    try:
        from active_trader import exit_watch as ew
    except ModuleNotFoundError:  # pragma: no cover
        from scripts.active_trader import exit_watch as ew
    try:
        out["exit_watch"] = [{"at": _et(r.get("ts_epoch")), "symbol": (r.get("position") or {}).get("symbol"),
                              "fired": r.get("fired"), "last": r.get("last"), "verdict": r.get("verdict"),
                              "sent": r.get("sent"), "mode": r.get("mode"), "position": r.get("position")}
                             for r in ew.read_rows(day)][-50:]
    except Exception:  # noqa: BLE001
        pass
    try:
        from active_trader import trade_learning as tl
        from active_trader import signal_calibration as sc
    except ModuleNotFoundError:  # pragma: no cover
        from scripts.active_trader import trade_learning as tl
        from scripts.active_trader import signal_calibration as sc
    try:
        rep = sc.read_report() or {}
        summ = tl.summary(tl.read_records(), min_sample=int(rep.get("min_sample") or sc.DEFAULTS["min_sample"]))
        summ["calibration"] = {k: rep.get(k) for k in ("status", "decisions", "worked_rate", "proposals", "generated_at")} if rep else None
        out["learning"] = summ
    except Exception:  # noqa: BLE001
        pass
    return out


def _outcome_view(o: Optional[dict]) -> Optional[dict]:
    if not o:
        return None
    v = dict(o)
    for k in ("best_exit", "rule_exit"):
        if isinstance(v.get(k), dict):
            v[k] = {**v[k], "at": _et(v[k].get("ts_epoch"))}
    v["first_touch_at"] = _et(v.get("first_touch_epoch"))
    return v


def operator_fills(day: str, symbols: set[str], *, conn=None) -> list[dict]:
    """Your broker fills on these symbols that day (read-only SELECT on trade_transactions)."""
    if not symbols:
        return []
    if conn is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return []          # tests never reach the live database; they inject a connection
    own = conn is None
    try:
        if own:
            from db_adapter import get_connection  # type: ignore
            conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""SELECT trade_time, account, symbol, action, quantity, price, amount, import_source
                           FROM trade_transactions
                           WHERE trade_date = %s AND symbol = ANY(%s) AND action IN ('Buy', 'Sell')
                           ORDER BY trade_time""", (day, sorted(symbols)))
            rows = cur.fetchall()
    except Exception:  # noqa: BLE001 — the feed never fails because the fills lookup did
        return []
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    out = []
    for r in rows:
        t = r[0]
        out.append({"ts_epoch": t.timestamp() if hasattr(t, "timestamp") else None, "account": r[1],
                    "symbol": r[2], "side": r[3], "qty": float(r[4] or 0), "price": float(r[5] or 0),
                    "amount": float(r[6] or 0), "source": r[7]})
    return out


def _with_replays(trips: list[dict], replays: list[dict]) -> list[dict]:
    by = {(r.get("symbol"), r.get("buy_ts"), r.get("qty")): r for r in replays or []}
    for t in trips:
        rp = by.get((t.get("symbol"), t.get("buy_ts"), t.get("qty")))
        if rp:
            t["replay"] = {"buy": rp.get("buy"), "sell": rp.get("sell")}
    return trips


def attribute_fills(fills: list[dict], decisions: list[dict]) -> list[dict]:
    """Pair buys with the following sells (FIFO, per symbol) and tag each round trip with the latest
    SENT alert on that symbol in the FILL_MATCH_WINDOW_S before the buy. Untagged trades stay
    visible as untagged — nothing is guessed."""
    sent = sorted((d for d in decisions if d.get("sent")), key=lambda d: d.get("ts_epoch") or 0)
    trips, open_ = [], {}
    for f in sorted(fills, key=lambda x: x.get("ts_epoch") or 0):
        q = open_.setdefault(f["symbol"], [])
        if f["side"] == "Buy":
            q.append(dict(f))
            continue
        qty = f["qty"]
        while qty > 1e-9 and q:
            b = q[0]
            take = min(qty, b["qty"])
            trips.append({"symbol": f["symbol"], "account": f["account"], "qty": take,
                          "buy_at": _et(b["ts_epoch"]), "buy_ts": b["ts_epoch"], "buy_price": b["price"],
                          "sell_at": _et(f["ts_epoch"]), "sell_price": f["price"],
                          "pnl": round((f["price"] - b["price"]) * take, 2),
                          "pnl_pct": round((f["price"] - b["price"]) / b["price"] * 100, 3) if b["price"] else None,
                          "held_s": round((f["ts_epoch"] or 0) - (b["ts_epoch"] or 0))})
            b["qty"] -= take
            qty -= take
            if b["qty"] <= 1e-9:
                q.pop(0)
    for sym, q in open_.items():
        for b in q:
            trips.append({"symbol": sym, "account": b["account"], "qty": b["qty"], "buy_at": _et(b["ts_epoch"]),
                          "buy_ts": b["ts_epoch"], "buy_price": b["price"], "sell_at": None, "sell_price": None,
                          "pnl": None, "pnl_pct": None, "held_s": None})
    for t in trips:
        prior = [d for d in sent if d.get("symbol") == t["symbol"] and d.get("ts_epoch") is not None
                 and t["buy_ts"] is not None and 0 <= t["buy_ts"] - d["ts_epoch"] <= FILL_MATCH_WINDOW_S]
        a = prior[-1] if prior else None
        t["source"] = "active_trader" if a else "untagged"
        t["alert"] = ({"id": a["id"], "kind": a.get("kind"), "at": a.get("at"), "ask_at_alert": (a.get("l2") or {}).get("best_ask"),
                       "last_at_alert": a.get("last"), "stop": a.get("stop"),
                       "lag_s": round(t["buy_ts"] - a["ts_epoch"])} if a else None)
    return trips


def alerts_snapshot(*, limit: int = 100, session_date: Optional[str] = None,
                    now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    d = ma.journal_dir()
    cfg = _alert_config()
    journal = [r for r in _rows(d / "momentum_alerts.jsonl") if r.get("contract") == ma.CONTRACT]
    day = session_date or datetime.fromtimestamp(now, ET).date().isoformat()
    today = [r for r in journal if (r.get("candidate") or {}).get("session_date") == day]
    latest_day = max(((r.get("candidate") or {}).get("session_date") or "" for r in journal), default=None)
    scored = {s.get("decision_id"): s for s in _rows(d / "momentum_alerts_scored.jsonl")}
    try:
        hb = json.loads((d / "momentum_alerts_heartbeat.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        hb = None
    alerts = [r for r in today if r.get("verdict") == ma.ALERT]
    vetoes = [r for r in today if r.get("verdict") == ma.VETO]
    reasons = Counter(x for r in vetoes for x in (r.get("veto_reasons") or []))
    all_scored = list(scored.values())
    today_ids = {ms.decision_id(r) for r in today}
    day_scored = [v for k, v in scored.items() if k in today_ids]
    compact = [_compact(r, scored.get(ms.decision_id(r)))
               for r in sorted(today, key=lambda x: x.get("ts_epoch") or 0, reverse=True)]
    fills = operator_fills(day, {d["symbol"] for d in compact if d.get("symbol")})
    extra = _learning_block(day)
    sessions = sorted({(r.get("candidate") or {}).get("session_date") for r in journal} - {None}, reverse=True)
    hb_age = (now - float(hb["ts_epoch"])) if hb and hb.get("ts_epoch") else None
    return {
        "contract": CONTRACT, "authority": ma.AUTHORITY, "read_only": True,
        "generated_at": _et(now), "session_date": day, "latest_session_with_decisions": latest_day,
        "mode": cfg.mode, "delivery": "telegram" if cfg.mode == "send" else "journal only (shadow)",
        "engine": {"window_et": ENGINE_WINDOW_ET, "last_pass_at": _et(hb.get("ts_epoch")) if hb else None,
                   "last_pass_age_s": None if hb_age is None else round(hb_age),
                   "last_pass": (hb or {}).get("last_pass"), "symbols_scored": (hb or {}).get("symbols_scored")},
        "l2": L2_PROOF,
        "rules": {
            "armed": f"trigger state ARMED (or IGN lane {'/'.join(cfg.armed_lanes)}) + book bid/ask ≥ "
                     f"{cfg.min_depth_ratio_armed:g}x, spread ≤ {cfg.max_spread_bps:g} bps",
            "triggered": f"trigger fired ≤ {cfg.max_fire_age_s / 60:g} min ago + book bid/ask ≥ "
                         f"{cfg.min_depth_ratio_triggered:g}x, spread ≤ {cfg.max_spread_bps:g} bps + "
                         f"tape buys ≥ {cfg.min_buy_ratio * 100:.0f}% of last {cfg.tape_prints} prints + stop set",
            "freshness": f"quote ≤ {cfg.max_quote_age_s:g}s · book ≤ {cfg.max_book_age_s:g}s · tape ≤ {cfg.max_tape_age_s:g}s",
            "throttle": f"{cfg.cooldown_s / 60:g} min cooldown per symbol+kind · {cfg.max_alerts_per_hour}/hour",
        },
        "counts": {"triggered_alerts": sum(1 for r in alerts if r.get("kind") == ma.TRIGGERED),
                   "armed_alerts": sum(1 for r in alerts if r.get("kind") == ma.ARMED),
                   "by_kind": {k: sum(1 for r in alerts if r.get("kind") == k) for k in ma.KINDS},
                   "buy_alerts": sum(1 for r in alerts if r.get("kind") in (ma.TRIGGERED, ma.PULLBACK_ZONE)),
                   "headsup_alerts": sum(1 for r in alerts if r.get("kind") in (ma.ARMED, ma.APPROACHING,
                                                                                 ma.EXTENDED, ma.TRIGGER_CANCELLED)),
                   "vetoes": len(vetoes), "sent": sum(1 for r in today if r.get("sent")),
                   "decisions": len(today)},
        "veto_reasons": dict(reasons.most_common()),
        "latency": latency_summary(today),
        "precision": {w: ms.precision_summary(all_scored, window=w, hit_r=1.0) for w in ("1m", "5m", "15m")},
        "precision_note": "legacy v1: measured from the trigger's fire price; a stop hit first still counts. Use outcomes.",
        "outcomes": {"session": ms.outcome_summary(day_scored), "all": ms.outcome_summary(all_scored),
                     "touch_min": cfg.score_touch_min, "horizon_min": cfg.score_horizon_min,
                     "pending": sum(1 for d in compact if not d.get("outcome"))},
        "scored_total": len(all_scored),
        "scored_session": len(day_scored),
        "sessions": sessions,
        "your_trades": _with_replays(attribute_fills(fills, compact), extra["replays"]),
        "exit_watch": extra["exit_watch"],
        "learning": extra["learning"],
        "decisions": compact[:max(1, int(limit))],
    }
