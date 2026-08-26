#!/usr/bin/env python3
"""READ-ONLY baseline audit: universe × thesis coverage.

Writes evidence JSON under evidence/ (worktree) by default.
Does NOT mutate production thesis store, timers, Telegram, or CURRENT.

Usage:
  .venv/bin/python scripts/symbol_thesis_baseline_audit.py \\
      --root /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild \\
      --out evidence/SYMBOL_THESIS_BASELINE_AUDIT.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        default=str(Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")),
        help="Live production tree for READ-ONLY data (default: live PROJ)",
    )
    ap.add_argument(
        "--out",
        default=str(ROOT / "evidence" / "SYMBOL_THESIS_BASELINE_AUDIT.json"),
    )
    ap.add_argument("--stale-days", type=int, default=30)
    args = ap.parse_args()

    live_root = Path(args.root)
    from scripts.lib.symbol_thesis_coverage import (
        build_coverage_report,
        research_gap_triggers,
    )

    report = build_coverage_report(root=live_root, stale_days=args.stale_days)
    gaps = research_gap_triggers(report, limit=200)

    # Focus cards
    focus = {}
    for sym in ("SCHG", "CSCO", "ANET"):
        focus[sym] = next((r for r in report["rows"] if r["symbol"] == sym), None)

    out = {
        "audit_id": "SYMBOL_THESIS_BASELINE_AUDIT",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "live_root": str(live_root),
        "accepted_main_at_worktree": None,  # filled by caller/CI
        "note": (
            "Read-only audit. Desk thesis may exist without per-symbol theses. "
            "Re-entry intel states are decision-control, not investment theses."
        ),
        "universe_counts": report.get("universe_counts"),
        "coverage_counts": report.get("coverage_counts"),
        "desk": {
            "thesis_id": (report.get("desk") or {}).get("thesis_id"),
            "thesis_version": (report.get("desk") or {}).get("thesis_version"),
            "stance": (report.get("desk") or {}).get("stance"),
            "linked_symbols": (report.get("desk") or {}).get("linked_symbols"),
            "summary": ((report.get("desk") or {}).get("summary") or "")[:500],
        },
        "focus": focus,
        "research_gap_triggers_sample": gaps[:40],
        "research_gap_trigger_count": len(gaps),
        "material_missing_thesis": [
            r["symbol"] for r in report["rows"]
            if r.get("material") and not r.get("has_current_symbol_thesis")
        ][:100],
        "universe_errors": report.get("universe_errors") or [],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({
        "wrote": str(out_path),
        "universe_union": (out.get("universe_counts") or {}).get("universe_union"),
        "coverage": out.get("coverage_counts"),
        "focus": {k: (v or {}).get("coverage_state") for k, v in focus.items()},
        "gap_triggers": out["research_gap_trigger_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
