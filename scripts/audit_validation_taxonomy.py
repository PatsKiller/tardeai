#!/usr/bin/env python3
"""P0-8: audit operator-facing taxonomy drift — forbid "paper" phrasing outside legacy contexts.

The canonical operator-facing lifecycle term is VALIDATION. This audit flags forbidden operator-
facing phrases in docs / config / generated reports. Legacy internal references are allowed ONLY in
DB table names, adapter/module identifiers, the alpaca_paper account id, or explicit "legacy alias"
lines. Read-only. Produces JSON + Markdown; exits non-zero (and the test fails) on a violation.

    python3 scripts/audit_validation_taxonomy.py --json
    python3 scripts/audit_validation_taxonomy.py --markdown > docs/diligence/current/VALIDATION_TAXONOMY_AUDIT.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Forbidden OPERATOR-FACING phrases (spaced / hyphenated). Underscore identifiers (paper_trades,
# paper_fast_path_candidates) are NOT these — they are legacy storage / alias field names.
FORBIDDEN = ["paper fast path", "paper approval", "paper sample", "paper-ready", "paper maturity",
             "paper submit", "paper-only"]

# A line is ALLOWED to mention a forbidden phrase if it is clearly a legacy/compat/alias context.
_ALLOW_MARKERS = ("legacy", "alias", "deprecat", "backward compat", "compatibility", "alpaca_paper",
                  "paper_trades", "paper_trade_proposals", "proposal_paper_submitter",
                  "paper_trade_logger", "momentum_scalp_paper_fast_path", "`paper_", "paper_*",
                  "do not use", "avoid operator-facing")

# The audit's own report legitimately lists the forbidden phrases — exclude it (self-reference).
_SELF_EXCLUDE = {"VALIDATION_TAXONOMY_AUDIT.md"}


# Files in scope: operator-facing docs, config, and generated reports.
def _targets():
    out = list((ROOT / "docs" / "diligence" / "current").glob("*.md"))
    out += [ROOT / "docs" / "CHANGELOG.md", ROOT / "config" / "strategies" / "momentum_scalp.yaml"]
    return [p for p in out if p.exists() and p.name not in _SELF_EXCLUDE]


def audit() -> dict:
    violations = []
    scanned = 0
    for path in _targets():
        scanned += 1
        rel = str(path.relative_to(ROOT))
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            low = line.lower()
            for phrase in FORBIDDEN:
                if phrase in low:
                    if any(m in low for m in _ALLOW_MARKERS):
                        continue
                    violations.append({"file": rel, "line": i, "phrase": phrase,
                                       "text": line.strip()[:140]})
    return {
        "ok": not violations,
        "status": "PASS" if not violations else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files_scanned": scanned,
        "forbidden_phrases": FORBIDDEN,
        "allowed_contexts": ["DB table names (paper_trades, paper_trade_proposals)",
                             "adapter/module names (proposal_paper_submitter, paper_trade_logger, "
                             "momentum_scalp_paper_fast_path)", "alpaca_paper account identifier",
                             "explicit legacy/alias/deprecated lines"],
        "violation_count": len(violations),
        "violations": violations,
        "note": "Operator-facing taxonomy is VALIDATION. Legacy paper_* names are allowed only as "
                "documented storage/adapter/compat aliases.",
    }


def to_markdown(r: dict) -> str:
    L = ["# Validation Taxonomy Audit", "",
         f"**Status: {r['status']}** | files scanned: {r['files_scanned']} | violations: {r['violation_count']}  ",
         f"_Generated: {r['generated_at']}_  ",
         "_Source: `python3 scripts/audit_validation_taxonomy.py --json`_  ", "",
         "Operator-facing lifecycle term is **validation**. Forbidden operator-facing phrases: "
         + ", ".join(f"`{p}`" for p in r["forbidden_phrases"]) + ".", "",
         "Allowed legacy contexts: " + "; ".join(r["allowed_contexts"]) + ".", ""]
    if r["violations"]:
        L += ["## Violations", "", "| File | Line | Phrase | Text |", "|------|------|--------|------|"]
        for v in r["violations"]:
            L.append(f"| {v['file']} | {v['line']} | `{v['phrase']}` | {v['text'].replace('|','/')} |")
    else:
        L += ["## Violations", "", "None — operator-facing docs/config/reports use validation taxonomy."]
    L += ["", "> " + r["note"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = audit()
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"Taxonomy audit: {r['status']} ({r['violation_count']} violations)")
        for v in r["violations"][:20]:
            print(f"  {v['file']}:{v['line']} — {v['phrase']}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
