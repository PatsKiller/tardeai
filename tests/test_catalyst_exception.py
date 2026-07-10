#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from catalyst_exception import qualifies_catalyst_exception, apply_catalyst_exception_fields  # noqa: E402


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    ok = True
    bnai = {"symbol": "BNAI", "decision": "WAIT", "score": 32, "rvol": 6.95, "gap_pct": 8.0, "change_pct": 2.74, "catalyst_verified": True}
    ok &= check("BNAI qualifies", qualifies_catalyst_exception(bnai))
    apply_catalyst_exception_fields(bnai)
    ok &= check("BNAI MANUAL_REVIEW", bnai["decision"] == "MANUAL_REVIEW")
    ok &= check("BNAI grade capped", bnai["grade"] in ("B", "A", "A+"))

    weak = {"symbol": "PR", "decision": "AVOID", "score": 5, "rvol": 0.37}
    ok &= check("PR rejected", not qualifies_catalyst_exception(weak))

    squeeze = {"symbol": "GMM", "decision": "MANUAL_REVIEW", "awareness_status": "SQUEEZE", "setup_class": "squeeze", "grade": "A"}
    ok &= check("squeeze warrior", qualifies_catalyst_exception(squeeze))

    if not ok:
        sys.exit(1)
    print("All catalyst_exception checks passed.")


if __name__ == "__main__":
    main()