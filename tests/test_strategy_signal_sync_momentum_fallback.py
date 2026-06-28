#!/usr/bin/env python3
"""P0-1: strategy_signal_sync fallback cannot over-route large-float into momentum_scalp."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from strategy_signal_sync import infer_strategy_id  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def s(**kw):
    base = {"price": 5, "rvol": 6, "gap_pct": 6, "float_m": 8, "catalyst_verified": True}
    base.update(kw)
    return base


def main():
    # 1. Micro-float verified → momentum_scalp allowed.
    check("micro-float verified → momentum_scalp",
          infer_strategy_id(s(float_m=8)) == "momentum_scalp")

    # 2. Large-float (50M) verified → NOT momentum_scalp.
    check("large-float verified is NOT momentum_scalp",
          infer_strategy_id(s(float_m=50)) != "momentum_scalp")
    check("large-float verified → large_float_social_scout",
          infer_strategy_id(s(float_m=50)) == "large_float_social_scout")

    # 3. Float exactly 20 is micro (boundary); 20.1 is large.
    check("float 20 → momentum_scalp", infer_strategy_id(s(float_m=20)) == "momentum_scalp")
    check("float 20.1 → not momentum_scalp", infer_strategy_id(s(float_m=20.1)) != "momentum_scalp")

    # 4. Unverified catalyst → never momentum_scalp.
    check("unverified → not momentum_scalp",
          infer_strategy_id(s(float_m=8, catalyst_verified=False)) != "momentum_scalp")

    # 5. Missing float → no momentum_scalp.
    check("missing float → not momentum_scalp",
          infer_strategy_id(s(float_m=None)) != "momentum_scalp")
    check("zero float → not momentum_scalp",
          infer_strategy_id(s(float_m=0)) != "momentum_scalp")

    # 6. Old 100M ceiling is gone — a 100M name is never momentum_scalp.
    check("100M float is never momentum_scalp",
          infer_strategy_id(s(float_m=100)) != "momentum_scalp")

    # 7. Low RVOL / low gap micro name doesn't qualify as momentum_scalp.
    check("low rvol → not momentum_scalp", infer_strategy_id(s(rvol=2)) != "momentum_scalp")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
