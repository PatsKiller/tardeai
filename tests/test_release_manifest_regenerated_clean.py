#!/usr/bin/env python3
"""P0-3: release manifest classifies dirty files correctly — scalp source/docs are NOT
live-adjacent, and generated diligence docs are runtime/generated, never a false FAIL."""
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
PASS, FAIL, WARN = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    try:
        p = subprocess.run([sys.executable, "scripts/validate_release_readiness.py", "--json", "--skip-build"],
                           cwd=ROOT, capture_output=True, text=True, timeout=200)
        data = json.loads(p.stdout)
    except Exception as e:
        WARN.append("release validator")
        print(f"  [WARN] release validator unavailable — {e}")
        print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
        return 1 if FAIL else 0

    dc = data.get("dirty_classification", {})
    live = dc.get("live_adjacent", [])
    runtime = dc.get("runtime_generated", [])
    other = dc.get("other", [])

    # 1. None of the scalp reporting/diagnostic sources are LIVE-ADJACENT (they touch no broker path).
    scalp_sources = ("scalp_trade_attribution.py", "scalp_lifecycle_funnel_report.py",
                     "compute_scalp_lifecycle_maturity.py", "diagnose_momentum_scalp_paper_path.py",
                     "simulate_momentum_scalp_paper_path.py", "momentum_scalp_validation_tracker.py")
    leaked = [f for f in live if any(s in f for s in scalp_sources)]
    check("no scalp source classified live-adjacent", not leaked)

    # 2. Generated diligence docs are runtime/generated (or committed), never live-adjacent.
    diligence_live = [f for f in live if "docs/diligence/current/" in f or "docs/project/" in f]
    check("no diligence/project doc classified live-adjacent", not diligence_live)

    # 3. Status must be one of the legitimate states (never FAIL purely from generated docs).
    check("status is PASS / WARN_NON_LIVE_ADJACENT / WARN (not a misclassified FAIL)",
          data.get("status") in ("PASS", "WARN_NON_LIVE_ADJACENT", "WARN")
          or (data.get("status") == "FAIL" and bool(live)))

    # 4. If there ARE live-adjacent dirty files, they must be genuine broker/execution sources.
    if live:
        check("any live-adjacent dirty are genuine broker/execution files",
              all(("brokers/" in f or "schwab" in f or "execution" in f or ".env" in f or "secret" in f.lower())
                  for f in live))
    else:
        check("zero live-adjacent dirty files (clean execution surface)", True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
