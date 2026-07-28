#!/usr/bin/env python3
"""M3-S3 — shadow ignition logger (Momentum Scalp Signal Engine).

SHADOW ONLY: compute everything, log everything to scalp_ignition_events, EMIT NOTHING. This module
contains NO Telegram/alert code and NO proposal/order code by construction — it cannot notify or
trade. It reads bars (Alpaca), the M3-S1 volume profile, catalyst rows, and the M3-S2 T0 metrics,
computes the §3.2 IGN score, and writes shadow rows. Nothing here imports paper_trade_proposals or
any order path. Kill file `~/.tradeai/SCALP_ENGINE_DISABLED` halts it.

Modes:
  --replay YYYY-MM-DD --minute N   deterministic: score the universe as-of minute N of that session
  --live                           score the universe as-of the current session minute (RTH only)

Usage:
  python scripts/scalp_shadow_logger.py --replay 2026-07-24 --minute 60 --apply
  python scripts/scalp_shadow_logger.py --replay 2026-07-24 --minute 60 --dry-run --top 15
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))

import scalp_ignition_scorer as scorer          # noqa: E402
import scalp_t0_metrics as t0                    # noqa: E402
import scalp_trigger_engine as trig              # noqa: E402
import scalp_setup_detectors as sdet             # noqa: E402  (Layer A named-setup taxonomy; SHADOW)
import scalp_setup_registry as sreg              # noqa: E402
from symbol_volume_profile_builder import (       # noqa: E402
    load_config, fetch_minute_bars, minute_of_session, get_profile_denominator,
)

_TAX_COLS = ("primary_setup_id", "primary_setup_label", "matched_setup_ids", "matched_setup_labels",
             "setup_state", "setup_version", "setup_fired_at", "market_session",
             "confirmation_labels", "setup_evidence", "setup_fail_reasons", "registry_hash")


def _tax_values(tax: dict | None, fired_at) -> list:
    """The 12 additive taxonomy column values (JSON-encoded for the JSONB columns), in _TAX_COLS order.
    A None tax (detector error / no registry) yields safe defaults so existing logging never breaks."""
    import json as _j
    t = tax or {}
    fired = fired_at if (t.get("setup_state") == "FIRED") else None
    return [
        t.get("primary_setup_id"), t.get("primary_setup_label"),
        _j.dumps(t.get("matched_setup_ids", [])), _j.dumps(t.get("matched_setup_labels", [])),
        t.get("setup_state"), t.get("setup_version"), fired, t.get("market_session"),
        _j.dumps(t.get("confirmation_labels", [])), _j.dumps(t.get("setup_evidence", {})),
        _j.dumps(t.get("setup_fail_reasons", {})), t.get("registry_hash"),
    ]

KILL_FILE = Path(os.path.expanduser("~/.tradeai/SCALP_ENGINE_DISABLED"))


def _conn():
    try:
        from db_adapter import get_connection
    except ModuleNotFoundError:
        from scripts.db_adapter import get_connection
    return get_connection()


# ─────────────────────────── data assembly ───────────────────────────

def session_rth_bars(symbol: str, cfg: dict, target_day: str, days: int = 6) -> list[dict]:
    """Ordered RTH bars (minute_of_session added as 'm') for `target_day`."""
    tz = ZoneInfo(cfg["session"]["tz"])
    open_hhmm = cfg["session"]["regular_open"]
    n_min = int(cfg["session"]["regular_minutes"])
    raw = fetch_minute_bars(symbol, cfg, days)
    out = []
    for b in raw:
        dt_local = datetime.fromisoformat(b["t"].replace("Z", "+00:00")).astimezone(tz)
        if dt_local.date().isoformat() != target_day:
            continue
        m = minute_of_session(dt_local, open_hhmm)
        if 0 <= m < n_min:
            bb = dict(b); bb["m"] = m
            out.append(bb)
    out.sort(key=lambda x: x["m"])
    return out


def profile_median_at(conn, symbol: str, minute: int, feed: str) -> tuple[float | None, int, str]:
    """(median_cum_volume at minute, n_sessions, source). source: per_symbol|none."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT median_cum_volume, n_sessions FROM symbol_volume_profile
               WHERE symbol=%s AND session_window='regular' AND feed=%s AND minute_of_session=%s""",
            [symbol, feed, minute])
        r = cur.fetchone()
    if r and r[0] is not None:
        return float(r[0]), int(r[1]), "per_symbol"
    return None, 0, "none"


def universe_ucurve(conn, feed: str, n_min: int = 390) -> list[float]:
    """Universe-level ExpectedFraction(t): median across profiled symbols of the normalized
    cumulative curve (cum_at_t / cum_at_close). Used for the §3.1 proxy fallback."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT symbol, minute_of_session, median_cum_volume FROM symbol_volume_profile
               WHERE session_window='regular' AND feed=%s ORDER BY symbol, minute_of_session""",
            [feed])
        rows = cur.fetchall()
    by_sym: dict[str, dict[int, float]] = {}
    for sym, mn, cv in rows:
        by_sym.setdefault(sym, {})[int(mn)] = float(cv)
    fracs_at = [[] for _ in range(n_min)]
    for sym, curve in by_sym.items():
        close = curve.get(n_min - 1) or max(curve.values() or [0])
        if not close or close <= 0:
            continue
        for mth in range(n_min):
            if mth in curve:
                fracs_at[mth].append(curve[mth] / close)
    return [statistics.median(f) if f else (mth + 1) / n_min for mth, f in enumerate(fracs_at)]


def catalyst_for(conn, symbol: str, cfg: dict, as_of: datetime) -> tuple[float | None, float | None]:
    """(tier_weight, age_min) from the most recent scalp_scan_results catalyst before as_of."""
    vc = cfg["ignition"]["subscores"]["v_cat"]
    with conn.cursor() as cur:
        cur.execute(
            """SELECT catalyst_source, scanned_at FROM scalp_scan_results
               WHERE symbol=%s AND catalyst_source IS NOT NULL AND catalyst_verified=true
                 AND scanned_at <= %s ORDER BY scanned_at DESC LIMIT 1""",
            [symbol, as_of])
        r = cur.fetchone()
    if not r:
        return None, None
    src = str(r[0]).lower().strip()
    weight = vc["tier_weights"].get(src, vc["default_weight"])
    age_min = max(0.0, (as_of - r[1]).total_seconds() / 60.0)
    return float(weight), age_min


def session_vwap(bars: list[dict]) -> float | None:
    num = den = 0.0
    for b in bars:
        h, l, c, v = t0._h(b), t0._l(b), t0._c(b), t0._v(b)
        if None in (h, l, c, v) or v <= 0:
            continue
        tp = (h + l + c) / 3.0
        num += tp * v; den += v
    return num / den if den > 0 else None


def assemble_inputs(bars: list[dict], profile_cum: float | None, tier_weight, age_min,
                    spy_ret: float | None, cfg: dict) -> dict:
    """Assemble one symbol's scorer inputs from its RTH bars up to the as-of minute. Pure over the
    bar slice (RVOL_tod resolved by caller with proxy fallback)."""
    vols = [t0._v(b) or 0.0 for b in bars]
    closes = [t0._c(b) for b in bars if t0._c(b) is not None]
    cum_vol = sum(vols)
    v_1m = vols[-1] if vols else 0.0
    win = vols[-20:]
    mu = statistics.mean(win) if win else 0.0
    sigma = statistics.pstdev(win) if len(win) > 1 else 0.0
    price = closes[-1] if closes else None
    open_px = t0._o(bars[0]) if bars else None
    ret_sym = ((price - open_px) / open_px) if (price and open_px) else None
    vwap = session_vwap(bars)
    atr_1m = t0.atr(bars, 14)
    vol_5m = sum(vols[-5:])
    rs_value = (ret_sym - spy_ret) if (ret_sym is not None and spy_ret is not None) else None
    return {
        "cum_vol": cum_vol, "v_1m": v_1m, "mu_20": mu, "sigma_20": sigma,
        "price": price, "vwap": vwap, "atr_1m": atr_1m, "n_bars": len(bars),
        "vol_5m": vol_5m, "tier_weight": tier_weight, "age_min": age_min,
        "ret_sym": ret_sym, "rs_value": rs_value, "profile_cum": profile_cum,
    }


# ─────────────────────────── run ───────────────────────────

def resolve_universe(conn, cfg: dict) -> list[str]:
    u = cfg["universe"]
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT {u['symbol_column']} FROM {u['source_table']}
                WHERE {u['time_column']} > now() - interval '{int(u['lookback_days'])} days'
                  AND ({u['float_column']} IS NULL OR {u['float_column']} <= %s)
                  AND {u['symbol_column']} IS NOT NULL ORDER BY 1""",
            [float(u["float_mm_max"])])
        return [r[0] for r in cur.fetchall()]


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute((_REPO / "migrations" / "2026-07-27_scalp_ignition_events.sql").read_text())
        # additive multi-setup taxonomy columns (idempotent ADD COLUMN IF NOT EXISTS)
        tax = _REPO / "migrations" / "2026-07-28_scalp_setup_taxonomy.sql"
        if tax.exists():
            cur.execute(tax.read_text())
    conn.commit()


def run(args) -> int:
    if KILL_FILE.exists():
        print(f"HALT: kill file {KILL_FILE} present"); return 0
    cfg = load_config()
    # M3-S7: notifications.emit MAY be true now (Telegram alert tiers enabled). Proposals remain OFF
    # by construction — this module has no proposal/order path (enforced by the AST isolation test).
    assert "proposal_path" not in cfg.get("notifications", {}), "no proposal emission at M3-S7 (proposals = M3-S9)"
    feed = cfg["data"]["feed"]
    tz = ZoneInfo(cfg["session"]["tz"])
    n_min = int(cfg["session"]["regular_minutes"])
    conn = _conn()

    from datetime import timedelta, date as _date
    if args.replay:
        day = args.replay
        minute = int(args.minute)
        oh, om = (int(x) for x in cfg["session"]["regular_open"].split(":"))
        as_of = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=tz).replace(
            hour=oh, minute=om) + timedelta(minutes=minute)
        # fetch window must reach back to the replay day (Alpaca IEX minute history is deep enough)
        fetch_days = (datetime.now(tz).date() - _date.fromisoformat(day)).days + 3
    else:
        now = datetime.now(tz)
        day = now.date().isoformat()
        minute = minute_of_session(now, cfg["session"]["regular_open"])
        as_of = now
        fetch_days = 3
        if minute < 0 or minute >= n_min:
            print(f"outside RTH (minute={minute}); nothing to log"); return 0

    symbols = ([s.strip().upper() for s in args.symbols.split(",")] if args.symbols
               else resolve_universe(conn, cfg))
    print(f"shadow-log: day={day} minute={minute} feed={feed} symbols={len(symbols)} apply={args.apply}")

    ucurve = universe_ucurve(conn, feed, n_min)
    # SPY reference return for v_rs (relative strength)
    try:
        spy_bars = session_rth_bars("SPY", cfg, day, fetch_days)
        spy_upto = [b for b in spy_bars if b["m"] <= minute]
        spy_open = t0._o(spy_upto[0]) if spy_upto else None
        spy_last = t0._c(spy_upto[-1]) if spy_upto else None
        spy_ret = ((spy_last - spy_open) / spy_open) if (spy_open and spy_last) else None
    except Exception:
        spy_ret = None

    # pass 1: assemble per-symbol (needs cross-sectional rs before scoring)
    assembled = []
    for sym in symbols:
        try:
            bars = [b for b in session_rth_bars(sym, cfg, day, fetch_days) if b["m"] <= minute]
            if not bars:
                continue
            # G2.2 freshness contract: the accessor REFUSES a stale/thin denominator (returns None)
            pcum, pmeta = get_profile_denominator(conn, sym, minute, cfg, now=as_of)
            tw, age = catalyst_for(conn, sym, cfg, as_of)
            inp = assemble_inputs(bars, pcum, tw, age, spy_ret, cfg)
            inp["_profile_source"] = "per_symbol" if pcum is not None else "none"
            inp["_profile_meta"] = pmeta
            inp["_bars"] = bars
            inp["_symbol"] = sym
            assembled.append(inp)
        except Exception as e:
            print(f"  {sym}: ERR {e}")

    universe_rs = [a["rs_value"] for a in assembled if a["rs_value"] is not None]

    if args.apply:
        ensure_schema(conn)

    try:
        _registry = sreg.load_registry()   # load once per run for the setup taxonomy
    except Exception:
        _registry = None
    results = []
    trigger_fires = []
    trigger_states = {}      # symbol → current FSM state (trace[-1]); drives the moomoo L2 arm
    ef = ucurve[minute] if 0 <= minute < len(ucurve) else (minute + 1) / n_min
    for a in assembled:
        # RVOL_tod: per-symbol profile, else universe-proxy (§3.1)
        if a["_profile_source"] == "per_symbol" and a["profile_cum"]:
            rt = scorer.rvol_tod(a["cum_vol"], a["profile_cum"]); psrc = "per_symbol"
        else:
            adv = (a["profile_cum"] / ef) if a["profile_cum"] else None  # fallback ADV proxy
            rt = scorer.rvol_tod_proxy(a["cum_vol"], adv, ef); psrc = "universe_proxy" if rt else "none"
        a["rvol_tod"] = rt
        a["universe_rs"] = universe_rs
        out = scorer.score(a, cfg)
        # T0 microstructure (M3-S2) over the session bars
        bars = a["_bars"]
        cs = t0.corwin_schultz_spread(bars); ar = t0.abdi_ranaldo_spread(bars)
        se = t0.spread_estimate(bars)
        spread_src = "max_cs_ar" if (cs is not None and ar is not None) else ("corwin_schultz" if cs else "abdi_ranaldo")
        evr = t0.effort_vs_result(bars)
        evr_last = next((x for x in reversed(evr) if x is not None), None)
        # hypothetical trade reference (NOT an order) — entry = fire price, stop = entry − 1·ATR_1m
        # (§6 noise-stop floor). Lets M3-S4 backfill measure MFE/MAE and hit_1r. No order is placed.
        price = a.get("price"); atr1 = a.get("atr_1m")
        entry_ref = price
        stop_ref = (price - atr1) if (price is not None and atr1 and atr1 > 0) else None
        r_dollars = (entry_ref - stop_ref) if (entry_ref is not None and stop_ref is not None) else None
        stop_dist_bps = (r_dollars / entry_ref * 1e4) if (r_dollars and entry_ref) else None
        row = {
            "symbol": a["_symbol"], "minute": minute, "session_date": day, "as_of": as_of,
            "ign": out["ign"], "lane": out["lane"], "subscores": out["subscores"],
            "rvol_tod": rt, "profile_source": psrc,
            "spread_bps": (se * 1e4) if se is not None else None, "spread_source": spread_src,
            "pressure": t0.bar_pressure(bars), "evr": evr_last, "amihud": t0.amihud_illiq(bars),
            "entry_ref": entry_ref, "stop_ref": stop_ref, "r_dollars": r_dollars, "stop_dist_bps": stop_dist_bps,
        }
        # Layer A: named-setup taxonomy for this symbol/minute (SHADOW; fail-safe — never breaks logging)
        try:
            row["_tax"] = sdet.taxonomy_for_symbol(bars=bars, now=as_of.time(), cfg=cfg,
                registry=_registry, ign_lane=out["lane"], ign_score=out["ign"], atr_1m=a.get("atr_1m"),
                spread_bps=row["spread_bps"], price=a.get("price"),
                bar_volume=(t0._v(bars[-1]) if bars else None), data_tier="T0")
        except Exception:
            row["_tax"] = None
        results.append(row)
        # M3-S5: run the entry-trigger state machine over the symbol's session bars; log TRIGGER fires
        tr = trig.run_trigger_engine(bars, cfg)
        trigger_states[a["_symbol"]] = (tr["trace"][-1] if tr.get("trace") else "IDLE")  # current FSM state
        for fe in trig.triggered_fires(tr):
            fb = bars[fe["fire_idx"]]
            fm = fb.get("m")
            if fm is None:
                continue
            try:  # taxonomy at the fire bar (bars up to the fire) — primary reflects the fired pattern
                ftax = sdet.taxonomy_for_symbol(bars=bars[:fe["fire_idx"] + 1], now=as_of.time(), cfg=cfg,
                    registry=_registry, ign_lane=out["lane"], ign_score=out["ign"], atr_1m=a.get("atr_1m"),
                    spread_bps=row["spread_bps"], price=fe.get("entry"),
                    bar_volume=t0._v(bars[fe["fire_idx"]]), data_tier="T0")
            except Exception:
                ftax = None
            trigger_fires.append({
                "symbol": a["_symbol"], "fire_minute": fm, "fire_ts": fb.get("t"), "_tax": ftax,
                "entry": fe["entry"], "stop": fe["stop"], "r_dollars": fe["r_dollars"],
                "stop_dist_bps": (fe["r_dollars"] / fe["entry"] * 1e4) if (fe.get("r_dollars") and fe.get("entry")) else None,
                "ign": out["ign"], "subscores": out["subscores"], "rvol_tod": rt, "profile_source": psrc,
                "pressure": row["pressure"], "evr": row["evr"], "amihud": row["amihud"],
                "spread_bps": row["spread_bps"], "spread_source": row["spread_source"],
                "gate_reasons": {"macd_hist_5m": tr["macd_hist_5m"], "rr": fe.get("rr"),
                                 "stop_pct": fe.get("stop_pct"), "floor_bound": fe.get("floor_bound"),
                                 "trigger": "TRIGGERED"},
            })

    results.sort(key=lambda r: r["ign"], reverse=True)
    written = 0
    if args.apply:
        with conn.cursor() as cur:
            for r in results:
                import json as _json
                cur.execute(
                    """INSERT INTO scalp_ignition_events
                       (symbol, fired_at, session_date, minute_of_session, lane, ign_score,
                        subscores, rvol_tod, profile_source, data_tier, dcf, spread_bps,
                        spread_source, pressure, evr, amihud_illiq, entry_ref, stop_ref,
                        r_dollars, stop_dist_bps, gate_result, engine_version,
                        primary_setup_id, primary_setup_label, matched_setup_ids, matched_setup_labels,
                        setup_state, setup_version, setup_fired_at, market_session,
                        confirmation_labels, setup_evidence, setup_fail_reasons, registry_hash)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'T0',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,'m3-s3',
                               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [r["symbol"], r["as_of"], r["session_date"], r["minute"], r["lane"], r["ign"],
                     _json.dumps(r["subscores"]), r["rvol_tod"], r["profile_source"],
                     cfg["data_tiers"]["dcf"]["T0"], r["spread_bps"], r["spread_source"],
                     r["pressure"], r["evr"], r["amihud"], r["entry_ref"], r["stop_ref"],
                     r["r_dollars"], r["stop_dist_bps"], *_tax_values(r.get("_tax"), r["as_of"])])
                written += 1
        conn.commit()

    twritten = 0
    if args.apply and trigger_fires:
        import json as _json
        from datetime import datetime as _dt
        with conn.cursor() as cur:
            for tf in trigger_fires:
                cur.execute("""SELECT 1 FROM scalp_ignition_events WHERE symbol=%s AND session_date=%s
                               AND minute_of_session=%s AND lane='TRIGGER'""",
                            [tf["symbol"], day, tf["fire_minute"]])
                if cur.fetchone():
                    continue   # dedup (intraday logger re-runs)
                fired = _dt.fromisoformat(tf["fire_ts"].replace("Z", "+00:00")) if tf.get("fire_ts") else as_of
                cur.execute(
                    """INSERT INTO scalp_ignition_events
                       (symbol, fired_at, session_date, minute_of_session, lane, ign_score, subscores,
                        rvol_tod, profile_source, data_tier, dcf, spread_bps, spread_source, pressure,
                        evr, amihud_illiq, entry_ref, stop_ref, r_dollars, stop_dist_bps, gate_result,
                        gate_reasons, engine_version,
                        primary_setup_id, primary_setup_label, matched_setup_ids, matched_setup_labels,
                        setup_state, setup_version, setup_fired_at, market_session,
                        confirmation_labels, setup_evidence, setup_fail_reasons, registry_hash)
                       VALUES (%s,%s,%s,%s,'TRIGGER',%s,%s,%s,%s,'T0',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PASS',%s,'m3-s5',
                               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [tf["symbol"], fired, day, tf["fire_minute"], tf["ign"], _json.dumps(tf["subscores"]),
                     tf["rvol_tod"], tf["profile_source"], cfg["data_tiers"]["dcf"]["T0"], tf["spread_bps"],
                     tf["spread_source"], tf["pressure"], tf["evr"], tf["amihud"], tf["entry"], tf["stop"],
                     tf["r_dollars"], tf["stop_dist_bps"], _json.dumps(tf["gate_reasons"]),
                     *_tax_values(tf.get("_tax"), fired)])
                twritten += 1
        conn.commit()
    if trigger_fires:
        print(f"  TRIGGER fires this pass: {len(trigger_fires)} (written {twritten} after dedup)")

    top = int(args.top or 15)
    print(f"\n  {'sym':6} {'IGN':>6} {'lane':>9} {'RVOL_tod':>9} {'src':>13} {'v_rvol':>6} {'v_burst':>7} {'v_disp':>6} {'v_rs':>5}")
    for r in results[:top]:
        ss = r["subscores"]
        rt = f"{r['rvol_tod']:.2f}" if r["rvol_tod"] is not None else "  -"
        print(f"  {r['symbol']:6} {r['ign']:>6.1f} {r['lane']:>9} {rt:>9} {r['profile_source']:>13} "
              f"{ss['v_rvol']:>6.2f} {ss['v_burst']:>7.2f} {ss['v_disp']:>6.2f} {ss['v_rs']:>5.2f}")
    # lane distribution
    from collections import Counter
    dist = Counter(r["lane"] for r in results)
    print(f"\n  lane distribution: {dict(dist)}")
    _emit = bool(cfg.get("notifications", {}).get("emit", False))
    print(f"  scored={len(results)} rows_written={written} emit={_emit}")

    # M3-S7: ignition alerts (§3.4) — ALERTS ONLY, never proposals. Gated by notifications.emit.
    # LIVE runs send via alert_dispatcher (which dedupes once/day/symbol + rate-limits 15/hr);
    # REPLAY is ALWAYS dry (historical → never alerts). --dry-run also never sends.
    if _emit:
        try:
            import scalp_alert_emitter as _ae
            alert_dry = bool(getattr(args, "dry_run", False)) or bool(args.replay)
            budget = _ae.AlertBudget(int(cfg["notifications"].get("session_cap", 8)))
            disp = None if alert_dry else _ae.load_dispatcher()
            alerts = _ae.emit_alerts(results, cfg, budget, dispatch_fn=disp, dry_run=alert_dry)
            tg = sum(1 for a in alerts if a.get("tier") == "ALERT" and a.get("action") == "dispatch")
            info = sum(1 for a in alerts if a.get("tier") == "INFO")
            print(f"  [alerts]{' DRY' if alert_dry else ''} telegram={tg} dashboard_info={info} "
                  f"(NOT proposals){'  — no send' if alert_dry else ''}")
        except Exception as e:
            print(f"  [alerts] skipped: {e}")

    # M3-S5.5: multi-source observation fabric — DEFAULT OFF. When off this block is a pure no-op and
    # the T0 path above is byte-identical. When on (dry-run/experiment) it acquires + arbitrates a
    # canonical bar snapshot and PRINTS provenance only — it does not change scoring, triggers, or any
    # persisted row (no schema change; observability only).
    try:
        from market_observations.fabric import MultiSourceFabric, is_enabled as _ms_enabled
    except Exception:
        _ms_enabled = lambda _c: False  # noqa: E731
        MultiSourceFabric = None
    if MultiSourceFabric is not None and _ms_enabled(cfg):
        try:
            ms = MultiSourceFabric(cfg).acquire_bar_snapshot([a["_symbol"] for a in assembled])
            srcs = sorted({v["provenance"]["selected_source"] for v in ms.values()
                           if v["provenance"]["selected_source"]})
            confs = sum(1 for v in ms.values() if v["provenance"]["conflict"])
            print(f"  [multi_source] canonical snapshot: {len(ms)} symbols · sources={srcs} · conflicts={confs} "
                  f"(provenance only — scoring/triggers unchanged)")
        except Exception as e:
            print(f"  [multi_source] skipped: {e}")

    # Moomoo T2 arm-on-demand: wire the trigger FSM ARMED state → L2 subscription budget. CONSERVING +
    # fail-closed (SCAFFOLD_ONLY until OpenD configured → no real subscription/cost). LIVE only (replay
    # is historical → never arms). Does NOT change scoring/triggers; state persists across cron runs.
    t2cfg = cfg.get("t2", {})
    if t2cfg.get("arm_from_trigger", False) and not args.replay:
        try:
            import json as _json, time as _time
            from pathlib import Path as _P
            from market_observations.moomoo_t2 import (default_provider, sync_arm_from_states,
                                                       ArmedSubscriptionManager)
            prov = default_provider()
            prov.manager = ArmedSubscriptionManager(int(t2cfg.get("max_armed", 8)),
                                                    float(t2cfg.get("ttl_seconds", 180)))
            sf = _P(_REPO) / t2cfg.get("state_file", "data/scalp/moomoo_armed_state.json")
            now_s = _time.time()
            if sf.exists():
                try:
                    prov.manager.load_state(_json.loads(sf.read_text()))
                except Exception:
                    pass
            res = sync_arm_from_states(prov, trigger_states, now_s)
            books = sum(1 for s in res["armed"] if prov.fetch_book(s, now_s, as_of.isoformat()) is not None)
            sf.parent.mkdir(parents=True, exist_ok=True)
            sf.write_text(_json.dumps(prov.manager.to_state(now_s)))
            used, cap = prov.manager.budget_used(now_s)
            print(f"  [moomoo-arm] armed={res['armed']} disarmed={res['disarmed']} "
                  f"budget={used}/{cap} books={books} opend_up={prov.opend_up()} (fail-closed until OpenD)")
        except Exception as e:
            print(f"  [moomoo-arm] skipped: {e}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M3-S3 shadow ignition logger (no alerts/proposals)")
    ap.add_argument("--replay", help="YYYY-MM-DD session to replay")
    ap.add_argument("--minute", default=60, help="minute-of-session to score as-of (replay)")
    ap.add_argument("--live", action="store_true", help="score as-of the current RTH minute")
    ap.add_argument("--symbols", help="comma-separated override (default: config universe)")
    ap.add_argument("--apply", action="store_true", help="write rows to scalp_ignition_events")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--top", default=15)
    args = ap.parse_args(argv)
    if not args.replay and not args.live:
        ap.error("provide --replay YYYY-MM-DD or --live")
    if args.dry_run:
        args.apply = False
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
