"""Contract tests for /api/v2/consumption/run-manual (review-hardened)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.consumption_run_manual import (  # noqa: E402
    classify_manual_lane,
    deepseek_readiness_rows,
    parse_operator_confirmed,
    process_allows_policy,
    sanitize_provider_error,
    clear_capability_probe_cache,
    projected_max_cost_usd,
    SMOKE_PROCESS_ID,
)


def test_grok_chatgpt_accepted():
    assert classify_manual_lane("grok")["ok"] is True
    assert classify_manual_lane("chatgpt")["ok"] is True


def test_deepseek_flash_maps_to_fast():
    c = classify_manual_lane("deepseek-flash")
    assert c["ok"] is True
    assert c["policy"] == "FAST"
    assert c["requested_model_id"] == "deepseek-v4-flash"


def test_fast_accepted():
    c = classify_manual_lane("fast")
    assert c["ok"] is True
    assert c["policy"] == "FAST"


def test_pro_never_on_generic_endpoint():
    for lane in ("pro", "pro_think", "pro_max", "deepseek-v4-pro", "PRO", "PRO_MAX"):
        c = classify_manual_lane(lane, operator_confirmed=True)
        assert c["ok"] is False, lane
        assert c["reason_code"] == "POLICY_NOT_ALLOWED"


def test_string_false_cannot_confirm_pro():
    assert parse_operator_confirmed("false") is False
    assert parse_operator_confirmed("False") is False
    assert parse_operator_confirmed("0") is False
    assert parse_operator_confirmed(1) is False
    assert parse_operator_confirmed("yes") is False
    assert parse_operator_confirmed("true") is True
    assert parse_operator_confirmed(True) is True
    # Even if someone passes truthy confirm, Pro still blocked on classify
    c = classify_manual_lane("pro", operator_confirmed="true")
    assert c["ok"] is False


def test_ambiguous_and_legacy_rejected():
    for lane in ("deepseek-v4", "deepseek_v4", "v4"):
        assert classify_manual_lane(lane)["reason_code"] == "AMBIGUOUS_LEGACY_LANE"
    for lane in ("deepseek-chat", "deepseek-reasoner"):
        assert classify_manual_lane(lane)["reason_code"] == "LEGACY_MODEL_REJECTED"


def test_unknown_process_rejected():
    r = process_allows_policy("not_a_real_process_xyz", "FAST", "deepseek-flash")
    assert r["ok"] is False
    assert r["reason_code"] == "PROCESS_NOT_REGISTERED"


def test_smoke_process_allows_fast_only():
    r = process_allows_policy(SMOKE_PROCESS_ID, "FAST", "deepseek-flash")
    assert r["ok"] is True
    r2 = process_allows_policy(SMOKE_PROCESS_ID, "PRO", "deepseek-v4-pro")
    assert r2["ok"] is False
    assert r2["reason_code"] == "POLICY_NOT_ALLOWED"


def test_registered_process_cannot_request_outside_allowlist():
    # holding_protection is grok_only
    r = process_allows_policy("holding_protection_advisor", "FAST", "deepseek-flash")
    assert r["ok"] is False
    assert r["reason_code"] == "POLICY_NOT_ALLOWED"


def test_readiness_flash_pro_independent():
    clear_capability_probe_cache()
    with patch("lib.consumption_run_manual._cached_list_models") as m:
        m.return_value = {
            "configured": True, "reachable": True,
            "has_v4_flash": True, "has_v4_pro": False,
        }
        # bypass cache function by patching deepseek_readiness_rows internals
        from lib import consumption_run_manual as crm
        with patch.object(crm, "_cached_list_models", return_value={
            "configured": True, "reachable": True,
            "has_v4_flash": True, "has_v4_pro": False,
        }):
            rows = crm.deepseek_readiness_rows()
        by = {r["lane"]: r for r in rows}
        assert by["deepseek-flash"]["ready"] is True
        assert by["deepseek-flash"]["model_available"] is True
        assert by["deepseek-v4-pro"]["ready"] is False
        assert by["deepseek-v4-pro"]["model_available"] is False


def test_configured_but_unreachable_not_ready():
    from lib import consumption_run_manual as crm
    with patch.object(crm, "_cached_list_models", return_value={
        "configured": True, "reachable": False,
        "has_v4_flash": False, "has_v4_pro": False,
    }):
        rows = crm.deepseek_readiness_rows()
    for r in rows:
        assert r["configured"] is True
        assert r["reachable"] is False
        assert r["ready"] is False


def test_no_secret_in_readiness():
    rows = deepseek_readiness_rows()
    blob = str(rows)
    assert "deepseek_tradeai" not in blob
    assert "DEEPSEEK_API_KEY" not in blob


def test_sanitize_errors_no_raw_text():
    safe = sanitize_provider_error(RuntimeError("AUTH_MISSING: secret stuff sk-abc123xyz"))
    assert safe["reason_code"] == "AUTH_MISSING"
    assert "sk-abc" not in safe["error"]
    assert "secret" not in safe["error"].lower()
    safe2 = sanitize_provider_error(Exception("totally unexpected traceback /tmp/foo"))
    assert safe2["reason_code"] == "PROVIDER_UNAVAILABLE"
    assert "/tmp" not in safe2["error"]


def test_projected_cost_positive():
    usd = projected_max_cost_usd(
        model_id="deepseek-v4-flash", max_input_tokens=64, max_output_tokens=32,
    )
    assert usd > 0


def test_smoke_process_in_registry():
    import json
    reg = json.loads((ROOT / "config/llm_process_registry.json").read_text())
    by = {p["id"]: p for p in reg["processes"]}
    assert SMOKE_PROCESS_ID in by
    p = by[SMOKE_PROCESS_ID]
    assert p["default_mode"] == "manual"
    assert p["deepseek_allowed_policies"] == ["FAST"]
    assert p["max_input_tokens"] == 64
    assert p["max_output_tokens"] == 32
    assert p["daily_cost_cap_usd"] == 0.05
