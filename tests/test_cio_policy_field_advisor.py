"""CIO policy field advisor: server-built prompt, registered process, no client text."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import llm_consumption as lc  # noqa: E402
from lib.cio_policy_field_advisor import PROCESS_ID, advise, build_prompt, field_claims  # noqa: E402
from lib.consumption_run_manual import process_allows_policy, validate_paid_cap_config  # noqa: E402

POLICY = {
    "fields": {
        "cash_target_range_pct": {"value": None, "status": "POLICY_REQUIRED", "kind": "range_pct"},
        "concentration_hierarchy": {"value": None, "status": "POLICY_REQUIRED", "kind": "object"},
    },
    "legacy_conflicts": [
        {"field": "cash_target_range_pct", "resolved_by": "cash_target_range_pct", "claims": [
            {"field": "cash_target_range_pct", "value": {"min": 2.0, "target": 5.0, "max": 15.0},
             "source": "config/model_portfolio.json", "status": "LEGACY_UNCONFIRMED"},
        ]},
        {"field": "max_single_position_pct", "resolved_by": "concentration_hierarchy", "claims": [
            {"field": "max_single_position_pct", "value": 8.0,
             "source": "config/investment_policy_statement.json", "status": "LEGACY_UNCONFIRMED"},
        ]},
    ],
}
READY = lambda: [{"lane": "deepseek-flash", "ready": True}]  # noqa: E731


def test_process_registered_fast_only_with_caps():
    assert lc.is_process_registered(PROCESS_ID)
    assert process_allows_policy(PROCESS_ID, "FAST", "deepseek-flash")["ok"] is True
    assert process_allows_policy(PROCESS_ID, "PRO", "deepseek-pro")["ok"] is False
    validate_paid_cap_config(lc.get_process_config(PROCESS_ID))  # raises if caps missing


def test_prompt_is_server_built_and_carries_claims():
    prompt = build_prompt(POLICY, "cash_target_range_pct")
    assert "cash_target_range_pct" in prompt and "config/model_portfolio.json" in prompt
    assert "target" in prompt and "Do not output an order" in prompt


def test_claims_follow_resolved_by():
    claims = field_claims(POLICY, "concentration_hierarchy")
    assert [c["field"] for c in claims] == ["max_single_position_pct"]


def test_advise_calls_registered_process_not_smoke():
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw, prompt=prompt)
        return "Option A …", {"usage": {"prompt_tokens": 300, "completion_tokens": 120}}

    out = advise("cash_target_range_pct", POLICY, generate=fake, readiness=READY)
    assert out["ok"] is True and out["text"] == "Option A …" and out["advisory_only"] is True
    assert seen["process_id"] == PROCESS_ID and seen["policy"] == "FAST" and seen["lane"] == "deepseek-flash"
    assert "Policy field" in seen["prompt"]


def test_unknown_field_never_calls_provider():
    def boom(*a, **k):
        raise AssertionError("provider must not be called")

    assert advise("not_a_field", POLICY, generate=boom, readiness=READY)["reason_code"] == "UNKNOWN_POLICY_FIELD"
    assert advise("", POLICY, generate=boom, readiness=READY)["reason_code"] == "FIELD_REQUIRED"


def test_provider_error_is_sanitized():
    def fail(*a, **k):
        raise RuntimeError("HTTP_429 secret-ish detail sk-123")

    out = advise("cash_target_range_pct", POLICY, generate=fail, readiness=READY)
    assert out["ok"] is False and out["reason_code"] == "RATE_LIMITED" and "sk-123" not in str(out)


def test_not_ready_short_circuits():
    out = advise("cash_target_range_pct", POLICY, generate=lambda *a, **k: 1 / 0,
                 readiness=lambda: [{"lane": "deepseek-flash", "ready": False, "reason_code": "AUTH_MISSING"}])
    assert out["ok"] is False and out["reason_code"] == "AUTH_MISSING"
