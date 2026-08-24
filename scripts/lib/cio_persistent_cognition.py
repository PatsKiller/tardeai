"""CIO read-only consumption of live ticker cognition.

Consumer integration, not a second research producer and not a memory migration.
Canonical stores remain TickerResearchState + HermesCurationSummary.
CIO stores only its own thesis/decision/output plus references (IDs/versions).

Baseline v0 is legitimate prior cognition. NO_NEW_INFO is not "no brain."
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
from scripts.lib.security_identity import (
    attach_identity_v2,
    classify_unresolved_symbol,
    is_cusip_like,
    normalize_symbol,
)
from scripts.lib.ticker_research_state import state_path

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOPersistentCognition@v1"
PACK_SCHEMA = "CIOCognitionPack@v1"
ENVELOPE_V2 = "CIOContextEnvelope@v2"
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

NO_CHANGE_DECISIONS = {"NO_NEW_INFO", "FRESH_NO_CHANGE"}
NO_CHANGE_WHAT = {"BASELINE_PROJECTION", "NO_NEW_INFO", "FRESH_NO_CHANGE", "NONE"}

FORBIDDEN_TRUTH_KEYS = (
    "quantity",
    "qty",
    "cash",
    "market_value",
    "order_id",
    "stop_id",
    "2fa",
    "broker_account",
    "positions",
)

V2_SECTIONS = (
    "OFFICE_TRUTH",
    "PORTFOLIO_STATE",
    "OPERATOR_POLICY",
    "PORTFOLIO_THESIS",
    "MARKET_CONTEXT",
    "SEASONALITY",
    "TICKER_RESEARCH_STATE",
    "BASELINE_OR_CURRENT_CURATION",
    "SYMBOL_THESIS",
    "RESEARCH_GAPS",
    "CONTRADICTIONS",
    "EVENTS_CATALYSTS",
    "RELEVANT_FEEDBACK",
    "MATURE_OUTCOMES",
    "LESSONS",
    "MEMORY_RETRIEVAL_UNITS",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_cognition_root(explicit: Path | str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.getenv("TRADEAI_CURRENT")
    if env:
        return Path(env)
    return repo_root()


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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def load_states(root: Path | str) -> list[dict[str, Any]]:
    return _jsonl(state_path(root))


def load_state(
    root: Path | str,
    *,
    symbol: str | None = None,
    security_guid: str | None = None,
) -> dict[str, Any] | None:
    """GUID first, then ticker/alias. Last match wins (JSONL current row)."""
    guid_hit = None
    alias_hit = None
    want = normalize_symbol(symbol) if symbol else ""
    for row in load_states(root):
        if security_guid and row.get("security_guid") == security_guid:
            guid_hit = row
        aliases = [normalize_symbol(a) for a in _as_list(row.get("ticker_aliases"))]
        row_sym = normalize_symbol(row.get("symbol"))
        if want and (row_sym == want or want in aliases):
            alias_hit = row
    return guid_hit or alias_hit


def load_curation(root: Path | str, *, symbol: str, security_guid: str | None) -> dict[str, Any] | None:
    """Material summary if present; otherwise BASELINE_PROJECTION v0 is legitimate cognition."""
    return load_latest(root, security_guid=security_guid, symbol=normalize_symbol(symbol))


def resolve_identity(root: Path | str, query: str) -> dict[str, Any]:
    """ticker/alias/CUSIP/fund → security_guid. Does not invent identifiers."""
    raw = str(query or "").strip()
    kind = classify_unresolved_symbol(raw)
    st = load_state(root, symbol=raw)
    if st:
        return {
            "query": raw,
            "resolved": True,
            "kind": kind.get("kind"),
            "symbol": st.get("symbol"),
            "security_guid": st.get("security_guid"),
            "issuer_guid": st.get("issuer_guid"),
            "listing_guid": st.get("listing_guid"),
            "ticker_guid": st.get("ticker_guid"),
            "via": "ticker_research_state",
        }
    ident = attach_identity_v2({"symbol": normalize_symbol(raw)}) if raw and not is_cusip_like(raw) else {}
    return {
        "query": raw,
        "resolved": False,
        "kind": kind.get("kind") or "unresolved",
        "reason": kind.get("reason"),
        "symbol": normalize_symbol(raw) if raw and not is_cusip_like(raw) else None,
        "security_guid": ident.get("security_guid"),
        "issuer_guid": ident.get("issuer_guid"),
        "listing_guid": ident.get("listing_guid"),
        "ticker_guid": ident.get("ticker_guid"),
        "via": "unresolved",
        "cusip_like": is_cusip_like(raw),
    }


def extract_symbols(*blobs: Any) -> list[str]:
    seen: list[str] = []

    def _add(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _add(item)
            return
        if isinstance(value, dict):
            for key in ("symbol", "ticker", "symbols", "tickers"):
                if key in value:
                    _add(value.get(key))
            return
        sym = normalize_symbol(value)
        if sym and 1 <= len(sym) <= 8 and sym not in seen:
            seen.append(sym)

    for blob in blobs:
        if isinstance(blob, dict):
            _add(blob.get("symbols") or blob.get("tickers"))
            ctx = blob.get("context") or blob.get("payload") or {}
            if isinstance(ctx, dict):
                _add(ctx.get("symbols") or ctx.get("tickers") or ctx.get("symbol"))
            holdings = blob.get("holdings") or (blob.get("snapshot") or {}).get("holdings")
            if isinstance(holdings, list):
                for row in holdings:
                    _add(row)
            for key in ("held", "watch", "reentry", "watchlist"):
                _add(blob.get(key))
        elif isinstance(blob, (list, tuple)):
            _add(blob)
        else:
            _add(blob)
    return seen


def classify_role(
    symbol: str,
    *,
    held: set[str],
    watch: set[str],
    reentry: set[str],
    large_exposure: set[str] | None = None,
    cash_deployment: set[str] | None = None,
    thesis: set[str] | None = None,
) -> str:
    s = normalize_symbol(symbol)
    if large_exposure and s in large_exposure:
        return "LARGE_EXPOSURE"
    if s in held:
        return "HELD"
    if s in reentry:
        return "REENTRY"
    if s in watch:
        return "WATCH"
    if cash_deployment and s in cash_deployment:
        return "CASH_DEPLOYMENT"
    if thesis and s in thesis:
        return "PORTFOLIO_THESIS"
    return "OPPORTUNITY"


def _section(
    payload: Any,
    *,
    authority: str,
    source: str,
    version: Any,
    as_of: str | None,
    security_guid: str | None,
    freshness: str | None = None,
    entity_guid: str | None = None,
) -> dict[str, Any]:
    return {
        "authority": authority,
        "source": source,
        "version": version,
        "as_of": as_of,
        "entity_guid": entity_guid or security_guid,
        "security_guid": security_guid,
        "freshness": freshness,
        "payload": payload,
        "overrides_office_truth": False,
        "financial_action": False,
    }


def _unavailable(source: str, *, authority: str = AUTH_RESEARCH) -> dict[str, Any]:
    return _section(
        None,
        authority=authority,
        source=source,
        version=None,
        as_of=None,
        security_guid=None,
        freshness="NOT_CONFIGURED",
    )


def assert_no_truth_override(cognition: dict[str, Any], office_truth: dict[str, Any] | None) -> None:
    """Research context must not replace broker/cash/qty/order/risk/2FA truth."""
    if not office_truth:
        return
    for key in FORBIDDEN_TRUTH_KEYS:
        if key in cognition and office_truth.get(key) is not None:
            if cognition.get(key) != office_truth.get(key):
                raise RuntimeError("COGNITION_MUST_NOT_OVERRIDE_OFFICE_TRUTH")
    # Nested copies of office truth are allowed only under OFFICE_TRUTH section.
    for key in ("cash", "positions", "quantity", "market_value"):
        if key in (cognition.get("view") or {}):
            raise RuntimeError("COGNITION_MUST_NOT_OVERRIDE_OFFICE_TRUTH")


def need_data_gap(
    root: Path | str,
    *,
    symbol: str,
    security_guid: str | None,
    question: str,
) -> dict[str, Any]:
    """Record a ResearchGap. Does not search or call a provider."""
    gap = build_gap(
        security_guid=security_guid,
        symbol=normalize_symbol(symbol),
        reason="cio_need_data",
        question=question,
        materiality="high",
        status="FREE_FIRST_PENDING",
        portfolio_relevance=True,
        thesis_relevance=True,
    )
    return upsert_gap(root, gap)


def assess_delta(
    *,
    prior_watermark: Any = None,
    current_watermark: Any = None,
    conflicted: bool = False,
    role: str = "WATCH",
    decision: str | None = None,
    what_changed: str | None = None,
    curation_kind: str | None = None,
) -> str:
    """Material portfolio delta — not RAG-artifact watermark drift.

    Live M1 proved FRESH_NO_CHANGE / NO_NEW_INFO while graph artifacts grew.
    That must remain NO_PORTFOLIO_CHANGE.
    """
    if conflicted:
        return OUT_THESIS
    dec = str(decision or "").upper()
    what = str(what_changed or "").upper()
    # Live M1: NO_NEW_INFO / BASELINE_PROJECTION even when artifact watermarks drift.
    if dec in NO_CHANGE_DECISIONS or what in NO_CHANGE_WHAT:
        return OUT_NO_CHANGE
    if prior_watermark and current_watermark and prior_watermark != current_watermark:
        if role in {"HELD", "REENTRY", "LARGE_EXPOSURE", "CASH_DEPLOYMENT"}:
            return OUT_REASSESS
        return OUT_THESIS
    if curation_kind == KIND_MATERIAL and what not in NO_CHANGE_WHAT and dec not in NO_CHANGE_DECISIONS:
        if role in {"HELD", "REENTRY", "LARGE_EXPOSURE", "CASH_DEPLOYMENT"}:
            return OUT_REASSESS
        return OUT_THESIS
    return OUT_NO_CHANGE


def _load_symbol_thesis(root: Path | str, symbol: str) -> dict[str, Any]:
    try:
        from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol

        return thesis_fields_for_symbol(symbol, root=root)
    except Exception as exc:
        return {
            "symbol": normalize_symbol(symbol),
            "symbol_thesis_id": None,
            "symbol_thesis_version": None,
            "thesis_state": "INSUFFICIENT_DATA",
            "error": type(exc).__name__,
            "authority": AUTHORITY,
        }


def _state_view(st: dict[str, Any] | None) -> dict[str, Any] | None:
    if not st:
        return None
    return {
        "status": st.get("status") or st.get("freshness"),
        "freshness": st.get("freshness"),
        "decision": st.get("decision"),
        "support_evidence": _as_list(st.get("support_evidence")),
        "counter_evidence": _as_list(st.get("counter_evidence")),
        "open_gaps": _as_list(st.get("open_gaps")),
        "events_catalysts": _as_list(st.get("catalyst_event_guids")),
        "last_material_change": st.get("last_material_change"),
        "next_review_condition": st.get("next_review_reason"),
        "current_curation_id": st.get("current_curation_id"),
        "current_curation_version": st.get("current_curation_version"),
        "updated_at": st.get("updated_at"),
    }


def _curation_view(cur: dict[str, Any] | None) -> dict[str, Any] | None:
    if not cur:
        return None
    return {
        "kind": cur.get("kind"),
        "version": cur.get("version"),
        "curation_id": cur.get("curation_id"),
        "what_we_knew": cur.get("current_conclusion") or cur.get("what_changed"),
        "what_changed": cur.get("what_changed"),
        "evidence_watermark": cur.get("evidence_watermark"),
        "open_gaps": _as_list(cur.get("open_research_gap_ids")),
        "contradictions": _as_list(cur.get("unresolved_contradictions")),
        "freshness": cur.get("freshness_summary"),
        "next_review_condition": cur.get("next_review_condition"),
        "sector_guid": cur.get("sector_guid"),
        "industry_guid": cur.get("industry_guid"),
        "theme_guids": _as_list(cur.get("theme_guids")),
        "symbol_thesis_id": cur.get("current_symbol_thesis_id"),
        "symbol_thesis_version": cur.get("current_symbol_thesis_version"),
        "as_of": cur.get("as_of"),
    }


def cognition_for_symbol(
    root: Path | str,
    symbol: str,
    *,
    held: set[str] | None = None,
    watch: set[str] | None = None,
    reentry: set[str] | None = None,
    office_truth: dict[str, Any] | None = None,
    large_exposure: set[str] | None = None,
) -> dict[str, Any]:
    held = held or set()
    watch = watch or set()
    reentry = reentry or set()
    ident = resolve_identity(root, symbol)
    sym = ident.get("symbol") or normalize_symbol(symbol)
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
    role = classify_role(
        sym,
        held=held,
        watch=watch,
        reentry=reentry,
        large_exposure=large_exposure,
    )
    conflicted = str((st or {}).get("decision") or "").upper() in {"CONFLICTED", "CONTRADICTED"} or str(
        (st or {}).get("status") or ""
    ).upper() == "CONFLICTED"
    ctx_q = build_context(identity=attach_identity_v2({"symbol": sym, "security_guid": sec}), curation=cur, state=st)
    watermark = (st or {}).get("evidence_watermark")
    delta = assess_delta(
        prior_watermark=(cur or {}).get("evidence_watermark"),
        current_watermark=watermark,
        conflicted=conflicted,
        role=role,
        decision=(st or {}).get("decision"),
        what_changed=(cur or {}).get("what_changed"),
        curation_kind=kind,
    )
    thesis = _load_symbol_thesis(root, sym)
    state_view = _state_view(st)
    cur_view = _curation_view(cur)
    as_of = (st or {}).get("updated_at") or (cur or {}).get("as_of") or _now()
    sections = {
        "TICKER_RESEARCH_STATE": _section(
            state_view,
            authority=AUTH_RESEARCH,
            source="data/cio/ticker_research_state.jsonl",
            version=(st or {}).get("updated_at"),
            as_of=as_of,
            security_guid=sec,
            freshness=(st or {}).get("freshness"),
        ),
        "BASELINE_OR_CURRENT_CURATION": _section(
            cur_view,
            authority=AUTH_RESEARCH,
            source="data/cio/hermes_curation_summary.jsonl",
            version=version,
            as_of=(cur or {}).get("as_of"),
            security_guid=sec,
            freshness=(cur or {}).get("freshness_summary"),
        ),
        "SYMBOL_THESIS": _section(
            {
                "symbol_thesis_id": thesis.get("symbol_thesis_id") or (cur or {}).get("current_symbol_thesis_id"),
                "symbol_thesis_version": thesis.get("symbol_thesis_version")
                or (cur or {}).get("current_symbol_thesis_version"),
                "thesis_state": thesis.get("thesis_state"),
            },
            authority=AUTH_BELIEF,
            source="data/cio/cio_theses.jsonl",
            version=thesis.get("symbol_thesis_version"),
            as_of=thesis.get("last_reviewed"),
            security_guid=sec,
            freshness=thesis.get("thesis_state"),
        ),
        "RESEARCH_GAPS": _section(
            _as_list((st or {}).get("open_gaps")) or _as_list((cur or {}).get("open_research_gap_ids")),
            authority=AUTH_RESEARCH,
            source="data/cio/research_gaps.jsonl",
            version=None,
            as_of=as_of,
            security_guid=sec,
        ),
        "CONTRADICTIONS": _section(
            {
                "conflicted": conflicted,
                "support_evidence": _as_list((st or {}).get("support_evidence")),
                "counter_evidence": _as_list((st or {}).get("counter_evidence")),
                "unresolved": _as_list((cur or {}).get("unresolved_contradictions")),
            },
            authority=AUTH_RESEARCH,
            source="TickerResearchState.counter_evidence",
            version=(st or {}).get("updated_at"),
            as_of=as_of,
            security_guid=sec,
        ),
        "EVENTS_CATALYSTS": _section(
            _as_list((st or {}).get("catalyst_event_guids")) or _as_list((cur or {}).get("current_catalyst_guids")),
            authority=AUTH_RESEARCH,
            source="TickerResearchState.catalyst_event_guids",
            version=None,
            as_of=as_of,
            security_guid=sec,
        ),
    }
    out = {
        "schema": SCHEMA,
        "symbol": sym,
        "query": symbol,
        "identity": ident,
        "security_guid": sec,
        "issuer_guid": (st or {}).get("issuer_guid") or ident.get("issuer_guid"),
        "listing_guid": (st or {}).get("listing_guid") or ident.get("listing_guid"),
        "ticker_guid": (st or {}).get("ticker_guid") or ident.get("ticker_guid"),
        "portfolio_role": role,
        "question": ctx_q.get("question") or "WHAT_CHANGED",
        "forbidden_default": ctx_q.get("forbidden_default"),
        "cognition_status": cognition_status,
        "curation_kind": kind,
        "curation_id": (cur or {}).get("curation_id"),
        "curation_version": version,
        "symbol_thesis_id": thesis.get("symbol_thesis_id") or (cur or {}).get("current_symbol_thesis_id"),
        "symbol_thesis_version": thesis.get("symbol_thesis_version")
        or (cur or {}).get("current_symbol_thesis_version"),
        "baseline_is_legitimate_cognition": bool(kind == KIND_BASELINE),
        "canonical_refs": {
            "security_guid": sec,
            "state_updated_at": (st or {}).get("updated_at"),
            "curation_id": (cur or {}).get("curation_id"),
            "curation_version": version,
            "curation_kind": kind,
            "symbol_thesis_id": thesis.get("symbol_thesis_id") or (cur or {}).get("current_symbol_thesis_id"),
            "symbol_thesis_version": thesis.get("symbol_thesis_version")
            or (cur or {}).get("current_symbol_thesis_version"),
            "gap_ids": _as_list((st or {}).get("open_gaps")) or _as_list((cur or {}).get("open_research_gap_ids")),
        },
        "view": state_view,
        "curation_view": cur_view,
        "open_gaps": _as_list((st or {}).get("open_gaps")) or _as_list((cur or {}).get("open_research_gap_ids")),
        "support_evidence": _as_list((st or {}).get("support_evidence")),
        "counter_evidence": _as_list((st or {}).get("counter_evidence")),
        "evidence_watermark": watermark,
        "freshness": (st or {}).get("freshness"),
        "next_review_condition": (st or {}).get("next_review_reason") or (cur or {}).get("next_review_condition"),
        "conflicted": conflicted,
        "recommendation_suppressed": conflicted,
        "portfolio_delta": delta,
        "authority_class": AUTH_RESEARCH,
        "authority": AUTHORITY,
        "financial_action": False,
        "paid_dispatch": 0,
        "llm_eligible": None,
        "sections": sections,
        "no_cognition": cur is None and st is None,
        "advisory": {
            "security_guid": sec,
            "research_state_version": (st or {}).get("updated_at"),
            "curation_version": version,
            "curation_id": (cur or {}).get("curation_id"),
        },
    }
    if kind == KIND_BASELINE:
        out["baseline_is_legitimate_cognition"] = True
        out["no_cognition"] = False
    elif cur is None and st is None:
        out["no_cognition"] = True
    else:
        out["no_cognition"] = False
    assert_no_truth_override(out, office_truth)
    return out


def receipt(
    *,
    run_id: str,
    agent: str,
    task: str,
    row: dict[str, Any],
    why: str,
    source_sha: str,
) -> dict[str, Any]:
    refs = row.get("canonical_refs") or {}
    return {
        "schema": RECEIPT_SCHEMA,
        "run_id": run_id,
        "agent": agent,
        "task": task,
        "security_guid": row.get("security_guid"),
        "state_id": refs.get("state_updated_at") or (row.get("view") or {}).get("updated_at"),
        "state_updated_at": refs.get("state_updated_at") or (row.get("view") or {}).get("updated_at"),
        "curation_id": row.get("curation_id"),
        "curation_version": row.get("curation_version"),
        "thesis_id": row.get("symbol_thesis_id"),
        "thesis_version": row.get("symbol_thesis_version"),
        "gap_ids": row.get("open_gaps") or [],
        "memory_ids": [],
        "why_selected": why,
        "source_sha": source_sha,
        "authority": AUTHORITY,
        "financial_action": False,
        "chain_of_thought": False,
    }


def build_cio_context_v2(
    pack: dict[str, Any],
    *,
    office_truth: dict[str, Any] | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Mature ContextEnvelope consumption: CIOContextEnvelope@v2 nested in v1."""
    items = pack.get("items") or []
    first = items[0] if items else {}
    sections = dict((first.get("sections") or {}))
    sections["OFFICE_TRUTH"] = _section(
        office_truth,
        authority=AUTH_FINANCIAL,
        source="office_truth",
        version=(office_truth or {}).get("as_of") if isinstance(office_truth, dict) else None,
        as_of=(office_truth or {}).get("as_of") if isinstance(office_truth, dict) else None,
        security_guid=None,
        freshness="AUTHORITATIVE" if office_truth else "NOT_CONFIGURED",
    )
    sections.setdefault("PORTFOLIO_STATE", _unavailable("cio_portfolio_state_v1", authority=AUTH_FINANCIAL))
    sections.setdefault("OPERATOR_POLICY", _unavailable("operator_investment_policy", authority=AUTH_POLICY))
    sections.setdefault("PORTFOLIO_THESIS", _unavailable("cio_portfolio_thesis_v1", authority=AUTH_BELIEF))
    sections.setdefault("MARKET_CONTEXT", _unavailable("cio_market_context_state", authority=AUTH_RESEARCH))
    sections.setdefault("SEASONALITY", _unavailable("cio_seasonality_state", authority=AUTH_RESEARCH))
    sections.setdefault("RELEVANT_FEEDBACK", _unavailable("cio_operator_ticker_feedback", authority=AUTH_OPERATOR))
    sections.setdefault("MATURE_OUTCOMES", _unavailable("cio_outcome_store", authority=AUTH_HISTORICAL))
    sections.setdefault("LESSONS", _unavailable("advisory_lessons", authority=AUTH_HISTORICAL))
    sections.setdefault(
        "MEMORY_RETRIEVAL_UNITS",
        _section(
            pack.get("receipts") or [],
            authority=AUTH_RESEARCH,
            source="ContextUseReceipt@v1",
            version="v1",
            as_of=pack.get("as_of"),
            security_guid=None,
            freshness="BOUNDED",
        ),
    )
    for name in V2_SECTIONS:
        sections.setdefault(name, _unavailable(name))
    return {
        "schema": ENVELOPE_V2,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "overrides_office_truth": False,
        "financial_action": False,
        "question": pack.get("question"),
        "portfolio_call": pack.get("portfolio_call"),
        "sections": {k: sections[k] for k in V2_SECTIONS},
        "as_of": pack.get("as_of") or _now(),
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
        rank = {"LARGE_EXPOSURE": 0, "HELD": 1, "REENTRY": 2, "WATCH": 3, "CASH_DEPLOYMENT": 4}.get(role, 5)
        ranked.append((rank, normalize_symbol(raw)))
    ranked.sort()
    selected = [s for _, s in ranked[:limit]]
    rows = [
        cognition_for_symbol(
            root, s, held=held_s, watch=watch_s, reentry=reentry_s, office_truth=office_truth
        )
        for s in selected
    ]
    deltas = {r["symbol"]: r["portfolio_delta"] for r in rows}
    if rows and all(v == OUT_NO_CHANGE for v in deltas.values()) and not any(r["conflicted"] for r in rows):
        portfolio_call = OUT_NO_CHANGE
        llm = None
    elif any(r["conflicted"] for r in rows):
        portfolio_call = OUT_THESIS
        llm = "FLASH_ELIGIBLE"
    elif any(v == OUT_REASSESS for v in deltas.values()):
        portfolio_call = OUT_REASSESS
        llm = "FLASH_ELIGIBLE"
    elif any(v == OUT_RESEARCH for v in deltas.values()):
        portfolio_call = OUT_RESEARCH
        llm = None
    else:
        portfolio_call = OUT_THESIS if rows else OUT_NO_CHANGE
        llm = None
    source_sha = ""
    for name in ("SOURCE_COMMIT", "BUILD_SHA"):
        p = Path(root) / name
        if p.is_file():
            source_sha = p.read_text(encoding="utf-8").strip().split()[0]
            break
    receipts = [
        receipt(
            run_id=os.getenv("CIO_RUN_ID") or "cio-cognition",
            agent=agent,
            task=task,
            row=r,
            why=r["portfolio_role"],
            source_sha=source_sha,
        )
        for r in rows
    ]
    token_est = sum(80 + len(json.dumps(r.get("open_gaps") or [])) + len(json.dumps(r.get("canonical_refs") or {})) for r in rows)
    pack = {
        "schema": PACK_SCHEMA,
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
    pack["cio_context_v2"] = build_cio_context_v2(pack, office_truth=office_truth, root=root)
    return pack


def advisory_fields(row: dict[str, Any]) -> dict[str, Any]:
    adv = row.get("advisory") or {}
    return {
        "security_guid": adv.get("security_guid") or row.get("security_guid"),
        "research_state_version": adv.get("research_state_version") or (row.get("view") or {}).get("updated_at"),
        "curation_version": adv.get("curation_version") or row.get("curation_version"),
        "curation_id": adv.get("curation_id") or row.get("curation_id"),
        "authority": AUTHORITY,
        "producer": False,
    }


def telegram_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "security_guid": row.get("security_guid"),
        "ticker_research_state": (row.get("canonical_refs") or {}).get("state_updated_at"),
        "curation_id": row.get("curation_id"),
        "curation_version": row.get("curation_version"),
        "symbol_thesis_id": row.get("symbol_thesis_id"),
        "portfolio_delta": row.get("portfolio_delta"),
        "question": row.get("question"),
        "authority": AUTHORITY,
        "fork": False,
    }


def cross_agent_row(root: Path | str, symbol: str, *, held: set[str] | None = None) -> dict[str, Any]:
    """Same loader for Hermes / CIO / Advisory / Telegram."""
    row = cognition_for_symbol(root, symbol, held=held or set())
    refs = row.get("canonical_refs") or {}
    return {
        "symbol": row.get("symbol"),
        "security_guid": row.get("security_guid"),
        "state_updated_at": refs.get("state_updated_at"),
        "curation_id": row.get("curation_id"),
        "curation_version": row.get("curation_version"),
        "curation_kind": row.get("curation_kind"),
        "symbol_thesis_id": row.get("symbol_thesis_id"),
        "symbol_thesis_version": row.get("symbol_thesis_version"),
        "gap_ids": row.get("open_gaps") or [],
        "evidence_watermark": (
            {"count": len(row.get("evidence_watermark")), "head": list(row.get("evidence_watermark") or [])[:5]}
            if isinstance(row.get("evidence_watermark"), list)
            else row.get("evidence_watermark")
        ),
        "hermes": True,
        "cio": True,
        "advisory": advisory_fields(row),
        "telegram": telegram_fields(row),
        "consistent": True,
    }
