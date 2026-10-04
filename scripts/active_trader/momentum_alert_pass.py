"""Bridge: one scalp_shadow_logger pass → Phase 1 ARMED/TRIGGERED alert decisions.

Called by scalp_shadow_logger after scoring and the trigger engine (live runs only; replay is
history and never alerts). Builds candidates from the ignition rows and trigger fires, gathers
moomoo evidence (primary) and the Schwab book (comparison), decides, journals, and sends only
when active_trader_alerts.mode == "send". Then scores alerts whose 15-minute window has closed.
ALERTS ONLY — no order path.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

try:
    from active_trader import momentum_alerts as ma
    from active_trader.momentum_alert_sources import MoomooSource, schwab_book_fetcher, float_lookup
except ModuleNotFoundError:  # imported as scripts.active_trader...
    from scripts.active_trader import momentum_alerts as ma
    from scripts.active_trader.momentum_alert_sources import MoomooSource, schwab_book_fetcher, float_lookup

MAX_CANDIDATES = 8   # == t2.max_armed: never subscribe more books than the L2 budget


def _epoch(ts: Any) -> Optional[float]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        return ts.timestamp()
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def build_candidates(results: Sequence[Mapping[str, Any]], trigger_fires: Sequence[Mapping[str, Any]],
                     trigger_states: Mapping[str, str], *, day: str) -> list[ma.Candidate]:
    latest_fire: dict[str, Mapping[str, Any]] = {}
    for f in trigger_fires:
        s = f.get("symbol")
        if s and (s not in latest_fire or (f.get("fire_minute") or 0) > (latest_fire[s].get("fire_minute") or 0)):
            latest_fire[s] = f
    out = []
    for r in results:
        sym = r.get("symbol")
        tax = r.get("_tax") or {}
        fire = latest_fire.get(sym)
        out.append(ma.Candidate(
            symbol=sym, lane=str(r.get("lane")), ign=float(r.get("ign") or 0.0),
            fsm_state=str(trigger_states.get(sym, "IDLE")),
            setup_id=tax.get("primary_setup_id"), setup_label=tax.get("primary_setup_label"),
            entry_ref=(fire or {}).get("entry", r.get("entry_ref")),
            stop_ref=(fire or {}).get("stop", r.get("stop_ref")),
            rvol=r.get("rvol_tod"), fire_ts_epoch=_epoch((fire or {}).get("fire_ts")),
            session_date=day))
    return out


def run_from_logger(conn, cfg: Mapping[str, Any], results, trigger_fires, trigger_states, *,
                    day: str, dry_run: bool = False, now: Optional[float] = None,
                    source: Optional[MoomooSource] = None, send_fn=None) -> dict:
    acfg = ma.AlertConfig.from_mapping(cfg.get("active_trader_alerts"))
    now = time.time() if now is None else now
    cands = build_candidates(results, trigger_fires, trigger_states, day=day)
    interesting = [c for c in cands if ma.alert_kind(c, now=now, cfg=acfg)]
    interesting.sort(key=lambda c: (ma.alert_kind(c, now=now, cfg=acfg) != ma.TRIGGERED, -c.ign))
    interesting = interesting[:MAX_CANDIDATES]
    if not interesting:
        res = {"evaluated": 0, "alerts": 0, "sent": 0, "vetoes": 0, "mode": acfg.mode}
        if not dry_run:
            _heartbeat(now, acfg.mode, len(cands), res)
        return res
    src = source or MoomooSource(levels=acfg.book_levels, prints=acfg.tape_prints)
    floats = float_lookup(conn) if conn is not None else (lambda s: None)
    for c in interesting:
        try:
            c.last, c.quote_ts_epoch = src.quote(c.symbol)
        except Exception:  # noqa: BLE001 — no quote → QUOTE_STALE veto
            c.last, c.quote_ts_epoch = None, None
        try:
            c.float_mm = floats(c.symbol)
        except Exception:  # noqa: BLE001
            c.float_mm = None
    if send_fn is None and acfg.mode == "send" and not dry_run:
        send_fn = ma.telegram_send
    rows = ma.evaluate_pass(
        interesting, cfg=acfg, now=now,
        fetch_primary_book=src.book, fetch_primary_tape=src.tape,
        fetch_compare_book=schwab_book_fetcher(conn) if conn is not None else None,
        send_fn=None if dry_run else send_fn, run_id=f"{day}:{int(now)}", persist=not dry_run)
    if source is None:
        src.close()
    res = {"evaluated": len(rows), "mode": acfg.mode,
           "alerts": sum(1 for r in rows if r["verdict"] == ma.ALERT),
           "sent": sum(1 for r in rows if r.get("sent")),
           "vetoes": sum(1 for r in rows if r["verdict"] == ma.VETO)}
    if not dry_run:
        _heartbeat(now, acfg.mode, len(cands), res)
    return res


def _heartbeat(now: float, mode: str, scored_symbols: int, res: Mapping[str, Any]) -> None:
    """One small file per live engine pass, so the page can show the engine is alive even when
    nothing qualified. Best effort; never breaks the logger."""
    import json
    try:
        p = ma.journal_dir() / "momentum_alerts_heartbeat.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ts_epoch": now, "mode": mode, "symbols_scored": scored_symbols,
                                   "last_pass": dict(res)}), encoding="utf-8")
        tmp.replace(p)
    except Exception:  # noqa: BLE001
        pass
