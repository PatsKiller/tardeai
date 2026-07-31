"""Domain FLEET critics — risk, vega, maria, pulse, steph, tax (read-only evidence)."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .agents.definitions import spec as fleet_spec
from .contracts import Environment
from .journal import ShadowRunJournal
from .pipeline_common import advisory_payload, load_holdings
from .runtime import MvlRuntime


def _risk_findings(holdings: Mapping[str, Any], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    rows = holdings.get("holdings") if isinstance(holdings.get("holdings"), list) else []
    total = float(holdings.get("portfolio_total") or holdings.get("total_value") or 0)
    if total <= 0:
        return [{"code": "no_holdings", "severity": "warning", "message": "Cannot assess risk — no portfolio total"}]
    max_pct = 0.0
    max_sym = ""
    unprotected = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sym = str(row.get("symbol") or "")
        try:
            mv = float(row.get("market_value") or row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        pct = (mv / total) * 100.0 if total else 0.0
        if pct > max_pct:
            max_pct = pct
            max_sym = sym
        if not row.get("stop_protected") and not row.get("protected"):
            unprotected += 1
    if max_pct > 15.0:
        findings.append(
            {
                "code": "concentration_breach",
                "severity": "high" if max_pct > 25.0 else "warning",
                "message": f"Top concentration {max_sym} at {max_pct:.1f}% of portfolio",
                "symbol": max_sym,
                "weight_pct": round(max_pct, 2),
            }
        )
    if unprotected > 0:
        findings.append(
            {
                "code": "unprotected_positions",
                "severity": "warning" if unprotected < 5 else "high",
                "message": f"{unprotected} positions appear unprotected by stops",
                "count": unprotected,
            }
        )
    if not findings:
        findings.append({"code": "risk_ok", "severity": "info", "message": "Risk evidence within nominal bounds"})
    return findings


def _allocation_findings(holdings: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = holdings.get("holdings") if isinstance(holdings.get("holdings"), list) else []
    total = float(holdings.get("portfolio_total") or holdings.get("total_value") or 0)
    if total <= 0:
        return [{"code": "no_holdings", "severity": "warning", "message": "Cannot review allocation — no total"}]
    income_mv = 0.0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        label = " ".join(
            str(row.get(k) or "") for k in ("asset_class", "category", "sector", "strategy", "name")
        ).lower()
        try:
            mv = float(row.get("market_value") or row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if any(k in label for k in ("dividend", "income", "yield", "bond", "reit")):
            income_mv += mv
    income_pct = (income_mv / total) * 100.0
    findings: list[dict[str, Any]] = []
    if income_pct < 15.0:
        findings.append(
            {
                "code": "income_underweight",
                "severity": "warning",
                "message": f"Income sleeve ~{income_pct:.1f}% vs 25-40% target band",
                "income_pct": round(income_pct, 2),
            }
        )
    else:
        findings.append(
            {
                "code": "allocation_ok",
                "severity": "info",
                "message": f"Income sleeve ~{income_pct:.1f}% within review band",
                "income_pct": round(income_pct, 2),
            }
        )
    return findings


def _symbol_payload_findings(payload: Mapping[str, Any], *, domain: str) -> list[dict[str, Any]]:
    sym = str(payload.get("symbol") or "").upper().strip()
    if not sym:
        return [{"code": "missing_symbol", "severity": "info", "message": f"No symbol in payload for {domain} review"}]
    return [
        {
            "code": f"{domain}_symbol_review",
            "severity": "info",
            "message": f"{domain} review scoped to {sym} — evidence bound to trigger payload",
            "symbol": sym,
            "packet_id": payload.get("packet_id") or payload.get("artifact_id"),
        }
    ]


def _tax_findings(holdings: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = holdings.get("holdings") if isinstance(holdings.get("holdings"), list) else []
    recent_loss = [str(r.get("symbol") or "") for r in rows if isinstance(r, Mapping) and float(r.get("unrealized_pl") or 0) < -500]
    if recent_loss:
        return [
            {
                "code": "wash_sale_watch",
                "severity": "warning",
                "message": f"Tax review: {len(recent_loss)} symbols with material unrealized losses — wash-sale awareness",
                "symbols": recent_loss[:10],
            }
        ]
    return [{"code": "tax_ok", "severity": "info", "message": "No material loss lots flagged in holdings snapshot"}]


_ANALYZERS: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], list[dict[str, Any]]]] = {
    "risk_agent": lambda h, p: _risk_findings(h, p),
    "steph": lambda h, p: _allocation_findings(h),
    "tax_agent": lambda h, p: _tax_findings(h),
    "vega": lambda h, p: _symbol_payload_findings(p, domain="technical"),
    "maria": lambda h, p: _symbol_payload_findings(p, domain="fundamental"),
    "pulse": lambda h, p: _symbol_payload_findings(p, domain="microstructure"),
}

_ARTIFACT_TYPES = {
    "risk_agent": "risk_evidence_critique",
    "steph": "allocation_review",
    "tax_agent": "tax_constraint_review",
    "vega": "technical_structure_review",
    "maria": "research_review",
    "pulse": "microstructure_review",
}


def run_domain_critic(agent_id: str, job_type: str, payload: Mapping[str, Any], persistence, journal_root) -> Mapping[str, Any]:
    agent = fleet_spec(agent_id)
    holdings = load_holdings()
    analyzer = _ANALYZERS.get(agent_id)
    findings = analyzer(holdings, payload) if analyzer else [{"code": "unknown", "severity": "info", "message": "No analyzer"}]
    artifact_type = _ARTIFACT_TYPES.get(agent_id, f"{agent_id}_integrity_review")
    runtime = MvlRuntime(
        definition=agent.definition,
        journal=ShadowRunJournal(journal_root, Environment.SHADOW),
        retrieval_provider=lambda _run_id, _q: [{"ref": f"{agent_id}:holdings", "content": str(len(holdings))}],
        model_provider=lambda _run_id, _req: {"verdict": "ADVISORY", "findings": [f["message"] for f in findings]},
        persistence=persistence,
    )
    run = runtime.start(
        job_type=job_type,
        objective=f"Domain critic review for {agent_id}",
        input_payload=dict(payload),
        validation_payload={"state": "PASS", "source": payload.get("source")},
    )
    if agent.definition.retrieval_required:
        runtime.retrieve(run.run_id, f"{agent_id} evidence")
    body = advisory_payload(
        agent_id=agent_id,
        job_type=job_type,
        source=payload.get("source"),
        findings=findings,
        artifact_kind=artifact_type,
    )
    runtime.create_artifact(
        run.run_id,
        artifact_type=artifact_type,
        payload=body,
        prompt_version="domain-critic-v1",
        provider_family="deterministic",
        model="none",
    )
    status = str(runtime.status(run.run_id).get("status") or "REVIEW_REQUIRED")
    return {"run_id": run.run_id, "status": status, "agent_id": agent_id, "severity": body["severity"]}
