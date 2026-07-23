#!/usr/bin/env python3
"""technical_intelligence.py — THE canonical multi-timeframe technical snapshot
(Section 17.1-17.3, 17.7, 17.9, 17.10, 17.12, 17.14).

One deterministic, LLM-free service consumed by decision packets, Local Quant,
family construction, the card rail and the Technicals drawer. Indicators come
from indicator_engine (weights + UNAVAILABLE semantics + capability audit),
patterns from chart_patterns (closed-bar lifecycle), bars from the proven
market_data_snapshot_loader path cached in market_ohlcv_bars; weekly/monthly
are deterministic resamples of daily. Freshness and direction are SEPARATE
axes, per timeframe, config-driven.

    analyze_technicals(symbol, timeframes=("1h","daily","weekly"),
                       include_patterns=True) -> snapshot dict (17.12 contract)

Caching: bars upsert into market_ohlcv_bars keyed by last closed bar; computed
snapshots memoized per (symbol, tf-set, last_closed_bars, FORMULA_VERSION).
An LLM may EXPLAIN this output; nothing here ever consults one.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import pandas as pd  # noqa: E402

import chart_patterns as cpat  # noqa: E402
import indicator_engine as ie  # noqa: E402

SCHEMA_VERSION = "1.0.0"
FORMULA_VERSION = f"ie:{getattr(ie, 'ENGINE_VERSION', '1')}+cp:{cpat.ENGINE_VERSION}"

# per-timeframe staleness (minutes, RTH) — config-driven via the V5 policy YAML
# (technical_freshness: block) with these defaults; off-hours multiplies by 6.
# daily bars are stamped at 00:00 of their session — the last CLOSED daily bar
# is legitimately ~40h old just before today's close. Windows accommodate that.
DEFAULT_FRESHNESS_MIN = {"5m": 10, "15m": 30, "1h": 90,
                         "daily": 45 * 60, "weekly": 9 * 24 * 60, "monthly": 35 * 24 * 60}
TF_FETCH = {   # fetchable intervals (weekly/monthly resample from daily)
    "5m": {"native": True}, "15m": {"native": True}, "1h": {"native": True},
    "daily": {"native": True}, "weekly": {"resample_of": "daily", "rule": "W-FRI"},
    "monthly": {"resample_of": "daily", "rule": "ME"},
}
TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "daily": 86400,
              "weekly": 7 * 86400, "monthly": 31 * 86400}
_SNAP_CACHE: dict = {}


def _now():
    return datetime.now(timezone.utc)


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _freshness_cfg() -> dict:
    try:
        import watch_decision_refresh as wdr
        return (wdr.load_policy().get("technical_freshness") or {})
    except Exception:
        return {}


# ── bars: DB cache + governed fetch + resample; CLOSED bars only ─────────────
def _bar_closed(ts: datetime, tf: str, now: datetime) -> bool:
    return ts + timedelta(seconds=TF_SECONDS.get(tf, 86400)) <= now


def load_bars(symbol: str, tf: str, conn=None, *, allow_fetch: bool = True) -> dict:
    """Returns {bars: [...closed only...], meta: 17.2 per-timeframe metadata}."""
    now = _now()
    sym = symbol.upper()
    spec = TF_FETCH.get(tf)
    if not spec:
        return {"bars": [], "meta": {"timeframe": tf, "freshness_state": "UNAVAILABLE",
                                     "missing_data_reasons": [f"unsupported timeframe {tf}"]}}
    if spec.get("resample_of"):
        base = load_bars(sym, spec["resample_of"], conn, allow_fetch=allow_fetch)
        bars = _resample(base["bars"], spec["rule"])
        meta = dict(base["meta"], timeframe=tf, bar_interval=tf,
                    derived_from=spec["resample_of"], bars=len(bars))
        if bars:
            meta.update(first_bar=bars[0]["ts"], last_closed_bar=bars[-1]["ts"])
        return {"bars": bars, "meta": meta}

    conn = conn or _conn()
    cur = conn.cursor()
    cur.execute("""SELECT bar_time, open, high, low, close, volume, source
                   FROM market_ohlcv_bars WHERE upper(symbol)=%s AND timeframe=%s
                   ORDER BY bar_time""", (sym, tf))
    rows = cur.fetchall()
    last = rows[-1][0] if rows else None
    stale_fetch = (last is None
                   or (now - last).total_seconds() > 1.5 * TF_SECONDS.get(tf, 86400))
    fetched_at = None
    if stale_fetch and allow_fetch:
        fetched_at = now
        try:
            import market_data_snapshot_loader as mdl
            if tf == "1h" and "1h" not in mdl.TIMEFRAME_MAP:
                mdl.TIMEFRAME_MAP["1h"] = {"yf_interval": "60m", "yf_period": "3mo",
                                           "max_days": 180}
            if tf == "daily":
                mdl.TIMEFRAME_MAP["daily"]["max_days"] = 730  # weekly/monthly resample depth
            days = {"5m": 30, "15m": 60, "1h": 180, "daily": 730}.get(tf, 365)
            fetched = mdl.fetch_yfinance_bars(sym, tf, days) or \
                mdl.fetch_polygon_bars(sym, tf, days)
            if fetched:
                mdl.store_bars(conn, fetched)
                conn.commit()
                cur.execute("""SELECT bar_time, open, high, low, close, volume, source
                               FROM market_ohlcv_bars WHERE upper(symbol)=%s AND timeframe=%s
                               ORDER BY bar_time""", (sym, tf))
                rows = cur.fetchall()
        except Exception:
            conn.rollback()
    bars = [{"ts": r[0].isoformat(), "_dt": r[0], "open": float(r[1]), "high": float(r[2]),
             "low": float(r[3]), "close": float(r[4]), "volume": float(r[5] or 0),
             "source": r[6]} for r in rows]
    closed = [b for b in bars if _bar_closed(b["_dt"], tf, now)]
    forming = len(bars) - len(closed)
    for b in closed:
        b.pop("_dt", None)
    fresh_limit_min = float(_freshness_cfg().get(tf, DEFAULT_FRESHNESS_MIN.get(tf, 1440)))
    try:
        import packet_invalidation as pi
        _rth = pi.is_us_cash_rth()
    except Exception:
        _rth = True
    if not _rth:
        fresh_limit_min *= 6
    if tf in ("5m", "15m", "1h"):
        # Intraday bars only close during the cash session. Off-hours — and in
        # the morning window before the first bar of this timeframe has closed —
        # the prior session's final bar IS the freshest possible data, so a
        # wall-clock window must not mark it stale (it flagged every card STALE
        # from close until ~10:30 ET). Cap 4 days: covers weekends + holidays.
        try:
            from zoneinfo import ZoneInfo
            _et = now.astimezone(ZoneInfo("America/New_York"))
            _since_open = (_et - _et.replace(hour=9, minute=30, second=0,
                                             microsecond=0)).total_seconds()
            if not _rth or _since_open < TF_SECONDS[tf] + 300:
                fresh_limit_min = max(fresh_limit_min, 4 * 24 * 60)
            else:
                # freshest possible closed bar is stamped open+(n-1)*interval;
                # allow its age plus the configured grace before calling STALE
                _n = int(_since_open // TF_SECONDS[tf])
                fresh_limit_min += (_since_open - (_n - 1) * TF_SECONDS[tf]) / 60.0
        except Exception:
            pass
    age_s = (now - closed[-1]["ts"] if False else
             (now - datetime.fromisoformat(closed[-1]["ts"])).total_seconds()) if closed else None
    state = ("UNAVAILABLE" if not closed
             else "STALE" if age_s is not None and age_s > fresh_limit_min * 60
             else "CURRENT")
    reasons = []
    if not rows:
        reasons.append("no bars in store and fetch returned none" if allow_fetch
                       else "no bars in store (fetch disabled)")
    meta = {"timeframe": tf, "bar_interval": tf, "bars": len(closed),
            "first_bar": closed[0]["ts"] if closed else None,
            "last_closed_bar": closed[-1]["ts"] if closed else None,
            "forming_bars_excluded": forming,
            "data_provider": closed[-1]["source"] if closed else None,
            "fetched_at": fetched_at.isoformat() if fetched_at else None,
            "age_seconds": round(age_s) if age_s is not None else None,
            "expected_cadence_min": fresh_limit_min,
            "freshness_state": state, "missing_data_reasons": reasons}
    return {"bars": closed, "meta": meta}


def _resample(daily: list[dict], rule: str) -> list[dict]:
    if not daily:
        return []
    df = pd.DataFrame(daily)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    r = df.resample(rule).agg(open=("open", "first"), high=("high", "max"),
                              low=("low", "min"), close=("close", "last"),
                              volume=("volume", "sum")).dropna()
    if len(r) > 0:      # the in-progress week/month is NOT a closed bar
        r = r.iloc[:-1]
    return [{"ts": i.isoformat(), "open": float(x.open), "high": float(x.high),
             "low": float(x.low), "close": float(x.close), "volume": float(x.volume),
             "source": "resample"} for i, x in r.iterrows()]


# ── divergence: pivot-aligned (17.7) ─────────────────────────────────────────
def detect_divergences(bars: list[dict], tf: str) -> list[dict]:
    out = []
    if len(bars) < 40:
        return out
    df = pd.DataFrame(bars)
    try:
        rsi = ie.ta.rsi(df["close"], length=14)
        macd_df = ie.ta.macd(df["close"])
        hist = macd_df[[c for c in macd_df.columns if c.startswith("MACDh")][0]]
    except Exception:
        return out
    piv = cpat.find_pivots(bars)
    for kind, direction, name in (("L", "BULLISH", "RSI_BULLISH_DIVERGENCE"),
                                  ("H", "BEARISH", "RSI_BEARISH_DIVERGENCE")):
        ps = [p for p in piv if p.kind == kind][-2:]
        if len(ps) < 2:
            continue
        p1, p2 = ps
        try:
            i1 = rsi.iloc[max(0, p1.idx - 1):p1.idx + 2].mean()
            i2 = rsi.iloc[max(0, p2.idx - 1):p2.idx + 2].mean()
        except Exception:
            continue
        if pd.isna(i1) or pd.isna(i2):
            continue
        lower_low = p2.price < p1.price
        higher_ind = i2 > i1 + 1.5
        higher_high = p2.price > p1.price
        lower_ind = i2 < i1 - 1.5
        if (kind == "L" and lower_low and higher_ind) or \
           (kind == "H" and higher_high and lower_ind):
            out.append({"divergence": name, "indicator": "rsi14", "timeframe": tf,
                        "direction": direction,
                        "price_pivot_1": p1.price, "price_pivot_2": p2.price,
                        "indicator_pivot_1": round(float(i1), 1),
                        "indicator_pivot_2": round(float(i2), 1),
                        "dates": [p1.ts, p2.ts],
                        "state": "CONFIRMED",   # both pivots on closed bars
                        "invalidation": p2.price,
                        "quality": min(100, round(20 * abs(float(i2 - i1))))})
    # MACD histogram divergence vs last two same-side price pivots (compact)
    try:
        lows = [p for p in piv if p.kind == "L"][-2:]
        if len(lows) == 2 and lows[1].price < lows[0].price:
            h1 = float(hist.iloc[lows[0].idx]); h2 = float(hist.iloc[lows[1].idx])
            if h2 > h1 + 1e-9:
                out.append({"divergence": "MACD_HISTOGRAM_BULLISH_DIVERGENCE",
                            "indicator": "macd_hist", "timeframe": tf, "direction": "BULLISH",
                            "price_pivot_1": lows[0].price, "price_pivot_2": lows[1].price,
                            "indicator_pivot_1": round(h1, 4), "indicator_pivot_2": round(h2, 4),
                            "dates": [lows[0].ts, lows[1].ts], "state": "CONFIRMED",
                            "invalidation": lows[1].price, "quality": 60})
    except Exception:
        pass
    return out


# ── overbought/oversold CONTEXT (17.9) ───────────────────────────────────────
def momentum_context(indicators: dict, divergences: list[dict]) -> dict:
    rsi = ((indicators.get("rsi") or {}).get("value"))
    macd_d = ((indicators.get("macd") or {}).get("details") or {})
    adx_d = ((indicators.get("adx") or {}).get("details") or {})
    hist_rising = str(macd_d.get("histogram_trend", macd_d.get("hist_trend", ""))).lower() in ("rising", "up", "improving")
    adx = adx_d.get("adx")
    bull_div = any(d["direction"] == "BULLISH" for d in divergences)
    if rsi is None:
        return {"state": "UNRESOLVED", "note": "rsi unavailable"}
    if rsi <= 32:
        if bull_div or hist_rising:
            return {"state": "OVERSOLD_RECOVERY", "rsi": rsi,
                    "note": "oversold with improving momentum — conditional bullish, not automatic"}
        return {"state": "OVERSOLD_CONTINUING_DOWN", "rsi": rsi,
                "note": "oversold in an intact downtrend — NOT a buy signal"}
    if rsi >= 68:
        if adx is not None and adx >= 35:
            return {"state": "OVERBOUGHT_STRONG_TREND", "rsi": rsi,
                    "note": "overbought inside a strong trend — chase risk, not automatically bearish"}
        if not hist_rising:
            return {"state": "OVERBOUGHT_EXHAUSTING", "rsi": rsi,
                    "note": "overbought with fading momentum"}
        return {"state": "OVERBOUGHT_STRONG_TREND", "rsi": rsi, "note": "trend intact"}
    return {"state": "NEUTRAL_RANGE", "rsi": rsi, "note": "no OB/OS condition"}


# ── levels with provenance (17.3E) ───────────────────────────────────────────
def build_levels(tf_results: dict) -> list[dict]:
    levels: list[dict] = []
    for tf, r in tf_results.items():
        ind = r.get("indicators") or {}
        fib = ((ind.get("fibonacci") or {}).get("details") or {}).get("key_levels") or {}
        for name, px in fib.items():
            if isinstance(px, (int, float)):
                levels.append({"price": round(float(px), 2), "source": f"{tf} fib {name}",
                               "timeframe": tf, "kind": "fibonacci"})
        for pname in ("pivots_daily", "pivots_weekly"):
            pv = (ind.get(pname) or {}).get("details") or {}
            for k in ("pp", "r1", "s1", "r2", "s2"):
                if isinstance(pv.get(k), (int, float)):
                    levels.append({"price": round(float(pv[k]), 2),
                                   "source": f"{tf} {pname.replace('pivots_', '')} pivot {k.upper()}",
                                   "timeframe": tf, "kind": "pivot"})
        for p in (r.get("patterns") or []):
            if p.get("trigger") is not None:
                levels.append({"price": p["trigger"], "source": f"{tf} {p['pattern']} trigger",
                               "timeframe": tf, "kind": "pattern_trigger"})
    # cluster within 0.35% into confluence entries with combined provenance
    levels.sort(key=lambda x: x["price"])
    clustered: list[dict] = []
    for lv in levels:
        if clustered and abs(lv["price"] - clustered[-1]["price"]) / max(lv["price"], 1e-9) < 0.0035:
            clustered[-1]["sources"].append(lv["source"])
            clustered[-1]["confluence"] = len(clustered[-1]["sources"])
        else:
            clustered.append({"price": lv["price"], "sources": [lv["source"]],
                              "confluence": 1, "kind": lv["kind"]})
    clustered.sort(key=lambda x: -x["confluence"])
    return clustered[:12]


# ── snapshot assembly (17.12) + pills (17.14) ────────────────────────────────
def analyze_technicals(symbol: str, timeframes=("1h", "daily", "weekly"),
                       conn=None, *, include_patterns: bool = True,
                       allow_fetch: bool = True) -> dict:
    sym = symbol.upper()
    conn = conn or _conn()
    tf_results: dict = {}
    unavailable: list[str] = []
    for tf in timeframes:
        pack = load_bars(sym, tf, conn, allow_fetch=allow_fetch)
        bars, meta = pack["bars"], pack["meta"]
        entry = {"meta": meta, "indicators": {}, "patterns": [], "candles": [],
                 "divergences": [], "direction": "UNRESOLVED"}
        if len(bars) >= 30:
            df = pd.DataFrame(bars)
            cfgs = (ie.CONFIG.get("strategies", {}) if ie.CONFIG else {})
            for name, fn in ie.STRATEGY_FUNCTIONS.items():
                try:
                    entry["indicators"][name] = fn(df, cfgs.get(name, {}))
                except Exception as e:
                    entry["indicators"][name] = ie._unavailable(e)
            entry["confluence"] = ie.analyze_confluence_v2(entry["indicators"], cfgs)
            entry["direction"] = _direction_word(entry["confluence"])
            if include_patterns:
                det = cpat.detect_all(bars)
                entry["patterns"] = det["patterns"][:6]
                entry["candles"] = det["candles"][:4]
            entry["divergences"] = detect_divergences(bars, tf)
            entry["momentum_context"] = momentum_context(entry["indicators"],
                                                         entry["divergences"])
        else:
            meta["missing_data_reasons"].append(f"only {len(bars)} closed bars (<30)")
            meta["freshness_state"] = "UNAVAILABLE"
            unavailable.append(tf)
        tf_results[tf] = entry

    freshness_states = [r["meta"]["freshness_state"] for r in tf_results.values()]
    overall_fresh = ("UNAVAILABLE" if all(s == "UNAVAILABLE" for s in freshness_states)
                     else "STALE" if "STALE" in freshness_states
                     else "PARTIAL" if "UNAVAILABLE" in freshness_states
                     else "CURRENT")
    dirs = [r["direction"] for r in tf_results.values() if r["direction"] != "UNRESOLVED"]
    overall_dir = (dirs[max(0, len(dirs) - 2)] if dirs else "UNRESOLVED")
    conflicts = []
    if "BULLISH" in " ".join(dirs) and "BEARISH" in " ".join(dirs):
        overall_dir = "MIXED"
        conflicts = [f"{tf} {r['direction']}" for tf, r in tf_results.items()
                     if r["direction"] != "UNRESOLVED"]
    all_pats = [dict(p, timeframe=tf) for tf, r in tf_results.items()
                for p in r.get("patterns", [])]
    order = {"CONFIRMED": 0, "RETESTING": 1, "AWAITING_CONFIRMATION": 2, "FORMING": 3}
    primary = next((p for p in sorted(all_pats, key=lambda p: (order.get(p["state"], 9),
                                                               -p["quality_score"]))
                    if p.get("primary_eligible")), None)
    src_hash = hashlib.sha256(json.dumps(
        [(tf, r["meta"].get("last_closed_bar"), r["meta"].get("bars"))
         for tf, r in sorted(tf_results.items())] + [FORMULA_VERSION],
        default=str).encode()).hexdigest()[:16]
    snap = {
        "schema_version": SCHEMA_VERSION, "formula_version": FORMULA_VERSION,
        "symbol": sym, "computed_at": _now().isoformat(),
        "overall_freshness": overall_fresh, "overall_direction": overall_dir,
        "timeframes": tf_results, "primary_pattern": primary, "patterns": all_pats[:10],
        "levels": build_levels(tf_results), "conflicts": conflicts,
        "unavailable": unavailable, "source_hash": src_hash,
    }
    snap["verdict"] = build_verdict(snap)
    snap["pills"] = select_pills(snap)
    return snap


def build_verdict(snap: dict) -> dict:
    """Deterministic synthesized verdict (V6 item 8): one operator conclusion +
    supporting/conflicting evidence lists, from the same snapshot the tiles use.
    The operator must never have to mentally reconcile six tiles."""
    tfs = snap.get("timeframes") or {}
    daily = tfs.get("daily") or {}
    conf = daily.get("confluence") or {}
    mc = (daily.get("momentum_context") or {})
    supporting, conflicting = [], []
    pp = snap.get("primary_pattern")
    if pp:
        line = f"{pp['timeframe']} {pp['pattern'].replace('_', ' ').lower()} {pp['state'].replace('_', ' ').lower()}"
        (supporting if pp["direction"] == "BULLISH" and pp["state"] in ("CONFIRMED", "RETESTING")
         else conflicting if pp["direction"] == "BEARISH" and pp["state"] in ("CONFIRMED", "RETESTING")
         else conflicting if pp["state"] in ("FORMING", "AWAITING_CONFIRMATION")
         else supporting).append(line + ("" if pp["state"] == "CONFIRMED" else " (not yet confirmed)"))
    lv = (snap.get("levels") or [None])[0]
    if lv and lv.get("confluence", 0) >= 3:
        supporting.append(f"{lv['confluence']}x support/level confluence at ${lv['price']}")
    st = str(conf.get("state", ""))
    if st.startswith("BULLISH"):
        supporting.append(f"daily confluence {st.replace('_', ' ').lower()}")
    elif st.startswith("BEARISH"):
        conflicting.append(f"daily confluence {st.replace('_', ' ').lower()}")
    elif st == "MIXED":
        conflicting.append("daily trend mixed")
    mcs = str(mc.get("state", ""))
    if mcs == "OVERSOLD_RECOVERY":
        supporting.append("oversold recovery underway")
    elif mcs in ("OVERSOLD_CONTINUING_DOWN", "OVERBOUGHT_EXHAUSTING"):
        conflicting.append(mcs.replace("_", " ").lower())
    elif mcs == "NEUTRAL_RANGE":
        conflicting.append("neutral momentum")
    vroc = ((daily.get("indicators") or {}).get("volume_roc") or {})
    vr = (vroc.get("details") or {}).get("volume_ratio")
    if vr is not None:
        if vroc.get("signal") == "BULLISH":
            supporting.append(f"RVOL {vr}x confirms")
        elif vr < 1.0:
            conflicting.append(f"RVOL {vr}x — below average, no confirmation")
    for c in (snap.get("conflicts") or [])[:2]:
        conflicting.append(str(c).lower())
    n_sup, n_con = len(supporting), len(conflicting)
    if snap.get("overall_freshness") not in ("CURRENT", "PARTIAL"):
        state, line = "STALE", "technical evidence is stale — refresh before acting"
    elif n_sup >= 2 and n_con == 0:
        state = "SUPPORTIVE"
        line = "technical evidence supports the setup"
    elif n_con >= 2 and n_sup == 0:
        state = "OPPOSED"
        line = "technical evidence opposes entry here"
    elif n_sup and n_con:
        state = "MIXED"
        line = "mixed — setup not confirmed by current evidence"
    else:
        state, line = "NEUTRAL", "no decisive technical evidence"
    return {"state": state, "line": line,
            "supporting": supporting[:4], "conflicting": conflicting[:4]}


def _direction_word(conf: dict) -> str:
    s = str(conf.get("state", ""))
    if s.startswith("BULLISH"):
        return "BULLISH"
    if s.startswith("BEARISH"):
        return "BEARISH"
    if s == "MIXED":
        return "MIXED"
    return "NEUTRAL" if s == "NEUTRAL" else "UNRESOLVED"


def select_pills(snap: dict) -> list[dict]:
    """Max 6 primary pills by deterministic decision relevance (17.14):
    pattern > trend > momentum > volume > level > freshness. Freshness rides on
    every pill separately from direction — STALE is never a direction."""
    pills: list[dict] = []
    tfs = snap["timeframes"]

    def freshness_of(tf):
        return tfs.get(tf, {}).get("meta", {}).get("freshness_state", "UNAVAILABLE")

    p = snap.get("primary_pattern")
    if p:
        pills.append({"rank": 1, "kind": "pattern",
                      "label": f"{p['timeframe'].upper()} {p['pattern'].replace('_', ' ')}",
                      "value": p["state"].replace("_", " "),
                      "direction": p["direction"], "lifecycle": p["state"],
                      "freshness": freshness_of(p["timeframe"]),
                      "tooltip": (f"trigger {p.get('trigger')} · invalidation "
                                  f"{p.get('invalidation')} · target {p.get('measured_target')} "
                                  f"· quality {p.get('quality_score')}")})
    ranked_tf = next((t for t in ("daily", "1h", "weekly") if t in tfs
                      and tfs[t].get("confluence")), None)
    if ranked_tf:
        r = tfs[ranked_tf]
        conf = r["confluence"]
        pills.append({"rank": 2, "kind": "trend",
                      "label": f"{ranked_tf.upper()} {conf['state'].replace('_', ' ')}",
                      "value": f"net {conf['net_score']:+d}",
                      "direction": _direction_word(conf), "lifecycle": "CONFIRMED",
                      "freshness": freshness_of(ranked_tf),
                      "tooltip": f"families bull {conf['independent_families_bullish']} / "
                                 f"bear {conf['independent_families_bearish']} · weighted, capped"})
        mc = r.get("momentum_context") or {}
        rsi = (r["indicators"].get("rsi") or {}).get("value")
        if mc.get("state") and mc["state"] not in ("UNRESOLVED",):
            pills.append({"rank": 3, "kind": "momentum",
                          "label": mc["state"].replace("_", " "),
                          "value": f"RSI {rsi}" if rsi is not None else "",
                          "direction": ("BULLISH" if "RECOVERY" in mc["state"]
                                        else "BEARISH" if "CONTINUING_DOWN" in mc["state"]
                                        or "EXHAUSTING" in mc["state"] else "NEUTRAL"),
                          "lifecycle": "CONFIRMED", "freshness": freshness_of(ranked_tf),
                          "tooltip": mc.get("note", "")})
        vroc = (r["indicators"].get("volume_roc") or {})
        det = vroc.get("details") or {}
        if det.get("volume_ratio") is not None:
            vr = det["volume_ratio"]
            pills.append({"rank": 4, "kind": "volume",
                          "label": f"RVOL {vr}×",
                          "value": ("CONFIRMS" if vroc.get("signal") == "BULLISH"
                                    else "SELL PRESSURE" if vroc.get("signal") == "BEARISH"
                                    else "NO CONFIRM"),
                          "direction": vroc.get("signal", "NEUTRAL"),
                          "lifecycle": "CONFIRMED", "freshness": freshness_of(ranked_tf),
                          "tooltip": f"classification {det.get('classification')}"})
    lv = (snap.get("levels") or [None])[0]
    if lv and lv["confluence"] >= 2:
        pills.append({"rank": 5, "kind": "level",
                      "label": f"${lv['price']}",
                      "value": f"{lv['confluence']}× confluence",
                      "direction": "NEUTRAL", "lifecycle": "CONFIRMED",
                      "freshness": snap["overall_freshness"],
                      "tooltip": " + ".join(lv["sources"][:4])})
    pills.append({"rank": 6, "kind": "freshness",
                  "label": f"TECH {snap['overall_freshness']}",
                  "value": "", "as_of": snap["computed_at"],
                  "direction": "NEUTRAL", "lifecycle": "CONFIRMED",
                  "freshness": snap["overall_freshness"],
                  "tooltip": f"source hash {snap['source_hash']} · {FORMULA_VERSION}"})
    return pills[:6]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--timeframes", default="1h,daily,weekly")
    a = ap.parse_args()
    s = analyze_technicals(a.symbol, tuple(a.timeframes.split(",")))
    slim = {k: v for k, v in s.items() if k != "timeframes"}
    slim["tf_meta"] = {tf: r["meta"] for tf, r in s["timeframes"].items()}
    print(json.dumps(slim, indent=1, default=str))
