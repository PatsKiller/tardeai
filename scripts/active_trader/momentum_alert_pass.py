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
    """Latest trade_ai_scans verdict + five-facts fields per symbol for the session day (read-only)."""
    syms = sorted({s for s in symbols if s})
    if conn is None or not syms:
        return {}
    try:
        with conn.cursor() as cur:
            # Prefer rich columns when present; fall back to verdict-only on older schemas.
            try:
                cur.execute(
                    """SELECT DISTINCT ON (symbol) symbol, decision, not_tradeable, scanned_at,
                              price, float_m, rvol, gap_pct, change_pct, catalyst, catalyst_verified,
                              catalyst_source, catalyst_url, catalyst_at
                         FROM trade_ai_scans WHERE run_date = %s AND symbol = ANY(%s)
                        ORDER BY symbol, scanned_at DESC""",
                    (day, syms),
                )
            except Exception:  # noqa: BLE001
                conn.rollback()
                cur.execute(
                    """SELECT DISTINCT ON (symbol) symbol, decision, not_tradeable, scanned_at
                         FROM trade_ai_scans WHERE run_date = %s AND symbol = ANY(%s)
                        ORDER BY symbol, scanned_at DESC""",
                    (day, syms),
                )
            rows = cur.fetchall()
        conn.rollback()
    except Exception:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {}
    out: dict[str, dict] = {}
    try:
        from lib.momentum_setup_evidence import build_setup_evidence
    except Exception:  # noqa: BLE001
        try:
            from scripts.lib.momentum_setup_evidence import build_setup_evidence
        except Exception:  # noqa: BLE001
            build_setup_evidence = None  # type: ignore
    for r in rows:
        if isinstance(r, Mapping):
            payload = dict(r)
            sym = str(payload.get("symbol"))
            at = payload.get("scanned_at")
            scanned = at.isoformat() if hasattr(at, "isoformat") else at
            entry = {
                "decision": payload.get("decision"),
                "not_tradeable": bool(payload.get("not_tradeable")),
                "scanned_at": scanned,
                "run_date": day,
                "scan_run_date": day,
                "price": payload.get("price"),
                "float_m": payload.get("float_m"),
                "rvol": payload.get("rvol"),
                "gap_pct": payload.get("gap_pct"),
                "change_pct": payload.get("change_pct"),
                "catalyst": payload.get("catalyst"),
                "catalyst_verified": payload.get("catalyst_verified"),
                "catalyst_source": payload.get("catalyst_source"),
                "catalyst_url": payload.get("catalyst_url"),
                "catalyst_at": payload.get("catalyst_at"),
            }
        else:
            sym = str(r[0])
            scanned = r[3].isoformat() if hasattr(r[3], "isoformat") else r[3]
            entry = {"decision": r[1], "not_tradeable": bool(r[2]), "scanned_at": scanned,
                     "run_date": day, "scan_run_date": day}
        if build_setup_evidence is not None:
            try:
                entry["setup_evidence"] = build_setup_evidence(
                    entry, observed_at=scanned, source_name="TRADE_AI"
                )
            except Exception:  # noqa: BLE001
                pass
        out[sym] = entry
    _attach_day_catalyst(conn, out, day)
    return out


def _attach_day_catalyst(conn, out: dict[str, dict], day: str) -> None:
    """2026-10-16 (NCPL): the LATEST scan row can carry no catalyst while an earlier scan today did (the 09:35
    Trade AI LIVE alert named NCPL's headline; the 10:10 ARMED alert said nothing). Attach today's most recent
    non-empty catalyst as ``day_catalyst`` for symbols whose latest row has none. Read-only, fail-soft."""
    need = sorted(s for s, e in out.items() if not str(e.get("catalyst") or "").strip())
    if conn is None or not need:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT ON (symbol) symbol, catalyst, catalyst_source, scanned_at
                     FROM trade_ai_scans
                    WHERE run_date = %s AND symbol = ANY(%s) AND COALESCE(TRIM(catalyst), '') <> ''
                    ORDER BY symbol, scanned_at DESC""",
                (day, need),
            )
            rows = cur.fetchall()
        conn.rollback()
    except Exception:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return
    for r in rows:
        vals = [r.get(k) for k in ("symbol", "catalyst", "catalyst_source", "scanned_at")] \
            if isinstance(r, Mapping) else list(r)[:4]
        sym, text, source, at = (vals + [None] * 4)[:4]
        if str(sym) in out and text:
            out[str(sym)]["day_catalyst"] = {
                "text": str(text), "source": source,
                "scanned_at": at.isoformat() if hasattr(at, "isoformat") else at,
            }


# ── same-day pass context for the fast loop (operator 2026-10-19, BETR 10:38) ───────────────────────────
# The fast loop builds its candidates from the recorder store only (symbol / state / last / quote time), so
# its alerts printed "float n/a · RVOL n/a · setup n/a" and "Trade-AI: NO_SAME_DAY_SCAN" although BETR had a
# 09:01 WAIT scan. These read what THIS pass already persisted for the same symbol and session day.

PASS5_FIELDS = ("rvol", "setup_id", "setup_label", "float_mm", "trade_ai")


def _journal_pass5(symbols: Sequence[str], day: str, *, path=None, max_bytes: int = 2_000_000) -> dict[str, dict]:
    """Newest non-empty value per field from this session day's 5-minute-pass journal rows (bounded tail)."""
    import json
    from zoneinfo import ZoneInfo

    want = {str(s).upper() for s in symbols if s}
    p = path or (ma.journal_dir() / "momentum_alerts.jsonl")
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()
            lines = fh.read(max_bytes).decode("utf-8", "replace").splitlines()
    except OSError:
        return {}
    et = ZoneInfo("America/New_York")
    out: dict[str, dict] = {}
    for line in reversed(lines):                       # newest first
        try:
            row = json.loads(line)
        except ValueError:
            continue
        c = row.get("candidate") if isinstance(row, dict) else None
        if not isinstance(c, dict) or str(c.get("symbol") or "").upper() not in want:
            continue
        if (row.get("source") or c.get("source")) != "pass5" or c.get("session_date") != day:
            continue
        ts = row.get("ts_epoch")
        if not isinstance(ts, (int, float)) or datetime.fromtimestamp(ts, et).date().isoformat() != day:
            continue                                   # stale guard: the same session day only
        got = out.setdefault(str(c["symbol"]).upper(), {})
        for k in PASS5_FIELDS:
            if got.get(k) is None and c.get(k) not in (None, "", {}):
                got[k] = c[k]
    return out


def _ignition_today(conn, symbols: Sequence[str], day: str) -> dict[str, dict]:
    """RVOL and setup from this session day's newest scalp_ignition_events row (what the pass persists for
    every scored symbol, not only the ones it alerted on). SELECT only; never raises."""
    syms = sorted({s for s in symbols if s})
    if conn is None or not syms:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, rvol_tod, primary_setup_id, primary_setup_label, fired_at
                             FROM scalp_ignition_events WHERE session_date = %s AND symbol = ANY(%s)
                            ORDER BY symbol, fired_at DESC""", (day, syms))
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
        vals = [r.get(k) for k in ("symbol", "rvol_tod", "primary_setup_id", "primary_setup_label")] \
            if isinstance(r, Mapping) else list(r)[:4]
        sym, rvol, sid, slabel = (vals + [None] * 4)[:4]
        out[str(sym).upper()] = {k: v for k, v in (("rvol", rvol), ("setup_id", sid), ("setup_label", slabel))
                                 if v is not None}
    return out


def pass5_context(conn, symbols: Sequence[str], day: str, *, journal_path=None) -> dict[str, dict]:
    """{SYM: {rvol, setup_id, setup_label, float_mm, trade_ai}} — the newest same-day values the 5-minute pass
    produced: its journal first, then (read-only DB) scalp_ignition_events, the pass's float lookup and
    trade_ai_today(). A field nobody produced today is absent; nothing is invented, no provider is called."""
    syms = sorted({str(s).upper() for s in symbols if s})
    out = {s: dict(v) for s, v in _journal_pass5(syms, day, path=journal_path).items()}

    def missing(field):
        return [s for s in syms if (out.get(s) or {}).get(field) is None]

    if conn is not None:
        need = sorted(set(missing("rvol")) | set(missing("setup_label")))
        for sym, vals in _ignition_today(conn, need, day).items():
            for k, v in vals.items():
                out.setdefault(sym, {}).setdefault(k, v)
        floats = float_lookup(conn)
        for sym in missing("float_mm"):
            try:
                f = floats(sym)
            except Exception:  # noqa: BLE001
                f = None
            finally:
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
            if f is not None:
                out.setdefault(sym, {})["float_mm"] = f
        for sym, t in trade_ai_today(conn, missing("trade_ai"), day).items():
            out.setdefault(str(sym).upper(), {})["trade_ai"] = t
    return {s: v for s, v in out.items() if v}


def apply_pass5_context(candidates: Sequence[ma.Candidate], ctx: Mapping[str, Mapping[str, Any]]) -> None:
    """Fill only the fields a candidate does not already carry."""
    for c in candidates:
        for k, v in (ctx.get(str(c.symbol).upper()) or {}).items():
            if k in PASS5_FIELDS and getattr(c, k, None) is None and v is not None:
                setattr(c, k, v)


def stand_down_candidates(throttle_state: Mapping[str, Any], trigger_states: Mapping[str, str],
                          trigger_info: Mapping[str, Mapping[str, Any]], fired: set, *, now: float,
                          cfg: "ma.AlertConfig", day: str, trig_cfg: Optional[Mapping[str, Any]] = None,
                          prices: Optional[Mapping[str, Any]] = None,
                          trade_ai: Optional[Mapping[str, dict]] = None) -> list[ma.Candidate]:
    """An ARMED leg that was SENT within stand_down_window_min and has since gone stale (ARMED past
    armed_max_bars) or left ARMED without firing gets one STAND_DOWN (2026-10-09: 18 of 19 ARMED alerts
    simply went quiet). Never twice for the same leg.

    2026-10-19 (NCPL 10-16 10:15 "last n/a · entry n/a · stop n/a"): the note states what is known —
    last from this pass's scored price, entry/stop from the trigger state machine while it still describes
    the SAME leg (a broken-down leg's levels belong to a different setup), and today's Trade-AI verdict."""
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
        lv = armed_levels(info, trig_cfg) if same_leg else {}
        last_px = (prices or {}).get(sym)
        out.append(ma.Candidate(symbol=sym, lane="", ign=0.0, fsm_state=state, kind_hint=ma.STAND_DOWN,
                                level_key=lvl, stand_down_reason=reason, session_date=day,
                                last=float(last_px) if isinstance(last_px, (int, float)) else None,
                                entry_ref=lv.get("entry_ref"), stop_ref=lv.get("stop_ref"),
                                trade_ai=(trade_ai or {}).get(sym)))
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
    prices = {r.get("symbol"): r.get("entry_ref") for r in results if r.get("symbol")}   # entry_ref == scored price
    interesting += stand_down_candidates(ma.load_throttle_state() if not dry_run else {}, trigger_states,
                                         trigger_info or {}, fired, now=now, cfg=acfg, day=day,
                                         trig_cfg=cfg.get("trigger"), prices=prices, trade_ai=tai)
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
