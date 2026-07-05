"""Protective-stop canary policy: per-account arming, lifecycle, one-canary-only, docs consistency."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

RUNBOOK = ROOT / "docs/runbooks/protective-stop-integration-2026-06-30.md"
CHANGELOG = ROOT / "docs/CHANGELOG.md"
ARM = ROOT / "scripts/schwab_pilot_arm.py"
API = ROOT / "scripts/api_v2.py"
UI = ROOT / "apps/command-center-v3/src/components/HoldingProtectionActions.tsx"
EV = ROOT / "scripts/brokers/evidence_approval.py"
CANARY = ROOT / "scripts/brokers/protective_stop_canary.py"


def test_docs_after_hours_override_required_not_24_7_default():
    rb = RUNBOOK.read_text(encoding="utf-8")
    assert "READY_FOR_OPERATOR_NEXT_REGULAR_SESSION" in rb
    assert "SCHWAB_AFTER_HOURS_STOP_OVERRIDE=1" in rb
    assert "override-required" in rb.lower() or "override-required" in rb
    assert "24/7 by default" not in rb.lower()
    cl = CHANGELOG.read_text(encoding="utf-8")
    assert "SUPERSEDED (2026-07-04)" in cl
    assert "override-required" in cl.lower() or "READY_FOR_OPERATOR_NEXT_REGULAR_SESSION" in cl


def test_schwab_pilot_arm_defaults_to_rollover_only():
    src = ARM.read_text(encoding="utf-8")
    assert "DEFAULT_ARM_ACCOUNTS" in src
    assert "schwab_rollover_ira" in src
    assert "--accounts" in src
    assert "api_write_enabled=false WHERE broker" in src


def test_roth_blocks_when_not_armed_message():
    api = API.read_text(encoding="utf-8")
    assert "Blocked: {label} is not armed for live API writes." in api
    ui = UI.read_text(encoding="utf-8")
    assert "Blocked:" in ui and "not armed for live API writes" in ui
    assert "account_api_write_enabled" in ui  # arming checked explicitly, not inferred from 2FA banner


def test_evidence_binding_includes_canary_fields():
    ev = EV.read_text(encoding="utf-8")
    for f in (
        "quote_timestamp_normalized", "quote_session", "after_hours_ack",
        "account_api_write_enabled", "oco_brackets_off", "broker_account_id",
        "stop_price", "limit_price",
    ):
        assert f in ev, f"missing binding field {f}"


def test_canary_lifecycle_states_defined():
    src = CANARY.read_text(encoding="utf-8")
    for st in (
        "NOT_ARMED", "READY_FOR_OPERATOR", "READY_FOR_OPERATOR_NEXT_REGULAR_SESSION",
        "READY_FOR_OPERATOR_AFTER_HOURS_GTC", "SUCCESS_READBACK_CONFIRMED", "FAILED_READBACK",
    ):
        assert st in src
    assert "broad_stop_placement_blocked" in src
    assert "preferred_canary_targets" in src


def test_one_v_canary_targets_differ():
    from brokers.protective_stop_canary import preferred_canary_targets
    from brokers.evidence_approval import order_spec_hash, protective_order_binding

    t = preferred_canary_targets()
    pref, alt = t["preferred"], t["alternate"]
    assert pref["account"] != alt["account"]
    assert pref["qty"] != alt["qty"]
    assert pref["trail_pct"] != alt["trail_pct"]
    b1 = protective_order_binding(None, {}, **{k: pref[k] for k in pref if k != "symbol"})
    # binding needs intent — compare hashes via manual dicts
    h1 = order_spec_hash({"orderType": "TRAILING_STOP"}, binding={
        "account_key": pref["account"], "symbol": "V", "qty": pref["qty"],
        "trail_pct": pref["trail_pct"], "time_in_force": "GTC",
    })
    h2 = order_spec_hash({"orderType": "TRAILING_STOP"}, binding={
        "account_key": alt["account"], "symbol": "V", "qty": alt["qty"],
        "trail_pct": alt["trail_pct"], "time_in_force": "GTC",
    })
    assert h1 != h2


def test_ui_shows_canary_target_and_lifecycle():
    ui = UI.read_text(encoding="utf-8")
    assert "CANARY TARGET" in ui
    assert "canary_lifecycle_state" in ui
    assert "broad_stop_placement_blocked" in ui
    assert "account_armed_message" in ui or "Account armed" in ui


def test_readiness_exports_operator_status():
    api = API.read_text(encoding="utf-8")
    assert "operator_status" in api
    assert "READY_FOR_ONE_CANARY_ONLY" in api
    assert "broad_stop_placement_blocked" in api
    assert "preferred_canary_target" in api