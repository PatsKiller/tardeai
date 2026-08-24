"""CIO read-only consumption of live ticker cognition.

Does not copy TickerResearchState into a second store. Does not dispatch
providers. Does not mutate broker/cash/positions. Baseline v0 is legitimate
prior cognition.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.hermes_curation_summary import KIND_BASELINE, KIND_MATERIAL, load_latest
from scripts.lib.hermes_research_context import build_context
from scripts.lib.research_gap import build_gap, upsert_gap
from scripts.lib.security_identity import attach_identity_v2, normalize_symbol
from scripts.lib.ticker_research_state import state_path

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOPersistentCognition@v1"
RECEIPT_SCHEMA = "ContextUseReceipt@v1"

AUTH_FINANCIAL = "AUTHORITATIVE_FINANCIAL_TRUTH"
AUTH_POLICY = "DETERMINISTIC_POLICY"
AUTH_BELIEF = "DURABLE_INVESTMENT_BELIEF"
AUTH_RESEARCH = "RESEARCH_CONTEXT"
AUTH_OPERATOR = "OPERATOR_CONTEXT"
AUTH_HISTORICAL = "HISTORICAL_CONTEXT"

OUT_NO_CHANGE = "NO_PORTFOLIO_CHANGE"
OUT_RESEARCH = "RESEARCH_REQUIRED"
OUT_THESIS = "THESIS_REVIEW_REQUIRED"
OUT_REASSESS = "PORTFOLIO_REASSESSMENT_REQUIRED"
OUT_NOTIFY = "OPERATOR_NOTIFICATION_CANDIDATE"

FORBIDDEN_TRUTH_KEYS = ("quantity", "qty", "cash", "market_value", "order_id", "stop_id", "2fa", "broker_account")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_states(root: Path | str) -> list[dict[str, Any]]:
    return _jsonl(state_path(root))


def load_state(root: Path | str, *, symbol: str | None = None, security_guid: str | None = None) -> dict[str, Any] | None:
    hit = None
    for row in load_states(root):
        if security_guid and row.get("security_guid") == security_guid:
            hit = row
        elif symbol and normalize_symbol(row.get("symbol")) == normalize_symbol(symbol):
            hit = row
    return hit


def load_curation(root: Path | str, *, symbol: str, security_guid: str | None) -> dict[str, Any] | None:
    """Material summary if present; otherwise BASELINE_PROJECTION v0 is legitimate cognition."""
    hit = load_latest(root, security_guid=security_guid, symbol=normalize_symbol(symbol))
    return hit


def classify_role(symbol: str, *, held: set[str], watch: set[str], reentry: set[str]) -> str:
    s = normalize_symbol(symbol)
    if s in held:
        return "HELD"
    if s in reentry:
        return "REENTRY"
    if s in watch:
        return "WATCH"
    return "OPPORTUNITY"


def _section(payload: Any, *, authority: str, source: str, version: Any, as_of: str | None, security_guid: str | None, freshness: str | None = None) -> dict[str, Any]:
    return {
        "authority": authority,
        "source": source,
        "version": version,
        "as_of": as_of,
        "security_guid": security_guid,
        "freshness": freshness,
        "payload": payload,
        "overrides_office_truth": False,
        "financial_action": False,
    }


def assert_no_truth_override(cognition: dict[str, Any], office_truth: dict[str, Any] | None) -> None:
    if not office_truth:
        return
    blob = json.dumps(cognition, default=str)
    for key in FORBIDDEN_TRUTH_KEYS:
        if key in ("2fa",):
            continue
        # cognition must not *set* office truth fields
    for key in ("cash", "positions", "quantity", "market_value"):
        if key in cognition and office_truth.get(key) is not None:
            if cognition.get(key) != office_truth.get(key):
                raise RuntimeError("COGNITION_MUST_NOT_OVERRIDE_OFFICE_TRUTH")


def need_data_gap(root: Path | str, *, symbol: str, security_guid: str | None, question: str) -> dict[str, Any]:
    """Record a ResearchGap. Does not search or call a provider."""
    gap = build_gap(
        security_guid=security_guid,
        symbol=normalize_symbol(symbol),
        reason="cio_need_data",
        question=question,
        materiality="high",
        status="FREE_FIRST_PENDING",
    )
    return upsert_gap(root, gap)


def assess_delta(*, prior_watermark: str | None, current_watermark: str | None, conflicted: bool, role: str) -> str:
    if conflicted:
        return OUT_THESIS
    if prior_watermark and current_watermark and prior_watermark != current_watermark and role in {"HELD", "REENTRY", "LARGE_EXPOSURE", "CASH_DEPLOYMENT"}:
        return OUT_REASSESS
    if prior_watermark and current_watermark and prior_watermark != current_watermark:
        return OUT_THESIS
    return OUT_NO_CHANGE


def cognition_for_symbol(
    root: Path | str,
    symbol: str,
    *,
    held: set[str] | None = None,
    watch: set[str] | None = None,
    reentry: set[str] | None = None,
    office_truth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    held = held or set()
    watch = watch or set()
    reentry = reentry or set()
    sym = normalize_symbol(symbol)
    ident = attach_identity_v2({"symbol": sym})
    st = load_state(root, symbol=sym, security_guid=ident.get("security_guid"))
    sec = (st or {}).get("security_guid") or ident.get("security_guid")
    cur = load_curation(root, symbol=sym, security_guid=sec)
    if cur is None:
        cognition_status = "NO_COGNITION_FILE"
        kind = None
        version = None
    else:
        kind = cur.get("kind")
        version = cur.get("version")
        cognition_status = "MATERIAL" if kind == KIND_MATERIAL else "BASELINE_PROJECTION"
    role = classify_role(sym, held=held, watch=watch, reentry=reentry)
    conflicted = str((st or {}).get("decision") or "").upper() in {"CONFLICTED", "CONTRADICTED"} or str((st or {}).get("status") or "").upper() == "CONFLICTED"
    ctx_q = build_context(identity=ident, curation=cur, state=st)
    watermark = (st or {}).get("evidence_watermark")
    delta = assess_delta(prior_watermark=(cur or {}).get("evidence_watermark"), current_watermark=watermark, conflicted=conflicted, role=role)
    suppress = conflicted
    out = {
        "schema": SCHEMA,
        "symbol": sym,
        "security_guid": sec,
        "issuer_guid": ident.get("issuer_guid") or (st or {}).get("issuer_guid"),
        "listing_guid": ident.get("listing_guid") or (st or {}).get("listing_guid"),
        "ticker_guid": ident.get("ticker_guid") or (st or {}).get("ticker_guid"),
        "portfolio_role": role,
        "question": ctx_q.get("question") or "WHAT_CHANGED",
        "forbidden_default": ctx_q.get("forbidden_default"),
        "cognition_status": cognition_status,
        "curation_kind": kind,
        "curation_id": (cur or {}).get("curation_id"),
        "curation_version": version,
        "baseline_is_legitimate_cognition": kind == KIND_BASELINE or (kind is None and False) or (version == 0 and kind == KIND_BASELINE),
        "ticker_research_state": st,
        "curation": cur,
        "open_gaps": (st or {}).get("open_gaps") or [],
        "support_evidence": (st or {}).get("support_evidence") or [],
        "counter_evidence": (st or {}).get("counter_evidence") or [],
        "evidence_watermark": watermark,
        "freshness": (st or {}).get("freshness"),
        "next_review_condition": (st or {}).get("next_review_reason") or (cur or {}).get("next_review_condition"),
        "conflicted": conflicted,
        "recommendation_suppressed": suppress,
        "portfolio_delta": delta,
        "authority_class": AUTH_RESEARCH,
        "authority": AUTHORITY,
        "financial_action": False,
        "paid_dispatch": 0,
        "llm_eligible": None,
        "sections": {
            "TICKER_RESEARCH_STATE": _section(st, authority=AUTH_RESEARCH, source="data/cio/ticker_research_state.jsonl", version=(st or {}).get("updated_at"), as_of=(st or {}).get("updated_at"), security_guid=sec, freshness=(st or {}).get("freshness")),
            "BASELINE_OR_CURRENT_CURATION": _section(cur, authority=AUTH_RESEARCH, source="data/cio/hermes_curation_summary.jsonl", version=version, as_of=(cur or {}).get("as_of"), security_guid=sec, freshness=(cur or {}).get("freshness_summary")),
        },
    }
    # Baseline v0 is cognition, not absence
    if kind == KIND_BASELINE:
        out["baseline_is_legitimate_cognition"] = True
        out["no_cognition"] = False
    elif cur is None:
        out["no_cognition"] = True
    else:
        out["no_cognition"] = False
    assert_no_truth_override(out, office_truth)
    return out


def receipt(*, run_id: str, agent: str, task: str, row: dict[str, Any], why: str, source_sha: str) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA,
        "run_id": run_id,
        "agent": agent,
        "task": task,
        "security_guid": row.get("security_guid"),
        "state_id": (row.get("ticker_research_state") or {}).get("symbol"),
        "state_updated_at": (row.get("ticker_research_state") or {}).get("updated_at"),
        "curation_id": row.get("curation_id"),
        "curation_version": row.get("curation_version"),
        "gap_ids": row.get("open_gaps") or [],
        "why_selected": why,
        "source_sha": source_sha,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def build_cio_cognition(
    root: Path | str,
    symbols: list[str],
    *,
    held: list[str] | None = None,
    watch: list[str] | None = None,
    reentry: list[str] | None = None,
    office_truth: dict[str, Any] | None = None,
    agent: str = "alex",
    task: str = "cio_reassessment",
    limit: int = 12,
) -> dict[str, Any]:
    """Bounded CIO cognition pack. Does not inject all 120 names."""
    held_s = {normalize_symbol(s) for s in (held or [])}
    watch_s = {normalize_symbol(s) for s in (watch or [])}
    reentry_s = {normalize_symbol(s) for s in (reentry or [])}
    ranked = []
    for raw in symbols:
        role = classify_role(raw, held=held_s, watch=watch_s, reentry=reentry_s)
        rank = {"HELD": 0, "REENTRY": 1, "WATCH": 2}.get(role, 3)
        ranked.append((rank, normalize_symbol(raw)))
    ranked.sort()
    selected = [s for _, s in ranked[:limit]]
    rows = [
        cognition_for_symbol(root, s, held=held_s, watch=watch_s, reentry=reentry_s, office_truth=office_truth)
        for s in selected
    ]
    deltas = {r["symbol"]: r["portfolio_delta"] for r in rows}
    if all(v == OUT_NO_CHANGE for v in deltas.values()) and rows:
        portfolio_call = OUT_NO_CHANGE
        llm = None
    elif any(r["conflicted"] for r in rows):
        portfolio_call = OUT_THESIS
        llm = "FLASH_ELIGIBLE"
    elif any(v == OUT_REASSESS for v in deltas.values()):
        portfolio_call = OUT_REASSESS
        llm = "FLASH_ELIGIBLE"
    else:
        portfolio_call = OUT_THESIS
        llm = None
    source_sha = ""
    for name in ("SOURCE_COMMIT", "BUILD_SHA"):
        p = Path(root) / name
        if p.is_file():
            source_sha = p.read_text(encoding="utf-8").strip().split()[0]
            break
    receipts = [receipt(run_id=os.getenv("CIO_RUN_ID") or "cio-cognition", agent=agent, task=task, row=r, why=r["portfolio_role"], source_sha=source_sha) for r in rows]
    token_est = sum(80 + len(json.dumps(r.get("open_gaps") or [])) for r in rows)
    return {
        "schema": "CIOCognitionPack@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "financial_action": False,
        "paid_dispatch": 0,
        "llm_dispatch": False,
        "llm_eligible": llm,
        "portfolio_call": portfolio_call,
        "question": "WHAT_MATERIAL_THING_CHANGED_FOR_THE_PORTFOLIO",
        "selected": selected,
        "items": rows,
        "receipts": receipts,
        "token_estimate": token_est,
        "counterevidence_count": sum(len(r.get("counter_evidence") or []) for r in rows),
        "open_gap_count": sum(len(r.get("open_gaps") or []) for r in rows),
        "source_sha": source_sha,
        "as_of": _now(),
    }
