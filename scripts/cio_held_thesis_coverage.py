#!/usr/bin/env python3
"""CLI: held-book thesis coverage SLA + optional acquisition + catalyst reassess stub.

Examples:
  python scripts/cio_held_thesis_coverage.py --report
  python scripts/cio_held_thesis_coverage.py --acquire --limit 5          # dry
  python scripts/cio_held_thesis_coverage.py --acquire --apply --limit 3
  python scripts/cio_held_thesis_coverage.py --reassess-catalysts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Held-book living thesis coverage")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--report", action="store_true", help="Print + write coverage SLA report")
    ap.add_argument("--acquire", action="store_true", help="Run acquisition for held gaps")
    ap.add_argument("--apply", action="store_true", help="Apply acquisition (default dry)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--max-llm", type=int, default=3)
    ap.add_argument("--symbols", default="", help="Comma symbols override")
    ap.add_argument("--reassess-catalysts", action="store_true",
                    help="Write dry revision ledger rows for held medium+ catalysts")
    ap.add_argument("--min-severity", default="medium")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    from scripts.lib.cio_held_thesis_coverage import (
        build_held_coverage_report,
        write_coverage_report,
        run_held_coverage_acquire,
        reassess_held_from_catalysts,
    )

    root = Path(a.root)
    out: dict = {}

    if a.report or (not a.acquire and not a.reassess_catalysts):
        rep = build_held_coverage_report(root=root)
        path = write_coverage_report(rep, root=root)
        out["report"] = {
            "held_count": rep["held_count"],
            "held_equity_ticker_n": rep.get("held_equity_ticker_n"),
            "current_count": rep["current_count"],
            "held_current_pct": rep["held_current_pct"],
            "coverage_pct": rep.get("coverage_pct"),
            "fresh_pct": rep.get("fresh_pct"),
            "sla_target_pct": rep.get("sla_target_pct"),
            "sla_met": rep["sla_met"],
            "by_state": rep["by_state"],
            "needs_coverage": rep["needs_coverage"],
            "path": str(path),
        }

    if a.acquire:
        syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or None
        out["acquire"] = run_held_coverage_acquire(
            root=root,
            limit=a.limit,
            max_llm=a.max_llm,
            apply=a.apply,
            symbols=syms,
        )

    if a.reassess_catalysts:
        out["reassess"] = reassess_held_from_catalysts(
            root=root,
            limit=a.limit,
            min_severity=a.min_severity,
        )

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
