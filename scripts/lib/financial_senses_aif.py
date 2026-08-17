"""AIF ↔ Financial Senses governed read-only adapter.

READ_ONLY_ADVISORY. This is the narrow registration/adapter layer that lets
the EXISTING AIF MCP gateway consume Financial Senses providers.

It does NOT:
  * create a second MCP gateway / server / router / brain
  * duplicate Financial Senses calculation logic
  * grant broker / order / stop / 2FA / risk-policy authority
  * persist raw Financial Senses output into memory
  * flip MEMORY_BEHAVIOR_INFLUENCE
  * change canonical financial action

AIF remains the single governed routing boundary. Financial Senses remains
the evidence/intelligence subsystem. Neither is execution authority.
"""
from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Optional

from scripts.lib.agent_feature_flags import _coerce_int_flag, load_feature_flags
from scripts.lib.agent_untrusted_data import UNTRUSTED_DATA, untrusted_envelope
from scripts.lib.financial_senses.critic import IndependentCriticProvider
from scripts.lib.financial_senses.evidence_graph import ClaimEvidenceProvider
from scripts.lib.financial_senses.factor_exposure import FactorOverlapProvider
from scripts.lib.financial_senses.identity import OpenFigiProvider
from scripts.lib.financial_senses.macro_provider import FredAlfredProvider
from scripts.lib.financial_senses.manifest import (
    MUTABILITY_READ_ONLY,
    TOOLS,
    render_registration_manifest,
    tool_names,
)
from scripts.lib.financial_senses.result import (
    AUTHORITY,
    Fact,
    FinancialSenseResult,
    ModelEstimate,
    STATUS_INVALID_REQUEST,
    STATUS_NOT_CONFIGURED,
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    make_result,
)
from scripts.lib.financial_senses.sec_provider import SecEdgarProvider
from scripts.lib.financial_senses.source_governance import (
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    SOURCE_MODEL_INFERENCE,
    VALID_QUALITY,
    can_back_fact,
)
from scripts.lib.financial_senses.stress_engine import PortfolioStressProvider

# ── Flags (defaults OFF; no behavior-influence flag exists) ────────────────
FLAG_AIF_FINANCIAL_SENSES_SHADOW = "AIF_FINANCIAL_SENSES_SHADOW"
DEFAULT_AIF_FINANCIAL_SENSES_SHADOW = 0

# OpenBB is optional plumbing in financial_senses/openbb.py and is NOT in the
# governed AIF-facing manifest. Intentionally unexposed: it is not a first-class
# provider contract and must not become a second truth source.
INTENTIONALLY_UNEXPOSED: dict[str, str] = {
    "openbb": (
        "Optional plumbing only (scripts/lib/financial_senses/openbb.py). "
        "Not in the governed Financial Senses AIF manifest. Not registered "
        "on the MCP gateway."
    ),
}

VALID_FRESHNESS = frozenset({FRESHNESS_FRESH, FRESHNESS_STALE, FRESHNESS_UNKNOWN})

# Request keys that attempt authority escalation. Any of these fail closed.
FORBIDDEN_REQUEST_KEYS = frozenset(
    {
        "authoritative",
        "approval",
        "approve",
        "2fa",
        "two_fa",
        "order",
        "orders",
        "stop",
        "stops",
        "broker",
        "place_order",
        "cancel_order",
        "risk_policy",
        "behavior_influence",
        "memory_behavior_influence",
        "mutability",
        "write",
        "governor",
    }
)

# Capability-class (domain) for each AIF-exposed tool. Derived from manifest.
AIF_TOOL_DOMAINS: dict[str, str] = {}
for _provider, _spec in TOOLS.items():
    for _tool in _spec.get("tools") or []:
        AIF_TOOL_DOMAINS[str(_tool["name"])] = str(_provider)

# Request fields accepted by the gateway schema check. Union of provider
# capability schemas + the AIF transport fields (request_id / as_of).
AIF_REQUEST_FIELDS: dict[str, set[str]] = {
    "sec.resolve_cik": {"symbol", "request_id", "as_of"},
    "sec.get_recent_filings": {"symbol", "form", "limit", "request_id", "as_of"},
    "sec.get_form4_context": {"symbol", "limit", "request_id", "as_of"},
    "sec.get_13f_context": {"symbol", "limit", "request_id", "as_of"},
    "sec.get_company_facts": {"symbol", "cik", "request_id", "as_of"},
    "sec.get_filing_metadata": {"symbol", "cik", "request_id", "as_of"},
    "sec.compare_filing_facts": {"cik", "period_a", "period_b", "request_id", "as_of"},
    "sec.get_decision_evidence": {"symbol", "request_id", "as_of"},
    "macro.get_series_snapshot": {"series_ids", "request_id", "as_of"},
    "macro.get_decision_time_snapshot": {"series_ids", "decision_date", "request_id", "as_of"},
    "macro.get_vintage": {"series_id", "decision_date", "request_id", "as_of"},
    "macro.compare_vintages": {"series_id", "decision_date", "request_id", "as_of"},
    "macro.get_vintage_dates": {"series_id", "request_id", "as_of"},
    "macro.get_latest_observation": {"series_id", "request_id", "as_of"},
    "macro.get_series": {"series_id", "request_id", "as_of"},
    "macro.regime_inputs": {"decision_date", "request_id", "as_of"},
    "identity.resolve": {
        "ticker",
        "exchange",
        "security_type",
        "cusip",
        "isin",
        "figi",
        "request_id",
        "as_of",
    },
    "risk.stress_portfolio": {"portfolio", "scenario", "request_id", "as_of"},
    "evidence.build_graph": {"nodes", "edges", "request_id", "as_of"},
    "factor.overlap": {"instrument_a", "instrument_b", "request_id", "as_of"},
    "critic.review": {"evidence", "proposed_action", "request_id", "as_of"},
}

PROVIDER_CTORS: dict[str, Any] = {
    "sec_edgar": SecEdgarProvider,
    "macro": FredAlfredProvider,
    "identity": OpenFigiProvider,
    "stress": PortfolioStressProvider,
    "evidence": ClaimEvidenceProvider,
    "factor": FactorOverlapProvider,
    "critic": IndependentCriticProvider,
}


def aif_exposed_tools() -> dict[str, str]:
    """tool name → capability class (provider family). All READ_ONLY."""
    return dict(AIF_TOOL_DOMAINS)


def aif_exposed_tool_names() -> list[str]:
    return sorted(AIF_TOOL_DOMAINS)


def governed_manifest_tool_names() -> set[str]:
    names: set[str] = set()
    for provider in TOOLS:
        names.update(tool_names(provider))
    return names


def manifest_drift() -> list[str]:
    """Empty when AIF-exposed set == governed FS manifest tool set."""
    exposed = set(AIF_TOOL_DOMAINS)
    governed = governed_manifest_tool_names()
    errors: list[str] = []
    extra = sorted(exposed - governed)
    missing = sorted(governed - exposed)
    if extra:
        errors.append(f"AIF-exposed tools not in FS manifest: {extra}")
    if missing:
        errors.append(f"FS manifest tools not AIF-exposed: {missing}")
    return errors


def shadow_enabled(env: Optional[dict[str, Any]] = None) -> bool:
    """True only when AIF_FINANCIAL_SENSES_SHADOW is unambiguously on."""
    src = os.environ if env is None else env
    raw = src.get(FLAG_AIF_FINANCIAL_SENSES_SHADOW) if hasattr(src, "get") else None
    if raw is None:
        flags = load_feature_flags(env)
        raw = flags.get(FLAG_AIF_FINANCIAL_SENSES_SHADOW, DEFAULT_AIF_FINANCIAL_SENSES_SHADOW)
    return _coerce_int_flag(raw) == 1


def behavior_influence() -> bool:
    """Structurally false for this program. No flag can turn this on."""
    return False


def memory_behavior_influence(env: Optional[dict[str, Any]] = None) -> int:
    flags = load_feature_flags(env)
    return int(flags.get("MEMORY_BEHAVIOR_INFLUENCE") or 0)


def is_fresh_current_evidence(freshness: Any) -> bool:
    """Only explicit FRESH qualifies as current authoritative Fact support."""
    return str(freshness or "").strip().upper() == FRESHNESS_FRESH


def aif_validate_result(result: Any) -> list[str]:
    """Fail-closed validation on top of FinancialSenseResult.validate()."""
    if not isinstance(result, FinancialSenseResult):
        return ["result is not a FinancialSenseResult"]
    errors = list(result.validate())
    if result.authority != AUTHORITY:
        errors.append(f"authority must be {AUTHORITY}")
    grade = (result.quality.grade if result.quality else None) or ""
    if grade and str(grade).upper() not in VALID_QUALITY:
        errors.append(f"invalid quality grade {grade!r}")
    freshness = (result.quality.freshness if result.quality else None)
    if freshness and str(freshness).upper() not in VALID_FRESHNESS:
        errors.append(f"invalid freshness {freshness!r}")
    for i, fact in enumerate(result.facts):
        if isinstance(fact, Fact) and fact.freshness:
            if str(fact.freshness).upper() not in VALID_FRESHNESS:
                errors.append(f"facts[{i}] ({fact.key}) invalid freshness {fact.freshness!r}")
        if isinstance(fact, ModelEstimate):
            errors.append(f"facts[{i}] is a ModelEstimate — cannot occupy facts[]")
        if isinstance(fact, Fact) and fact.source_type == SOURCE_MODEL_INFERENCE:
            errors.append(f"facts[{i}] ({fact.key}) ModelEstimate source cannot be Fact")
    for i, est in enumerate(result.estimates):
        if isinstance(est, Fact):
            errors.append(f"estimates[{i}] is a Fact — cannot occupy estimates[]")
        if isinstance(est, ModelEstimate) and can_back_fact(est.source_type or ""):
            errors.append(
                f"estimates[{i}] ({est.key}) cannot wear a fact-capable source_type"
            )
    return errors


def _wrap_untrusted(value: Any, *, source: str, ref: str) -> Any:
    """Mark provider text as UNTRUSTED_DATA. Structure is preserved."""
    if isinstance(value, str):
        return untrusted_envelope(
            content_type="financial_senses_text",
            source=source,
            content=value,
            ref=ref,
        )
    if isinstance(value, dict):
        return {k: _wrap_untrusted(v, source=source, ref=f"{ref}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_wrap_untrusted(v, source=source, ref=f"{ref}[{i}]") for i, v in enumerate(value)]
    return value


def result_to_aif_payload(result: FinancialSenseResult, *, validation: Optional[list[str]] = None) -> dict[str, Any]:
    """Structured AIF payload. Never flattens evidence into prose."""
    errors = list(validation if validation is not None else aif_validate_result(result))
    facts_out: list[dict[str, Any]] = []
    for fact in result.facts:
        d = fact.to_dict() if hasattr(fact, "to_dict") else dict(fact)
        fresh = is_fresh_current_evidence(d.get("freshness") or (result.quality.freshness if result.quality else None))
        d["is_current_authoritative_support"] = bool(
            fresh and d.get("quality") and str(d.get("quality")).upper() in VALID_QUALITY
            and d.get("source_type") and can_back_fact(str(d.get("source_type")))
            and not errors
        )
        if not fresh:
            d["current_evidence_warning"] = (
                f"freshness={d.get('freshness') or result.quality.freshness or 'MISSING'} "
                "is not FRESH — not current authoritative Fact support"
            )
        facts_out.append(d)
    estimates_out = [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in result.estimates]
    source = result.provider or "financial_senses"
    payload = {
        "status": result.status if not errors else (
            result.status if result.status != STATUS_OK else STATUS_PARTIAL
        ),
        "source_asof": result.as_of or result.observed_at or result.requested_at,
        "authority": AUTHORITY,
        "shadow_only": True,
        "behavior_influence": False,
        "financial_senses": {
            "request_id": result.request_id,
            "provider": result.provider,
            "capability": result.capability,
            "as_of": result.as_of,
            "observed_at": result.observed_at,
            "requested_at": result.requested_at,
            "completed_at": result.completed_at,
            "status": result.status,
            "subject": result.subject.to_dict() if result.subject else {},
            "freshness": result.quality.freshness if result.quality else None,
            "quality": result.quality.grade if result.quality else None,
            "freshness_is_current": is_fresh_current_evidence(
                result.quality.freshness if result.quality else None
            ),
            "fact_count": len(result.facts),
            "estimate_count": len(result.estimates),
            "claim_count": len(result.claims),
            "opinion_count": len(result.opinions),
            "facts": facts_out,
            "estimates": estimates_out,
            "claims": [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in result.claims],
            "opinions": [o.to_dict() if hasattr(o, "to_dict") else dict(o) for o in result.opinions],
            "warnings": list(result.warnings),
            "provenance": result.provenance.to_dict() if result.provenance else None,
            "validation_ok": not errors,
            "validation_errors": errors,
            "data": _wrap_untrusted(result.data, source=source, ref=result.request_id or "data"),
            "evidence_type": "Fact" if result.facts and not result.estimates else (
                "mixed" if result.facts and result.estimates else (
                    "ModelEstimate" if result.estimates else "none"
                )
            ),
        },
    }
    if errors:
        payload["financial_senses"]["authoritative_facts"] = []
    else:
        payload["financial_senses"]["authoritative_facts"] = [
            f for f in facts_out if f.get("is_current_authoritative_support")
        ]
    return payload


def envelope_item_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """ContextEnvelope specialist_context.financial_senses.items[] entry."""
    fs = payload.get("financial_senses") if isinstance(payload, dict) else {}
    fs = fs if isinstance(fs, dict) else {}
    return {
        "provider": fs.get("provider"),
        "capability": fs.get("capability"),
        "request_id": fs.get("request_id"),
        "instrument_identity": fs.get("subject") or {},
        "as_of": fs.get("as_of"),
        "observed_at": fs.get("observed_at"),
        "freshness": fs.get("freshness"),
        "freshness_is_current": bool(fs.get("freshness_is_current")),
        "quality": fs.get("quality"),
        "evidence_type": fs.get("evidence_type"),
        "fact_vs_model_estimate": {
            "facts": fs.get("fact_count") or 0,
            "estimates": fs.get("estimate_count") or 0,
        },
        "source_identifiers": (fs.get("provenance") or {}).get("source_ids") if isinstance(fs.get("provenance"), dict) else [],
        "source_provenance": fs.get("provenance"),
        "validation_status": "OK" if fs.get("validation_ok") else "INVALID",
        "warnings": list(fs.get("warnings") or []) + list(fs.get("validation_errors") or []),
        "claim_evidence_refs": [
            c.get("text") if isinstance(c, dict) else None for c in (fs.get("claims") or [])
        ],
        "shadow_only": True,
        "behavior_influence": False,
        "status": payload.get("status") or fs.get("status"),
        "facts": fs.get("facts") or [],
        "estimates": fs.get("estimates") or [],
        "data": fs.get("data"),
    }


def empty_financial_senses_section() -> dict[str, Any]:
    return {
        "enabled": False,
        "shadow_only": True,
        "behavior_influence": False,
        "availability": "NOT_CONFIGURED",
        "items": [],
        "warnings": [],
        "dropped_for_budget": [],
    }


def attach_to_envelope(envelope: dict[str, Any], payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach structured FS items under specialist_context. Never mutates input."""
    env = deepcopy(envelope) if isinstance(envelope, dict) else {}
    spec = env.setdefault("specialist_context", {})
    if not isinstance(spec, dict):
        spec = {}
        env["specialist_context"] = spec
    section = spec.setdefault("financial_senses", empty_financial_senses_section())
    if not isinstance(section, dict):
        section = empty_financial_senses_section()
        spec["financial_senses"] = section
    items = list(section.get("items") or [])
    for payload in payloads:
        items.append(envelope_item_from_payload(payload))
    section["items"] = items
    section["enabled"] = True
    section["shadow_only"] = True
    section["behavior_influence"] = False
    statuses = [p.get("status") for p in payloads]
    if any(s == STATUS_OK for s in statuses):
        section["availability"] = "OK"
    elif any(s == STATUS_NOT_CONFIGURED for s in statuses):
        section["availability"] = "NOT_CONFIGURED"
    elif payloads:
        section["availability"] = "UNAVAILABLE"
    # Keep envelope provenance digest honest after the structured attach.
    try:
        from scripts.lib.agent_context_envelope import context_envelope_digest

        if isinstance(env.get("provenance"), dict):
            env["provenance"]["context_digest"] = context_envelope_digest(env)
    except Exception:
        pass
    return env


def drop_financial_senses_items(envelope: dict[str, Any]) -> list[str]:
    """Drop FS evidence items for budget, keeping classification fields.

    Never silently drops authority / freshness / quality / Fact vs ModelEstimate
    / instrument identity / critical provenance on remaining items. When the
    whole item list is dropped, a stub records that evidence was truncated.
    """
    spec = envelope.get("specialist_context")
    if not isinstance(spec, dict):
        return []
    section = spec.get("financial_senses")
    if not isinstance(section, dict):
        return []
    items = section.get("items")
    if not isinstance(items, list) or not items:
        return []
    dropped_ids = [str(it.get("request_id") or it.get("capability") or "item") for it in items if isinstance(it, dict)]
    section["dropped_for_budget"] = dropped_ids
    section["items"] = []
    section["budget_truncated"] = True
    section["warnings"] = list(section.get("warnings") or []) + [
        "Financial Senses evidence items dropped for context budget; "
        "office_truth / decision / governance were preserved"
    ]
    # Preserve the classification envelope so consumers still see the policy.
    section["shadow_only"] = True
    section["behavior_influence"] = False
    return dropped_ids


def reject_raw_memory_admission(record: Any) -> tuple[bool, str]:
    """Raw Financial Senses output is not durable memory. Fail closed."""
    if not isinstance(record, dict):
        return False, "memory record must be a dict"
    if record.get("financial_senses") or record.get("provider") in AIF_TOOL_DOMAINS.values():
        return False, "raw Financial Senses output is not durable memory"
    if record.get("authority_class") in ("Fact", "FACT") and record.get("source") == "financial_senses":
        return False, "Financial Senses memory cannot become Fact"
    return True, "not a raw financial-senses blob"


def _reject_forbidden_request(request: dict[str, Any]) -> Optional[str]:
    bad = sorted(k for k in request if str(k).lower() in FORBIDDEN_REQUEST_KEYS)
    if bad:
        return f"forbidden authority field(s): {bad}"
    return None


def invoke_capability(
    tool: str,
    request: Optional[dict[str, Any]] = None,
    *,
    providers: Optional[dict[str, Any]] = None,
) -> FinancialSenseResult:
    """Call the existing FS provider. Does not invent data."""
    req = dict(request or {})
    forbidden = _reject_forbidden_request(req)
    provider_id = AIF_TOOL_DOMAINS.get(tool)
    if not provider_id:
        r = make_result("unknown", tool, STATUS_INVALID_REQUEST)
        r.add_warning(f"tool {tool!r} is not an AIF-exposed Financial Senses capability")
        return r.complete()
    if forbidden:
        r = make_result(provider_id, tool, STATUS_INVALID_REQUEST)
        r.add_warning(forbidden)
        return r.complete()
    registry = providers if providers is not None else build_live_providers()
    provider = registry.get(provider_id)
    if provider is None:
        r = make_result(provider_id, tool, STATUS_UNAVAILABLE)
        r.add_warning(f"provider {provider_id!r} is not registered")
        return r.complete()
    mut = MUTABILITY_READ_ONLY
    for cap in getattr(provider, "capabilities", lambda: [])():
        if getattr(cap, "name", None) == tool:
            mut = getattr(cap, "mutability", MUTABILITY_READ_ONLY)
            break
    if str(mut) != MUTABILITY_READ_ONLY:
        r = make_result(provider_id, tool, STATUS_UNAVAILABLE)
        r.add_warning(f"capability {tool!r} is not READ_ONLY")
        return r.complete()
    try:
        result = provider.query(tool, req)
    except Exception as exc:  # fail-soft
        r = make_result(provider_id, tool, STATUS_UNAVAILABLE)
        r.add_warning(f"{provider_id}.{tool} failed: {exc}")
        return r.complete()
    if not isinstance(result, FinancialSenseResult):
        r = make_result(provider_id, tool, STATUS_UNAVAILABLE)
        r.add_warning("provider did not return FinancialSenseResult")
        return r.complete()
    return result


def build_live_providers() -> dict[str, Any]:
    """Real constructors. Unconfigured providers report NOT_CONFIGURED honestly."""
    fred = os.environ.get("FRED_API_KEY") or ""
    figi = os.environ.get("OPENFIGI_API_KEY") or os.environ.get("OPENFIGI_KEY") or ""
    return {
        "sec_edgar": SecEdgarProvider(),
        "macro": FredAlfredProvider(api_key=fred or None),
        "identity": OpenFigiProvider(api_key=figi or None),
        "stress": PortfolioStressProvider(),
        "evidence": ClaimEvidenceProvider(),
        "factor": FactorOverlapProvider(),
        "critic": IndependentCriticProvider(),
    }


def build_fixture_providers() -> dict[str, Any]:
    """Deterministic in-process providers. No network."""

    class _MacroClient:
        _obs = [
            {"date": "2024-06-01", "value": 5.5},
            {"date": "2025-01-01", "value": 5.9},
        ]

        def observations(self, series_id, realtime_start=None, realtime_end=None,
                         observation_start=None, observation_end=None):
            obs = list(self._obs)
            if observation_start:
                obs = [o for o in obs if o["date"] >= observation_start]
            if observation_end:
                obs = [o for o in obs if o["date"] <= observation_end]
            if realtime_end:
                obs = [o for o in obs if o["date"] <= realtime_end]
            return obs

        def latest(self, series_id):
            return self._obs[-1]

        def latest_as_of(self, series_id, decision_date):
            e = [o for o in self._obs if o["date"] <= decision_date]
            return e[-1] if e else None

        def observation_value(self, series_id, observation_date, realtime_end=None):
            for o in self._obs:
                if o["date"] == observation_date:
                    return o["value"]
            return None

        def vintage_dates(self, series_id, limit=10):
            return ["2024-06-01", "2025-01-01"]

    def _cik(symbol: str) -> str:
        return {"AAPL": "0000320193", "MSFT": "0000789019", "SCHD": "0001540305"}.get(
            str(symbol).upper(), ""
        )

    def _figi(query: dict) -> list[dict]:
        ticker = str(query.get("ticker") or query.get("idValue") or "TEST").upper()
        return [{"ticker": ticker, "figi": f"BBG{ticker[:6].ljust(6, 'X')}", "name": ticker, "exchCode": "US"}]

    return {
        "sec_edgar": SecEdgarProvider(configured=True, cik_resolver=_cik, fetcher=lambda url: {}),
        "macro": FredAlfredProvider(api_key="fixture", client=_MacroClient()),
        "identity": OpenFigiProvider(resolver=_figi),
        "stress": PortfolioStressProvider(),
        "evidence": ClaimEvidenceProvider(),
        "factor": FactorOverlapProvider(),
        "critic": IndependentCriticProvider(),
    }


class FinancialSensesReadOnlyProvider:
    """MCP ReadOnlyProvider adapter. No write methods exist."""

    name = "FinancialSensesProvider"
    domain = "financial_senses"
    configured = True

    def __init__(self, providers: Optional[dict[str, Any]] = None) -> None:
        self._providers = providers if providers is not None else build_live_providers()

    def health(self) -> bool:
        # Adapter is loaded. Individual capabilities report NOT_CONFIGURED
        # via get() so the gateway does not swallow honest provider status.
        return True

    def get(self, **kwargs: Any) -> dict:
        tool = str(kwargs.get("tool") or "")
        request = {k: v for k, v in kwargs.items() if k != "tool"}
        result = invoke_capability(tool, request, providers=self._providers)
        payload = result_to_aif_payload(result)
        if result.status == STATUS_NOT_CONFIGURED:
            payload["status"] = STATUS_NOT_CONFIGURED
        return payload

    def search(self, **kwargs: Any) -> dict:
        return self.get(**kwargs)


def build_financial_senses_registry(
    providers: Optional[dict[str, Any]] = None,
) -> dict[str, FinancialSensesReadOnlyProvider]:
    adapter = FinancialSensesReadOnlyProvider(providers=providers)
    return {name: adapter for name in AIF_TOOL_DOMAINS}


def receipt_fields_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Trace metadata required by the program. No secrets."""
    fs = payload.get("financial_senses") if isinstance(payload, dict) else {}
    fs = fs if isinstance(fs, dict) else {}
    return {
        "request_id": fs.get("request_id"),
        "provider": fs.get("provider"),
        "capability": fs.get("capability"),
        "validation_ok": fs.get("validation_ok"),
        "freshness_summary": fs.get("freshness"),
        "quality_summary": fs.get("quality"),
        "fact_count": fs.get("fact_count") or 0,
        "estimate_count": fs.get("estimate_count") or 0,
        "source_provenance": fs.get("provenance"),
        "shadow_only": True,
        "behavior_influence": False,
        "status": payload.get("status"),
    }


def registration_contract() -> dict[str, Any]:
    """Drift-check surface: AIF view of the FS manifest."""
    man = render_registration_manifest()
    return {
        "authority": AUTHORITY,
        "mutability": MUTABILITY_READ_ONLY,
        "gateway": "scripts.lib.mcp_read_only_gateway.call_mcp_tool",
        "second_gateway": False,
        "tools": aif_exposed_tools(),
        "intentionally_unexposed": INTENTIONALLY_UNEXPOSED,
        "manifest_version": man.get("version"),
        "drift": manifest_drift(),
        "shadow_flag": FLAG_AIF_FINANCIAL_SENSES_SHADOW,
        "shadow_default": DEFAULT_AIF_FINANCIAL_SENSES_SHADOW,
        "behavior_influence": False,
        "memory_behavior_influence_default": 0,
    }
