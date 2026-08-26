#!/usr/bin/env python3
"""Run the research-governance subsystem acceptance suite (PR-R1).

Prints the phase-aware RGA acceptance report and exits nonzero on FAIL.
READ_ONLY_ADVISORY. No provider calls, no broker calls, no production DB writes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# `scripts` is a namespace package; its PARENT (the repo root) must be importable
# for `from scripts.lib...` to resolve when this file is run directly.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance.acceptance import run_acceptance  # noqa: E402


def main(argv: list[str]) -> int:
    profile = argv[0] if argv else "R1_foundation"
    report = run_acceptance(profile)
    out = {
        "acceptance_profile": report["profile"],
        "overall": report["overall"],
    }
    if report.get("not_implemented"):
        out["not_implemented"] = True
    else:
        out["required_runtime_pass"] = report["required_runtime_pass"]
        out["required_runtime_fail"] = report["required_runtime_fail"]
        out["required_contract_pass"] = report["required_contract_pass"]
        out["required_contract_fail"] = report["required_contract_fail"]
    out["not_in_scope"] = report.get("not_in_scope", [])
    print(json.dumps(out, indent=2))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
