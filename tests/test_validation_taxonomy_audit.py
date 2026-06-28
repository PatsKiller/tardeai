#!/usr/bin/env python3
"""P0-8: operator-facing taxonomy audit — docs/config/reports use validation, not paper."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from audit_validation_taxonomy import audit, to_markdown, FORBIDDEN  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    r = audit()
    check("audit scanned files", r["files_scanned"] > 0)
    check("forbidden phrases include 'paper fast path' + 'paper approval'",
          "paper fast path" in FORBIDDEN and "paper approval" in FORBIDDEN)
    # The gating assertion: NO operator-facing taxonomy violations remain.
    if r["violations"]:
        for v in r["violations"][:15]:
            print(f"    VIOLATION {v['file']}:{v['line']} — {v['phrase']}")
    check("taxonomy audit PASSES (0 violations)", r["ok"] and r["violation_count"] == 0)
    check("markdown renders", "Validation Taxonomy Audit" in to_markdown(r))
    check("documents allowed legacy contexts", any("alpaca_paper" in c for c in r["allowed_contexts"]))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
