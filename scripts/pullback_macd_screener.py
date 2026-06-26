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
    approaching = below and neg_hist and rising and prox_ok

    if cfg.get("rsi_confirm"):
        if _rsi(close, int(cfg.get("rsi_period", 14))) > float(cfg.get("rsi_max", 50)):
            approaching = False

    if not (uptrend and in_pullback):
        return {"sym": sym, "skip": True}  # not even in the watch funnel

    # why-not (watch tier diagnostics)
    why = []
    if not below: why.append("already crossed")
    if not neg_hist: why.append("hist>0")
    if not rising: why.append("hist falling")
    if not prox_ok: why.append(f"prox {prox:.2f}>{cfg['macd_proximity_pct']}")
    tier = "trigger" if approaching else "watch"

    atr = _atr(df, int(cfg.get("atr_period", 14)))
    entry = round(px, 2)
    stop = round(px - float(cfg.get("stop_atr_mult", 1.5)) * atr, 2)
    risk = max(entry - stop, 0.01)
    target1 = round(entry + float(cfg.get("rr_target", 2.0)) * risk, 2)
    rr = round((target1 - entry) / risk, 2)
    slope = float(h.iloc[-1]) - float(h.iloc[-2])
    bars = round(abs(float(h.iloc[-1]) / slope), 1) if slope > 0 else None
    trend_pct = round((s_f / s_s - 1) * 100, 2)
    score = round(100 - prox / max(float(cfg["macd_proximity_pct"]), 0.01) * 30
                  - abs(pull - float(cfg.get("pullback_target_pct", 20))) * 1.5 + trend_pct, 1)

    return {
        "sym": sym, "tier": tier, "price": entry, "pullback_pct": round(pull, 1),
        "trend_pct": trend_pct, "macd_prox_pct": round(prox, 3),
        "hist_rising_bars": rising_n if rising else 0, "bars_to_cross_est": bars,
        "atr": round(atr, 3), "entry": entry, "stop": stop, "target1": target1, "rr": rr,
        "score": score, "why_not": ", ".join(why), "skip": False,
    }


def _fetch_all(syms: list[str]) -> dict:
    import yfinance as yf
    data = yf.download(syms, period="2y", interval="1d", group_by="ticker",
                       threads=True, progress=False, auto_adjust=True)
    out = {}
    for s in syms:
        try:
            out[s] = data[s] if len(syms) > 1 else data
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
                  why_not, payload, status, scan_date, last_scan_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'active',%s,NOW())
               ON CONFLICT (symbol) DO UPDATE SET
                 prev_tier=pullback_macd_candidates.tier, tier=EXCLUDED.tier,
                 price=EXCLUDED.price, pullback_pct=EXCLUDED.pullback_pct, trend_pct=EXCLUDED.trend_pct,
                 macd_prox_pct=EXCLUDED.macd_prox_pct, hist_rising_bars=EXCLUDED.hist_rising_bars,
                 bars_to_cross_est=EXCLUDED.bars_to_cross_est, atr=EXCLUDED.atr, entry=EXCLUDED.entry,
                 stop=EXCLUDED.stop, target1=EXCLUDED.target1, rr=EXCLUDED.rr, score=EXCLUDED.score,
                 why_not=EXCLUDED.why_not, payload=EXCLUDED.payload, status='active',
                 scan_date=EXCLUDED.scan_date, last_scan_at=NOW()""",
            (c["sym"], c["tier"], prev_tier, c["price"], c["pullback_pct"], c["trend_pct"],
             c["macd_prox_pct"], c["hist_rising_bars"], c["bars_to_cross_est"], c["atr"],
             c["entry"], c["stop"], c["target1"], c["rr"], c["score"], c["why_not"],
             json.dumps(c), scan_d))
        c["_prev_tier"] = prev_tier
    # mark anything not in this scan as stale
    if seen:
        _db("UPDATE pullback_macd_candidates SET status='stale' WHERE symbol <> ALL(%s) AND status='active'",
            (seen,))


def _emit_proposals(cands: list[dict], cfg: dict) -> int:
    tiers = set(cfg.get("proposal_tiers") or ["trigger"])
    notional = float(cfg.get("proposal_notional_usd", 5000))
    strat = cfg.get("default_strategy_id", "pullback_macd_reversal")
    exp_h = int(cfg.get("proposal_expiry_hours", 48))
    cols = _db("""SELECT column_name FROM information_schema.columns
                  WHERE table_name='paper_trade_proposals'""", fetch="all") or []
    avail = {r["column_name"] for r in cols}
    n = 0
    for c in cands:
        if c["tier"] not in tiers:
            continue
        shares = max(1, int(notional / max(c["entry"], 0.01)))
        risk = round(shares * (c["entry"] - c["stop"]), 2)
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
        # de-dupe: skip if an active PENDING proposal for this symbol+source already exists
        dup = _db("""SELECT id FROM paper_trade_proposals
                     WHERE symbol=%s AND status='PENDING'
                       AND COALESCE(discovery_source,'')='pullback_macd'""",
                  (c["sym"],), fetch="one")
        if dup:
            c["proposal_id"] = dup["id"]; continue
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


# ── main ────────────────────────────────────────────────────────────────────────────────
def run(dry: bool = False, limit: int = 0, as_json: bool = False) -> dict:
    t0 = time.time()
    cfg = load_cfg()
    if not cfg.get("enabled", True):
        return {"ok": False, "reason": "disabled"}
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
    triggers = [c for c in cands if c["tier"] == "trigger"]
    watch = [c for c in cands if c["tier"] == "watch"]
    scan_d = date.today()

    emitted = 0
    if not dry:
        _persist_candidates(cands, scan_d)
        if cfg.get("emit_proposals", True):
            emitted = _emit_proposals(cands, cfg)
        if cfg.get("feed_candidate_pipeline", True):
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
        "ok": True, "dry_run": dry, "universe": len(syms),
        "in_pullback_uptrend": funnel["uptrend_pullback"],
        "triggers": len(triggers), "watch": len(watch),
        "proposals_emitted": emitted, "data_errors": errors,
        "duration_s": round(time.time() - t0, 1),
        "top_triggers": sorted(triggers, key=lambda x: -x["score"])[:15],
        "top_watch": sorted(watch, key=lambda x: x["macd_prox_pct"])[:15],
    }
    if as_json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"\nuniverse={summary['universe']} errors={errors} | "
              f"uptrend+pullback={summary['in_pullback_uptrend']} → "
              f"TRIGGER={summary['triggers']} WATCH={summary['watch']} | "
              f"proposals={emitted} ({'DRY' if dry else 'written'})")
        print(f"\n{'TIER':<8}{'SYM':<7}{'PULL%':>7}{'TREND%':>7}{'PROX%':>7}{'ENTRY':>9}{'STOP':>9}{'TGT':>9}{'R:R':>6}{'SCORE':>7}")
        for c in summary["top_triggers"] + summary["top_watch"][:8]:
            print(f"{c['tier']:<8}{c['sym']:<7}{c['pullback_pct']:>7}{c['trend_pct']:>7}"
                  f"{c['macd_prox_pct']:>7}{c['entry']:>9}{c['stop']:>9}{c['target1']:>9}{c['rr']:>6}{c['score']:>7}")
    return summary


def main():
    ap = argparse.ArgumentParser(description="S&P 500 pullback + approaching-MACD-cross screener")
    ap.add_argument("--dry-run", action="store_true", help="compute + print, no DB writes / no proposals / no alerts")
    ap.add_argument("--limit", type=int, default=0, help="limit universe size (testing)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    run(dry=a.dry_run, limit=a.limit, as_json=a.json)


if __name__ == "__main__":
    main()
