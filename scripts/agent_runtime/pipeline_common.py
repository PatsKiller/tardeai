"""Shared helpers for real FLEET critic pipelines."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

Severity = Literal["info", "warning", "high", "critical"]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def load_holdings() -> Mapping[str, Any]:
    path = STATE_DIR / "holdings.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def holdings_total_drift(holdings: Mapping[str, Any]) -> tuple[float | None, float | None, float | None]:
    """Return (declared_total, computed_sum, drift_pct) or Nones if unavailable."""
    rows = holdings.get("holdings") if isinstance(holdings.get("holdings"), list) else []
    declared = holdings.get("portfolio_total") or holdings.get("total_value")
    try:
        declared_f = float(declared) if declared is not None else None
    except (TypeError, ValueError):
        declared_f = None
    computed = 0.0
    counted = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        mv = row.get("market_value") or row.get("value")
        try:
            computed += float(mv)
            counted += 1
        except (TypeError, ValueError):
            continue
    if declared_f is None or counted == 0 or declared_f <= 0:
        return declared_f, computed if counted else None, None
    drift_pct = abs(computed - declared_f) / declared_f * 100.0
    return declared_f, computed, drift_pct


def severity_from_findings(findings: Sequence[Mapping[str, Any]]) -> Severity:
    levels = {str(f.get("severity") or "info").lower() for f in findings}
    if "critical" in levels:
        return "critical"
    if "high" in levels:
        return "high"
    if "warning" in levels:
        return "warning"
    return "info"


def advisory_payload(
    *,
    agent_id: str,
    job_type: str,
    source: Any,
    findings: Sequence[Mapping[str, Any]],
    severity: Severity | None = None,
    artifact_kind: str,
    **extra: Any,
) -> dict[str, Any]:
    sev = severity or severity_from_findings(findings)
    return {
        "agent_id": agent_id,
        "job_type": job_type,
        "source": source,
        "authority": "ADVISORY_ONLY",
        "severity": sev,
        "artifact_kind": artifact_kind,
        "findings": list(findings),
        **extra,
    }


def persistence_factory(persistence: Any):
    return getattr(persistence, "_factory", None)


def load_knowledge_index(persistence: Any):
    """Load RATIFIED+ lessons for retrieval-required agents (fail-closed to empty)."""
    from .knowledge import KnowledgeIndex, KnowledgeRecord

    if persistence is None:
        return KnowledgeIndex([])
    try:
        factory = persistence_factory(persistence)
        if factory is None:
            return KnowledgeIndex([])
        conn = factory()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT lesson_id, lesson_version, lifecycle, title, statement, created_at
            FROM agentic_runtime.kb_lessons
            WHERE lifecycle IN ('RATIFIED', 'DISPUTED', 'OBSERVED')
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
        cols = [d[0] for d in cur.description or ()]
        raw = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
    except Exception:
        return KnowledgeIndex([])
    records = []
    for row in raw:
        records.append(
            KnowledgeRecord(
                record_id=str(row.get("lesson_id")),
                version=int(row.get("lesson_version") or 1),
                kind="LESSON",
                lifecycle=str(row.get("lifecycle") or "OBSERVED").upper(),
                title=str(row.get("title") or ""),
                content=str(row.get("statement") or ""),
                source_refs=(f"lesson:{row.get('lesson_id')}",),
                source_hash="0" * 64,
                valid_from=str(row.get("created_at") or ""),
            )
        )
    return KnowledgeIndex(records)
