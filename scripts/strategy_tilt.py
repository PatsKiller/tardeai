#!/usr/bin/env python3
"""strategy_tilt.py — per-strategy allocation tilt toward LIVE winners (operator 2026-06-19).

Mirrors rec_source_quality (per-source) but keyed by STRATEGY: a bounded multiplier (0.50-1.50) from
each strategy's live expectancy, applied to BOTH (a) candidate ranking in auto_proposal_generator and
(b) the per-trade risk budget in account_policy.compute_sizing — so winning strategies get more
candidates AND more size (still capped by the percent-of-equity position cap; paper-only).

Excludes momentum_scalp (operator: "do not disturb momentum day scalp") — pinned to 1.0 always.
Kill switch: env STRATEGY_TILT=0 disables (default ON). Neutral (1.0) until a minimum live sample.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

EXCLUDED = {"momentum_scalp"}      # never tilted (operator exclusion)
MIN_SAMPLE = 2                     # below this, stay neutral (1.0)
LO, HI = 0.50, 1.50                # multiplier bounds
SLOPE = 0.25                       # multiplier = 1.0 + SLOPE * avg_r, then clamped
_ROOT = Path(__file__).resolve().parent.parent
_JSON = _ROOT / "data" / "runtime" / "strategy_tilt_latest.json"

_DDL = """
CREATE TABLE IF NOT EXISTS strategy_tilt_multipliers (
  id bigserial PRIMARY KEY,
  strategy_id text NOT NULL,
  multiplier numeric NOT NULL,
  sample_size int NOT NULL,
  avg_r numeric,
  basis text,
  computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_stm_key ON strategy_tilt_multipliers(strategy_id, computed_at DESC);
"""


def _clamp(v):
    return max(LO, min(HI, v))


def enabled() -> bool:
    return os.getenv("STRATEGY_TILT", "1") != "0"


def compute_tilts() -> dict:
    """Recompute per-strategy multipliers from closed paper trades. Persists history + latest JSON."""
    conn = _get_conn(); cur = conn.cursor()
    cur.execute(_DDL); conn.commit()
    cur.execute("""SELECT strategy_id, count(*) AS n, round(avg(r_multiple)::numeric,3) AS avg_r
                     FROM paper_trades WHERE status='closed' AND pnl IS NOT NULL
                    GROUP BY strategy_id""")
    out = {}
    for sid, n, avg_r in cur.fetchall():
        if sid in EXCLUDED:
            mult, basis = 1.0, "excluded (momentum_scalp — operator)"
        elif (n or 0) < MIN_SAMPLE or avg_r is None:
            mult, basis = 1.0, f"neutral (n={n} < {MIN_SAMPLE})"
        else:
            mult = round(_clamp(1.0 + SLOPE * float(avg_r)), 3)
            basis = f"1.0 + {SLOPE}*avgR({avg_r}) clamped [{LO},{HI}]"
        out[sid] = mult
        cur.execute("""INSERT INTO strategy_tilt_multipliers (strategy_id, multiplier, sample_size, avg_r, basis)
                       VALUES (%s,%s,%s,%s,%s)""", (sid, mult, int(n or 0), avg_r, basis))
    conn.commit()
    try:
        _JSON.parent.mkdir(parents=True, exist_ok=True)
        _JSON.write_text(json.dumps({"multipliers": out, "excluded": sorted(EXCLUDED)}))
    except Exception:
        pass
    return out


def get_tilt(strategy_id: str) -> float:
    """Latest multiplier for a strategy (1.0 default / disabled / excluded). Never raises."""
    sid = (strategy_id or "").strip()
    if not enabled() or sid in EXCLUDED:
        return 1.0
    try:
        cur = _get_conn().cursor()
        cur.execute("""SELECT multiplier FROM strategy_tilt_multipliers WHERE strategy_id=%s
                        ORDER BY computed_at DESC LIMIT 1""", (sid,))
        r = cur.fetchone()
        return float(r[0]) if r else 1.0
    except Exception:
        try:
            _get_conn().rollback()
        except Exception:
            pass
        return 1.0


if __name__ == "__main__":
    tilts = compute_tilts()
    print("strategy tilts (excl. momentum_scalp):")
    for sid, m in sorted(tilts.items(), key=lambda x: -x[1]):
        tag = " (EXCLUDED)" if sid in EXCLUDED else ""
        print(f"  {sid:28} {m:.3f}x{tag}")
