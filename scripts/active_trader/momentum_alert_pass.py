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


def armed_levels(info: Optional[Mapping[str, Any]], trig_cfg: Optional[Mapping[str, Any]]) -> dict:
    """ARMED entry/stop from the trigger state machine (2026-10-09): entry = the break of the prior bar's
    high + entry_offset (what a fire would use), stop = pullback low − stop_offset. The old ARMED line
    printed last price and last − 1·ATR ("entry 4.05 · stop 4.01 · R 0.04"), which was not the setup."""
    info = info or {}
    tc = trig_cfg or {}
    ph, pl = info.get("prev_high"), info.get("pullback_low")
    out: dict[str, Any] = {"armed_bars": info.get("armed_bars"), "leg_high": info.get("leg_high"),
                           "pullback_low": pl}
    if ph is None or pl is None:
        return out
    entry = float(ph) + float(tc.get("entry_offset") or 0.0)
    stop = float(pl) - float(tc.get("stop_offset") or 0.0)
    if stop < entry:
        out.update(entry_ref=round(entry, 4), stop_ref=round(stop, 4), break_level=float(ph))
    return out


def build_candidates(results: Sequence[Mapping[str, Any]], trigger_fires: Sequence[Mapping[str, Any]],
                     trigger_states: Mapping[str, str], *, day: str,
                     trigger_info: Optional[Mapping[str, Mapping[str, Any]]] = None,
                     trig_cfg: Optional[Mapping[str, Any]] = None,
                     trade_ai: Optional[Mapping[str, dict]] = None) -> list[ma.Candidate]:
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
        state = str(trigger_states.get(sym, "IDLE"))
        lv = armed_levels((trigger_info or {}).get(sym), trig_cfg) if state.upper() == "ARMED" else {}
        use_fsm = fire is None and "entry_ref" in lv
        out.append(ma.Candidate(
            symbol=sym, lane=str(r.get("lane")), ign=float(r.get("ign") or 0.0),
            fsm_state=state,
            setup_id=tax.get("primary_setup_id"), setup_label=tax.get("primary_setup_label"),
            entry_ref=lv["entry_ref"] if use_fsm else (fire or {}).get("entry", r.get("entry_ref")),
            stop_ref=lv["stop_ref"] if use_fsm else (fire or {}).get("stop", r.get("stop_ref")),
            break_level=lv.get("break_level") if use_fsm else None,
            armed_bars=lv.get("armed_bars"), leg_high=lv.get("leg_high"), pullback_low=lv.get("pullback_low"),
            trade_ai=(trade_ai or {}).get(sym),
            rvol=r.get("rvol_tod"), fire_ts_epoch=_epoch((fire or {}).get("fire_ts")),
            session_date=day))
    return out


def trade_ai_today(conn, symbols: Sequence[str], day: str) -> dict[str, dict]:
    """Latest trade_ai_scans verdict per symbol for the session day (read-only). {} on any failure."""
    syms = sorted({s for s in symbols if s})
    if conn is None or not syms:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, decision, not_tradeable, scanned_at
                             FROM trade_ai_scans WHERE run_date = %s AND symbol = ANY(%s)
                            ORDER BY symbol, scanned_at DESC""", (day, syms))
            rows = cur.fetchall()
        conn.rollback()
    except Exception:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {}
    out = {}
    for r in rows:
        sym, dec, nt, at = (r["symbol"], r["decision"], r["not_tradeable"], r["scanned_at"]) if isinstance(r, Mapping) \
            else (r[0], r[1], r[2], r[3])
        out[str(sym)] = {"decision": dec, "not_tradeable": bool(nt),
                         "scanned_at": at.isoformat() if hasattr(at, "isoformat") else at}
    return out


def stand_down_candidates(throttle_state: Mapping[str, Any], trigger_states: Mapping[str, str],
                          trigger_info: Mapping[str, Mapping[str, Any]], fired: set, *, now: float,
                          cfg: "ma.AlertConfig", day: str) -> list[ma.Candidate]:
    """An ARMED leg that was SENT within stand_down_window_min and has since gone stale (ARMED past
    armed_max_bars) or left ARMED without firing gets one STAND_DOWN (2026-10-09: 18 of 19 ARMED alerts
    simply went quiet). Never twice for the same leg."""
    last = dict((throttle_state or {}).get("last") or {})
    out = []
    for key, ts in last.items():
        parts = key.split(":", 2)
        if len(parts) != 3 or parts[1] != ma.ARMED or not parts[2].startswith("leg:"):
            continue
        sym, lvl = parts[0], parts[2]
        if now - float(ts) > cfg.stand_down_window_min * 60 or f"{sym}:{ma.STAND_DOWN}:{lvl}" in last or sym in fired:
            continue
        info = (trigger_info or {}).get(sym) or {}
        state = str(trigger_states.get(sym, "")).upper()
        same_leg = info.get("leg_high") is not None and f"leg:{float(info['leg_high']):.4f}" == lvl
        if state == "ARMED" and same_leg and (info.get("armed_bars") or 0) <= cfg.armed_max_bars:
            continue                                   # still a live setup
        if not state:
            continue                                   # not scored this pass: no evidence either way
        reason = ("the setup went stale — no break after "
                  f"{info.get('armed_bars')} min" if state == "ARMED" and same_leg
                  else "the setup broke down without triggering")
        out.append(ma.Candidate(symbol=sym, lane="", ign=0.0, fsm_state=state, kind_hint=ma.STAND_DOWN,
                                level_key=lvl, stand_down_reason=reason, session_date=day))
    return out


def run_from_logger(conn, cfg: Mapping[str, Any], results, trigger_fires, trigger_states, *,
                    day: str, dry_run: bool = False, now: Optional[float] = None,
                    source: Optional[MoomooSource] = None, send_fn=None,
                    trigger_info: Optional[Mapping[str, Mapping[str, Any]]] = None) -> dict:
    acfg = ma.AlertConfig.from_mapping(cfg.get("active_trader_alerts"))
    now = time.time() if now is None else now
    tai = trade_ai_today(conn, [r.get("symbol") for r in results], day)
    cands = build_candidates(results, trigger_fires, trigger_states, day=day, trigger_info=trigger_info,
                             trig_cfg=cfg.get("trigger"), trade_ai=tai)
    interesting = [c for c in cands if ma.alert_kind(c, now=now, cfg=acfg)]
    interesting.sort(key=lambda c: (ma.alert_kind(c, now=now, cfg=acfg) != ma.TRIGGERED, -c.ign))
    interesting = interesting[:MAX_CANDIDATES]
    fired = {f.get("symbol") for f in trigger_fires if f.get("symbol")}
    interesting += stand_down_candidates(ma.load_throttle_state() if not dry_run else {}, trigger_states,
                                         trigger_info or {}, fired, now=now, cfg=acfg, day=day)
    if not interesting:
        res = {"evaluated": 0, "alerts": 0, "sent": 0, "vetoes": 0, "mode": acfg.mode}
        if not dry_run:
            _heartbeat(now, acfg.mode, len(cands), res)
        return res
    src = source or MoomooSource(levels=acfg.book_levels, prints=acfg.tape_prints)
    floats = float_lookup(conn) if conn is not None else (lambda s: None)
    for c in interesting:
        if c.kind_hint == ma.STAND_DOWN:
            continue                 # a closing note needs no quote or book (and no L2 subscription)
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
        send_fn=None if dry_run else send_fn, run_id=f"{day}:{int(now)}", persist=not dry_run,
        fetch_signals=signals_fetcher(conn, cfg, day=day, now=now))
    if source is None:
        src.close()
    res = {"evaluated": len(rows), "mode": acfg.mode,
           "alerts": sum(1 for r in rows if r["verdict"] == ma.ALERT),
           "sent": sum(1 for r in rows if r.get("sent")),
           "vetoes": sum(1 for r in rows if r["verdict"] == ma.VETO)}
    if not dry_run:
        _heartbeat(now, acfg.mode, len(cands), res)
    return res


def schwab_row_fetcher(conn, *, max_age_s: float = 60.0):
    """Latest Schwab NASDAQ_BOOK row with market-maker counts per level (SELECT only)."""
    def _f(symbol: str):
        if conn is None:
            return None
        with conn.cursor() as cur:
            cur.execute("""SELECT bid_levels, ask_levels FROM schwab_stream_book
                           WHERE symbol=%s AND captured_at > now() - make_interval(secs => %s)
                           ORDER BY captured_at DESC LIMIT 1""", [symbol.upper(), float(max_age_s)])
            row = cur.fetchone()
        return {"bid_levels": row[0], "ask_levels": row[1]} if row else None
    return _f


def signals_fetcher(conn, cfg: Mapping[str, Any], *, day: str, now: float):
    """Entry microstructure signals from the recorder's last 15 minutes for a symbol, plus the
    Schwab book. Without recorder data the evidence says so (never guessed)."""
    try:
        from active_trader import microstructure_signals as msig
        from active_trader import microstructure_recorder as rec
    except ModuleNotFoundError:  # pragma: no cover
        from scripts.active_trader import microstructure_signals as msig
        from scripts.active_trader import microstructure_recorder as rec
    scfg = msig.SignalConfig.from_mapping(cfg.get("microstructure_signals"))
    schwab = schwab_row_fetcher(conn)

    def _f(symbol: str) -> dict:
        snaps = rec.load_snapshots(day, symbol, start=now - 15 * 60, end=now)
        try:
            srow = schwab(symbol)
        except Exception:  # noqa: BLE001
            srow = None
        if not snaps:
            return {"status": "NO_RECORDER_DATA", "schwab_mm_stack": msig.schwab_book(srow, scfg)}
        bars = [b for b in msig.bars_from_ticks(msig.ticks(snaps)) if b["t"] + 60 <= now]
        return {"status": "OK", "snapshots": len(snaps),
                **msig.entry_signals(snaps, bars, now=now, cfg=scfg, schwab_row=srow)}
    return _f


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
