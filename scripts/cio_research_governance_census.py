#!/usr/bin/env python3
"""Read-only census of CIO research-engine governance (P4 / WS6–8).

Inspects code-level invariants and optional live/overlay stores. Never calls a
vendor, never raises a budget, never writes unless `--write-evidence` points at
an explicit output path under docs/ (operator-owned snapshot).

    python3 scripts/cio_research_governance_census.py --json
    python3 scripts/cio_research_governance_census.py --root CURRENT --json

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.lib import cio_corpus_index as corpus  # noqa: E402
from scripts.lib import cio_research_budget as budget  # noqa: E402
from scripts.lib import cio_research_gate as gate  # noqa: E402
from scripts.lib import cio_residual_web as residual  # noqa: E402


SCHEMA = "CIOResearchGovernanceCensus@v1"
AUTHORITY = "READ_ONLY_ADVISORY"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exists(root: Path, *parts: str) -> dict[str, Any]:
    p = root.joinpath(*parts)
    out: dict[str, Any] = {"path": str(p), "exists": p.is_file() or p.is_dir()}
    if p.is_file():
        try:
            out["bytes"] = p.stat().st_size
            if p.suffix == ".jsonl":
                out["lines"] = sum(1 for line in p.open(encoding="utf-8", errors="replace") if line.strip())
        except OSError as exc:
            out["error"] = str(exc)
    return out


def _fred_layer(root: Path) -> dict[str, Any]:
    """Free-first macro: FRED/Fed/gov series on disk + provider docs."""
    series_dir = root / "reference" / "library" / "series"
    fred_files = sorted(p.name for p in series_dir.glob("fred_*.csv")) if series_dir.is_dir() else []
    ff_files = sorted(p.name for p in series_dir.glob("ff_*.csv")) if series_dir.is_dir() else []
    provider_doc = root / "docs" / "financial-senses" / "FRED_ALFRED_PROVIDER.md"
    ingest = root / "scripts" / "fred_data_ingest.py"
    free_first = root / "scripts" / "free_first_refresh.py"
    return {
        "layer": "free_research",
        "fred_series_on_disk": fred_files,
        "fred_series_count": len(fred_files),
        "ff_factor_files": ff_files,
        "provider_doc_exists": provider_doc.is_file(),
        "ingest_script_exists": ingest.is_file(),
        "free_first_refresh_exists": free_first.is_file(),
        "api_key_env_names": ["FRED_API_KEY"],
        "note": (
            "Without FRED_API_KEY the financial-senses provider returns "
            "NOT_CONFIGURED honestly; on-disk reference series remain usable "
            "for free-first / RAG context."
        ),
    }


def _code_invariants() -> dict[str, Any]:
    return {
        "research_budget": {
            "schema": budget.SCHEMA,
            "daily_cap": budget.DAILY_CAP,
            "held_slots": budget.HELD_SLOTS,
            "cash_slots": budget.CASH_SLOTS,
            "reentry_or_watch_slots": budget.REENTRY_OR_WATCH_SLOTS,
            "mbi_behavior": budget.MBI_BEHAVIOR,
            "authority": budget.AUTHORITY,
        },
        "residual_web": {
            "max_hops_per_subject_per_day": residual.MAX_HOPS_PER_SUBJECT_PER_DAY,
            "daily_subject_budget": residual.DAILY_SUBJECT_BUDGET,
            "residual_decision_token": residual.RESIDUAL_DECISION
            if hasattr(residual, "RESIDUAL_DECISION")
            else gate.RESIDUAL_DECISION,
            "lane": getattr(residual, "LANE", gate.RESIDUAL_LANE),
        },
        "gate_ladder": {
            "version": gate.GATE_VERSION,
            "decisions": list(gate.DECISIONS),
            "paid_decisions": sorted(gate.PAID_DECISIONS),
            "lane_for": dict(gate.LANE_FOR),
            "free_rungs": ["skip", "reuse", "corpus_hit"],
            "model_rungs": ["flash", "pro", "openai", "grok_critique"],
        },
        "corpus": {
            "closing_grades": sorted(corpus.CLOSING_GRADES),
            "grade_c_or_d_may_corpus_hit": False,
            "law": "only A/B close; C/D/X are context-only / not corpus_hit",
        },
    }


def _store_snapshot(root: Path) -> dict[str, Any]:
    return {
        "instrument_records": _exists(root, "data", "cio", "cio_instrument_records.jsonl"),
        "specialist_artifacts": _exists(root, "data", "cio", "cio_specialist_artifacts.jsonl"),
        "hermes_research_results": _exists(root, "data", "cio", "hermes_research_results.jsonl"),
        "workflow_lineage": _exists(root, "data", "cio", "cio_workflow_lineage.jsonl"),
        "research_budget_ledger": _exists(root, "data", "cio", "cio_research_budget_ledger.jsonl"),
        "plans_projection": _exists(root, "data", "cio", "cio_plans_projection.json"),
    }


def census(root: Path) -> dict[str, Any]:
    inv = _code_invariants()
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "memory_behavior_influence": 0,
        "as_of": _utc(),
        "root": str(root),
        "free_first": _fred_layer(root),
        "invariants": inv,
        "stores": _store_snapshot(root),
        "wave3d_ops_notes": [
            "docs/ops/CIO_WAVE3D_2026-08-29.md",
            "docs/ops/CIO_WAVE3D_HOP_2026-08-29.md",
            "docs/ops/CIO_WAVE3D_FLASH_2026-08-29.md",
            "docs/ops/CIO_WAVE3D_CRITIQUE_2026-08-29.md",
            "docs/ops/CIO_WAVE3D_CRITIQUE_DEEPSEEK_2026-08-29.md",
        ],
        "cited_modules": [
            "scripts/lib/cio_residual_web.py",
            "scripts/lib/cio_research_budget.py",
            "scripts/cio_research_budget_report.py",
            "scripts/lib/cio_research_gate.py",
            "scripts/lib/cio_corpus_index.py",
            "scripts/lib/cio_research_librarian.py",
        ],
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        default=os.environ.get("TRADEAI_ROOT") or str(REPO),
        help="Project / overlay root (default: TRADEAI_ROOT or repo)",
    )
    ap.add_argument("--json", action="store_true", help="Print JSON census")
    ap.add_argument(
        "--write-evidence",
        default="",
        help="Optional path to write the JSON snapshot (read-only census; writes only this file)",
    )
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    doc = census(root)
    text = json.dumps(doc, indent=2, sort_keys=False) + "\n"
    if args.write_evidence:
        out = Path(args.write_evidence)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    if args.json or not args.write_evidence:
        sys.stdout.write(text)
    else:
        print(f"wrote {args.write_evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
