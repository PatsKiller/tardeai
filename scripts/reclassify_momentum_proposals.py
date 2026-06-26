#!/usr/bin/env python3
"""reclassify_momentum_proposals.py — correct mean-reversion strategy labels on momentum/gap setups.

A high-RVOL gap-up is a MOMENTUM continuation setup. Labeling it `fib_retracement_bounce` (a
mean-reversion *pullback* — buy weakness, target prior swing high) is not just wrong, it's dangerous:
the exit plan inverts (it would buy the dip and cap upside). This re-labels such setups onto the right
momentum strategy by the actual driver:

  Momentum signature: rvol >= 8  AND  gap_pct >= 5  AND  catalyst present, currently on a
  mean-reversion / income / core strategy:
    • explicit squeeze language (heavily-shorted / meme / short-interest) + large/unknown float
        -> meme_squeeze_momentum   (large-cap squeeze)
    • micro-cap (float < 50M)
        -> left alone (momentum_scalp's strict micro-cap gate owns these)
    • otherwise (large/unknown float, generic momentum gap — sympathy/news/breakout)
        -> swing_breakout          (SHORT_SWING momentum continuation, trailing exit, large-float ok)

Conservative: only RE-LABELS a clearly-wrong mean-reversion/income tag, never an already-correct
momentum tag. Routing to swing_breakout fixes the dangerous exit-plan inversion; it is a best-fit
momentum home, not a claim the name has a 20-day base.

    .venv/bin/python scripts/reclassify_momentum_proposals.py            # dry-run
    .venv/bin/python scripts/reclassify_momentum_proposals.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Mean-reversion / income / core / pullback strategies — WRONG for a high-RVOL gap-up. Reclassify off.
WRONG_FOR_GAP = {
    "fib_retracement_bounce", "swing_trade", "core_growth_compounder", "dividend_growth_compounder",
    "covered_call_income", "high_yield_income_bdc", "reit_income", "bond_income", "income_add",
    "core_index", "international_dividend", "sector_rotation", "recovery_watch", "defense_thesis",
    "tax_loss_harvest", "cash_or_stable",
}
# Already a momentum/squeeze/breakout/earnings strategy — never touch.
MOMENTUM_OK = {
    "meme_squeeze_momentum", "momentum_scalp", "gap_and_go", "swing_breakout", "earnings_catalyst",
    "earnings_post_momentum", "speculative_growth",
}
_SQUEEZE_RE = re.compile(r"squeez|meme|shorted|short interest|pounce|short.?squeeze", re.I)

MIN_RVOL, MIN_GAP, MIN_FLOAT_M = 8.0, 5.0, 50.0


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _target(rvol, gap, flt, cat) -> str | None:
    """Resolve the correct momentum strategy for a setup, or None if it isn't a momentum gap / is micro."""
    if not ((rvol is not None and rvol >= MIN_RVOL) and (gap is not None and gap >= MIN_GAP) and bool(cat)):
        return None
    if flt is not None and flt < MIN_FLOAT_M:
        return "__micro__"  # momentum_scalp's domain — leave alone
    if _SQUEEZE_RE.search(cat or ""):
        return "meme_squeeze_momentum"
    return "swing_breakout"  # generic large-cap momentum gap (sympathy/news/breakout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the reclassification (default dry-run)")
    args = ap.parse_args()
    from db_adapter import _execute

    rows = _execute(
        """SELECT id, symbol, strategy_id, rvol, gap_pct, float_m, catalyst
           FROM paper_trade_proposals
           WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST')""", None, fetch="all") or []

    moves, micro = [], []
    for r in rows:
        sid = str(r.get("strategy_id") or "")
        if sid in MOMENTUM_OK or sid not in WRONG_FOR_GAP:
            continue
        tgt = _target(_f(r.get("rvol")), _f(r.get("gap_pct")), _f(r.get("float_m")), str(r.get("catalyst") or ""))
        if tgt is None:
            continue
        if tgt == "__micro__":
            micro.append(r)
        elif tgt != sid:
            moves.append((r, tgt))

    print(f"[reclassify_momentum] scanned {len(rows)} active · {len(moves)} reclassified · "
          f"{len(micro)} micro-cap (left to momentum_scalp)")
    for r, tgt in moves:
        print(f"  #{r['id']} {r['symbol']}: {r['strategy_id']} → {tgt} "
              f"(rvol={_f(r['rvol'])}, gap={_f(r['gap_pct'])}%, float={_f(r['float_m'])}M)")
    for r in micro:
        print(f"  (micro) #{r['id']} {r['symbol']}: float={_f(r['float_m'])}M — momentum_scalp candidate")

    if args.apply and moves:
        for r, tgt in moves:
            _execute("UPDATE paper_trade_proposals SET strategy_id=%s, strategy_type=%s WHERE id=%s",
                     (tgt, tgt, r["id"]), fetch=None)
        print(f"[reclassify_momentum] APPLIED {len(moves)} reclassification(s)")
    elif moves:
        print("[reclassify_momentum] dry-run — re-run with --apply to write")


if __name__ == "__main__":
    main()
