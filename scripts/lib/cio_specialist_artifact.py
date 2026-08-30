"""SpecialistArtifact@v1-lite — the record of one research gate's output.

Wave 3B. `ResearchNeedDecision@v2` decides *which* gate should run; this is the
record of what a gate produced. It is a schema and a validator, not a client:
**nothing here performs HTTP to a vendor.** The writer exists for tests and for
the deterministic council join, and a test asserts the module contains no
network call.

Distinct from `cio_specialist_artifacts.py` (plural), which extracts advisory
positions out of agent handoffs. This one records provider, cost and outcome
for a research artifact so the join and the notification policy have something
auditable to read.

G-SPEC-01 (2026-08-30): *new* writes MUST stamp a non-empty `workflow_id`.
`build()` raises; `append()` returns a structured refusal. Historical jsonl
rows with null/empty workflow_id remain readable (READ_ONLY_ADVISORY —
no silent DELETE/rewrite). `validate()` stays historical-tolerant unless
`new_write=True`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SPECIALIST_ARTIFACT_SCHEMA = "SpecialistArtifact@v1-lite"
AUTHORITY = "READ_ONLY_ADVISORY"

STORE_REL = "data/cio/cio_specialist_artifacts.jsonl"

PROVIDERS = ("stub", "flash", "pro", "openai", "grok_critique", "edgar")
# grok_critique is a real paid-lane provider (free_oauth today, still ledgered).
OUTCOMES = ("VALID", "PARTIAL", "FAIL", "execution_language", "cost_cap")

# Providers that may never be selected from inside this process. The gate
# authorises a paid call; this module only records that one happened.
_NO_LIVE_CALL = True

# G-SPEC-01 new-write bind policy (does not rewrite historical rows).
NEW_WRITE_REQUIRES_WORKFLOW_ID = True
MISSING_WORKFLOW_ID = "missing_workflow_id"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def workflow_id_bound(workflow_id: Any) -> bool:
    """True iff workflow_id is a non-empty string (after strip)."""
    return isinstance(workflow_id, str) and bool(workflow_id.strip())


def build(*, workflow_id: str, plan_id: str | None = None,
          research_id: str | None = None, artifact_id: str,
          provider: str, outcome: str, cost_usd: float = 0.0,
          source_refs: Optional[list[dict[str, Any]]] = None,
          created_at: str | None = None) -> dict[str, Any]:
    """Build one artifact row. Raises on unknown provider/outcome or unbound wf.

    Raising beats coercing: an unrecognised provider silently normalised to
    "stub" would make a paid call look free in the cost ledger. G-SPEC-01:
    null/empty workflow_id raises — builders used in tests should fail loud.
    """
    if not workflow_id_bound(workflow_id):
        raise ValueError(
            "workflow_id is required for new SpecialistArtifact writes "
            f"(G-SPEC-01); got {workflow_id!r}"
        )
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider!r} (expected {PROVIDERS})")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome: {outcome!r} (expected {OUTCOMES})")
    try:
        cost = round(float(cost_usd), 6)
    except (TypeError, ValueError):
        raise ValueError(f"cost_usd must be numeric, got {cost_usd!r}")
    if cost < 0:
        raise ValueError("cost_usd must not be negative")
    if provider == "stub" and cost != 0.0:
        raise ValueError("a stub artifact must cost 0.0")
    return {
        "schema": SPECIALIST_ARTIFACT_SCHEMA,
        "artifact_id": str(artifact_id),
        "workflow_id": str(workflow_id).strip(),
        "plan_id": plan_id,
        "research_id": research_id,
        "provider": provider,
        "cost_usd": cost,
        "outcome": outcome,
        "source_refs": list(source_refs or []),
        "created_at": created_at or _utc(),
        "authority": AUTHORITY,
        "financial_action": False,
    }


def validate(row: dict[str, Any], *, new_write: bool = False) -> list[str]:
    """Return a list of problems. Empty means valid.

    Historical rows with null workflow_id remain structurally valid
    (`new_write=False`, default). New-write path (`new_write=True`) adds
    `missing_workflow_id` when unbound — used by `append()`.
    """
    problems: list[str] = []
    if row.get("schema") != SPECIALIST_ARTIFACT_SCHEMA:
        problems.append("wrong_schema")
    if not row.get("artifact_id"):
        problems.append("missing_artifact_id")
    if row.get("provider") not in PROVIDERS:
        problems.append("bad_provider")
    if row.get("outcome") not in OUTCOMES:
        problems.append("bad_outcome")
    if not isinstance(row.get("cost_usd"), (int, float)):
        problems.append("bad_cost")
    if row.get("financial_action") is not False:
        problems.append("financial_action_must_be_false")
    if new_write and NEW_WRITE_REQUIRES_WORKFLOW_ID and not workflow_id_bound(
        row.get("workflow_id")
    ):
        problems.append(MISSING_WORKFLOW_ID)
    return problems


def store_path(root: Path | str) -> Path:
    return Path(root) / STORE_REL


def append(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    """Append one validated *new-write* artifact.

    Jobs must not crash on missing workflow_id: returns a structured refusal
    (`wrote=False`, `refused=True`, `reason=missing_workflow_id`) instead of
    raising. Does not rewrite or delete historical rows.
    """
    problems = validate(row, new_write=True)
    if problems:
        refused = MISSING_WORKFLOW_ID in problems
        out: dict[str, Any] = {
            "wrote": False,
            "problems": problems,
            "refused": refused,
        }
        if refused:
            out["reason"] = MISSING_WORKFLOW_ID
        return out
    p = store_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"wrote": True, "problems": [], "refused": False, "path": str(p)}


def load(root: Path | str) -> list[dict[str, Any]]:
    p = store_path(root)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
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


def total_cost(rows: list[dict[str, Any]]) -> float:
    return round(sum(float(r.get("cost_usd") or 0) for r in rows), 6)
