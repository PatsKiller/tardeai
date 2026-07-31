"""Argus — deterministic population-integrity scanner (0 model calls)."""
from __future__ import annotations

from typing import Any, Mapping

from .agents.definitions import spec as fleet_spec
from .contracts import Environment
from .journal import ShadowRunJournal
from .pipeline_common import advisory_payload, holdings_total_drift, load_holdings
from .runtime import MvlRuntime


def _scan_population(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    holdings = load_holdings()
    declared, computed, drift_pct = holdings_total_drift(holdings)
    if drift_pct is not None and drift_pct > 1.0:
        findings.append(
            {
                "code": "portfolio_total_drift",
                "severity": "high" if drift_pct > 5.0 else "warning",
                "message": f"Holdings total drift {drift_pct:.2f}% (declared={declared}, computed={computed})",
                "declared_total": declared,
                "computed_total": computed,
                "drift_pct": round(drift_pct, 4),
            }
        )
    rows = holdings.get("holdings") if isinstance(holdings.get("holdings"), list) else []
    symbols = []
    dup_symbols: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        if sym in symbols:
            dup_symbols.add(sym)
        symbols.append(sym)
    for sym in sorted(dup_symbols):
        findings.append(
            {
                "code": "duplicate_holding_symbol",
                "severity": "warning",
                "message": f"Duplicate holding rows for {sym} in holdings.json",
                "symbol": sym,
            }
        )
    if not holdings:
        findings.append(
            {
                "code": "holdings_missing",
                "severity": "warning",
                "message": "holdings.json missing or unreadable — population scan incomplete",
            }
        )
    if not findings:
        findings.append(
            {
                "code": "population_ok",
                "severity": "info",
                "message": "No population integrity exceptions detected in holdings snapshot",
                "holding_count": len(rows),
            }
        )
    return findings


def run_argus(job_type: str, payload: Mapping[str, Any], persistence, journal_root) -> Mapping[str, Any]:
    agent = fleet_spec("argus")
    runtime = MvlRuntime(
        definition=agent.definition,
        journal=ShadowRunJournal(journal_root, Environment.SHADOW),
        retrieval_provider=lambda _run_id, _q: [],
        model_provider=lambda _run_id, _req: {"verdict": "PASS", "findings": []},
        persistence=persistence,
    )
    findings = _scan_population(payload)
    run = runtime.start(
        job_type=job_type,
        objective="Deterministic population integrity scan",
        input_payload=dict(payload),
        validation_payload={"state": "PASS", "source": payload.get("source")},
    )
    body = advisory_payload(
        agent_id="argus",
        job_type=job_type,
        source=payload.get("source"),
        findings=findings,
        artifact_kind="integrity_review",
    )
    runtime.create_artifact(
        run.run_id,
        artifact_type="integrity_review",
        payload=body,
        prompt_version="argus-population-v1",
        provider_family="deterministic",
        model="none",
    )
    status = str(runtime.status(run.run_id).get("status") or "REVIEW_REQUIRED")
    return {"run_id": run.run_id, "status": status, "agent_id": "argus", "severity": body["severity"]}
