#!/usr/bin/env python3
"""pullback_macd_screener.py — S&P 500 uptrend + ~20% pullback + approaching-MACD-cross screen.

Daily post-close scan. For each S&P 500 name:
  uptrend (px>SMA200, SMA50>SMA200 rising) → pullback band (off 52w high) → MACD approaching
  bullish cross (hist<0 rising, within proximity of signal). Two tiers: 'trigger' / 'watch'.

Outputs (all advisory; nothing auto-executes):
  1. pullback_macd_candidates table + /api/v2/pullback-macd/candidates + Command Center screen
  2. Telegram alert on NEW triggers
  3. candidate/incubator pipeline feed (ticker_strategy_classifications + watchlist_items)
  4. advisory proposals into paper_trade_proposals (operator approval queue) for configured tiers

Usage:
  python3 scripts/pullback_macd_screener.py [--dry-run] [--limit N] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ── env ───────────────────────────────────────────────────────────────────────────────
def _load_env() -> None:
    """Load the full .env into os.environ. db_adapter only loads DB_* keys, so without this
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are absent under cron (no shell profile) and alerts
    silently skip. Mirrors alert_dispatcher_unified._load_env."""
    p = PROJECT_ROOT / ".env"
    if not p.exists():
        return
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))
    except Exception:
        pass


# ── config ────────────────────────────────────────────────────────────────────────────
def load_cfg() -> dict:
    try:
        from config_db_loader import get_config
        c = get_config("pullback_macd_screener",
                       fallback_path="config/pullback_macd_screener.yaml")
        if c:
            return c.get("pullback_macd_screener", c)
    except Exception:
        pass
    try:
        import yaml
        d = yaml.safe_load((PROJECT_ROOT / "config" / "pullback_macd_screener.yaml").read_text())
        return (d or {}).get("pullback_macd_screener", {})
    except Exception:
        return {}


def _db(sql, params=None, fetch=None):
    from db_adapter import _execute
    return _execute(sql, params, fetch=fetch)


# ── indicators (pandas-native; no pandas_ta dependency) ─────────────────────────────────
def _macd(close: pd.Series, fast: int, slow: int, sig: int):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    line = ema_f - ema_s
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal


def _rsi(close: pd.Series, period: int) -> float:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def _atr(df: pd.DataFrame, period: int) -> float:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1])


# ── universe ────────────────────────────────────────────────────────────────────────────
def _refresh_universe() -> list[str]:
    """Fetch S&P 500 constituents (datahub CSV primary) and upsert sp500_constituents."""
    syms: list[tuple] = []
    try:
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        txt = urllib.request.urlopen(req, timeout=20).read().decode()
        df = pd.read_csv(pd.io.common.StringIO(txt))
        for _, r in df.iterrows():
            syms.append((str(r["Symbol"]).replace(".", "-").upper(),
                         str(r.get("Security") or ""), str(r.get("GICS Sector") or "")))
    except Exception as e:
        print(f"  [universe] fetch failed ({str(e)[:60]}); using existing table")
        rows = _db("SELECT symbol FROM sp500_constituents WHERE active", fetch="all") or []
        return [r["symbol"] for r in rows]
    for sym, name, sector in syms:
        _db("""INSERT INTO sp500_constituents (symbol, name, sector, active, last_seen_at)
               VALUES (%s,%s,%s,TRUE,NOW())
               ON CONFLICT (symbol) DO UPDATE SET
                 name=EXCLUDED.name, sector=EXCLUDED.sector, active=TRUE, last_seen_at=NOW()""",
            (sym, name, sector))
    fetched = {s[0] for s in syms}
    if fetched:
        _db("UPDATE sp500_constituents SET active=FALSE WHERE symbol <> ALL(%s)", (list(fetched),))
    return sorted(fetched)


def _load_universe(dry: bool) -> list[str]:
    rows = _db("SELECT symbol FROM sp500_constituents WHERE active", fetch="all") or []
    if rows and dry:
        return [r["symbol"] for r in rows]
    return _refresh_universe()


# ── scan ────────────────────────────────────────────────────────────────────────────────
def _evaluate(sym: str, df: pd.DataFrame, cfg: dict) -> dict | None:
    df = df.dropna()
    if len(df) < int(cfg.get("min_bars", 205)):
        return None
    close = df["Close"].astype(float)
    px = float(close.iloc[-1])
    sma_f = close.rolling(int(cfg["sma_fast"])).mean()
    sma_s = close.rolling(int(cfg["sma_slow"])).mean()
    s_f, s_s = float(sma_f.iloc[-1]), float(sma_s.iloc[-1])
    if not (s_f > 0 and s_s > 0):
        return None
    line, signal, hist = _macd(close, int(cfg["macd_fast"]), int(cfg["macd_slow"]), int(cfg["macd_signal"]))
    h = hist.dropna()
    hi = float(close.tail(int(cfg.get("lookback_high_days", 252))).max())
    pull = (hi - px) / hi * 100.0 if hi > 0 else 0.0

    rising_n = int(cfg.get("hist_rising_bars", 2))
    rising = len(h) > rising_n and all(float(h.iloc[-1 - i]) > float(h.iloc[-2 - i]) for i in range(rising_n))
    below = float(line.iloc[-1]) < float(signal.iloc[-1])
    neg_hist = float(h.iloc[-1]) < 0
    prox = abs(float(h.iloc[-1])) / px * 100.0 if px else 999.0
    prox_ok = prox <= float(cfg.get("macd_proximity_pct", 0.6))

    rising_sma = (not cfg.get("require_sma50_rising", True)) or \
        s_f > float(sma_f.iloc[-1 - int(cfg.get("sma50_rising_lookback", 5))])
    uptrend = px > s_s and s_f > s_s and rising_sma
    in_pullback = float(cfg["pullback_min_pct"]) <= pull <= float(cfg["pullback_max_pct"])

    # EARLIEST confirmed recovery: the MACD histogram has turned up off the pullback trough — rising
    # for hist_rising_bars while still negative and below the signal line (pre-cross). This fires at
    # the momentum inflection, not when the cross is imminent. Proximity to the cross is a SCORE input
    # by default (set macd_require_proximity to also gate on it — later, but tighter).
    require_prox = bool(cfg.get("macd_require_proximity", False))
    macd_recovering = below and neg_hist and rising
    approaching = macd_recovering and (prox_ok or not require_prox)

    if cfg.get("rsi_confirm"):
        if _rsi(close, int(cfg.get("rsi_period", 14))) > float(cfg.get("rsi_max", 50)):
            approaching = False

    if not (uptrend and in_pullback):
        return {"sym": sym, "skip": True}  # not even in the watch funnel

    # why-not (watch tier diagnostics)
    why = []
    if not below: why.append("already crossed")
    if not neg_hist: why.append("hist>0")
    if not rising: why.append("hist not turning up yet")
    if require_prox and not prox_ok: why.append(f"prox {prox:.2f}>{cfg['macd_proximity_pct']}")
    tier = "trigger" if approaching else "watch"

    atr = _atr(df, int(cfg.get("atr_period", 14)))
    entry = round(px, 2)
    # Authoritative TECHNICAL levels (not generic R:R geometry — passes broker_trade_plan_gate):
    #   stop   = recent swing low (the pullback's support); just under it
    #   target = retrace toward the 52-week high (the resistance the name pulled back from)
    swing_low = float(df["Low"].tail(int(cfg.get("swing_low_lookback", 10))).min())
    stop = round(swing_low * 0.999, 2)
    if stop >= entry:  # price sitting on a fresh low → fall back to an ATR buffer
        stop = round(entry - max(float(cfg.get("stop_atr_mult", 1.5)) * atr, 0.01), 2)
    frac = float(cfg.get("target_retrace_frac", 1.0))   # 1.0 = full retrace to the 52w high
    target1 = round(entry + frac * (hi - entry), 2)
    risk = max(entry - stop, 0.01)
    rr = round((target1 - entry) / risk, 2)
    slope = float(h.iloc[-1]) - float(h.iloc[-2])
    bars = round(abs(float(h.iloc[-1]) / slope), 1) if slope > 0 else None
    trend_pct = round((s_f / s_s - 1) * 100, 2)
    score = round(100 - prox / max(float(cfg["macd_proximity_pct"]), 0.01) * 30
                  - abs(pull - float(cfg.get("pullback_target_pct", 20))) * 1.5 + trend_pct, 1)

    return {
        "sym": sym, "tier": tier, "macd_approaching": approaching,
        "price": entry, "pullback_pct": round(pull, 1),
        "trend_pct": trend_pct, "macd_prox_pct": round(prox, 3),
        "hist_rising_bars": rising_n if rising else 0, "bars_to_cross_est": bars,
        "atr": round(atr, 3), "entry": entry, "stop": stop, "target1": target1, "rr": rr,
        "score": score, "why_not": ", ".join(why), "skip": False,
    }


def _session_vwap(syms: list[str]) -> dict:
    """Intraday session VWAP for a small set of symbols (the daily-screen survivors), via 5-min bars.
    Returns {sym: {vwap, last, above_vwap, dist_pct}}. Daily bars can't give VWAP, so this is a
    separate light intraday pull used only as an entry-timing confirmation."""
    out: dict = {}
    if not syms:
        return out
    try:
        import yfinance as yf
        data = yf.download(syms, period="1d", interval="5m", group_by="ticker",
                           threads=True, progress=False, auto_adjust=False)
    except Exception:
        return out
    for s in syms:
        try:
            df = (data[s] if len(syms) > 1 else data).dropna()
            if df.empty or df["Volume"].sum() <= 0:
                continue
            tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
            vwap = float((tp * df["Volume"]).cumsum().iloc[-1] / df["Volume"].cumsum().iloc[-1])
            last = float(df["Close"].iloc[-1])
            if vwap <= 0:
                continue
            out[s] = {"vwap": round(vwap, 2), "last": round(last, 2),
                      "above_vwap": last >= vwap, "dist_pct": round((last / vwap - 1) * 100, 2)}
        except Exception:
            continue
    return out


def _fetch_all(syms: list[str]) -> dict:
    import yfinance as yf
    data = yf.download(syms, period="2y", interval="1d", group_by="ticker",
                       threads=True, progress=False, auto_adjust=True)
    out = {}
    multi = isinstance(data.columns, pd.MultiIndex)
    for s in syms:
        try:
            # group_by="ticker" yields MultiIndex columns even for a single-symbol list — select the
            # ticker level so callers always get flat OHLCV columns.
            out[s] = data[s] if multi and s in data.columns.get_level_values(0) else data
        except Exception:
            pass
    return out


# ── outputs ─────────────────────────────────────────────────────────────────────────────
def _persist_candidates(cands: list[dict], scan_d: date) -> None:
    seen = []
    for c in cands:
        seen.append(c["sym"])
        prev = _db("SELECT tier FROM pullback_macd_candidates WHERE symbol=%s", (c["sym"],), fetch="one")
        prev_tier = prev["tier"] if prev else None
        _db("""INSERT INTO pullback_macd_candidates
                 (symbol, tier, prev_tier, price, pullback_pct, trend_pct, macd_prox_pct,
                  hist_rising_bars, bars_to_cross_est, atr, entry, stop, target1, rr, score,
                  why_not, vwap, above_vwap, vwap_dist_pct, payload, status, scan_date, last_scan_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'active',%s,NOW())
               ON CONFLICT (symbol) DO UPDATE SET
                 prev_tier=pullback_macd_candidates.tier, tier=EXCLUDED.tier,
                 price=EXCLUDED.price, pullback_pct=EXCLUDED.pullback_pct, trend_pct=EXCLUDED.trend_pct,
                 macd_prox_pct=EXCLUDED.macd_prox_pct, hist_rising_bars=EXCLUDED.hist_rising_bars,
                 bars_to_cross_est=EXCLUDED.bars_to_cross_est, atr=EXCLUDED.atr, entry=EXCLUDED.entry,
                 stop=EXCLUDED.stop, target1=EXCLUDED.target1, rr=EXCLUDED.rr, score=EXCLUDED.score,
                 why_not=EXCLUDED.why_not, vwap=EXCLUDED.vwap, above_vwap=EXCLUDED.above_vwap,
                 vwap_dist_pct=EXCLUDED.vwap_dist_pct, payload=EXCLUDED.payload, status='active',
                 scan_date=EXCLUDED.scan_date, last_scan_at=NOW()""",
            (c["sym"], c["tier"], prev_tier, c["price"], c["pullback_pct"], c["trend_pct"],
             c["macd_prox_pct"], c["hist_rising_bars"], c["bars_to_cross_est"], c["atr"],
             c["entry"], c["stop"], c["target1"], c["rr"], c["score"], c["why_not"],
             c.get("vwap"), c.get("above_vwap"), c.get("vwap_dist_pct"),
             json.dumps(c), scan_d))
        c["_prev_tier"] = prev_tier
    # mark anything not in this scan as stale
    if seen:
        _db("UPDATE pullback_macd_candidates SET status='stale' WHERE symbol <> ALL(%s) AND status='active'",
            (seen,))


def _write_trade_plan(c: dict, strat: str, shares: int, dollar_size: float, dollar_risk: float) -> int | None:
    """Write an authoritative trade_plans row (technical entry/stop/target). broker_trade_plan_gate
    resolves this by symbol and treats the levels as authoritative — clearing the 'no authoritative
    trade plan / R:R-math-only (gambling blocked)' route block. Replaces this screener's prior plan."""
    stop_pct = round((c["entry"] - c["stop"]) / c["entry"] * 100, 2) if c["entry"] else 0.0
    _db("DELETE FROM trade_plans WHERE symbol=%s AND generated_by='pullback_macd_screener'", (c["sym"],))
    row = _db("""INSERT INTO trade_plans
                   (strategy_id, symbol, entry_low, entry_high, stop_loss, stop_pct, target_1,
                    risk_reward_1, shares, dollar_size, dollar_risk, atr_value, disqualified,
                    generated_at, generated_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,NOW(),'pullback_macd_screener')
                 RETURNING id""",
              (strat, c["sym"], c["entry"], c["entry"], c["stop"], stop_pct, c["target1"],
               c["rr"], shares, dollar_size, dollar_risk, c.get("atr")), fetch="one")
    return row["id"] if row else None


def _emit_proposals(cands: list[dict], cfg: dict) -> int:
    tiers = set(cfg.get("proposal_tiers") or ["trigger"])
    notional = float(cfg.get("proposal_notional_usd", 5000))
    strat = cfg.get("default_strategy_id", "pullback_macd_reversal")
    exp_h = int(cfg.get("proposal_expiry_hours", 48))
    cap = int(cfg.get("max_proposals_per_scan", 5))
    # Tier-eligible, highest-score first, hard-capped. Each PENDING proposal spawns local+cloud LLM
    # oversight, so the cap bounds load when many names trigger at once. Dropped names still appear
    # on the tab + feed the pipeline.
    eligible = sorted([c for c in cands if c["tier"] in tiers], key=lambda x: -x.get("score", 0))
    if len(eligible) > cap:
        print(f"  [proposals] capping {len(eligible)} eligible → {cap} (max_proposals_per_scan); "
              f"rest stay on tab/pipeline only")
        eligible = eligible[:cap]
    cols = _db("""SELECT column_name FROM information_schema.columns
                  WHERE table_name='paper_trade_proposals'""", fetch="all") or []
    avail = {r["column_name"] for r in cols}
    n = 0
    for c in eligible:
        shares = max(1, int(notional / max(c["entry"], 0.01)))
        risk = round(shares * (c["entry"] - c["stop"]), 2)
        dollar_size = round(shares * c["entry"], 2)
        # Authoritative plan first, so the gate sees real technical levels for this symbol.
        _write_trade_plan(c, strat, shares, dollar_size, risk)
        # If an active proposal already exists, refresh its levels to match the authoritative plan
        # instead of creating a duplicate.
        dup0 = _db("""SELECT id FROM paper_trade_proposals
                      WHERE symbol=%s AND status='PENDING'
                        AND COALESCE(discovery_source,'')='pullback_macd'""", (c["sym"],), fetch="one")
        if dup0:
            _db("""UPDATE paper_trade_proposals
                   SET proposed_entry=%s, proposed_stop=%s, proposed_target1=%s, proposed_rr=%s,
                       updated_at=NOW()
                   WHERE id=%s""", (c["entry"], c["stop"], c["target1"], c["rr"], dup0["id"]))
            c["proposal_id"] = dup0["id"]
            _db("UPDATE pullback_macd_candidates SET proposal_id=%s WHERE symbol=%s", (dup0["id"], c["sym"]))
            continue
        data = {
            "symbol": c["sym"], "strategy_id": strat,
            "setup_type": f"Pullback {c['pullback_pct']}% + MACD {c['tier']}",
            "signal_score": int(min(99, max(1, c["score"]))), "signal_grade": "B",
            "proposed_entry": c["entry"], "proposed_stop": c["stop"],
            "proposed_target1": c["target1"], "proposed_shares": shares,
            "proposed_dollar_size": round(shares * c["entry"], 2), "proposed_dollar_risk": risk,
            "proposed_rr": c["rr"], "proposed_by": "pullback_macd_screener",
            "status": "PENDING", "discovery_source": "pullback_macd", "origin": "auto",
            "auto_execution_label": "manual", "auto_created": True,
            "risk_gate_result": "ADVISORY",
            "catalyst": f"Uptrend dip-buy: {c['pullback_pct']}% off 52w high, MACD {c['tier']}",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=exp_h)).isoformat(),
        }
        ins = {k: v for k, v in data.items() if k in avail and v is not None}
        cols_str = ", ".join(ins)
        ph = ", ".join(["%s"] * len(ins))
        row = _db(f"INSERT INTO paper_trade_proposals ({cols_str}) VALUES ({ph}) RETURNING id",
                  list(ins.values()), fetch="one")
        if row:
            c["proposal_id"] = row["id"]
            _db("UPDATE pullback_macd_candidates SET proposal_id=%s WHERE symbol=%s", (row["id"], c["sym"]))
            n += 1
    return n


def _feed_pipeline(cands: list[dict], cfg: dict) -> None:
    strat = cfg.get("default_strategy_id", "pullback_macd_reversal")
    for c in cands:
        _db("""INSERT INTO ticker_strategy_classifications
                 (symbol, strategy_type, asset_type, classification_source, confidence, rationale)
               VALUES (%s,%s,'stock','pullback_macd',%s,%s)
               ON CONFLICT (symbol) DO NOTHING""",
            (c["sym"], strat, 0.75 if c["tier"] == "trigger" else 0.6,
             f"Pullback {c['pullback_pct']}% in uptrend, MACD {c['tier']}"))
        _db("""INSERT INTO watchlist_items (symbol, source, status, updated_at)
               VALUES (%s,'pullback_macd','active',NOW())
               ON CONFLICT DO NOTHING""", (c["sym"],))


def _alert_new_triggers(cands: list[dict]) -> None:
    new = [c for c in cands if c["tier"] == "trigger" and c.get("_prev_tier") != "trigger"]
    if not new:
        return
    try:
        from telegram_alert import send_telegram
    except Exception:
        return
    lines = ["📉➡️📈 *Pullback/MACD triggers* (uptrend dip, cross approaching)"]
    for c in sorted(new, key=lambda x: -x["score"])[:10]:
        lines.append(f"• *{c['sym']}*  {c['pullback_pct']}% off high · entry {c['entry']} "
                     f"stop {c['stop']} tgt {c['target1']} (R:R {c['rr']})")
    lines.append("_Advisory — review in approval queue. Nothing auto-executes._")
    try:
        send_telegram("\n".join(lines))
    except Exception:
        pass


def _reconcile_proposals(cands: list[dict]) -> int:
    """Retire PENDING pullback proposals that no longer FIT THE PLAN — run each intraday monitor pass.
    A proposal is expired when the name is no longer a confirmed trigger (MACD/VWAP/pullback no longer
    line up) or live price broke the thesis (<= stop or >= target). Still-fitting ones are refreshed by
    _emit_proposals; this just prunes the ones that fell out so the queue reflects only valid setups."""
    by_sym = {c["sym"]: c for c in cands}
    trig = {c["sym"] for c in cands if c["tier"] == "trigger"}
    rows = _db("""SELECT id, symbol, proposed_stop, proposed_target1 FROM paper_trade_proposals
                  WHERE status='PENDING' AND COALESCE(discovery_source,'')='pullback_macd'""",
               fetch="all") or []
    retired = 0
    for r in rows:
        sym = r["symbol"]
        c = by_sym.get(sym)
        reason = None
        if sym not in trig:
            reason = "no longer a confirmed trigger (MACD inflection / VWAP / pullback no longer fit)"
        elif c:
            px = _f(c.get("price"))
            stop, tgt = _f(r.get("proposed_stop")), _f(r.get("proposed_target1"))
            if px and stop and px <= stop:
                reason = f"plan broken: price {px} at/below stop {stop}"
            elif px and tgt and px >= tgt:
                reason = f"plan complete: price {px} at/above target {tgt}"
        if reason:
            _db("""UPDATE paper_trade_proposals SET status='EXPIRED', rejected_at=NOW(),
                   rejection_reason=%s, updated_at=NOW() WHERE id=%s""",
                (f"pullback monitor: {reason}", r["id"]))
            retired += 1
    return retired


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _adjust_open_trades(cfg: dict) -> dict:
    """While in a trade: produce ADVISORY adjustment guidance for OPEN pullback positions each monitor
    pass — trail the stop up as price advances, flag take-profit at target, flag exit when the thesis
    breaks (lost VWAP or MACD rolling back down). Advisory only: it never modifies a live stop (that
    stays with the operator / ATM stop manager); it writes guidance to pullback_trade_adjustments and
    alerts on actionable changes."""
    strat = cfg.get("default_strategy_id", "pullback_macd_reversal")
    trades = _db("""SELECT pt.id, pt.symbol, pt.entry_price, pt.shares,
                           tp.stop_loss AS plan_stop, tp.target_1 AS plan_target
                    FROM paper_trades pt
                    LEFT JOIN LATERAL (
                      SELECT stop_loss, target_1 FROM trade_plans
                      WHERE symbol = pt.symbol AND generated_by='pullback_macd_screener'
                      ORDER BY generated_at DESC LIMIT 1
                    ) tp ON TRUE
                    WHERE pt.status='open' AND pt.strategy_id=%s""", (strat,), fetch="all") or []
    if not trades:
        return {"open": 0, "actionable": 0}
    syms = sorted({t["symbol"] for t in trades})
    bars = _fetch_all(syms)
    vwap_map = _session_vwap(syms)
    vwap_buf = float(cfg.get("trail_vwap_buffer_pct", 0.5)) / 100.0
    actionable = 0
    for t in trades:
        sym = t["symbol"]
        df = bars.get(sym)
        if df is None or df.dropna().empty:
            continue
        df = df.dropna()
        close = df["Close"].astype(float)
        px = round(float(close.iloc[-1]), 2)
        entry = _f(t["entry_price"])
        plan_stop = _f(t["plan_stop"])
        target = _f(t["plan_target"])
        vw = vwap_map.get(sym) or {}
        vwap = _f(vw.get("vwap")) or None
        above_vwap = vw.get("above_vwap")
        line, signal, hist = _macd(close, int(cfg["macd_fast"]), int(cfg["macd_slow"]), int(cfg["macd_signal"]))
        h = hist.dropna()
        macd_falling = len(h) >= 2 and float(h.iloc[-1]) < float(h.iloc[-2])
        swing_low = float(df["Low"].tail(int(cfg.get("swing_low_lookback", 10))).min())
        in_profit = px > entry

        # Trail the stop UP only: max of plan stop, recent swing low, breakeven (once green),
        # just under VWAP (once green). Never lower an existing stop.
        cands_stop = [plan_stop, round(swing_low * 0.999, 2)]
        if in_profit:
            cands_stop.append(round(entry, 2))                      # breakeven
            if vwap:
                cands_stop.append(round(vwap * (1 - vwap_buf), 2))  # under VWAP
        suggested_stop = round(max([s for s in cands_stop if s > 0] or [plan_stop]), 2)

        unreal = round((px / entry - 1) * 100, 2) if entry else 0.0
        if target and px >= target:
            action, why = "take_profit", f"price {px} at/above target {target} — take profit"
        elif (above_vwap is False) or macd_falling:
            action = "exit_thesis_break"
            why = "lost VWAP" if above_vwap is False else "MACD histogram rolling back down"
            why += f" — defend/exit (live {px}, {unreal:+.1f}%)"
        elif suggested_stop > plan_stop + 0.01:
            action, why = "trail_stop", f"raise stop {plan_stop} → {suggested_stop} (price {px}, {unreal:+.1f}%)"
        else:
            action, why = "hold", f"thesis intact (live {px}, {unreal:+.1f}%, stop {plan_stop}, target {target})"
        is_actionable = action != "hold"
        if is_actionable:
            actionable += 1
        _db("""INSERT INTO pullback_trade_adjustments
                 (trade_id, symbol, entry, current_stop, suggested_stop, target, live_price, vwap,
                  above_vwap, macd_falling, unrealized_pct, action, rationale, actionable, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
               ON CONFLICT (trade_id) DO UPDATE SET
                 current_stop=EXCLUDED.current_stop, suggested_stop=EXCLUDED.suggested_stop,
                 target=EXCLUDED.target, live_price=EXCLUDED.live_price, vwap=EXCLUDED.vwap,
                 above_vwap=EXCLUDED.above_vwap, macd_falling=EXCLUDED.macd_falling,
                 unrealized_pct=EXCLUDED.unrealized_pct, action=EXCLUDED.action,
                 rationale=EXCLUDED.rationale, actionable=EXCLUDED.actionable, updated_at=NOW()""",
            (t["id"], sym, entry, plan_stop, suggested_stop, target or None, px, vwap,
             above_vwap, macd_falling, unreal, action, why, is_actionable))
    return {"open": len(trades), "actionable": actionable}


# ── main ────────────────────────────────────────────────────────────────────────────────
def run(dry: bool = False, limit: int = 0, as_json: bool = False, monitor: bool = False) -> dict:
    t0 = time.time()
    _load_env()
    cfg = load_cfg()
    if not cfg.get("enabled", True):
        return {"ok": False, "reason": "disabled"}
    if monitor:
        # Intraday monitor: only re-evaluate the current active candidate set + any symbols with a
        # standing pullback proposal — cheap enough to run several times a day. The daily pullback
        # universe is set post-close; intraday we watch those names for VWAP/MACD confirmation and
        # keep proposals in sync with the live setup.
        act = _db("SELECT symbol FROM pullback_macd_candidates WHERE status='active'", fetch="all") or []
        pend = _db("""SELECT DISTINCT symbol FROM paper_trade_proposals
                      WHERE status='PENDING' AND COALESCE(discovery_source,'')='pullback_macd'""",
                   fetch="all") or []
        syms = sorted({r["symbol"] for r in act} | {r["symbol"] for r in pend})
        if not syms:
            return {"ok": True, "monitor": True, "note": "no active pullback candidates to monitor"}
    else:
        syms = _load_universe(dry)
    if limit:
        syms = syms[:limit]
    bars = _fetch_all(syms)
    cands, funnel, errors = [], {"uptrend_pullback": 0}, 0
    for s in syms:
        df = bars.get(s)
        if df is None:
            errors += 1
            continue
        try:
            r = _evaluate(s, df, cfg)
        except Exception:
            errors += 1
            continue
        if not r or r.get("skip"):
            continue
        funnel["uptrend_pullback"] += 1
        cands.append(r)

    # VWAP entry-timing confirmation. A TRIGGER requires BOTH the MACD approaching-cross AND price
    # holding above intraday VWAP. MACD-approaching names below VWAP drop to watch (timing not there
    # yet). VWAP is fetched only for the daily-screen survivors (a handful), not the whole universe.
    vwap_required = bool(cfg.get("vwap_trigger", True))
    vwap_map = _session_vwap([c["sym"] for c in cands]) if cands else {}
    for c in cands:
        vw = vwap_map.get(c["sym"])
        if vw:
            c["vwap"], c["above_vwap"], c["vwap_dist_pct"] = vw["vwap"], vw["above_vwap"], vw["dist_pct"]
        else:
            c["vwap"], c["above_vwap"], c["vwap_dist_pct"] = None, None, None
        if not vwap_required:
            continue
        # Final tier: trigger only when MACD-approaching AND confirmed above VWAP.
        if c.get("macd_approaching") and c.get("above_vwap"):
            c["tier"] = "trigger"
        else:
            if c.get("macd_approaching"):  # MACD ok but VWAP not confirmed → demote with reason
                why = [c.get("why_not", "")] if c.get("why_not") else []
                why.append("below VWAP" if c.get("above_vwap") is False else "VWAP unconfirmed")
                c["why_not"] = ", ".join(w for w in why if w)
            c["tier"] = "watch"

    triggers = [c for c in cands if c["tier"] == "trigger"]
    watch = [c for c in cands if c["tier"] == "watch"]
    scan_d = date.today()

    emitted = retired = 0
    adjust = {"open": 0, "actionable": 0}
    if not dry:
        _persist_candidates(cands, scan_d)
        if cfg.get("emit_proposals", True):
            emitted = _emit_proposals(cands, cfg)
        # Keep standing pullback proposals in sync with the live setup: refresh those that still fit
        # (done inside _emit_proposals), expire those that no longer fit the plan.
        if cfg.get("reconcile_proposals", True):
            retired = _reconcile_proposals(cands)
        # While IN a trade: advisory adjustment guidance for open pullback positions (trail / TP / exit).
        if cfg.get("adjust_open_trades", True):
            adjust = _adjust_open_trades(cfg)
        if cfg.get("feed_candidate_pipeline", True) and not monitor:
            _feed_pipeline(cands, cfg)
        if cfg.get("telegram_alerts", True):
            _alert_new_triggers(cands)
        _db("""INSERT INTO pullback_macd_runs
                 (scan_date, universe_count, screened, uptrend_count, pullback_count,
                  trigger_count, watch_count, proposals_emitted, data_errors, duration_s)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (scan_d, len(syms), len(syms) - errors, None, funnel["uptrend_pullback"],
             len(triggers), len(watch), emitted, errors, round(time.time() - t0, 1)))

    summary = {
        "ok": True, "dry_run": dry, "monitor": monitor, "universe": len(syms),
        "in_pullback_uptrend": funnel["uptrend_pullback"],
        "triggers": len(triggers), "watch": len(watch),
        "proposals_emitted": emitted, "proposals_retired": retired,
        "open_trades": adjust["open"], "trade_adjustments": adjust["actionable"], "data_errors": errors,
        "duration_s": round(time.time() - t0, 1),
        "top_triggers": sorted(triggers, key=lambda x: -x["score"])[:15],
        "top_watch": sorted(watch, key=lambda x: x["macd_prox_pct"])[:15],
    }
    if as_json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"\n{'MONITOR ' if monitor else ''}universe={summary['universe']} errors={errors} | "
              f"uptrend+pullback={summary['in_pullback_uptrend']} → "
              f"TRIGGER={summary['triggers']} WATCH={summary['watch']} | "
              f"proposals +{emitted}/-{retired} | open trades {adjust['open']} "
              f"(adjustments {adjust['actionable']}) ({'DRY' if dry else 'written'})")
        print(f"\n{'TIER':<8}{'SYM':<7}{'PULL%':>7}{'PROX%':>7}{'VWAP':>9}{'>VWAP':>6}{'ENTRY':>9}{'STOP':>9}{'TGT':>9}{'R:R':>6}{'SCORE':>7}")
        for c in summary["top_triggers"] + summary["top_watch"][:8]:
            av = "yes" if c.get("above_vwap") else ("no" if c.get("above_vwap") is False else "—")
            print(f"{c['tier']:<8}{c['sym']:<7}{c['pullback_pct']:>7}{c['macd_prox_pct']:>7}"
                  f"{str(c.get('vwap') or '—'):>9}{av:>6}{c['entry']:>9}{c['stop']:>9}{c['target1']:>9}{c['rr']:>6}{c['score']:>7}")
    return summary


def main():
    ap = argparse.ArgumentParser(description="S&P 500 pullback + approaching-MACD-cross screener")
    ap.add_argument("--dry-run", action="store_true", help="compute + print, no DB writes / no proposals / no alerts")
    ap.add_argument("--limit", type=int, default=0, help="limit universe size (testing)")
    ap.add_argument("--monitor", action="store_true",
                    help="intraday monitor: re-evaluate only active candidates + open proposals; refresh "
                         "those that still fit the plan, expire those that don't")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    run(dry=a.dry_run, limit=a.limit, as_json=a.json, monitor=a.monitor)


if __name__ == "__main__":
    main()
