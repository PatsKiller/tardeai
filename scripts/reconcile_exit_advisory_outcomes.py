#!/usr/bin/env python3
"""Gain Guardian outcome reconciliation (F5, Phase-193 pattern).

For each PUBLISHED exit advisory, at +5 and +21 trading days record what the
market actually did and whether the operator acted — the evidence base that
will eventually justify (or kill) threshold changes. Without this, Gain
Guardian is another unfalsifiable advisor.

Verdicts (21d horizon):
  SIGNAL_CORRECT — post-advisory return underperforms SPY by >3% OR drawdown
                   from advisory price exceeds 1.5 ATR
  SIGNAL_EARLY   — 21d still outperforming, but a >1.5 ATR drawdown happened
                   along the way (the risk was real, the exit early)
  SIGNAL_WRONG   — outperformed SPY and never drew down 1.5 ATR
  NOT_EVALUABLE  — missing bars/ATR/benchmark

Usage:
  python scripts/reconcile_exit_advisory_outcomes.py            # reconcile due advisories
  python scripts/reconcile_exit_advisory_outcomes.py --self-test  # fixture verdict tests
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

DDL = """
CREATE TABLE IF NOT EXISTS exit_advisory_outcomes (
    id BIGSERIAL PRIMARY KEY,
    advisory_id BIGINT,
    symbol TEXT NOT NULL,
    advisory TEXT,
    advisory_at TIMESTAMPTZ,
    horizon_days INT NOT NULL,
    price_at_advisory NUMERIC,
    price_at_horizon NUMERIC,
    symbol_return_pct NUMERIC,
    spy_return_pct NUMERIC,
    max_drawdown_atr NUMERIC,
    giveback_frac_then NUMERIC,
    operator_acted BOOLEAN,
    verdict TEXT,
    evaluated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (advisory_id, horizon_days)
);
"""


def verdict_for(*, symbol_return_pct: float | None, spy_return_pct: float | None,
                max_drawdown_atr: float | None) -> str:
    """Pure verdict logic — unit-tested with fixtures below."""
    if symbol_return_pct is None or spy_return_pct is None:
        return "NOT_EVALUABLE"
    rel = symbol_return_pct - spy_return_pct
    deep_dd = max_drawdown_atr is not None and max_drawdown_atr > 1.5
    if rel < -3.0 or deep_dd and rel < 0:
        return "SIGNAL_CORRECT"
    if deep_dd:
        return "SIGNAL_EARLY"
    return "SIGNAL_WRONG"


def _closes_since(symbol: str, since_iso: str, max_days: int) -> list[float]:
    from holdings_gain_guardian import _bars_with_volume
    bars = _bars_with_volume(symbol, days=max_days + 60)
    out = []
    for b in bars:
        ts = b.get("datetime") or b.get("t") or b.get("date") or ""
        try:
            import datetime as dt
            when = (dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)
                    if isinstance(ts, (int, float)) else dt.datetime.fromisoformat(str(ts)[:19]).replace(tzinfo=dt.timezone.utc))
        except Exception:
            continue
        if str(when.date()) >= since_iso[:10]:
            c = float(b.get("close") or 0)
            if c > 0:
                out.append(c)
    return out


def reconcile() -> int:
    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        return 2
    for stmt in DDL.strip().split(";"):
        if stmt.strip():
            ex(stmt, fetch="none")

    advisories = ex(
        """SELECT id, symbol, topic, created_at, evidence_json
           FROM hermes_research_intelligence
           WHERE research_type='exit_intelligence'
             AND created_at < now() - interval '5 days'
           ORDER BY created_at ASC LIMIT 200""",
        fetch="all",
    ) or []
    if not advisories:
        print("[exit-outcomes] no published exit advisories due — clean run on zero rows")
        return 0

    done = 0
    for a in advisories:
        ev = a.get("evidence_json")
        if isinstance(ev, str):
            try:
                ev = json.loads(ev)
            except Exception:
                ev = {}
        m = (ev or {}).get("metrics_row") or {}
        p0 = float(m.get("price") or 0)
        atr = None
        try:
            atr = float((ev or {}).get("metrics_row", {}).get("atr14") or 0) or None
        except (TypeError, ValueError):
            pass
        age_days = ex("SELECT EXTRACT(day FROM now() - %s)::int AS d", (a["created_at"],), fetch="one")["d"]
        for horizon, trading_days in ((5, 5), (21, 21)):
            if age_days < int(trading_days * 1.5):  # calendar buffer around trading days
                continue
            dup = ex("SELECT 1 FROM exit_advisory_outcomes WHERE advisory_id=%s AND horizon_days=%s",
                     (a["id"], horizon), fetch="one")
            if dup:
                continue
            closes = _closes_since(a["symbol"], str(a["created_at"]), trading_days + 10)
            spy = _closes_since("SPY", str(a["created_at"]), trading_days + 10)
            if len(closes) <= trading_days or len(spy) <= trading_days or p0 <= 0:
                ret = spy_ret = dd_atr = None
                v = "NOT_EVALUABLE"
            else:
                p_h = closes[trading_days]
                ret = round(100.0 * (p_h / p0 - 1), 2)
                spy_ret = round(100.0 * (spy[trading_days] / spy[0] - 1), 2)
                dd = p0 - min(closes[: trading_days + 1])
                dd_atr = round(dd / atr, 2) if atr else None
                v = verdict_for(symbol_return_pct=ret, spy_return_pct=spy_ret, max_drawdown_atr=dd_atr)
            acted = None
            try:
                acted_row = ex(
                    """SELECT 1 FROM alert_events
                       WHERE symbol=%s AND created_at BETWEEN %s AND %s
                         AND alert_type IN ('stop_replaced','order_filled','position_trimmed') LIMIT 1""",
                    (a["symbol"], a["created_at"], f"{a['created_at']}"), fetch="one",
                )
                acted = bool(acted_row)
            except Exception:
                acted = None
            ex(
                """INSERT INTO exit_advisory_outcomes
                   (advisory_id, symbol, advisory, advisory_at, horizon_days, price_at_advisory,
                    price_at_horizon, symbol_return_pct, spy_return_pct, max_drawdown_atr,
                    giveback_frac_then, operator_acted, verdict)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (advisory_id, horizon_days) DO NOTHING""",
                (a["id"], a["symbol"], m.get("advisory"), a["created_at"], horizon, p0 or None,
                 (closes[trading_days] if ret is not None else None), ret, spy_ret, dd_atr,
                 m.get("giveback_frac"), acted, v),
                fetch="none",
            )
            done += 1
    print(f"[exit-outcomes] evaluated {done} advisory-horizon pairs")
    return 0


def self_test() -> int:
    fixtures = [
        # (sym_ret, spy_ret, dd_atr, expected)
        (-8.0, 1.0, 0.8, "SIGNAL_CORRECT"),   # big relative underperformance
        (4.0, 2.0, 2.1, "SIGNAL_EARLY"),      # still outperforming but deep drawdown happened
        (6.0, 2.0, 0.4, "SIGNAL_WRONG"),      # clean outperformance, shallow dd
        (None, 2.0, None, "NOT_EVALUABLE"),
        (-1.0, 1.0, 1.8, "SIGNAL_CORRECT"),   # deep dd while lagging
    ]
    fails = 0
    for sr, br, dd, want in fixtures:
        got = verdict_for(symbol_return_pct=sr, spy_return_pct=br, max_drawdown_atr=dd)
        status = "ok" if got == want else "FAIL"
        if got != want:
            fails += 1
        print(f"  [{status}] ret={sr} spy={br} dd_atr={dd} → {got} (want {want})")
    print("self-test:", "PASS" if fails == 0 else f"{fails} FAILURES")
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    return self_test() if args.self_test else reconcile()


if __name__ == "__main__":
    raise SystemExit(main())
