#!/usr/bin/env python3
"""P5 SpecialistArtifact sample audit (N≤100) — read-only.

Loads live/overlay `SpecialistArtifact@v1-lite` rows. When the live store has
fewer than `--limit` rows, projects recent `hermes_research_results` into
SpecialistArtifact-*shaped* fixture rows (explicitly labeled) so bind-rate and
orphan metrics can be measured without new LLM spend.

Qualitative scorecard axes (accuracy / relevance) are **DATA_UNAVAILABLE**
unless a human score is supplied — this package does not call a model.

    python3 scripts/cio_specialist_sample_audit.py \
        --root /path/to/persistent-state --limit 100 --json

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.lib.cio_specialist_artifact import (  # noqa: E402
    SPECIALIST_ARTIFACT_SCHEMA,
    validate,
)

NO_CONSUMER_REASON = (
    "operator-invoked diligence CLI: CIOSpecialistSampleAudit@v1 is a stdout scorecard for Phase 5, not an ingested store contract"
)

SCHEMA = "CIOSpecialistSampleAudit@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _lineage_research_to_workflow(root: Path) -> dict[str, set[str]]:
    rid_to_wfs: dict[str, set[str]] = defaultdict(set)
    for row in _load_jsonl(root / "data" / "cio" / "cio_workflow_lineage.jsonl"):
        nid = row.get("node_id")
        wf = row.get("workflow_id")
        if nid and wf and str(nid).startswith("res_"):
            rid_to_wfs[str(nid)].add(str(wf))
    return rid_to_wfs


def _plans(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "data" / "cio" / "cio_plans_projection.json"
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {
        str(pid): p
        for pid, p in (doc.get("plans") or {}).items()
        if isinstance(p, dict)
    }


def _symbol_to_subjects(root: Path) -> dict[str, set[str]]:
    sym_to: dict[str, set[str]] = defaultdict(set)
    for row in _load_jsonl(root / "data" / "cio" / "cio_instrument_records.jsonl"):
        sk = str(row.get("subject_key") or "")
        if not sk:
            continue
        for s in row.get("symbols") or []:
            sym_to[str(s).upper()].add(sk)
        if ":" in sk:
            sym_to[sk.split(":", 1)[1].upper()].add(sk)
    return sym_to


def _live_artifacts(root: Path) -> list[dict[str, Any]]:
    rows = _load_jsonl(root / "data" / "cio" / "cio_specialist_artifacts.jsonl")
    out = []
    for r in rows:
        if r.get("schema") != SPECIALIST_ARTIFACT_SCHEMA:
            continue
        item = dict(r)
        item["_sample_source"] = "live_overlay"
        out.append(item)
    return out


def _project_hermes(root: Path, need: int, exclude_rids: set[str]) -> list[dict[str, Any]]:
    """Project hermes results into SpecialistArtifact-shaped fixture rows."""
    if need <= 0:
        return []
    results = _load_jsonl(root / "data" / "cio" / "hermes_research_results.jsonl")
    seen: set[str] = set(exclude_rids)
    projected: list[dict[str, Any]] = []
    for r in reversed(results):  # newest first
        rid = str(r.get("research_id") or "")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        provider = "stub"
        # hermes results are not SpecialistArtifact writers; mark fixture.
        row = {
            "schema": SPECIALIST_ARTIFACT_SCHEMA,
            "artifact_id": f"fixture_proj_{rid}",
            "workflow_id": None,  # recovered via lineage join below
            "plan_id": r.get("plan_id"),
            "research_id": rid,
            "provider": provider,
            "cost_usd": 0.0,
            "outcome": "VALID" if r.get("event") == "HERMES_RESEARCH_COMPLETED" else "PARTIAL",
            "source_refs": [
                {
                    "projection": "hermes_research_results",
                    "result_id": r.get("result_id"),
                    "symbol": r.get("symbol"),
                    "actor_id": r.get("actor_id"),
                }
            ],
            "created_at": r.get("created_ts") or r.get("as_of") or _utc(),
            "authority": AUTHORITY,
            "financial_action": False,
            "_sample_source": "fixture_projection_hermes_result",
            "_symbol": r.get("symbol"),
        }
        projected.append(row)
        if len(projected) >= need:
            break
    return projected


def _score_row(
    row: dict[str, Any],
    *,
    rid_to_wfs: dict[str, set[str]],
    plans: dict[str, dict[str, Any]],
    sym_to: dict[str, set[str]],
) -> dict[str, Any]:
    problems = validate({k: v for k, v in row.items() if not str(k).startswith("_")})
    rid = str(row.get("research_id") or "")
    wfs = sorted(rid_to_wfs.get(rid) or set())
    stamped_wf = row.get("workflow_id")
    recovered_wf = wfs[0] if len(wfs) == 1 else None

    pid = str(row.get("plan_id") or "")
    plan = plans.get(pid) or {}
    symbols: list[str] = []
    for s in plan.get("symbols") or []:
        symbols.append(str(s).upper())
    sym = row.get("_symbol")
    if sym and str(sym).upper() not in symbols:
        symbols.append(str(sym).upper())
    subjects: set[str] = set()
    for s in symbols:
        subjects.update(sym_to.get(s) or [])

    # Orphan definitions (structural):
    # - orphan_workflow: no stamped workflow_id AND no recoverable single lineage wf
    # - orphan_instrument: no InstrumentRecord subject via plan/symbol
    orphan_workflow = not stamped_wf and recovered_wf is None
    orphan_instrument = len(subjects) == 0

    # Consistency: schema valid + financial_action false + provider/outcome enums
    consistency = "PASS" if not problems else "FAIL"
    # Traceability: research_id present and (stamped or recoverable) workflow OR plan_id
    if rid and (stamped_wf or recovered_wf or pid):
        traceability = "PASS"
    elif rid or pid:
        traceability = "PARTIAL"
    else:
        traceability = "FAIL"

    return {
        "artifact_id": row.get("artifact_id"),
        "sample_source": row.get("_sample_source"),
        "research_id": rid or None,
        "plan_id": pid or None,
        "provider": row.get("provider"),
        "outcome": row.get("outcome"),
        "workflow_id_stamped": stamped_wf,
        "workflow_ids_via_lineage": wfs,
        "workflow_id_recovered": recovered_wf,
        "same_workflow_bind": bool(stamped_wf or recovered_wf) and len(wfs) <= 1,
        "instrument_subjects": sorted(subjects),
        "same_instrument_record_bind": len(subjects) == 1,
        "orphan_workflow": orphan_workflow,
        "orphan_instrument": orphan_instrument,
        "validate_problems": problems,
        "scorecard": {
            "accuracy": DATA_UNAVAILABLE,
            "relevance": DATA_UNAVAILABLE,
            "consistency": consistency,
            "traceability": traceability,
        },
    }


def audit(root: Path, limit: int = 100) -> dict[str, Any]:
    live = _live_artifacts(root)
    need = max(0, int(limit) - len(live))
    exclude = {str(r.get("research_id")) for r in live if r.get("research_id")}
    fixtures = _project_hermes(root, need, exclude)
    sample = (live + fixtures)[: int(limit)]

    rid_to_wfs = _lineage_research_to_workflow(root)
    plans = _plans(root)
    sym_to = _symbol_to_subjects(root)

    scored = [
        _score_row(r, rid_to_wfs=rid_to_wfs, plans=plans, sym_to=sym_to)
        for r in sample
    ]

    n = len(scored) or 1
    same_wf = sum(1 for s in scored if s["same_workflow_bind"])
    same_ir = sum(1 for s in scored if s["same_instrument_record_bind"])
    orphan_wf = sum(1 for s in scored if s["orphan_workflow"])
    orphan_ir = sum(1 for s in scored if s["orphan_instrument"])
    sources = Counter(s["sample_source"] for s in scored)
    consistency = Counter(s["scorecard"]["consistency"] for s in scored)
    traceability = Counter(s["scorecard"]["traceability"] for s in scored)

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "memory_behavior_influence": 0,
        "as_of": _utc(),
        "root": str(root),
        "limit": int(limit),
        "sample_n": len(scored),
        "sources": dict(sources),
        "live_specialist_artifact_n": len(live),
        "fixture_projection_n": len(fixtures),
        "bind_rates": {
            "same_workflow_id": {
                "count": same_wf,
                "rate": round(same_wf / n, 4),
                "note": (
                    "stamped workflow_id OR single recoverable lineage workflow "
                    "via research_id→node_id; multi-wf counts as not same-bind"
                ),
            },
            "same_instrument_record": {
                "count": same_ir,
                "rate": round(same_ir / n, 4),
                "note": "exactly one InstrumentRecord subject_key via plan/symbol",
            },
        },
        "orphans": {
            "orphan_workflow_count": orphan_wf,
            "orphan_instrument_count": orphan_ir,
            "orphan_workflow_rate": round(orphan_wf / n, 4),
            "orphan_instrument_rate": round(orphan_ir / n, 4),
        },
        "scorecard_summary": {
            "accuracy": DATA_UNAVAILABLE,
            "relevance": DATA_UNAVAILABLE,
            "consistency": dict(consistency),
            "traceability": dict(traceability),
            "honesty": (
                "accuracy/relevance require human or authorized LLM rubric; "
                "this package is READ_ONLY and did not score them"
            ),
        },
        "gap_g_spec_01": {
            "id": "G-SPEC-01",
            "live_store_n": len(live),
            "workflow_id_stamped_on_live": sum(
                1 for r in live if r.get("workflow_id")
            ),
            "finding": (
                "SpecialistArtifact@v1-lite exists; live overlay has very few "
                "rows and does not stamp workflow_id. Same-workflow bind is "
                "recoverable via lineage for some research_ids; InstrumentRecord "
                "last_artifact_id pointer unused on live tip census."
            ),
        },
        "rows": scored,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        default=os.environ.get("TRADEAI_ROOT") or str(REPO),
    )
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-evidence", default="")
    args = ap.parse_args(argv)
    doc = audit(Path(args.root).resolve(), limit=args.limit)
    # Keep committed evidence lean: drop per-row blobs unless writing full path
    text_full = json.dumps(doc, indent=2) + "\n"
    summary = {k: v for k, v in doc.items() if k != "rows"}
    summary["row_artifact_ids"] = [r["artifact_id"] for r in doc["rows"]]
    text_summary = json.dumps(summary, indent=2) + "\n"
    if args.write_evidence:
        out = Path(args.write_evidence)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text_full if out.suffix == ".jsonl" else text_summary, encoding="utf-8")
        # also write full beside summary when .json
        if out.suffix == ".json":
            full = out.with_name(out.stem + "_full.json")
            full.write_text(text_full, encoding="utf-8")
    if args.json or not args.write_evidence:
        sys.stdout.write(text_summary if args.write_evidence else text_full)
    else:
        print(f"wrote {args.write_evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
