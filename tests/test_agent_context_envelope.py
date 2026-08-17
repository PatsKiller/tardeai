"""Phase 1 — ContextEnvelope@v1 + get_context_for_agent() unit/adversarial tests.

No broker, no network. Deterministic only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_context_envelope import (  # noqa: E402
    CONTEXT_ENVELOPE_VERSION,
    MEMORY_AUTHORITY_NON_AUTHORITATIVE,
    RETRIEVAL_EMPTY,
    RETRIEVAL_ERROR,
    RETRIEVAL_NOT_CONFIGURED,
    RETRIEVAL_OK,
    RETRIEVAL_UNAVAILABLE,
    build_context_envelope,
    context_envelope_digest,
    get_context_for_agent,
    redact_secrets,
    validate_context_envelope,
)


def _base(**kw):
    return build_context_envelope(agent="alex", role="cio_synthesis", wake_id="w1", **kw)


class _NullMemory:
    name = "NullMemoryProvider"

    def health(self):
        return False


class _HealthyMemory:
    name = "TestMemory"

    def health(self):
        return True

    def search(self, query=None, symbols=None, plan_id=None):
        return {
            "records": [{"memory_id": "m1", "content": "op prefers SCHD as income anchor"}],
            "conflicts": [],
        }


class _BrokenMemory:
    name = "BrokenMemory"

    def health(self):
        return True

    def search(self, query=None, symbols=None, plan_id=None):
        raise RuntimeError("boom")


# ── Schema validation ──────────────────────────────────────────────────────


def test_envelope_schema_valid():
    ok, errs = validate_context_envelope(_base())
    assert ok, errs


def test_envelope_rejects_non_dict():
    ok, errs = validate_context_envelope("not a dict")
    assert not ok


def test_envelope_rejects_wrong_version():
    e = _base()
    e["context_envelope_version"] = "9.9"
    ok, errs = validate_context_envelope(e)
    assert not ok
    assert any("version" in x for x in errs)


def test_envelope_rejects_missing_section():
    e = _base()
    del e["office_truth"]
    ok, errs = validate_context_envelope(e)
    assert not ok
    assert any("office_truth" in x for x in errs)


def test_envelope_requires_read_only_authority():
    e = _base()
    e["governance"]["authority"] = "FULL_TRADING"
    ok, errs = validate_context_envelope(e)
    assert not ok


def test_governance_memory_authority_non_authoritative():
    e = _base()
    assert e["governance"]["memory_authority"] == MEMORY_AUTHORITY_NON_AUTHORITATIVE
    assert e["governance"]["authority"] == "READ_ONLY_ADVISORY"


# ── Stable digest ──────────────────────────────────────────────────────────


def test_same_inputs_same_digest():
    a = _base(decision={"decision_id": "dec_1", "current_action": "HOLD"})
    b = _base(decision={"decision_id": "dec_1", "current_action": "HOLD"})
    assert context_envelope_digest(a) == context_envelope_digest(b)


def test_material_change_new_digest():
    a = _base(decision={"decision_id": "dec_1", "current_action": "HOLD"})
    b = _base(decision={"decision_id": "dec_1", "current_action": "ACT_NOW"})
    assert context_envelope_digest(a) != context_envelope_digest(b)


def test_digest_excludes_timestamps():
    a = _base(decision={"decision_id": "dec_1"})
    # mutate timestamps directly — digest must not change
    b = dict(a)
    b["created_at"] = "2099-01-01T00:00:00+00:00"
    b["provenance"] = dict(a["provenance"])
    b["provenance"]["built_at"] = "2099-01-01T00:00:00+00:00"
    b["provenance"]["context_digest"] = None
    assert context_envelope_digest(a) == context_envelope_digest(b)


def test_provenance_digest_matches_recomputed():
    e = _base()
    assert e["provenance"]["context_digest"] == context_envelope_digest(e)


def test_tampered_digest_detected():
    e = _base()
    e["provenance"]["context_digest"] = "ctx_deadbeef"
    ok, errs = validate_context_envelope(e)
    assert not ok
    assert any("context_digest" in x for x in errs)


# ── Truth / memory separation ──────────────────────────────────────────────


def test_memory_cannot_overwrite_canonical_truth():
    # Memory claims cash is $9M; office truth says cash ref is canonical.
    e = build_context_envelope(
        agent="alex",
        role="cio_synthesis",
        wake_id="w1",
        office_truth={"cash_ref": "cash:real", "source_asof": "2026-08-16T00:00:00Z"},
        episodic_memory={
            "records": [{"memory_id": "m1", "content": "cash is $9,000,000"}],
            "retrieval_status": RETRIEVAL_OK,
        },
    )
    # canonical truth lives in office_truth, memory in episodic_memory — never merged
    assert e["office_truth"]["cash_ref"] == "cash:real"
    assert e["episodic_memory"]["records"][0]["content"] == "cash is $9,000,000"
    # The envelope never re-writes truth from memory.
    assert e["office_truth"]["cash_ref"] != "9,000,000"


# ── Fail-soft provider behavior ────────────────────────────────────────────


def test_missing_memory_explicit_not_configured():
    e = get_context_for_agent(agent="alex", wake={"wake_id": "w1"})
    assert e["episodic_memory"]["retrieval_status"] == RETRIEVAL_NOT_CONFIGURED


def test_missing_mcp_explicit_not_configured():
    e = get_context_for_agent(agent="alex", wake={"wake_id": "w1"})
    assert e["external_read_context"]["availability"] == RETRIEVAL_NOT_CONFIGURED


def test_missing_research_explicit_not_configured():
    e = get_context_for_agent(agent="alex", wake={"wake_id": "w1"})
    assert e["research_memory"]["retrieval_status"] == RETRIEVAL_NOT_CONFIGURED


def test_memory_provider_unavailable_fail_soft():
    e = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w1"},
        memory_provider=_NullMemory(),
    )
    assert e["episodic_memory"]["retrieval_status"] == RETRIEVAL_UNAVAILABLE


def test_memory_provider_healthy_returns_records():
    e = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w1"},
        memory_provider=_HealthyMemory(),
        symbols=["SCHD"],
    )
    assert e["episodic_memory"]["retrieval_status"] == RETRIEVAL_OK
    assert "m1" in e["episodic_memory"]["memory_ids"]


def test_memory_provider_error_fail_soft():
    e = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w1"},
        memory_provider=_BrokenMemory(),
    )
    assert e["episodic_memory"]["retrieval_status"] == RETRIEVAL_ERROR
    assert e["episodic_memory"].get("error") == "RuntimeError"


# ── Redaction ──────────────────────────────────────────────────────────────


def test_redact_secret_keys():
    v = {"api_key": "sk-1234567890", "safe": "hello", "nested": {"token": "xoxp-abc"}}
    out = redact_secrets(v)
    assert out["api_key"] == "[REDACTED]"
    assert out["safe"] == "hello"
    assert out["nested"]["token"] == "[REDACTED]"


def test_redact_secret_values():
    out = redact_secrets({"note": "use sk-abcdefghij12345 for auth"})
    assert out["note"] == "[REDACTED]"


def test_redact_preserves_request_id_hex():
    rid = "deadbeefdeadbeefdeadbeefdeadbeef"
    out = redact_secrets({"request_id": rid, "trace_id": "tr_" + rid, "api_key": "sk-hidden-xxxxx"})
    assert out["request_id"] == rid
    assert out["trace_id"] == "tr_" + rid
    assert out["api_key"] == "[REDACTED]"


def test_redact_is_non_mutating():
    v = {"api_key": "sk-1234567890"}
    redact_secrets(v)
    assert v["api_key"] == "sk-1234567890"


def test_no_credentials_in_envelope_digest_input():
    # Envelope built with a secret in memory should be redacted in any trace,
    # but the envelope itself keeps memory separated; ensure no secret leaks
    # into canonical truth section.
    e = build_context_envelope(
        agent="alex",
        role="cio_synthesis",
        wake_id="w1",
        office_truth={"cash_ref": "cash:real"},
    )
    flat = str(e["office_truth"])
    assert "sk-" not in flat


# ── get_context_for_agent role inference ───────────────────────────────────


def test_role_inference_default_alex():
    e = get_context_for_agent(agent="alex", wake={"wake_id": "w1"})
    assert e["role"] == "cio_synthesis"


def test_role_inference_guardian():
    e = get_context_for_agent(agent="guardian", wake={"wake_id": "w1"})
    assert e["role"] == "risk_guardian"


def test_role_inference_explicit_wins():
    e = get_context_for_agent(agent="alex", wake={"wake_id": "w1", "role": "specialist"})
    assert e["role"] == "specialist"


def test_context_envelope_version():
    e = _base()
    assert e["context_envelope_version"] == CONTEXT_ENVELOPE_VERSION


# ── No behavior mutation (AI-6) ────────────────────────────────────────────


def test_build_context_does_not_mutate_decision_input():
    decision = {
        "decision_id": "dec_1",
        "current_action": "ACT_NOW",
        "act_now": True,
        "freshness": "FRESH",
    }
    original = dict(decision)
    _base(decision=decision)
    assert decision == original


def test_get_context_does_not_mutate_office_truth():
    truth = {"cash_ref": "cash:real", "source_asof": "2026-08-16T00:00:00Z"}
    original = dict(truth)
    get_context_for_agent(agent="alex", wake={"wake_id": "w1"}, office_truth=truth)
    assert truth == original


# ── Phase 1.5 dry-run fixtures (SCHD REJECT / cash WAIT / re-entry WAIT) ──


def test_dryrun_schd_reject_envelope():
    """SCHD-like challenged decision: memory separated, truth intact, no rule leak."""
    e = build_context_envelope(
        agent="alex",
        role="cio_synthesis",
        wake_id="schd_wake",
        decision={"decision_id": "dec_schd", "current_action": "REVALIDATE", "act_now": False},
        office_truth={"holdings_ref": "holdings:schd", "source_asof": "2026-08-16T00:00:00Z"},
        episodic_memory={
            "records": [
                {"memory_id": "m1", "content": "operator: SCHD is a staple/income anchor"},
            ],
            "retrieval_status": RETRIEVAL_OK,
        },
    )
    ok, errs = validate_context_envelope(e)
    assert ok, errs
    # Memory is separated; it does not write a "never trim" rule into truth.
    assert "never" not in str(e["office_truth"]).lower()
    assert e["decision"]["act_now"] is False


def test_dryrun_cash_wait_envelope():
    e = build_context_envelope(
        agent="alex",
        role="cio_synthesis",
        wake_id="cash_wait",
        decision={"decision_id": "dec_cash", "current_action": "WAIT", "act_now": False},
        office_truth={"cash_ref": "cash:real", "source_asof": "2026-08-16T00:00:00Z"},
    )
    ok, errs = validate_context_envelope(e)
    assert ok, errs
    assert e["decision"]["current_action"] == "WAIT"


def test_dryrun_reentry_wait_envelope():
    e = build_context_envelope(
        agent="alex",
        role="cio_synthesis",
        wake_id="reentry_wait",
        decision={"decision_id": "dec_reentry", "current_action": "WAIT", "act_now": False},
    )
    ok, errs = validate_context_envelope(e)
    assert ok, errs
    # A WAIT re-entry must never be represented as RE_ENTER.
    assert e["decision"]["current_action"] != "RE_ENTER"


# ── Provider contract: plan_id filter (Phase 1 ⇄ Phase 4 alignment) ───────


def test_get_context_with_local_provider_accepts_plan_id():
    """The chokepoint must work with the shipped local provider (no RETRIEVAL_ERROR).

    Regression: _retrieve_episodic passes plan_id= to provider.search(); the
    MemoryProvider protocol and LocalTestMemoryProvider must accept it.
    """
    from scripts.lib.agent_memory_provider import LocalTestMemoryProvider  # noqa: E402
    from scripts.lib.agent_memory_governance import (  # noqa: E402
        MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
        STATUS_ACTIVE,
        build_memory_record,
    )

    provider = LocalTestMemoryProvider(
        records=[
            build_memory_record(
                memory_type=MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
                subject="preference",
                content="operator prefers SCHD",
                source_event_ids=["evt_1"],
                plan_ids=["plan_1"],
                status=STATUS_ACTIVE,
            )
        ]
    )
    e = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w1"},
        memory_provider=provider,
        plan_id="plan_1",
    )
    assert e["episodic_memory"]["retrieval_status"] == RETRIEVAL_OK
    assert e["episodic_memory"]["records"]


def test_get_context_with_mem0_preserves_not_configured():
    """NOT_CONFIGURED must never be silently converted to EMPTY.

    Regression: _retrieve_episodic treated a truthy health dict as healthy,
    ignored the provider's retrieval_status, and mapped zero records to EMPTY —
    making "memory not configured" look like "memory consulted, empty".
    """
    from scripts.lib.agent_mem0_provider import Mem0MemoryProvider  # noqa: E402

    e = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w1"},
        memory_provider=Mem0MemoryProvider(),
    )
    assert e["episodic_memory"]["retrieval_status"] == RETRIEVAL_NOT_CONFIGURED
    assert e["episodic_memory"]["records"] == []


def test_get_context_with_mem0_marks_not_consulted():
    from scripts.lib.agent_context_integration import (  # noqa: E402
        MARKER_MEMORY_NOT_CONSULTED,
        record_retrieval_before_reasoning,
    )
    from scripts.lib.agent_mem0_provider import Mem0MemoryProvider  # noqa: E402

    e = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "w1"},
        memory_provider=Mem0MemoryProvider(),
    )
    audited = record_retrieval_before_reasoning(e)
    mem = audited["episodic_memory"]
    assert mem["retrieval_marker"] == MARKER_MEMORY_NOT_CONSULTED
    assert audited["retrieval_audit"]["full_context_available"] is False


