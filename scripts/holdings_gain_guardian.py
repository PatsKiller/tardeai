#!/usr/bin/env python3
"""Gain Guardian — holdings exit intelligence for the LIVE book (advisory-only).

Phase 191's giveback ladder + the protection advisor's technicals, ported to
the real book, with a parabolic layer on top. Deterministic core — zero LLM
calls. Read-only on every broker surface: this script never places, moves, or
proposes anything; it measures, classifies, and (once the operator promotes it
out of shadow) publishes advisory briefs.

Usage:
  python scripts/holdings_gain_guardian.py                 # dry-run (default)
  python scripts/holdings_gain_guardian.py --apply         # persist metrics + HWM ratchet
  python scripts/holdings_gain_guardian.py --apply --shadow  # explicit shadow (same as published=false)
  python scripts/holdings_gain_guardian.py --symbols V,SCHG --dry-run
  python scripts/holdings_gain_guardian.py --promote       # operator: flip config published=true

HWM seeding (verified 2026-07-16): schwab_cost_basis_lots.opened_date is NULL
on 100% of rows, so 'lots_history' seeding is impossible — HWMs seed from
daily-bar history ('52w_high', ≥60 bars) or current price ('provisional',
labeled, never above REVIEW severity). Basis hierarchy: lots > holdings.json >
basis_unknown (gain-based advisories suppressed, never guessed).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

CONFIG_PATH = ROOT / "config" / "gain_guardian_thresholds.json"
HOLDINGS_PATH = ROOT / "data" / "portfolios" / "state" / "holdings.json"

DDL = """
CREATE TABLE IF NOT EXISTS holding_high_water_marks (
    symbol       TEXT NOT NULL,
    account      TEXT NOT NULL,
    hwm_price    NUMERIC,
    hwm_date     DATE,
    basis_ps     NUMERIC,
    basis_source TEXT,
    seeded_from  TEXT,
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, account)
);
CREATE TABLE IF NOT EXISTS holding_exit_metrics (
    id BIGSERIAL PRIMARY KEY,
    run_at TIMESTAMPTZ DEFAULT NOW(),
    symbol TEXT NOT NULL,
    account TEXT NOT NULL,
    price NUMERIC, weight_pct NUMERIC,
    ext50_atr NUMERIC, ext200_atr NUMERIC, rsi14 NUMERIC, rvol20 NUMERIC,
    up_streak INT, gain_5d_pct NUMERIC, gap_ups_5d INT, slope_accel NUMERIC,
    open_gain_pct NUMERIC, giveback_frac NUMERIC,
    parabolic_score NUMERIC, extension_state TEXT, giveback_state TEXT,
    advisory TEXT, severity TEXT,
    basis_source TEXT, seeded_from TEXT,
    metrics JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_holding_exit_metrics_run ON holding_exit_metrics (run_at DESC);
"""


def _db():
    from db_adapter import _execute, USE_DB
    if not USE_DB:
        raise RuntimeError("DB unavailable")
    return _execute


def _load_cfg() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _iron_rule() -> tuple[float, int]:
    """Holdings sanity gate — STOP if the state file looks wrong."""
    d = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    total = float((d.get("portfolio_totals") or {}).get("total_value") or 0)
    n = len([h for h in d.get("holdings") or [] if not h.get("is_cash")])
    if not (1_000_000 <= total <= 1_400_000) or n <= 0:
        raise SystemExit(f"IRON RULE FAIL: total_value={total} holdings={n} — refusing to run")
    return total, n


def _holdings(cfg: dict, only: set[str] | None) -> list[dict[str, Any]]:
    import holding_family as hf
    d = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    total = float((d.get("portfolio_totals") or {}).get("total_value") or 0) or 1.0
    skip_syms = {s.upper() for s in cfg.get("skip_symbols") or []}
    skip_fams = {f.lower() for f in cfg.get("skip_families") or []}
    out = []
    for h in d.get("holdings") or []:
        sym = str(h.get("symbol") or "").upper()
        if not sym or h.get("is_cash") or sym in skip_syms:
            continue
        if only and sym not in only:
            continue
        try:
            fam = str(hf.classify_family(sym) or "").lower()
        except Exception:
            fam = ""
        if fam in skip_fams:
            continue
        mv = float(h.get("market_value") or 0)
        out.append({
            "symbol": sym,
            "account": str(h.get("account") or "unknown"),
            "market_value": mv,
            "weight_pct": round(100.0 * mv / total, 2),
            "shares": float(h.get("shares") or 0),
            "holdings_avg_cost": h.get("avg_cost") or h.get("cost_basis_ps"),
            "holdings_cost_basis": h.get("cost_basis"),
            "family": fam,
        })
    return out


def _lots_basis(ex, symbol: str, account: str) -> float | None:
    """Share-weighted basis from schwab_cost_basis_lots, ACCOUNT-matched.

    Adaptation vs the original plan (live data wins): lots are stale
    (2026-06-10), cover only two accounts, and opened_date is 100% NULL — so
    holdings.json per-account basis ranks FIRST and lots are the fallback.
    """
    try:
        rows = ex(
            """SELECT quantity, cost_per_share FROM schwab_cost_basis_lots
               WHERE upper(symbol)=%s AND account=%s AND kind='unrealized'
                 AND quantity > 0 AND cost_per_share > 0""",
            (symbol, account), fetch="all",
        ) or []
    except Exception:
        return None
    qty = sum(float(r["quantity"]) for r in rows)
    if qty <= 0:
        return None
    return sum(float(r["quantity"]) * float(r["cost_per_share"]) for r in rows) / qty


def _stop_state(ex) -> tuple[set[str], set[str]]:
    """(symbols with an ACTIVE stop on any account, symbols whose stop FILLED in
    ~5 trading days). Read-only; fail-open — unknown never counts as unprotected."""
    active: set[str] = set()
    recent: set[str] = set()
    try:
        rows = ex("""SELECT DISTINCT upper(symbol) AS s FROM stop_lifecycle
                     WHERE status IN ('working','open','awaiting_stop_condition','new')""",
                  fetch="all") or []
        active |= {r["s"] for r in rows}
        for tbl in ("fidelity_monitored_stops", "synthetic_stops"):
            try:
                rows = ex(f"""SELECT DISTINCT upper(symbol) AS s FROM {tbl}
                              WHERE COALESCE(status,'active') NOT IN
                              ('canceled','cancelled','filled','removed','inactive','disarmed')""",
                          fetch="all") or []
                active |= {r["s"] for r in rows}
            except Exception:
                continue
        rows = ex("""SELECT DISTINCT upper(symbol) AS s FROM stop_lifecycle
                     WHERE status='filled' AND snapshot_at > now() - interval '7 days'""",
                  fetch="all") or []
        recent = {r["s"] for r in rows}
    except Exception:
        return set(), set()
    return active, recent


def _bars_with_volume(symbol: str, days: int = 400) -> list[dict]:
    """Daily OHLCV. Schwab transport first (has volume); protection-advisor
    _bars() as fallback (its yfinance/proxy paths may drop volume — RVOL is
    fail-soft downstream)."""
    end = dt.date.today()
    start = end - dt.timedelta(days=int(days * 1.5))
    try:
        import schwab_transport as st
        bars = st.get_price_history(symbol, start.isoformat(), end.isoformat(), timeframe="1Day")
        if isinstance(bars, list) and len(bars) >= 30:
            return bars
    except Exception:
        pass
    try:
        import holding_protection_advisor as hpa
        return hpa._bars(symbol, days=days) or []
    except Exception:
        return []


def _sma(vals: list[float], n: int) -> float | None:
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def _broker_indicators(symbols: list[str]) -> dict[str, dict]:
    """Try indicator_snapshot broker for RSI/ATR/RVOL/SMA. Returns {SYM: {rsi14, atr14, rvol_session, sma50, sma200}}."""
    out: dict[str, dict] = {}
    try:
        from lib.data_broker.indicator_snapshot import get_indicator_snapshot
        snap = get_indicator_snapshot(symbols)
        for sym in symbols:
            s = sym.upper()
            d = snap.get(s, {}) or {}
            entry = {}
            if d.get("rsi_14") is not None:
                entry["rsi14"] = float(d["rsi_14"])
            if d.get("atr_14") is not None:
                entry["atr14"] = float(d["atr_14"])
            if d.get("rvol_session") is not None:
                entry["rvol20"] = float(d["rvol_session"])
            if d.get("sma_50") is not None:
                entry["sma50"] = float(d["sma_50"])
            if d.get("sma_200") is not None:
                entry["sma200"] = float(d["sma_200"])
            if entry:
                out[sym] = entry
    except Exception:
        pass
    return out


def compute_metrics(bars: list[dict], symbol: str | None = None,
                    broker: dict | None = None) -> dict[str, Any] | None:
    """Per-holding metrics. Broker indicators have priority; bars are fallback."""
    closes = [float(b.get("close") or b.get("c") or 0) for b in bars]
    highs = [float(b.get("high") or b.get("h") or 0) for b in bars]
    lows = [float(b.get("low") or b.get("l") or 0) for b in bars]
    opens = [float(b.get("open") or b.get("o") or 0) for b in bars]
    vols = [float(b.get("volume") or b.get("v") or 0) for b in bars]
    closes = [c for c in closes if c > 0]
    if len(closes) < 30:
        return None
    price = closes[-1]
    if symbol:
        try:
            from market_quote_provider import get_best_quote
            q = get_best_quote(symbol) or {}
            live = q.get("last_price")
            if live and float(live) > 0:
                price = float(live)
        except Exception:
            pass

    b = broker or {}
    sym_key = (symbol or "").upper()

    # RSI/ATR/RVOL/SMA from broker (canonical), fall back to local bars
    rsi14 = b.get(sym_key, {}).get("rsi14") if b else None
    atr14 = b.get(sym_key, {}).get("atr14") if b else None
    rvol20 = b.get(sym_key, {}).get("rvol20") if b else None
    sma50_b = b.get(sym_key, {}).get("sma50") if b else None
    sma200_b = b.get(sym_key, {}).get("sma200") if b else None

    if rsi14 is None:
        gains = losses = 0.0
        for i in range(-14, 0):
            d = closes[i] - closes[i - 1]
            gains += max(d, 0)
            losses += max(-d, 0)
        rsi14 = round(100 - 100 / (1 + (gains / losses)), 1) if losses else 100.0

    if atr14 is None:
        trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
               for i in range(-14, 0)] if len(closes) >= 15 else []
        atr14 = (sum(trs) / len(trs)) if trs else None

    sma50 = sma50_b if sma50_b is not None else _sma(closes, 50)
    sma200 = sma200_b if sma200_b is not None else _sma(closes, 200)
    ext50 = round((price - sma50) / atr14, 2) if (sma50 and atr14) else None
    ext200 = round((price - sma200) / atr14, 2) if (sma200 and atr14) else None

    if rvol20 is None:
        have_vol = len([v for v in vols if v > 0]) >= 21
        rvol20 = round(vols[-1] / (sum(vols[-21:-1]) / 20), 2) if have_vol and sum(vols[-21:-1]) > 0 else None

    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            streak += 1
        else:
            break

    gain_5d = round(100.0 * (closes[-1] / closes[-6] - 1), 2) if len(closes) >= 6 else None

    gap_ups_5d = None
    if atr14 and len(opens) >= 6 and all(o > 0 for o in opens[-5:]):
        gap_ups_5d = sum(
            1 for i in range(-5, 0)
            if opens[i] > closes[i - 1] + 1.5 * atr14
        )

    def _slope(idx_end: int) -> float | None:
        # SMA20 slope over 5 bars ending at idx_end (negative python index)
        s_now = _sma(closes[:len(closes) + idx_end + 1], 20)
        s_then = _sma(closes[:len(closes) + idx_end - 4], 20)
        if s_now is None or s_then is None:
            return None
        return (s_now - s_then) / 5.0
    slope_recent = _slope(-1)
    slope_prior = _slope(-11)
    slope_accel = None
    if slope_recent is not None and slope_prior not in (None, 0):
        if abs(slope_prior) > 1e-9:
            slope_accel = round(slope_recent / slope_prior, 2)

    hwm_52w = max(closes[-252:]) if len(closes) >= 60 else None

    return {
        "price": round(price, 4), "atr14": round(atr14, 4) if atr14 else None,
        "rsi14": rsi14, "sma50": round(sma50, 4) if sma50 else None,
        "sma200": round(sma200, 4) if sma200 else None,
        "ext50_atr": ext50, "ext200_atr": ext200, "rvol20": rvol20,
        "up_streak": streak, "gain_5d_pct": gain_5d, "gap_ups_5d": gap_ups_5d,
        "slope_accel": slope_accel, "bars_n": len(closes),
        "hwm_52w": round(hwm_52w, 4) if hwm_52w else None,
        "volume_available": have_vol,
    }


def parabolic_score(m: dict, cfg: dict) -> float:
    """Weighted 0–100 score. Missing components (e.g. RVOL on volume-less
    fallback bars) RENORMALIZE the remaining weights instead of deflating the
    score — never fabricate the missing input (amended-build delta 4)."""
    w = cfg["weights"]
    n = cfg["normalize"]

    def clamp(x: float) -> float:
        return max(0.0, min(1.0, x))

    comps: list[tuple[float, float]] = []  # (weight, normalized value)
    if m.get("ext50_atr") is not None:
        comps.append((w["ext50_atr"], clamp(m["ext50_atr"] / n["ext50_atr_max"])))
    if m.get("rsi14") is not None:
        comps.append((w["rsi14"], clamp((m["rsi14"] - n["rsi_lo"]) / (n["rsi_hi"] - n["rsi_lo"]))))
    if m.get("rvol20") is not None:
        comps.append((w["rvol20"], clamp(m["rvol20"] / n["rvol_max"])))
    if m.get("up_streak") is not None:
        comps.append((w["up_streak"], clamp(m["up_streak"] / n["up_streak_max"])))
    if m.get("slope_accel") is not None:
        comps.append((w["slope_accel"], clamp((m["slope_accel"] - 1.0) / (n["slope_accel_max"] - 1.0))))
    total_w = sum(c[0] for c in comps)
    if total_w <= 0:
        return 0.0
    full_w = sum(v for v in w.values() if isinstance(v, (int, float)))
    return round(full_w * sum(wi * xi for wi, xi in comps) / total_w, 1)


def classify(m: dict, *, score: float, weight_pct: float, open_gain_pct: float | None,
             giveback_frac: float | None, basis_known: bool, provisional_hwm: bool,
             cfg: dict, no_raise_stop: bool = False,
             no_raise_stop_reason: str | None = None) -> dict[str, Any]:
    ext_cfg, gb, trim = cfg["extension"], cfg["giveback"], cfg["trim"]
    ext_state = "NORMAL"
    if score >= ext_cfg["climax_score"] and (m.get("rvol20") or 0) >= ext_cfg["climax_rvol_min"]:
        ext_state = "CLIMAX_RISK"
    elif score >= ext_cfg["extended_score"]:
        ext_state = "EXTENDED"

    gb_state = None
    if basis_known and open_gain_pct is not None and giveback_frac is not None \
            and open_gain_pct >= gb["min_open_gain_pct"]:
        breach_at = gb["breach_frac_big_weight"] if weight_pct >= gb["big_weight_pct"] else gb["breach_frac"]
        if giveback_frac >= breach_at:
            gb_state = "GIVEBACK_BREACH"
        elif giveback_frac >= gb["watch_frac"]:
            gb_state = "GIVEBACK_WATCH"

    advisory, severity = None, None
    frac = trim["fraction_big_weight"] if weight_pct >= gb["big_weight_pct"] else trim["fraction_default"]
    if gb_state == "GIVEBACK_BREACH":
        advisory, severity = "TRIM_ADVISORY+RAISE_STOP_ADVISORY", "urgent"
    elif ext_state == "CLIMAX_RISK":
        advisory, severity = "TRIM_ADVISORY", "high"
    elif ext_state == "EXTENDED":
        advisory, severity = "RAISE_STOP_ADVISORY", "normal"
    elif gb_state == "GIVEBACK_WATCH":
        advisory, severity = "REVIEW", "normal"

    notes = []
    # Amended-build delta: unstoppable funds (can't carry a broker stop) and
    # names that JUST stopped out never get RAISE_STOP — TRIM/REVIEW only
    if advisory and "RAISE_STOP" in advisory and no_raise_stop:
        if advisory == "RAISE_STOP_ADVISORY":
            advisory, severity = "REVIEW", "normal"
        else:  # combined breach advisory keeps the trim leg
            advisory = "TRIM_ADVISORY"
        notes.append(no_raise_stop_reason or "RAISE_STOP suppressed")
    if advisory and provisional_hwm:
        # Provisional HWMs never escalate above REVIEW
        if advisory != "REVIEW":
            notes.append(f"provisional HWM — downgraded from {advisory}")
        advisory, severity = "REVIEW", "normal"
    if not basis_known:
        notes.append("basis unknown — gain-based advisories suppressed")

    return {
        "extension_state": ext_state, "giveback_state": gb_state,
        "advisory": advisory, "severity": severity,
        "suggested_trim_fraction": frac if advisory and "TRIM" in (advisory or "") else None,
        "notes": notes,
    }


def latest_protection_rec(ex, symbol: str) -> str | None:
    """Cite the protection advisor's most recent stop rec instead of recomputing."""
    try:
        r = ex(
            """SELECT topic, created_at FROM hermes_research_intelligence
               WHERE research_type='protection_advisory' AND upper(symbol)=%s
               ORDER BY created_at DESC LIMIT 1""",
            (symbol,), fetch="one",
        )
        if r:
            return f"see protection_advisory '{(r['topic'] or '')[:80]}' ({str(r['created_at'])[:10]})"
    except Exception:
        pass
    return None


def run(*, apply: bool, shadow: bool, symbols: set[str] | None, limit: int, json_out: bool) -> int:
    cfg = _load_cfg()
    ex = _db()
    total_before, n_before = _iron_rule()
    for stmt in DDL.strip().split(";"):
        if stmt.strip():
            ex(stmt, fetch="none")

    published = bool(cfg.get("published")) and not shadow
    holds = _holdings(cfg, symbols)

    # Priority ordering (2026-07-16 morning brief): unprotected large positions
    # with open gains first — the $355K no-stop cohort is the population this
    # engine exists for. Then everything else by position value.
    active_stops, recently_stopped = _stop_state(ex)

    # ── Fetch broker indicators once for all symbols (2026-08-01: RSI/ATR/RVOL via broker) ──
    all_symbols = [h["symbol"] for h in holds if h.get("symbol")]
    broker_inds = _broker_indicators(all_symbols) if all_symbols else {}
    if broker_inds:
        print(f"  [guardian] Broker indicators available for {len(broker_inds)}/{len(all_symbols)} symbols")

    def _rough_gain_pct(h: dict) -> float:
        try:
            cb = float(h.get("holdings_cost_basis") or 0)
            if cb > 0:
                return 100.0 * (h["market_value"] - cb) / cb
        except (TypeError, ValueError):
            pass
        return 0.0

    def _prio(h: dict):
        unprotected_large = (
            h["symbol"] not in active_stops
            and h["market_value"] >= 10_000
            and _rough_gain_pct(h) >= 15.0
        )
        return (0 if unprotected_large else 1, -h["market_value"])
    holds.sort(key=_prio)
    if limit:
        holds = holds[:limit]

    hwm_rows = {
        (r["symbol"], r["account"]): r
        for r in (ex("SELECT * FROM holding_high_water_marks", fetch="all") or [])
    }

    results, provisional_n = [], 0
    for h in holds:
        sym, acct = h["symbol"], h["account"]
        bars = _bars_with_volume(sym)
        m = compute_metrics(bars, sym, broker=broker_inds) if bars else None
        if not m:
            results.append({"symbol": sym, "account": acct, "skip": "no_bars"})
            continue

        basis, basis_source = None, None
        try:
            ac = float(h.get("holdings_avg_cost") or 0)
            if ac <= 0 and float(h.get("holdings_cost_basis") or 0) > 0 and h["shares"] > 0:
                ac = float(h["holdings_cost_basis"]) / h["shares"]
            if ac > 0:
                basis, basis_source = ac, "holdings_json"
        except (TypeError, ValueError):
            pass
        if not basis:
            basis = _lots_basis(ex, sym, acct)
            basis_source = "lots" if basis else None
        basis_known = basis is not None and basis > 0
        if not basis_known:
            basis_source = "basis_unknown"

        # HWM: ratchet-only; seeded from bar history (lots have no dates — verified).
        # seeded_from='bars_<n>d' is honest about the anchor: "peak over trailing
        # <window>", never "peak since purchase" (amended-build delta 1).
        prev = hwm_rows.get((sym, acct))
        if prev and prev.get("hwm_price"):
            hwm = float(prev["hwm_price"])
            seeded_from = prev.get("seeded_from") or f"bars_{min(int(m.get('bars_n') or 252), 252)}d"
        elif m.get("hwm_52w"):
            hwm = float(m["hwm_52w"])
            seeded_from = f"bars_{min(int(m.get('bars_n') or 252), 252)}d"
        else:
            hwm, seeded_from = float(m["price"]), "provisional"
        hwm = max(hwm, float(m["price"]))
        if seeded_from == "provisional":
            provisional_n += 1

        open_gain_pct = round(100.0 * (m["price"] - basis) / basis, 2) if basis_known else None
        giveback_frac = None
        if basis_known and hwm > basis:
            giveback_frac = round((hwm - m["price"]) / (hwm - basis), 3)

        if not m.get("volume_available"):
            m["rvol_note"] = "n/a (no volume on fallback bars)"
        score = parabolic_score(m, cfg)
        nrs_reason = None
        try:
            import holding_family as _hf
            if _hf.is_unstoppable_fund(sym):
                nrs_reason = "unstoppable fund (no broker stop possible) — TRIM/REVIEW only"
        except Exception:
            pass
        if not nrs_reason and sym in recently_stopped:
            nrs_reason = "stopped out within ~5 trading days — no stop advice on a just-stopped name"
        cls = classify(
            m, score=score, weight_pct=h["weight_pct"], open_gain_pct=open_gain_pct,
            giveback_frac=giveback_frac, basis_known=basis_known,
            provisional_hwm=(seeded_from == "provisional"), cfg=cfg,
            no_raise_stop=bool(nrs_reason), no_raise_stop_reason=nrs_reason,
        )
        if sym not in active_stops:
            cls["notes"].append("no active stop on file — priority cohort")
        if cls.get("advisory") == "RAISE_STOP_ADVISORY" or "RAISE_STOP" in (cls.get("advisory") or ""):
            cite = latest_protection_rec(ex, sym)
            if cite:
                cls["notes"].append(cite)

        row = {
            "symbol": sym, "account": acct, "weight_pct": h["weight_pct"],
            "basis_ps": round(basis, 4) if basis_known else None,
            "basis_source": basis_source, "seeded_from": seeded_from,
            "hwm_price": round(hwm, 4), "open_gain_pct": open_gain_pct,
            "giveback_frac": giveback_frac, "parabolic_score": score,
            **{k: m.get(k) for k in ("price", "ext50_atr", "ext200_atr", "rsi14", "rvol20",
                                     "up_streak", "gain_5d_pct", "gap_ups_5d", "slope_accel")},
            **cls,
        }
        results.append(row)

        if apply:
            ex(
                """INSERT INTO holding_high_water_marks
                   (symbol, account, hwm_price, hwm_date, basis_ps, basis_source, seeded_from, updated_at)
                   VALUES (%s,%s,%s,CURRENT_DATE,%s,%s,%s,NOW())
                   ON CONFLICT (symbol, account) DO UPDATE SET
                     hwm_price = GREATEST(holding_high_water_marks.hwm_price, EXCLUDED.hwm_price),
                     hwm_date = CASE WHEN EXCLUDED.hwm_price > holding_high_water_marks.hwm_price
                                     THEN CURRENT_DATE ELSE holding_high_water_marks.hwm_date END,
                     basis_ps = EXCLUDED.basis_ps, basis_source = EXCLUDED.basis_source,
                     updated_at = NOW()""",
                (sym, acct, row["hwm_price"], row["basis_ps"], basis_source, seeded_from),
                fetch="none",
            )
            ex(
                """INSERT INTO holding_exit_metrics
                   (symbol, account, price, weight_pct, ext50_atr, ext200_atr, rsi14, rvol20,
                    up_streak, gain_5d_pct, gap_ups_5d, slope_accel, open_gain_pct, giveback_frac,
                    parabolic_score, extension_state, giveback_state, advisory, severity,
                    basis_source, seeded_from, metrics)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (sym, acct, m["price"], h["weight_pct"], m["ext50_atr"], m["ext200_atr"],
                 m["rsi14"], m["rvol20"], m["up_streak"], m["gain_5d_pct"], m["gap_ups_5d"],
                 m["slope_accel"], open_gain_pct, giveback_frac, score,
                 cls["extension_state"], cls["giveback_state"], cls["advisory"], cls["severity"],
                 basis_source, seeded_from, json.dumps({**m, **cls}, default=str)),
                fetch="none",
            )

    ok_rows = [r for r in results if not r.get("skip")]
    prov_pct = 100.0 * provisional_n / max(1, len(ok_rows))
    if prov_pct > 50:
        print(f"⚠ FLAG-BACK: {prov_pct:.0f}% of book HWMs are provisional — "
              f"stop before trusting giveback thresholds", file=sys.stderr)

    if published and apply:
        try:
            from lib.gain_guardian_publish import publish_run
            publish_run(results=ok_rows, cfg=cfg, db_execute=ex)
        except Exception as e:  # publication must never corrupt the metrics run
            print(f"[publish] failed: {e}", file=sys.stderr)

    _iron_rule()  # after: state file untouched by us, but verify anyway

    fired = [r for r in ok_rows if r.get("advisory")]
    summary = {
        "ok": True, "apply": apply, "published": published,
        "holdings_scanned": len(ok_rows), "skipped": len(results) - len(ok_rows),
        "provisional_hwm_pct": round(prov_pct, 1),
        "advisories": len(fired),
        "iron_rule": {"total_value": total_before, "holdings": n_before},
    }
    if json_out:
        print(json.dumps({"summary": summary, "rows": results}, indent=2, default=str))
    else:
        print(f"[gain-guardian] scanned={summary['holdings_scanned']} "
              f"advisories={summary['advisories']} apply={apply} published={published} "
              f"provisional={summary['provisional_hwm_pct']}%")
        for r in sorted(ok_rows, key=lambda x: -(x.get("parabolic_score") or 0))[:15]:
            print(f"  {r['symbol']:6} {r['account'][:16]:16} score={r['parabolic_score']:5} "
                  f"ext50={r.get('ext50_atr')} rsi={r.get('rsi14')} rvol={r.get('rvol20')} "
                  f"gain={r.get('open_gain_pct')}% gb={r.get('giveback_frac')} "
                  f"[{r['extension_state']}{('/' + r['giveback_state']) if r.get('giveback_state') else ''}] "
                  f"{r.get('advisory') or ''}")
    return 0


def promote() -> int:
    cfg = _load_cfg()
    cfg["published"] = True
    cfg["promoted_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("Gain Guardian PROMOTED — publication enabled (config published=true). "
          "Review the shadow report before trusting the first digest.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Persist metrics + HWM ratchet")
    ap.add_argument("--dry-run", action="store_true", help="Default — compute and print only")
    ap.add_argument("--shadow", action="store_true", help="Force no publication even if promoted")
    ap.add_argument("--symbols", default="", help="Comma list, e.g. V,SCHG")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--promote", action="store_true", help="Operator: enable publication after shadow window")
    ap.add_argument("--test-render", metavar="SYMBOL",
                    help="Render one chart PNG + print the digest text — ZERO writes/sends")
    args = ap.parse_args()
    if args.promote:
        return promote()
    if args.test_render:
        from lib.gain_guardian_publish import render_chart, digest_text
        sym = args.test_render.upper()
        path = render_chart(sym, _bars_with_volume(sym, days=200))
        print(f"chart: {path or 'RENDER FAILED'}")
        print(digest_text([{
            "symbol": sym, "extension_state": "CLIMAX_RISK", "giveback_state": None,
            "parabolic_score": 81.0, "open_gain_pct": 42.0, "giveback_frac": 0.18,
            "advisory": "TRIM_ADVISORY", "severity": "high",
        }]))
        return 0
    syms = {s.strip().upper() for s in args.symbols.split(",") if s.strip()} or None
    return run(apply=bool(args.apply and not args.dry_run), shadow=args.shadow,
               symbols=syms, limit=args.limit, json_out=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
