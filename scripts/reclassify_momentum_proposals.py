#!/usr/bin/env python3
"""reclassify_squeeze_proposals.py — correct obviously-wrong strategy labels on momentum/squeeze setups.

A large-cap name gapping up on huge RVOL with a meme/short-squeeze catalyst (e.g. WEN: RVOL 33x, gap
+25%, "Heavily Shorted … Meme Traders Pounce") is a MOMENTUM / SQUEEZE setup — NOT a fib-retracement
pullback (a mean-reversion setup, the literal opposite). The screener sometimes mislabels these.

Rule (conservative — only RE-LABELS a clearly-wrong mean-reversion/income tag, never an already-correct
momentum tag):
  rvol >= 8  AND  gap_pct >= 5  AND  float_m >= 50 (large-cap)  AND  catalyst present
  AND current strategy_id is a non-momentum strategy
  -> meme_squeeze_momentum   (large float = squeeze, distinct from micro-cap momentum_scalp)

Micro-cap (float < 50M) momentum gaps are logged as momentum_scalp candidates but left alone (that
strategy has its own strict micro-cap gate).

    .venv/bin/python scripts/reclassify_squeeze_proposals.py            # dry-run
    .venv/bin/python scripts/reclassify_squeeze_proposals.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Strategies that are WRONG for a high-RVOL gap-up (mean-reversion / income / core / pullback).
NON_MOMENTUM = {
    "fib_retracement_bounce", "swing_breakout", "swing_trade", "core_growth_compounder",
    "dividend_growth_compounder", "covered_call_income", "high_yield_income_bdc", "reit_income",
    "bond_income", "income_add", "core_index", "international_dividend", "sector_rotation",
    "recovery_watch", "defense_thesis", "tax_loss_harvest", "cash_or_stable",
}
# Already a momentum/squeeze/earnings strategy — never touch.
MOMENTUM_OK = {
    "meme_squeeze_momentum", "momentum_scalp", "gap_and_go", "earnings_catalyst",
    "earnings_post_momentum", "speculative_growth",
}
_SQUEEZE_RE = re.compile(r"squeez|meme|shorted|short interest|soar|pounce|short.?squeeze", re.I)

MIN_RVOL, MIN_GAP, MIN_FLOAT_M = 8.0, 5.0, 50.0


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the reclassification (default dry-run)")
    args = ap.parse_args()
    from db_adapter import _execute

    rows = _execute(
        """SELECT id, symbol, strategy_id, rvol, gap_pct, float_m, catalyst
           FROM paper_trade_proposals
           WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST')""", None, fetch="all") or []

    reclassified, scalp_candidates = [], []
    for r in rows:
        sid = str(r.get("strategy_id") or "")
        if sid in MOMENTUM_OK:
            continue
        rvol, gap, flt = _f(r.get("rvol")), _f(r.get("gap_pct")), _f(r.get("float_m"))
        cat = str(r.get("catalyst") or "")
        # Momentum signature: high RVOL + gap, with a catalyst (squeeze keywords strengthen it).
        is_momentum = (rvol is not None and rvol >= MIN_RVOL) and (gap is not None and gap >= MIN_GAP) and bool(cat)
        if not is_momentum:
            continue
        squeeze_words = bool(_SQUEEZE_RE.search(cat))
        large_float = flt is not None and flt >= MIN_FLOAT_M
        # MEME/SQUEEZE requires explicit squeeze language (heavily shorted / meme / short interest /
        # short-squeeze). A generic high-RVOL gap on a large cap is momentum but NOT a squeeze — those
        # belong in gap_and_go / earnings_post_momentum, not here, so we leave them alone (precision
        # over recall: better to under-reclassify than to mislabel a non-squeeze as a meme squeeze).
        if not squeeze_words:
            continue
        if large_float or flt is None:
            if sid in NON_MOMENTUM:
                reclassified.append(r)
        elif flt is not None and flt < MIN_FLOAT_M:
            scalp_candidates.append(r)  # micro-cap squeeze — momentum_scalp's domain, left alone

    print(f"[reclassify_squeeze] scanned {len(rows)} active · "
          f"{len(reclassified)} → meme_squeeze_momentum · {len(scalp_candidates)} micro-cap scalp candidates (left alone)")
    for r in reclassified:
        print(f"  #{r['id']} {r['symbol']}: {r['strategy_id']} → meme_squeeze_momentum "
              f"(rvol={_f(r['rvol'])}, gap={_f(r['gap_pct'])}%, float={_f(r['float_m'])}M)")
    for r in scalp_candidates:
        print(f"  (micro) #{r['id']} {r['symbol']}: float={_f(r['float_m'])}M — momentum_scalp candidate")

    if args.apply and reclassified:
        for r in reclassified:
            _execute("UPDATE paper_trade_proposals SET strategy_id='meme_squeeze_momentum', "
                     "strategy_type='meme_squeeze_momentum' WHERE id=%s", (r["id"],), fetch=None)
        print(f"[reclassify_squeeze] APPLIED {len(reclassified)} reclassification(s)")
    elif reclassified:
        print("[reclassify_squeeze] dry-run — re-run with --apply to write")


if __name__ == "__main__":
    main()
