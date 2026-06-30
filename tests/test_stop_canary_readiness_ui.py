"""PR #33 — Schwab live-stop canary: disabled-reason visibility + read-only readiness panel.

Source-scan + read-only behavioural tests (no broker writes, no order placement). Mirrors the style of
test_stop_management_ui_hardening.py.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "apps/command-center-v3/src/components/HoldingProtectionActions.tsx"
LOGIC = ROOT / "apps/command-center-v3/src/lib/stopManagement.ts"
API = ROOT / "scripts/api_v2.py"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── Part B: a disabled live-stop button is never silent ───────────────────────────────────────────
def test_01_logic_exposes_primary_disabled_reason():
    src = read(LOGIC)
    assert "disabledReason" in src and "disabledReasonHuman" in src
    assert "BLOCKER_PRIORITY" in src
    # whole-share confirmation is the LAST hard blocker so genuine data problems are reported first
    pr = src.split("BLOCKER_PRIORITY")[1].split("]")[0]
    assert pr.index("stale_quote") < pr.index("fractional_qty")


def test_02_disabled_button_shows_reason_on_button_and_inline():
    src = read(UI)
    assert "Disabled — " in src                      # tooltip on the disabled button
    assert "disabledReasonHuman" in src
    assert "schwab-stop-disabled-reason" in src       # inline reason element beside the buttons
    assert "⛔ Disabled:" in src


def test_03_whole_share_checkbox_label_and_enable_path():
    src = read(UI)
    assert "I confirm this Schwab stop will sell" in src
    assert "residual" in src and "remain monitored" in src
    assert "setWholeShareConfirmed" in src
    # fractional_qty blocker clears once confirmed (logic), enabling the button when all else is clean
    assert "!wholeShareConfirmed" in read(LOGIC)


def test_04_fractional_qty_is_the_whole_share_blocker():
    src = read(LOGIC)
    assert "code: 'fractional_qty'" in src
    assert "Schwab stop orders require whole shares" in src


# ── Part C: live stop readiness panel + read-only endpoint ────────────────────────────────────────
def test_05_readiness_panel_present_with_all_gates():
    src = read(UI)
    assert "live-stop-readiness" in src and "LIVE STOP READINESS" in src
    for label in ["Build", "Quote", "DB / evidence store", "Schwab validator", "Execution state",
                  "Active approval", "Whole-share confirmation", "Preflight", "OCO", "Broker submit"]:
        assert label in src, f"readiness panel missing gate: {label}"
    # icons
    assert "✅" in src and "⚠️" in src and "⛔" in src


def test_06_canary_state_marker_and_ready_for_operator():
    assert "READY_FOR_OPERATOR" in read(UI)
    assert "canary-state" in read(UI)
    api = read(API)
    assert "READY_FOR_OPERATOR" in api and "canary_state" in api


def test_07_backend_hard_block_reasons_present():
    src = read(UI)
    assert "Schwab 2FA live path disabled by execution_state." in src
    assert "DB unavailable / evidence store unavailable." in src
    assert "OCO is ON" in src


def test_08_readiness_endpoint_registered_and_read_only():
    api = read(API)
    assert "/api/v2/holdings/stop-readiness" in api
    assert "_stop_live_readiness" in api
    # the readiness function must not place / submit / cancel any broker order
    fn = api.split("def _stop_live_readiness")[1].split("\ndef ")[0]
    for bad in ("place_order", "submit_order", "schwab_transport", "create_order_evidence_approval",
                "DELETE", "INSERT INTO", "UPDATE "):
        assert bad not in fn, f"readiness endpoint must be read-only — found {bad!r}"
    assert "broker_request_sent" in fn


# ── Safety invariants ────────────────────────────────────────────────────────────────────────────
def test_09_funds_remain_not_applicable_no_stop_buttons():
    src = read(LOGIC) + read(UI)
    assert "FCNTX" in src and "SPAXX" in src
    assert "NOT APPLICABLE" in src
    assert "instrument_not_applicable" in read(LOGIC)


def test_10_fidelity_remains_manual_ticket_only():
    src = read(UI)
    assert "Create Fidelity manual ticket" in src
    assert "does not submit to Fidelity" in src
    # the live "Request Schwab ... via 2FA" buttons are gated behind isSchwab, never rendered for fidelity
    assert "isSchwab && btn(" in src


def test_11_oco_brackets_schwab_off_and_not_enabled():
    api = read(API)
    assert "OCO_BRACKETS_SCHWAB" in api
    assert "oco_brackets_schwab_off" in api
    # nothing in the readiness/canary path sets the flag on
    assert 'OCO_BRACKETS_SCHWAB"] = "1"' not in api and "OCO_BRACKETS_SCHWAB=1" not in read(UI)


def test_12_readiness_endpoint_runtime_is_read_only(tmp_path):
    """Call the endpoint and assert it returns the gate snapshot WITHOUT submitting anything."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import api_v2
    except Exception:
        import pytest
        pytest.skip("api_v2 import unavailable in this environment")
    r = api_v2._stop_live_readiness({"symbol": "V", "account": "schwab_rollover_ira"})
    assert r["broker_request_sent"] is False
    assert r["build_marker"] == "cc-v3 stop-evidence PR33 2026-06-30"
    assert r["canary_state"] in ("READY_FOR_OPERATOR", "BLOCKED")
    assert "execution" in r and "schwab_validator" in r and "active_approval" in r
    # OCO must be reported off (we never enable it)
    assert r.get("oco_brackets_schwab_off") is True
