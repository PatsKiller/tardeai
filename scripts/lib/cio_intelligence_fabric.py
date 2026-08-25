"""Persistent intelligence fabric — projection/receipt lifecycle, not a second truth.

Closes: office change → provenance → entity resolution → graph impact →
materiality → prior cognition → WHAT_CHANGED → research-gap → free-first →
LLM eligibility (no spend) → lifecycle projection.

READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE=0. No broker/order/stop/2FA.
Financial truth stays outside memory. UI is a projection, never an ingestion bus.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from scripts.lib.research_gap import STATUSES as GAP_STATUSES
from scripts.lib.research_gap import build_gap, upsert_gap
from scripts.lib.security_identity import attach_identity_v2, normalize_symbol
from scripts.lib.ticker_knowledge_graph import (
    ENTITY_KINDS,
    build_profile,
    entity_guid,
    graph_path,
    upgrade_record_guids,
)

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA_DELTA = "IntelligenceDeltaReceipt@v1"
SCHEMA_IMPACT = "GraphImpactResolution@v1"
SCHEMA_LIFECYCLE = "IntelligenceLifecycleReceipt@v1"
SCHEMA_PENDING = "FreeFirstPending@v1"
SCHEMA_ENVELOPE_STATUS = "EnvelopeProviderStatus@v1"
SCHEMA_COVERAGE = "IntelligenceCoverageMatrix@v1"
SCHEMA_INVENTORY = "IntelligenceProducerInventory@v1"
SCHEMA_WEB = "WebEvidenceProvenance@v1"

DELTA_PATH = "data/cio/intelligence_delta_receipts.jsonl"
PENDING_PATH = "data/cio/free_first_pending.jsonl"
WEB_PATH = "data/cio/web_evidence_provenance.jsonl"
LIFECYCLE_PATH = "data/cio/intelligence_lifecycle.jsonl"

MATERIALITY = (
    "NO_CHANGE",
    "NON_MATERIAL_CHANGE",
    "MATERIAL_CHANGE",
    "CONFLICT",
    "STALE",
    "DATA_UNAVAILABLE",
)
WAKE_MATERIALITY = frozenset({"MATERIAL_CHANGE", "CONFLICT"})
LLM_STATES = (
    "NO_NEW_INFO",
    "FREE_RESOLVED",
    "LLM_ELIGIBLE",
    "CONFLICT_REVIEW_ELIGIBLE",
    "DEEP_REVIEW_ELIGIBLE",
)
SECTION_STATUS = (
    "OK",
    "EMPTY",
    "NOT_CONFIGURED",
    "UNAVAILABLE",
    "STALE",
    "CONFLICTED",
)
ENVELOPE_SECTIONS = (
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
SAME_BRAIN_AGENTS = (
    "alex",
    "hermes",
    "advisory",
    "telegram",
    "maria",
    "steph",
    "guardian",
    "ledger",
    "command_center",
)
FREE_FIRST_ORDER = (
    "TICKER_RESEARCH_STATE",
    "HERMES",
    "RAG",
    "STRUCTURED",
    "SEARXNG",
)
GENERIC_QUERY_RE = re.compile(
    r"^\s*[A-Z0-9.\-]{1,8}\s+earnings\s+catalyst\s+20\d{2}\s*$",
    re.IGNORECASE,
)
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
    "credentials",
    "password",
    "token",
)
COVERAGE_FLAGS = (
    "SOURCE_EXISTS",
    "IDENTITY_RESOLVED",
    "MATERIALITY_SUPPORTED",
    "PERSISTENT_STATE_SUPPORTED",
    "CONTEXT_ENVELOPE_SUPPORTED",
    "GUI_VISIBLE",
    "RESEARCH_TRIGGER_SUPPORTED",
    "OUTCOME_LINKED",
)
EXPOSURE_MIN = 0.3
STALE_SECONDS = 14 * 24 * 3600

# Live producer catalog — inspected against the repo, not invented names.
# current_wiring is pre-fabric (honest). missing_wiring is what this module closes.
_PRODUCERS: tuple[dict[str, Any], ...] = (
    {"producer_id": "holdings", "canonical_source": "data/portfolios/state/holdings.json", "schema": "HoldingsSnapshot", "entity_scope": "security", "authority_class": "AUTHORITATIVE_FINANCIAL_TRUTH", "memory_eligible": False, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "positions", "canonical_source": "scripts/lib/cio_office_state.py", "schema": "PositionRow", "entity_scope": "security", "authority_class": "AUTHORITATIVE_FINANCIAL_TRUTH", "memory_eligible": False, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "cash", "canonical_source": "scripts/lib/cio_cash_capital_v1.py", "schema": "CashDeploymentSituation@v1", "entity_scope": "portfolio", "authority_class": "AUTHORITATIVE_FINANCIAL_TRUTH", "memory_eligible": False, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "portfolio_allocation", "canonical_source": "scripts/lib/cio_portfolio_state_v1.py", "schema": "PortfolioState@v1", "entity_scope": "portfolio", "authority_class": "AUTHORITATIVE_FINANCIAL_TRUTH", "memory_eligible": False, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": False}},
    {"producer_id": "risk", "canonical_source": "scripts/lib/cio_situation_state.py", "schema": "CIOSituationState@v1", "entity_scope": "portfolio", "authority_class": "DETERMINISTIC_POLICY", "memory_eligible": False, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "stop_advisory", "canonical_source": "scripts/lib/cio_advisory_synthesis.py", "schema": "AdvisoryStopState", "entity_scope": "security", "authority_class": "READ_ONLY_ADVISORY", "memory_eligible": False, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "watch_reentry", "canonical_source": "scripts/lib/cio_office_state.py", "schema": "ReentryClassification", "entity_scope": "security", "authority_class": "READ_ONLY_ADVISORY", "memory_eligible": False, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "symbol_thesis", "canonical_source": "data/cio/cio_theses.jsonl", "schema": "SymbolThesis", "entity_scope": "security", "authority_class": "DURABLE_INVESTMENT_BELIEF", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": True}},
    {"producer_id": "portfolio_thesis", "canonical_source": "scripts/lib/cio_portfolio_thesis_v1.py", "schema": "PortfolioThesis@v1", "entity_scope": "portfolio", "authority_class": "DURABLE_INVESTMENT_BELIEF", "memory_eligible": True, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": True}},
    {"producer_id": "sector_rotation", "canonical_source": "scripts/lib/cio_sector_opportunity.py", "schema": "SectorOpportunity", "entity_scope": "sector", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": False, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": False}},
    {"producer_id": "industry", "canonical_source": "scripts/lib/industry_momentum.py", "schema": "IndustryMomentum", "entity_scope": "industry", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": False, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": False}},
    {"producer_id": "macro_regime", "canonical_source": "scripts/lib/cio_market_context_state.py", "schema": "MarketContextState@v1", "entity_scope": "macro", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": False}},
    {"producer_id": "breadth", "canonical_source": "scripts/lib/cio_market_context_state.py", "schema": "MarketContextState@v1", "entity_scope": "macro", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": False, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": False}},
    {"producer_id": "rates", "canonical_source": "scripts/lib/cio_market_context_state.py", "schema": "MarketContextState@v1", "entity_scope": "macro", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": False, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": False}},
    {"producer_id": "volatility", "canonical_source": "scripts/lib/cio_market_context_state.py", "schema": "MarketContextState@v1", "entity_scope": "macro", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": False, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": False}},
    {"producer_id": "seasonality", "canonical_source": "scripts/lib/cio_seasonality_state.py", "schema": "SeasonalityState@v1", "entity_scope": "calendar", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": False}},
    {"producer_id": "catalysts", "canonical_source": "scripts/lib/catalyst_domain.py", "schema": "CatalystEvent", "entity_scope": "catalyst", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "earnings", "canonical_source": "scripts/lib/catalyst_domain.py", "schema": "CatalystEvent", "entity_scope": "catalyst", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "sec_primary", "canonical_source": "hermes_research_intelligence", "schema": "HermesResearchRow", "entity_scope": "security", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "news", "canonical_source": "scripts/lib/free_first_circulation.py", "schema": "StructuredEvidence", "entity_scope": "security", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "hermes_research", "canonical_source": "data/cio/hermes_research_results.jsonl", "schema": "HermesResearchResult", "entity_scope": "security", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": True}},
    {"producer_id": "rag", "canonical_source": "scripts/lib/artifact_embed.py", "schema": "TickerResearchArtifact@v1", "entity_scope": "security", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "operator_policy", "canonical_source": "scripts/lib/cio_operator_investment_policy.py", "schema": "OperatorInvestmentPolicy@v1", "entity_scope": "portfolio", "authority_class": "DETERMINISTIC_POLICY", "memory_eligible": False, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": False}},
    {"producer_id": "operator_feedback", "canonical_source": "data/cio/operator_ticker_feedback.jsonl", "schema": "OperatorTickerFeedback@v1", "entity_scope": "security", "authority_class": "OPERATOR_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": True}},
    {"producer_id": "notifications", "canonical_source": "scripts/lib/cio_notification_signal.py", "schema": "NotificationDecision", "entity_scope": "portfolio", "authority_class": "ORCHESTRATION", "memory_eligible": False, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": True}},
    {"producer_id": "specialist_artifacts", "canonical_source": "scripts/lib/cio_r13_institution.py", "schema": "SpecialistArtifact@v1", "entity_scope": "security", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": False, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": True}},
    {"producer_id": "action_ledger", "canonical_source": "scripts/lib/cio_action_ledger.py", "schema": "CIOAction", "entity_scope": "portfolio", "authority_class": "ORCHESTRATION", "memory_eligible": False, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": False, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": True}},
    {"producer_id": "plans", "canonical_source": "scripts/lib/cio_plans.py", "schema": "CIOPlan", "entity_scope": "security", "authority_class": "DURABLE_INVESTMENT_BELIEF", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": True}},
    {"producer_id": "research_challenges", "canonical_source": "data/cio/hermes_challenge_queue.jsonl", "schema": "HermesChallenge", "entity_scope": "security", "authority_class": "RESEARCH_CONTEXT", "memory_eligible": True, "research_trigger_eligible": True, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": True, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": False, "GUI_VISIBLE": False, "RESEARCH_TRIGGER_SUPPORTED": True, "OUTCOME_LINKED": False}},
    {"producer_id": "outcomes", "canonical_source": "scripts/lib/cio_outcome_store.py", "schema": "CIOOutcome", "entity_scope": "decision", "authority_class": "HISTORICAL_CONTEXT", "memory_eligible": True, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": False, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": True}},
    {"producer_id": "lessons", "canonical_source": "scripts/lib/memory_consolidator.py", "schema": "LessonCandidate@v1", "entity_scope": "decision", "authority_class": "HISTORICAL_CONTEXT", "memory_eligible": True, "research_trigger_eligible": False, "coverage": {"SOURCE_EXISTS": True, "IDENTITY_RESOLVED": True, "MATERIALITY_SUPPORTED": False, "PERSISTENT_STATE_SUPPORTED": True, "CONTEXT_ENVELOPE_SUPPORTED": True, "GUI_VISIBLE": True, "RESEARCH_TRIGGER_SUPPORTED": False, "OUTCOME_LINKED": True}},
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _strip_truth(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in FORBIDDEN_TRUTH_KEYS:
        out.pop(key, None)
    return out


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append_locked(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)


# ── Wave 1: inventory + coverage ──────────────────────────────────────────


def producer_inventory(*, as_of: str | None = None) -> dict[str, Any]:
    producers = []
    for raw in _PRODUCERS:
        cov = dict(raw["coverage"])
        missing = [flag for flag in COVERAGE_FLAGS if not cov.get(flag)]
        producers.append({
            "producer_id": raw["producer_id"],
            "canonical_source": raw["canonical_source"],
            "schema": raw["schema"],
            "entity_scope": raw["entity_scope"],
            "as_of": as_of or _now(),
            "freshness": "LIVE_SOURCE_DECLARED",
            "authority_class": raw["authority_class"],
            "subject_identity": raw["entity_scope"],
            "consumer_paths": ["cio_intelligence_fabric.process_observation", "GET /api/v3/cio/brain"],
            "memory_eligible": raw["memory_eligible"],
            "research_trigger_eligible": raw["research_trigger_eligible"],
            "current_wiring": "PARTIAL" if missing else "FULL",
            "missing_wiring": missing,
            "gui_is_producer": False,
        })
    return {
        "schema": SCHEMA_INVENTORY,
        "as_of": as_of or _now(),
        "producers": producers,
        "source_domains_total": len(producers),
        "ui_is_producer": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def coverage_matrix() -> dict[str, Any]:
    rows = []
    counts = {"FULL": 0, "PARTIAL": 0, "UNWIRED": 0}
    for raw in _PRODUCERS:
        cov = dict(raw["coverage"])
        present = sum(1 for flag in COVERAGE_FLAGS if cov.get(flag))
        if not cov.get("SOURCE_EXISTS"):
            wiring = "UNWIRED"
        elif present == len(COVERAGE_FLAGS):
            wiring = "FULL"
        else:
            wiring = "PARTIAL"
        counts[wiring] += 1
        rows.append({
            "producer_id": raw["producer_id"],
            "wiring": wiring,
            **{flag: bool(cov.get(flag)) for flag in COVERAGE_FLAGS},
            "missing": [flag for flag in COVERAGE_FLAGS if not cov.get(flag)],
        })
    return {
        "schema": SCHEMA_COVERAGE,
        "rows": rows,
        "counts": counts,
        "not_connected": [r["producer_id"] for r in rows if r["wiring"] != "FULL"],
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


# ── Wave 2: delta receipt + materiality + idempotency ─────────────────────


def classify_materiality(
    *,
    before_hash: str | None,
    after_hash: str | None,
    available: bool = True,
    stale: bool = False,
    conflict: bool = False,
    material_fields_changed: bool = False,
    any_change: bool = False,
) -> str:
    if not available:
        return "DATA_UNAVAILABLE"
    if conflict:
        return "CONFLICT"
    if stale:
        return "STALE"
    if not after_hash:
        return "DATA_UNAVAILABLE"
    if before_hash and before_hash == after_hash:
        return "NO_CHANGE"
    if material_fields_changed:
        return "MATERIAL_CHANGE"
    if any_change or (before_hash and before_hash != after_hash):
        return "NON_MATERIAL_CHANGE"
    return "NO_CHANGE"


def delta_id(*, source_domain: str, source_ref: str, source_version: str, after_hash: str) -> str:
    return _sha({
        "source_domain": source_domain,
        "source_ref": source_ref,
        "source_version": source_version,
        "after_hash": after_hash,
    })[:32]


def build_delta_receipt(
    *,
    source_domain: str,
    source_ref: str,
    source_version: str,
    entity_guid_value: str | None,
    entity_type: str,
    change_type: str,
    before_hash: str | None,
    after_hash: str | None,
    materiality: str,
    freshness: str,
    affected_entity_guids: list[str] | None = None,
    research_relevance: bool = False,
    portfolio_relevance: bool = False,
    policy_relevance: bool = False,
    reason: str = "",
    as_of: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    mat = materiality if materiality in MATERIALITY else "DATA_UNAVAILABLE"
    etype = str(entity_type or "").lower()
    if etype not in ENTITY_KINDS and etype not in {"security", "portfolio", "macro", "decision", "policy"}:
        etype = "ticker"
    receipt = {
        "schema": SCHEMA_DELTA,
        "delta_id": delta_id(
            source_domain=source_domain,
            source_ref=str(source_ref),
            source_version=str(source_version),
            after_hash=str(after_hash or ""),
        ),
        "source_domain": source_domain,
        "source_ref": str(source_ref),
        "source_version": str(source_version),
        "observed_at": observed_at or _now(),
        "as_of": as_of or _now(),
        "entity_guid": entity_guid_value,
        "entity_type": etype,
        "change_type": change_type,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "materiality": mat,
        "freshness": freshness,
        "affected_entity_guids": list(affected_entity_guids or ([entity_guid_value] if entity_guid_value else [])),
        "research_relevance": bool(research_relevance),
        "portfolio_relevance": bool(portfolio_relevance),
        "policy_relevance": bool(policy_relevance),
        "reason": str(reason or "")[:400],
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "second_portfolio_truth": False,
    }
    return _strip_truth(receipt)


def upsert_delta(root: Path | str, receipt: dict[str, Any]) -> dict[str, Any]:
    """Same source version/change → one receipt. Replay is a no-op."""
    path = Path(root) / DELTA_PATH
    wanted = receipt.get("delta_id")
    for row in _jsonl(path):
        if row.get("delta_id") == wanted:
            return {"wrote": False, "reason": "IDEMPOTENT_REPLAY", "receipt": row, "duplicate": True}
    clean = _strip_truth(receipt)
    _append_locked(path, clean)
    return {"wrote": True, "reason": "APPENDED", "receipt": clean, "duplicate": False}


# ── Wave 3: graph impact ──────────────────────────────────────────────────


def _edge_status(edge: dict[str, Any], *, now: datetime) -> str:
    status = str(edge.get("status") or "CONFIRMED").upper()
    if status in {"DISPUTED", "STALE", "CANDIDATE", "CONFIRMED"}:
        pass
    else:
        status = "CANDIDATE"
    valid_to = _parse_ts(edge.get("valid_to"))
    if valid_to and valid_to < now:
        return "STALE"
    confirmed = _parse_ts(edge.get("last_confirmed_at") or edge.get("observed_at"))
    if confirmed and (now - confirmed).total_seconds() > STALE_SECONDS:
        return "STALE"
    if str(edge.get("freshness") or "").upper() == "STALE":
        return "STALE"
    return status


def _memberships(profile: dict[str, Any]) -> set[str]:
    return {str(x).upper() for x in (profile.get("memberships") or []) if x}


def _exposure(profile: dict[str, Any], kind: str) -> float:
    explicit = profile.get(f"{kind}_exposure")
    try:
        if explicit is not None:
            return float(explicit)
    except (TypeError, ValueError):
        pass
    memberships = _memberships(profile)
    if memberships & {"HELD", "T0-HOLD"}:
        return 1.0
    if memberships & {"WATCH", "REENTRY", "PROPOSAL", "T1-WATCH", "T0-PROP"}:
        return 0.55
    if kind in {"ticker", "issuer", "catalyst", "calendar"}:
        return 1.0
    if kind == "peer":
        return 0.2
    return 0.4


def _override_status(profile: dict[str, Any], target_guid: str, *, now: datetime) -> str | None:
    overrides = profile.get("relationship_overrides") or {}
    if not isinstance(overrides, dict):
        return None
    raw = overrides.get(target_guid) or overrides.get(str(target_guid))
    if isinstance(raw, str):
        return raw.upper()
    if isinstance(raw, dict):
        return _edge_status(raw, now=now)
    return None


def resolve_impact(
    delta: dict[str, Any],
    profiles: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    exposure_min: float = EXPOSURE_MIN,
) -> dict[str, Any]:
    """Wake only confirmed, fresh, exposed members. Never shared-industry text."""
    now = now or datetime.now(timezone.utc)
    entity = delta.get("entity_guid")
    etype = str(delta.get("entity_type") or "ticker").lower()
    materiality = str(delta.get("materiality") or "")
    freshness = str(delta.get("freshness") or "FRESH").upper()
    affected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def reject(profile: dict[str, Any], reason: str) -> None:
        rejected.append({
            "symbol": profile.get("symbol"),
            "ticker_guid": profile.get("ticker_guid"),
            "reason": reason,
        })

    if materiality not in WAKE_MATERIALITY or freshness == "STALE":
        return {
            "schema": SCHEMA_IMPACT,
            "delta_id": delta.get("delta_id"),
            "affected": [],
            "wake_symbols": [],
            "context_only": [],
            "rejected": [{"reason": "NON_MATERIAL_OR_STALE_DELTA", "materiality": materiality, "freshness": freshness}],
            "authority": AUTHORITY,
            "financial_action": False,
            "inferred_from_shared_industry_text": False,
        }

    for raw in profiles:
        profile = attach_identity_v2(dict(raw))
        symbol = normalize_symbol(profile.get("symbol"))
        if not symbol:
            continue
        ticker_guid = profile.get("ticker_guid") or entity_guid("ticker", symbol)
        security = profile.get("security_guid")
        hit_kind = None
        thesis_evidence = False
        context_only = False
        membership = False

        if etype in {"ticker", "security"} and entity and entity in {ticker_guid, security, profile.get("listing_guid")}:
            hit_kind = "ticker"
            membership = True
            thesis_evidence = True
        elif etype == "issuer" and entity and entity == profile.get("issuer_guid"):
            hit_kind = "issuer"
            membership = True
            thesis_evidence = True
        elif etype == "sector" and entity and entity == profile.get("sector_guid"):
            hit_kind = "sector"
            membership = True
            thesis_evidence = True
        elif etype == "industry" and entity and entity == profile.get("industry_guid"):
            hit_kind = "industry"
            membership = True
            thesis_evidence = True
        elif etype == "subindustry" and entity and entity == profile.get("subindustry_guid"):
            hit_kind = "subindustry"
            membership = True
            thesis_evidence = True
        elif etype == "theme" and entity and entity in (profile.get("theme_guids") or []):
            hit_kind = "theme"
            membership = True
            thesis_evidence = True
        elif etype in {"ticker", "security"} and entity and entity in (profile.get("peer_guids") or []):
            hit_kind = "peer"
            membership = True
            thesis_evidence = False
            context_only = True
        elif etype == "catalyst" and entity and entity in (profile.get("catalyst_guids") or []):
            hit_kind = "catalyst"
            membership = True
            thesis_evidence = True
        elif etype == "calendar" and entity and entity in (profile.get("calendar_event_guids") or []):
            hit_kind = "calendar"
            membership = True
            thesis_evidence = True

        # False-positive isolation: industry/sector *text* without GUID membership.
        if hit_kind is None:
            if etype == "industry" and str(profile.get("industry") or "").strip():
                reject(profile, "SHARED_INDUSTRY_TEXT_WITHOUT_GUID_MEMBERSHIP")
            elif etype == "sector" and str(profile.get("sector") or "").strip():
                reject(profile, "SHARED_SECTOR_TEXT_WITHOUT_GUID_MEMBERSHIP")
            continue

        if not membership:
            reject(profile, "NO_MEMBERSHIP")
            continue

        rel_status = _override_status(profile, str(entity), now=now)
        if rel_status is None:
            rel_status = "CONFIRMED"
            for edge in profile.get("relationships") or []:
                if not isinstance(edge, dict):
                    continue
                if str(edge.get("target_guid")) == str(entity) or str(edge.get("source_guid")) == str(entity):
                    rel_status = _edge_status(edge, now=now)
                    break
        if rel_status == "DISPUTED":
            reject(profile, "DISPUTED_RELATIONSHIP")
            continue
        if rel_status == "STALE":
            reject(profile, "STALE_RELATIONSHIP")
            continue
        if rel_status == "CANDIDATE" and hit_kind not in {"peer"}:
            reject(profile, "CANDIDATE_RELATIONSHIP_NOT_CONFIRMED")
            continue

        exposure = _exposure(profile, hit_kind)
        if hit_kind in {"sector", "industry", "subindustry", "theme"} and exposure < exposure_min:
            reject(profile, "EXPOSURE_BELOW_THRESHOLD")
            continue
        if hit_kind == "peer":
            # Peer is context, never automatic thesis evidence and never a research wake.
            affected.append({
                "symbol": symbol,
                "ticker_guid": ticker_guid,
                "security_guid": security,
                "issuer_guid": profile.get("issuer_guid"),
                "sector_guid": profile.get("sector_guid"),
                "industry_guid": profile.get("industry_guid"),
                "theme_guids": list(profile.get("theme_guids") or []),
                "peer_guids": list(profile.get("peer_guids") or []),
                "hit_kind": hit_kind,
                "membership": True,
                "exposure": exposure,
                "relationship_status": rel_status,
                "wake_research": False,
                "thesis_evidence": False,
                "context_only": True,
            })
            continue

        affected.append({
            "symbol": symbol,
            "ticker_guid": ticker_guid,
            "security_guid": security,
            "issuer_guid": profile.get("issuer_guid"),
            "sector_guid": profile.get("sector_guid"),
            "industry_guid": profile.get("industry_guid"),
            "theme_guids": list(profile.get("theme_guids") or []),
            "peer_guids": list(profile.get("peer_guids") or []),
            "hit_kind": hit_kind,
            "membership": True,
            "exposure": exposure,
            "relationship_status": rel_status,
            "wake_research": True,
            "thesis_evidence": thesis_evidence,
            "context_only": context_only,
        })

    wake = [a["symbol"] for a in affected if a.get("wake_research")]
    context = [a["symbol"] for a in affected if a.get("context_only")]
    return {
        "schema": SCHEMA_IMPACT,
        "delta_id": delta.get("delta_id"),
        "entity_guid": entity,
        "entity_type": etype,
        "affected": affected,
        "wake_symbols": wake,
        "context_only": context,
        "rejected": rejected,
        "security_guids": [a.get("security_guid") for a in affected if a.get("security_guid")],
        "issuer_guids": sorted({a.get("issuer_guid") for a in affected if a.get("issuer_guid")}),
        "sector_guids": sorted({a.get("sector_guid") for a in affected if a.get("sector_guid")}),
        "industry_guids": sorted({a.get("industry_guid") for a in affected if a.get("industry_guid")}),
        "theme_guids": sorted({g for a in affected for g in (a.get("theme_guids") or [])}),
        "peer_guids": sorted({g for a in affected for g in (a.get("peer_guids") or [])}),
        "authority": AUTHORITY,
        "financial_action": False,
        "inferred_from_shared_industry_text": False,
    }


def load_graph_profiles(root: Path | str) -> list[dict[str, Any]]:
    rows = []
    path = graph_path(root)
    for row in _jsonl(path):
        upgraded = upgrade_record_guids(row)
        if upgraded.get("schema") == "TickerKnowledgeProfile@v1" or (
            upgraded.get("ticker_guid") and not upgraded.get("research_artifact_guid")
        ):
            rows.append(upgraded)
    return rows


# ── Wave 4: envelope status + bounded context ─────────────────────────────


def envelope_section_status(section: str, payload: Any, *, configured: bool = True, stale: bool = False, conflicted: bool = False) -> str:
    if not configured:
        return "NOT_CONFIGURED"
    if conflicted:
        return "CONFLICTED"
    if stale:
        return "STALE"
    if payload is None:
        return "UNAVAILABLE"
    if payload == {} or payload == [] or payload == "":
        return "EMPTY"
    return "OK"


def envelope_provider_statuses(sections: dict[str, Any] | None = None, *, configured: dict[str, bool] | None = None, stale: dict[str, bool] | None = None, conflicted: dict[str, bool] | None = None) -> dict[str, Any]:
    sections = sections or {}
    configured = configured or {}
    stale = stale or {}
    conflicted = conflicted or {}
    out = {}
    for name in ENVELOPE_SECTIONS:
        out[name] = envelope_section_status(
            name,
            sections.get(name, None if name not in sections else sections.get(name)),
            configured=configured.get(name, name in sections),
            stale=bool(stale.get(name)),
            conflicted=bool(conflicted.get(name)),
        )
    live = sum(1 for v in out.values() if v == "OK")
    return {
        "schema": SCHEMA_ENVELOPE_STATUS,
        "sections": out,
        "sections_total": len(ENVELOPE_SECTIONS),
        "sections_live": live,
        "sections_not_configured": sum(1 for v in out.values() if v == "NOT_CONFIGURED"),
        "never_silently_omitted": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def budget_context(
    items: list[dict[str, Any]],
    *,
    portfolio_role: str | None = None,
    material_delta: bool = False,
    limit: int = 12,
) -> dict[str, Any]:
    """Do not dump the institutional database into every prompt."""
    scored = []
    for item in items:
        score = 0
        if item.get("portfolio_role") == portfolio_role or (portfolio_role and item.get("held")):
            score += 4
        if item.get("material_delta") or material_delta:
            score += 4
        if item.get("relationship") in {"LINEAR", "issuer", "ticker"}:
            score += 3
        if item.get("research_gap"):
            score += 3
        if str(item.get("freshness") or "").upper() == "FRESH":
            score += 2
        if item.get("contradiction"):
            score += 3
        if item.get("operator_question"):
            score += 4
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    kept = [item for _, item in scored[: max(1, int(limit))]]
    dropped = [item for _, item in scored[max(1, int(limit)):]]
    return {
        "schema": "BoundedContextBudget@v1",
        "kept": kept,
        "dropped": [{"reason": "BUDGET", "item": item.get("id") or item.get("symbol") or item.get("guid")} for item in dropped],
        "limit": int(limit),
        "authority": AUTHORITY,
    }


def same_brain_institutional(root: Path | str, symbols: list[str], *, held: set[str] | None = None) -> dict[str, Any]:
    from scripts.lib.cio_persistent_cognition import cross_agent_row

    rows = {s: cross_agent_row(root, s, held=held or set()) for s in symbols}
    consistent = all(r.get("consistent") for r in rows.values())
    return {
        "schema": "SameBrainAcceptance@v1",
        "agents": list(SAME_BRAIN_AGENTS),
        "symbols": rows,
        "consistent": consistent,
        "divergences": [s for s, r in rows.items() if not r.get("consistent")],
        "authority": AUTHORITY,
        "telegram_fork": False,
        "financial_action": False,
        "presentation_may_differ": True,
        "facts_may_not": True,
    }


# ── Wave 5: event-driven free-first ───────────────────────────────────────


def research_question_from_gap(
    *,
    gap: dict[str, Any] | None = None,
    entity: str | None = None,
    event_type: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    what_changed: str | None = None,
    symbol: str | None = None,
) -> str:
    explicit = str((gap or {}).get("question") or "").strip()
    if explicit and not GENERIC_QUERY_RE.match(explicit) and explicit.lower() not in {
        f"{(symbol or '').lower()} news",
        f"{(symbol or '').lower()} stock",
        f"{(symbol or '').lower()} earnings catalyst 2026",
    }:
        return explicit[:400]
    parts = []
    if what_changed:
        parts.append(f"what_changed={what_changed}")
    if event_type:
        parts.append(f"event={event_type}")
    if entity:
        parts.append(f"entity={entity}")
    if sector:
        parts.append(f"sector={sector}")
    if industry:
        parts.append(f"industry={industry}")
    if symbol:
        parts.append(f"alias={normalize_symbol(symbol)}")
    question = "; ".join(parts) or "unresolved_material_gap"
    if GENERIC_QUERY_RE.match(question):
        question = f"gap.question required for {normalize_symbol(symbol)} {event_type or 'event'}"
    return question[:400]


def prior_resolves(*, state: dict[str, Any] | None, watermark: str | None, after_hash: str | None, contradiction_open: bool) -> bool:
    if contradiction_open:
        return False
    if not state:
        return False
    decision = str(state.get("decision") or state.get("what_changed") or "")
    if decision in {"NO_NEW_INFO", "FRESH_NO_CHANGE", "BASELINE_PROJECTION"} and after_hash and watermark == after_hash:
        return True
    existing = str(state.get("evidence_watermark") or state.get("source_sha") or "")
    return bool(after_hash and existing and existing == after_hash)


def close_gap(gap: dict[str, Any], *, status: str, artifact_guids: list[str] | None = None) -> dict[str, Any]:
    """OPEN is not RESOLVED. Explicit evidence required."""
    current = str(gap.get("status") or "OPEN")
    target = status if status in GAP_STATUSES else current
    if current == target:
        return dict(gap)
    if target in {"RESOLVED_FREE", "RESOLVED_LLM", "NO_LONGER_RELEVANT"} and not artifact_guids and target != "NO_LONGER_RELEVANT":
        out = dict(gap)
        out["status"] = current
        out["close_blocked"] = "MISSING_RESOLUTION_EVIDENCE"
        return out
    out = dict(gap)
    out["status"] = target
    out["resolved_by_artifact_guids"] = list(artifact_guids or gap.get("resolved_by_artifact_guids") or [])
    out["resolved_at"] = _now() if target.startswith("RESOLVED") or target == "NO_LONGER_RELEVANT" else None
    return out


def persist_web_evidence(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "schema": SCHEMA_WEB,
        "query": row.get("query"),
        "url": row.get("url"),
        "title": row.get("title"),
        "retrieved_at": row.get("retrieved_at") or _now(),
        "source_valid": bool(row.get("source_valid")),
        "content_hash": row.get("content_hash") or _sha(row.get("url")),
        "materiality": row.get("materiality") or "NON_MATERIAL_CHANGE",
        "entity_relationship": row.get("entity_relationship") or "UNKNOWN",
        "thesis_truth": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    if not evidence["source_valid"]:
        evidence["thesis_truth"] = False
        evidence["note"] = "unsupported_web_snippet_is_not_thesis_truth"
    _append_locked(Path(root) / WEB_PATH, evidence)
    return evidence


def llm_eligibility_from_free_first(result: dict[str, Any]) -> str:
    """Eligibility does not spend money."""
    if result.get("conflict") or result.get("contradiction_open"):
        if result.get("deep_review"):
            return "DEEP_REVIEW_ELIGIBLE"
        return "CONFLICT_REVIEW_ELIGIBLE"
    if result.get("unresolved"):
        return "LLM_ELIGIBLE"
    if result.get("resolved") and result.get("new_evidence"):
        return "FREE_RESOLVED"
    return "NO_NEW_INFO"


def enqueue_free_first_pending(
    root: Path | str,
    *,
    delta: dict[str, Any],
    hit: dict[str, Any],
    gap: dict[str, Any],
) -> dict[str, Any]:
    pending = {
        "schema": SCHEMA_PENDING,
        "pending_id": _sha({"delta": delta.get("delta_id"), "gap": gap.get("gap_id")})[:24],
        "delta_id": delta.get("delta_id"),
        "gap_id": gap.get("gap_id"),
        "security_guid": hit.get("security_guid") or gap.get("security_guid"),
        "symbol": hit.get("symbol") or gap.get("symbol"),
        "question": gap.get("question"),
        "order": list(FREE_FIRST_ORDER),
        "paid_forbidden": True,
        "created_at": _now(),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
    path = Path(root) / PENDING_PATH
    for row in _jsonl(path):
        if row.get("pending_id") == pending["pending_id"]:
            return {"wrote": False, "pending": row, "duplicate": True}
    _append_locked(path, pending)
    return {"wrote": True, "pending": pending, "duplicate": False}


def run_targeted_free_first(
    *,
    pending: dict[str, Any],
    prior_state: dict[str, Any] | None,
    hermes_resolved: bool,
    rag_resolved: bool,
    structured_resolved: bool,
    searx_resolved: bool = False,
    searx_allowed: bool = True,
    contradiction_open: bool = False,
) -> dict[str, Any]:
    """Reuse first. SearXNG is discovery, only after reusable/structured fail."""
    used = None
    resolved = False
    searx_ran = False
    if prior_state and not contradiction_open and (
        prior_state.get("resolves")
        or str(prior_state.get("decision") or prior_state.get("what_changed") or "") in {
            "NO_NEW_INFO",
            "FRESH_NO_CHANGE",
        }
    ):
        used, resolved = "TICKER_RESEARCH_STATE", True
    elif hermes_resolved:
        used, resolved = "HERMES", True
    elif rag_resolved:
        used, resolved = "RAG", True
    elif structured_resolved:
        used, resolved = "STRUCTURED", True
    elif searx_allowed:
        searx_ran = True
        used, resolved = "SEARXNG", bool(searx_resolved)
    else:
        used, resolved = None, False
    result = {
        "resolved": resolved,
        "used": used,
        "order": list(FREE_FIRST_ORDER),
        "searx_ran": searx_ran,
        "unresolved": not resolved,
        "new_evidence": resolved and used not in {None, "TICKER_RESEARCH_STATE"},
        "contradiction_open": contradiction_open,
        "paid_dispatch": 0,
        "authority": AUTHORITY,
    }
    result["eligibility"] = llm_eligibility_from_free_first(result)
    result["spent_money"] = False
    return result


# ── Orchestrator ──────────────────────────────────────────────────────────


def process_observation(
    root: Path | str,
    observation: dict[str, Any],
    *,
    profiles: list[dict[str, Any]] | None = None,
    prior_states: dict[str, dict[str, Any]] | None = None,
    free_first_fn: Callable[..., dict[str, Any]] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """One office change → one lifecycle receipt. Never a second portfolio book."""
    source_domain = str(observation.get("source_domain") or "unknown")
    before_hash = observation.get("before_hash")
    after_hash = observation.get("after_hash") or _sha(observation.get("source_version") or observation.get("source_ref"))
    materiality = observation.get("materiality") or classify_materiality(
        before_hash=before_hash,
        after_hash=after_hash,
        available=observation.get("available", True),
        stale=bool(observation.get("stale")),
        conflict=bool(observation.get("conflict")),
        material_fields_changed=bool(observation.get("material_fields_changed")),
        any_change=bool(observation.get("any_change")),
    )
    delta = build_delta_receipt(
        source_domain=source_domain,
        source_ref=str(observation.get("source_ref") or observation.get("entity_guid") or source_domain),
        source_version=str(observation.get("source_version") or after_hash),
        entity_guid_value=observation.get("entity_guid"),
        entity_type=str(observation.get("entity_type") or "ticker"),
        change_type=str(observation.get("change_type") or "UPDATE"),
        before_hash=before_hash,
        after_hash=after_hash,
        materiality=materiality,
        freshness=str(observation.get("freshness") or "FRESH"),
        research_relevance=bool(observation.get("research_relevance", True)),
        portfolio_relevance=bool(observation.get("portfolio_relevance")),
        policy_relevance=bool(observation.get("policy_relevance")),
        reason=str(observation.get("reason") or ""),
        as_of=observation.get("as_of"),
    )
    stored = upsert_delta(root, delta) if persist else {"wrote": True, "receipt": delta, "duplicate": False}
    delta = stored["receipt"]
    profiles = profiles if profiles is not None else load_graph_profiles(root)
    impact = resolve_impact(delta, profiles)
    prior_states = prior_states or {}
    wakes: list[dict[str, Any]] = []
    paid = 0
    for hit in impact.get("affected") or []:
        if not hit.get("wake_research"):
            continue
        symbol = hit["symbol"]
        state = prior_states.get(symbol)
        watermark = None if not state else str(state.get("evidence_watermark") or state.get("source_sha") or "")
        resolved = prior_resolves(
            state=state,
            watermark=watermark,
            after_hash=after_hash,
            contradiction_open=bool(observation.get("contradiction_open")),
        )
        what_changed = "NO_NEW_INFO" if resolved else str(observation.get("what_changed") or observation.get("reason") or materiality)
        gap = None
        pending = None
        ff = None
        if resolved:
            eligibility = "NO_NEW_INFO"
        else:
            question = research_question_from_gap(
                gap=observation.get("gap"),
                entity=delta.get("entity_guid"),
                event_type=observation.get("event_type") or source_domain,
                sector=observation.get("sector"),
                industry=observation.get("industry"),
                what_changed=what_changed,
                symbol=symbol,
            )
            gap = build_gap(
                security_guid=hit.get("security_guid"),
                symbol=symbol,
                reason=str(observation.get("reason") or materiality),
                question=question,
                materiality="high" if materiality in WAKE_MATERIALITY else "low",
                required_evidence_type=str(observation.get("required_evidence_type") or "research"),
                portfolio_relevance=bool(delta.get("portfolio_relevance")),
                thesis_relevance=bool(hit.get("thesis_evidence")),
                status="OPEN",
            )
            gap["status"] = "FREE_FIRST_PENDING"
            if persist:
                upsert_gap(root, gap)
                pending = enqueue_free_first_pending(root, delta=delta, hit=hit, gap=gap)
            else:
                pending = {"pending": {"question": question, "order": list(FREE_FIRST_ORDER)}, "duplicate": False}
            if free_first_fn:
                ff = free_first_fn(pending=pending.get("pending"), prior_state=state, **{k: observation.get(k) for k in ()})
            else:
                ff = run_targeted_free_first(
                    pending=pending.get("pending") or {},
                    prior_state=state,
                    hermes_resolved=bool(observation.get("hermes_resolved")),
                    rag_resolved=bool(observation.get("rag_resolved")),
                    structured_resolved=bool(observation.get("structured_resolved")),
                    searx_resolved=bool(observation.get("searx_resolved")),
                    searx_allowed=observation.get("searx_allowed", True),
                    contradiction_open=bool(observation.get("contradiction_open")),
                )
            eligibility = ff.get("eligibility") or "LLM_ELIGIBLE"
            paid += int(ff.get("paid_dispatch") or 0)
            if persist and gap and ff.get("resolved") and ff.get("used") != "SEARXNG":
                closed = close_gap(gap, status="RESOLVED_FREE", artifact_guids=[str(ff.get("used"))])
                upsert_gap(root, closed)
                gap = closed
            elif persist and gap and eligibility == "LLM_ELIGIBLE":
                gap = dict(gap)
                gap["status"] = "LLM_ELIGIBLE_NOT_AUTHORIZED"
                upsert_gap(root, gap)
        wakes.append({
            "symbol": symbol,
            "security_guid": hit.get("security_guid"),
            "what_changed": what_changed,
            "eligibility": eligibility,
            "gap_id": None if not gap else gap.get("gap_id"),
            "free_first": None if not ff else {k: ff.get(k) for k in ("used", "resolved", "searx_ran", "eligibility", "paid_dispatch")},
            "pending_duplicate": False if not pending else pending.get("duplicate"),
        })
    receipt = {
        "schema": SCHEMA_LIFECYCLE,
        "delta": delta,
        "duplicate_delta": bool(stored.get("duplicate")),
        "impact": {
            "wake_symbols": impact.get("wake_symbols"),
            "context_only": impact.get("context_only"),
            "rejected_count": len(impact.get("rejected") or []),
        },
        "wakes": wakes,
        "llm_calls": 0,
        "paid_dispatch": paid,
        "memory_behavior_influence": MBI,
        "authority": AUTHORITY,
        "financial_action": False,
        "canary_enabled": False,
        "model_policy_auto_changed": False,
    }
    if persist:
        _append_locked(Path(root) / LIFECYCLE_PATH, receipt)
    return receipt


def observe_from_scan(root: Path | str, scan: dict[str, Any], *, profiles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Fail-soft hook from the material scanner. No notify, no paid LLM."""
    observations: list[dict[str, Any]] = []
    for event in scan.get("holdings_events") or []:
        if not isinstance(event, dict):
            continue
        symbol = normalize_symbol(event.get("symbol") or event.get("ticker"))
        if not symbol:
            continue
        profile = build_profile(symbol, metadata=event)
        observations.append({
            "source_domain": "holdings",
            "source_ref": symbol,
            "source_version": str(event.get("as_of") or event.get("fingerprint") or _sha(event)),
            "entity_guid": profile.get("ticker_guid"),
            "entity_type": "ticker",
            "change_type": str(event.get("type") or event.get("event_type") or "HOLDINGS_DELTA"),
            "before_hash": event.get("before_hash"),
            "after_hash": event.get("after_hash") or _sha(event),
            "material_fields_changed": True,
            "research_relevance": True,
            "portfolio_relevance": True,
            "reason": str(event.get("reason") or event.get("type") or "holdings_delta"),
            "what_changed": str(event.get("type") or "holdings_delta"),
            "freshness": "FRESH",
        })
    cash = scan.get("cash") or {}
    if cash.get("cash_posture_status") in {"ABOVE_BAND", "BELOW_BAND", "POLICY_GAP"}:
        observations.append({
            "source_domain": "cash",
            "source_ref": "portfolio:cash",
            "source_version": str(cash.get("as_of") or scan.get("at") or _now()),
            "entity_guid": entity_guid("theme", "cash-posture"),
            "entity_type": "theme",
            "change_type": "CASH_POSTURE",
            "before_hash": cash.get("before_hash"),
            "after_hash": _sha({"status": cash.get("cash_posture_status"), "at": scan.get("at")}),
            "material_fields_changed": True,
            "policy_relevance": True,
            "portfolio_relevance": True,
            "research_relevance": False,
            "reason": str(cash.get("cash_posture_status") or "cash"),
            "freshness": "FRESH",
        })
    results = [process_observation(root, obs, profiles=profiles) for obs in observations]
    return {
        "schema": "ScanFabricOverlay@v1",
        "observations": len(observations),
        "lifecycle_receipts": len(results),
        "paid_dispatch": sum(int(r.get("paid_dispatch") or 0) for r in results),
        "llm_calls": 0,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def lifecycle_projection(
    *,
    symbol: str,
    delta: dict[str, Any] | None = None,
    impact: dict[str, Any] | None = None,
    prior: dict[str, Any] | None = None,
    gap: dict[str, Any] | None = None,
    free_first: dict[str, Any] | None = None,
    curation: dict[str, Any] | None = None,
    thesis: dict[str, Any] | None = None,
    specialists: list[dict[str, Any]] | None = None,
    memory: dict[str, Any] | None = None,
    notification: dict[str, Any] | None = None,
    model: dict[str, Any] | None = None,
    unwired: list[str] | None = None,
) -> dict[str, Any]:
    """GUI projection. Not an ingestion bus."""
    return {
        "schema": "IntelligenceLifecycleProjection@v1",
        "symbol": normalize_symbol(symbol),
        "WHY_AWAKE": None if not delta else delta.get("reason") or delta.get("change_type"),
        "SOURCE_DELTA": None if not delta else {
            "delta_id": delta.get("delta_id"),
            "source_domain": delta.get("source_domain"),
            "materiality": delta.get("materiality"),
        },
        "ENTITY_RELATIONSHIPS": None if not impact else {
            "wake": impact.get("wake_symbols"),
            "context_only": impact.get("context_only"),
            "issuer_guids": impact.get("issuer_guids"),
            "sector_guids": impact.get("sector_guids"),
            "industry_guids": impact.get("industry_guids"),
            "theme_guids": impact.get("theme_guids"),
        },
        "PRIOR_COGNITION": None if not prior else {
            "curation_id": prior.get("curation_id"),
            "curation_version": prior.get("curation_version"),
            "kind": prior.get("curation_kind") or prior.get("kind"),
        },
        "WHAT_CHANGED": None if not delta else delta.get("reason"),
        "RESEARCH_GAP": None if not gap else {"gap_id": gap.get("gap_id"), "status": gap.get("status"), "question": gap.get("question")},
        "FREE_FIRST_STATUS": None if not free_first else free_first.get("used") or free_first.get("eligibility"),
        "WEB_SEARCH_STATUS": None if not free_first else ("RAN" if free_first.get("searx_ran") else "NOT_NEEDED"),
        "LLM_STATUS": None if not free_first else free_first.get("eligibility"),
        "MODEL_USED": None if not model else model.get("model_id"),
        "WHY_THAT_MODEL": None if not model else model.get("reason"),
        "CURATION_VERSION": None if not curation else curation.get("version"),
        "THESIS_VERSION": None if not thesis else thesis.get("version"),
        "CONTRADICTIONS": (prior or {}).get("contradictions") or [],
        "SPECIALIST_VIEWS": specialists or [],
        "MEMORY_ADMISSION": None if not memory else memory.get("admitted"),
        "NOTIFICATION": None if not notification else notification.get("class") or notification.get("status"),
        "NEXT_REVIEW": (curation or {}).get("next_review_condition") or "ON_MATERIAL_CHANGE",
        "UNWIRED_PROVIDERS": unwired or [],
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "ingestion_bus": False,
        "financial_action": False,
    }


def fault_response(kind: str, **detail: Any) -> dict[str, Any]:
    """No silent loss. No fabricated certainty."""
    mapping = {
        "duplicate_event": "IDEMPOTENT_REPLAY",
        "stale_source": "STALE",
        "contradictory_source": "CONFLICT",
        "bad_security_identity": "UNRESOLVED_IDENTITY",
        "searx_outage": "UNAVAILABLE",
        "rag_unavailable": "UNAVAILABLE",
        "structured_unavailable": "UNAVAILABLE",
        "hermes_worker_crash": "UNAVAILABLE",
        "llm_bridge_unavailable": "UNAVAILABLE",
        "flash_unavailable": "UNAVAILABLE",
        "pro_unavailable": "UNAVAILABLE",
        "schema_invalid": "REJECTED",
        "truncated_output": "REJECTED",
        "memory_admission_reject": "REJECTED",
        "duplicate_curation": "IDEMPOTENT_REPLAY",
        "restart_before_admission": "PENDING_RETRY",
        "restart_before_thesis": "PENDING_RETRY",
        "gui_partial_provider": "DEGRADED",
    }
    status = mapping.get(kind, "UNAVAILABLE")
    return {
        "schema": "IntelligenceFault@v1",
        "kind": kind,
        "status": status,
        "silent_loss": False,
        "fabricated_certainty": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "detail": {k: v for k, v in detail.items() if k not in FORBIDDEN_TRUTH_KEYS},
    }
