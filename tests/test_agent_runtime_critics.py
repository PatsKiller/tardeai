from __future__ import annotations

from datetime import datetime, timezone

from scripts.agent_runtime.critics import CriticLane, CriticPanel
from scripts.agent_runtime.sentinel import inspect_ticket


NOW = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)


def deterministic(pass_state: bool = True):
    ticket = {
        "symbol": "SCHG",
        "state": "READY",
        "direction": "LONG",
        "input_hash": "b" * 64,
        "validation_hash": "a" * 64,
        "as_of": "2026-07-23T13:30:00+00:00",
        "mechanics": {"entry": 34.1, "stop": 33.6, "target": 35.5},
    }
    validation = {
        "state": "PASS" if pass_state else "FAIL",
        "proposal_allowed": pass_state,
        "hard_failures": [] if pass_state else ["fixture"],
    }
    return inspect_ticket(ticket, validation, now=NOW)


def lanes():
    return (
        CriticLane("local", "local", "gemma-fixture", max_cost_usd=0.0),
        CriticLane("grok", "grok-oauth", "grok-fixture", max_cost_usd=0.0),
        CriticLane("chatgpt", "chatgpt-oauth", "chatgpt-fixture", max_cost_usd=0.0),
    )


def response(family: str, model: str, verdict: str, refs=("lesson:integrity:v1",)):
    return {
        "provider_family": family,
        "model": model,
        "verdict": verdict,
        "findings": [f"{verdict} fixture"],
        "evidence_refs": list(refs),
        "cost_usd": 0.0,
    }


def test_deterministic_failure_skips_every_critic() -> None:
    calls = []

    def provider(request):
        calls.append(request)
        return response("local", "gemma-fixture", "PASS")

    panel = CriticPanel(lanes(), {"local": provider, "grok": provider, "chatgpt": provider})
    result = panel.review({"artifact_hash": "c" * 64}, deterministic(False))
    assert result.state == "BLOCK_DETERMINISTIC"
    assert result.results == ()
    assert calls == []


def test_pass_reject_disagreement_is_preserved_without_majority_vote() -> None:
    panel = CriticPanel(
        lanes(),
        {
            "local": lambda request: response("local", "gemma-fixture", "PASS"),
            "grok": lambda request: response("grok-oauth", "grok-fixture", "REJECT", ("case:counter:v1",)),
            "chatgpt": lambda request: response("chatgpt-oauth", "chatgpt-fixture", "PASS"),
        },
    )
    result = panel.review({"artifact_hash": "c" * 64}, deterministic(True))
    assert result.state == "DISAGREEMENT"
    assert [item.verdict for item in result.results] == ["PASS", "REJECT", "PASS"]
    assert result.disagreements == ("PASS and REJECT coexist; majority voting is prohibited.",)
    assert "operator" in result.operator_action.lower()


def test_provider_provenance_mismatch_is_error_not_silent_fallback() -> None:
    calls = {"local": 0, "grok": 0, "chatgpt": 0}

    def local(request):
        calls["local"] += 1
        return response("chatgpt-oauth", "chatgpt-fixture", "PASS")

    def grok(request):
        calls["grok"] += 1
        return response("grok-oauth", "grok-fixture", "PASS")

    def chatgpt(request):
        calls["chatgpt"] += 1
        return response("chatgpt-oauth", "chatgpt-fixture", "PASS")

    panel = CriticPanel(lanes(), {"local": local, "grok": grok, "chatgpt": chatgpt})
    result = panel.review({"artifact_hash": "c" * 64}, deterministic(True))
    assert result.state == "PARTIAL_PROVIDER_FAILURE"
    assert result.failed_lanes == ("local",)
    assert result.results[0].verdict == "ERROR"
    assert "provenance mismatch" in (result.results[0].error or "")
    assert calls == {"local": 1, "grok": 1, "chatgpt": 1}


def test_supported_verdict_without_evidence_is_downgraded() -> None:
    panel = CriticPanel(
        (CriticLane("local", "local", "gemma-fixture"),),
        {"local": lambda request: response("local", "gemma-fixture", "PASS", ())},
    )
    result = panel.review({"artifact_hash": "c" * 64}, deterministic(True))
    assert result.state == "INSUFFICIENT_EVIDENCE"
    assert result.results[0].verdict == "INSUFFICIENT_EVIDENCE"
    assert "downgraded" in result.results[0].findings[-1]


def test_provider_exception_is_retained_and_other_lane_is_not_substituted() -> None:
    def broken(request):
        raise RuntimeError("fixture outage")

    panel = CriticPanel(
        (
            CriticLane("local", "local", "gemma-fixture"),
            CriticLane("grok", "grok-oauth", "grok-fixture"),
        ),
        {
            "local": broken,
            "grok": lambda request: response("grok-oauth", "grok-fixture", "CAUTION"),
        },
    )
    result = panel.review({"artifact_hash": "c" * 64}, deterministic(True))
    assert result.state == "PARTIAL_PROVIDER_FAILURE"
    assert result.failed_lanes == ("local",)
    assert result.results[0].verdict == "ERROR"
    assert result.results[1].verdict == "CAUTION"


def test_cost_budget_violation_is_a_lane_error() -> None:
    panel = CriticPanel(
        (CriticLane("paid", "openai-api", "paid-fixture", max_cost_usd=0.01),),
        {
            "paid": lambda request: {
                **response("openai-api", "paid-fixture", "PASS"),
                "cost_usd": 0.02,
            }
        },
    )
    result = panel.review({"artifact_hash": "c" * 64}, deterministic(True))
    assert result.state == "PROVIDER_FAILURE"
    assert "cost budget exceeded" in (result.results[0].error or "")


def test_all_abstain_is_valid_insufficient_evidence() -> None:
    panel = CriticPanel(
        (
            CriticLane("local", "local", "gemma-fixture"),
            CriticLane("grok", "grok-oauth", "grok-fixture"),
        ),
        {
            "local": lambda request: response("local", "gemma-fixture", "ABSTAIN", ()),
            "grok": lambda request: response("grok-oauth", "grok-fixture", "INSUFFICIENT_EVIDENCE", ()),
        },
    )
    result = panel.review({"artifact_hash": "c" * 64}, deterministic(True))
    assert result.state == "INSUFFICIENT_EVIDENCE"
    assert result.failed_lanes == ()
    assert len(result.reconciliation_hash) == 64
