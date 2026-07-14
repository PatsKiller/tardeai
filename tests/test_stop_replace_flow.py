"""Regression tests for Schwab protective-stop replace (cancel-then-place) flow."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
API_SRC = (ROOT / "scripts" / "api_v2.py").read_text()
ROUTER_SRC = (ROOT / "scripts" / "brokers" / "intent_submit_router.py").read_text()
TELEGRAM_SRC = (ROOT / "scripts" / "telegram_callback_handler.py").read_text()
TRANSPORT_SRC = (ROOT / "scripts" / "schwab_transport.py").read_text()
UI_SRC = (ROOT / "apps/command-center-v3/src/components/HoldingProtectionActions.tsx").read_text()
CARD_SRC = (ROOT / "apps/command-center-v3/src/components/PositionDecisionCardV4.tsx").read_text()
OTI_SRC = (ROOT / "scripts/open_trades_intelligence.py").read_text()


def test_confirm_uses_verified_cancel_before_replace_submit():
    confirm = API_SRC[
        API_SRC.index('if base_path == "/api/v2/holdings/protective-stop/confirm"'):
        API_SRC.index('if base_path == "/api/v2/holdings/protective-stop/cancel"')
    ]
    assert "submit_fully_approved(intent_id)" in confirm
    assert 'stage": "modify_cancel"' in confirm


def test_router_defers_replace_cancel_to_transport():
    block = ROUTER_SRC[
        ROUTER_SRC.index("elif marker == PROTECTIVE_STOP_MARKER:"):
        ROUTER_SRC.index("elif marker == QUEUE_ENTRY_MARKER:")
    ]
    assert "cancel_replace_stop_if_needed(intent)" not in block
    assert "schwab_transport.place_order" in TRANSPORT_SRC or "cancel_order_for_replace" in TRANSPORT_SRC


def test_telegram_auto_submit_uses_same_router_path():
    assert "submit_fully_approved(iid)" in TELEGRAM_SRC
    assert 'stage") == "modify_cancel"' in TELEGRAM_SRC or "stage') == 'modify_cancel'" in TELEGRAM_SRC


def test_duplicate_guard_blocks_live_replace_target():
    assert "replace_cancel_incomplete" in TRANSPORT_SRC
    assert "still live" in TRANSPORT_SRC
    # Must not blindly skip a still-live replace_order_id
    assert "if _oid and _oid == _replace_id:" in TRANSPORT_SRC
    assert "continue   # the order we are replacing (already cancelled) — allowed" not in TRANSPORT_SRC


def test_transport_exposes_cancel_verify_helpers():
    assert "def cancel_order_for_replace" in TRANSPORT_SRC
    assert "def verify_order_canceled" in TRANSPORT_SRC


def test_place_order_marks_immediate_readback_rejection():
    place = TRANSPORT_SRC[TRANSPORT_SRC.index("def place_order"):TRANSPORT_SRC.index("def cancel_order_for_replace")]
    assert "_rb_status == \"REJECTED\"" in place
    assert "rejected_by_broker" in place


def test_transport_cancels_replace_before_post():
    place = TRANSPORT_SRC[TRANSPORT_SRC.index("def place_order"):TRANSPORT_SRC.index("def cancel_order_for_replace")]
    assert "cancel_order_for_replace(account_key, _replace_oid" in place
    assert place.index("cancel_order_for_replace") < place.index("client.place_order")


def test_cancel_order_idempotent_on_already_canceled():
    cancel = TRANSPORT_SRC[TRANSPORT_SRC.index("def cancel_order("):TRANSPORT_SRC.index("def replace_order")]
    assert "already canceled" in cancel
    assert "verify_order_canceled" in cancel


def test_ui_threads_replace_from_fresh_preflight_snap():
    assert "resolveReplaceParams" in UI_SRC
    assert "liveSnap: pf.liveSnap" in UI_SRC
    assert "opts?.liveSnap ?? effectiveConfirmed" in UI_SRC


def test_open_modify_only_replaces_pilot_placed_stops():
    assert "effectiveBrokerStop.pilot_placed ? effectiveBrokerStop.order_id : null" in CARD_SRC


def test_open_trades_broker_stop_tags_pilot_placed():
    assert "pilot_placed" in OTI_SRC
    assert "_pilot_stop_ids" in OTI_SRC


def test_request_response_surfaces_replace_mode():
    block = API_SRC[
        API_SRC.index('if base_path == "/api/v2/holdings/protective-stop"'):
        API_SRC.index('if base_path == "/api/v2/holdings/protective-stop/reject-intent"')
    ]
    assert '"replace_mode": bool(replace_order_id)' in block
    assert '"replace_order_id":' in block