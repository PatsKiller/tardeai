#!/usr/bin/env python3
"""P1-3: outcome learning is advisory, bounded, neutral on low sample, gate-safe."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from scalp_outcome_learning import learn, _bounded_weight, WEIGHT_MIN, WEIGHT_MAX, MIN_SAMPLE  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # 1. Bounded weights: never below 0.5, never above 1.2.
    check("perfect win rate clamps to max", _bounded_weight(1.0, 100) == WEIGHT_MAX)
    check("zero win rate stays at/above min and below neutral",
          WEIGHT_MIN <= _bounded_weight(0.0, 100) < 1.0)
    check("50% win rate is neutral", _bounded_weight(0.5, 100) == 1.0)
    check("never below 0.5 (sweep)", all(_bounded_weight(w / 20, 100) >= WEIGHT_MIN for w in range(21)))
    check("never above 1.2 (sweep)", all(_bounded_weight(w / 20, 100) <= WEIGHT_MAX for w in range(21)))

    # 2. Low sample → neutral weight (no change before MIN_SAMPLE).
    check("below min-sample stays neutral", _bounded_weight(1.0, MIN_SAMPLE - 1) == 1.0)
    check("at min-sample can move", _bounded_weight(1.0, MIN_SAMPLE) != 1.0)

    # 3. Live report shape: advisory-only, bounded, reports sample size + confidence.
    r = learn(180)
    check("report runs", r.get("ok") is not None)
    check("advisory_only flag set", r.get("advisory_only") is True)
    check("reports sample size", "sample_size" in r)
    check("reports confidence", r.get("confidence") in ("low", "medium", "high"))
    check("weight bounds documented", r.get("weight_bounds", {}).get("min") == WEIGHT_MIN
          and r.get("weight_bounds", {}).get("max") == WEIGHT_MAX)

    # 4. Every emitted weight is within bounds.
    in_bounds = True
    for dim, keys in (r.get("weights") or {}).items():
        for k, v in keys.items():
            if not (WEIGHT_MIN <= v["weight"] <= WEIGHT_MAX):
                in_bounds = False
    check("all emitted weights within [0.5, 1.2]", in_bounds)

    # 5. Low sample → all weights neutral (current paper sample is tiny).
    if r.get("sample_size", 0) < MIN_SAMPLE:
        all_neutral = all(v["weight"] == 1.0
                          for keys in (r.get("weights") or {}).values() for v in keys.values())
        check("tiny sample → neutral weights", all_neutral)
    else:
        check("sample sufficient (informational)", True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
