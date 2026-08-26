"""AdjudicationReceipt@v1 — persist the decision before durable cognition.

No private chain-of-thought. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "AdjudicationReceipt@v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_receipt(
    *,
    tenant_id: str,
    subject_guid: str,
    predicate: str,
    candidate_fact_ids: list[str],
    selected_fact_id: str | None,
    rejected_fact_ids: list[str],
    policy: str,
    policy_version: str = "v1",
    conflict_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    evidence_refs: list[str] | None = None,
    trace_id: str | None = None,
    source_sha: str | None = None,
) -> dict[str, Any]:
    if not tenant_id:
        raise RuntimeError("TENANT_SCOPE_REQUIRED")
    rec = {
        "schema": SCHEMA,
        "adjudication_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "subject_guid": subject_guid,
        "predicate": predicate,
        "conflict_id": conflict_id,
        "candidate_fact_ids": list(candidate_fact_ids),
        "selected_fact_id": selected_fact_id,
        "rejected_fact_ids": list(rejected_fact_ids),
        "policy": policy,
        "policy_version": policy_version,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "evidence_refs": list(evidence_refs or []),
        "trace_id": trace_id,
        "source_sha": source_sha,
        "recorded_at": _now(),
        "chain_of_thought": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    if rec["chain_of_thought"]:
        raise RuntimeError("PRIVATE_COT_FORBIDDEN")
    return rec
