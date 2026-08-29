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
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SPECIALIST_ARTIFACT_SCHEMA = "SpecialistArtifact@v1-lite"
AUTHORITY = "READ_ONLY_ADVISORY"

STORE_REL = "data/cio/cio_specialist_artifacts.jsonl"

PROVIDERS = ("stub", "flash", "pro", "openai", "grok_critique")
OUTCOMES = ("VALID", "PARTIAL", "FAIL", "execution_language", "cost_cap")

# Providers that may never be selected from inside this process. The gate
# authorises a paid call; this module only records that one happened.
_NO_LIVE_CALL = True


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def build(*, workflow_id: str | None = None, plan_id: str | None = None,
          research_id: str | None = None, artifact_id: str,
          provider: str, outcome: str, cost_usd: float = 0.0,
          source_refs: Optional[list[dict[str, Any]]] = None,
          created_at: str | None = None) -> dict[str, Any]:
    """Build one artifact row. Raises on an unknown provider or outcome.

    Raising beats coercing: an unrecognised provider silently normalised to
    "stub" would make a paid call look free in the cost ledger.
    """
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
        "workflow_id": workflow_id,
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


def validate(row: dict[str, Any]) -> list[str]:
    """Return a list of problems. Empty means valid."""
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
    return problems


def store_path(root: Path | str) -> Path:
    return Path(root) / STORE_REL


def append(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    """Append one validated artifact. Used by tests and the join only."""
    problems = validate(row)
    if problems:
        return {"wrote": False, "problems": problems}
    p = store_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"wrote": True, "problems": [], "path": str(p)}


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
