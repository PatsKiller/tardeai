from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
API_SRC = (ROOT / "scripts" / "api_v2.py").read_text()
ROUTER_SRC = (ROOT / "scripts" / "brokers" / "intent_submit_router.py").read_text()
TRANSPORT_SRC = (ROOT / "scripts" / "schwab_transport.py").read_text()
EVIDENCE_SRC = (ROOT / "scripts" / "brokers" / "evidence_approval.py").read_text()
OCO_READINESS_SRC = (ROOT / "scripts" / "oco_readiness_report.py").read_text()
PREFLIGHT_SRC = (ROOT / "scripts" / "protective_stop_2fa_preflight.py").read_text()


def test_schwab_stop_request_creates_approval_not_direct_submit():
    protective_block = API_SRC[
        API_SRC.index('if base_path == "/api/v2/holdings/protective-stop"'):
        API_SRC.index('if base_path == "/api/v2/holdings/protective-stop/reject-intent"')
    ]
    assert "req = _psp.request_2fa(intent)" in protective_block
    assert "_psp.submit(" not in protective_block
    assert '"mode": "awaiting_approval"' in protective_block


def test_confirm_binds_evidence_before_schwab_submit():
    assert "create_order_evidence_approval" in ROUTER_SRC
    assert "eb = create_order_evidence_approval(intent, order_spec, readiness_snapshot=readiness)" in ROUTER_SRC
    assert "res = _psp.submit(acct, order_spec, intent)" in ROUTER_SRC
    assert ROUTER_SRC.index("create_order_evidence_approval") < ROUTER_SRC.index("res = _psp.submit")


def test_missing_or_changed_evidence_blocks_before_broker_write():
    assert 'reason": "no_evidence_bound_approval"' in EVIDENCE_SRC
    assert 'reason": "order_spec_hash_changed"' in EVIDENCE_SRC
    assert "revalidate_before_submit(" in TRANSPORT_SRC
    assert "current_order_spec=order_spec" in TRANSPORT_SRC
    assert TRANSPORT_SRC.index("revalidate_before_submit(") < TRANSPORT_SRC.index("client.place_order")
    assert "broker_submitted" in ROUTER_SRC
    assert "evidence_revalidation" in ROUTER_SRC


def test_confirm_requires_ticker_or_6_digit_code_before_submit():
    confirm_block = API_SRC[
        API_SRC.index('if base_path == "/api/v2/holdings/protective-stop/confirm"'):
        API_SRC.index('if base_path == "/api/v2/holdings/protective-stop/cancel"')
    ]
    assert "approval_service.confirm(intent_id, channel" in confirm_block
    assert 'channel not in ("web", "telegram")' in confirm_block
    assert "if not cr.get(\"ok\")" in confirm_block
    assert "if not cr.get(\"fully_approved\")" in confirm_block
    assert "_isr.submit_fully_approved(intent_id)" in confirm_block


def test_evidence_and_2fa_are_single_use():
    assert "approval_service.consume(intent.intent_id)" in TRANSPORT_SRC
    assert "_consume_evidence_approval(intent.intent_id)" in TRANSPORT_SRC
    assert "approval_already_used_single_use" in EVIDENCE_SRC


def test_typed_ticker_or_code_proof_is_bound_to_order_evidence():
    assert "ticker_code_proof_hash" in EVIDENCE_SRC
    assert "proof_type" in EVIDENCE_SRC
    assert "typed_ticker" in EVIDENCE_SRC
    assert "six_digit_code" in EVIDENCE_SRC
    assert "order_spec_hash" in EVIDENCE_SRC


def test_active_approval_lock_and_reject_are_exposed():
    assert "one order at a time" in (ROOT / "scripts" / "brokers" / "approval_service.py").read_text()
    assert "active_approval_detail" in API_SRC
    assert '"/api/v2/holdings/protective-stop/reject-intent"' in API_SRC
    assert "approval rejected; no broker order submitted" in API_SRC


def test_no_autonomous_oco_or_bracket_enablement_for_basic_stops():
    assert "OCO_BRACKETS_SCHWAB=1" not in API_SRC
    assert '"OCO"' not in ROUTER_SRC
    assert '"BRACKET"' not in ROUTER_SRC


def test_oco_readiness_report_keeps_oco_off_until_basic_stop_canaries_pass():
    assert "OCO_BRACKETS_SCHWAB" in OCO_READINESS_SRC
    assert '"protective_stop_canary_passed": False' in OCO_READINESS_SRC
    assert '"trailing_stop_canary_passed": False' in OCO_READINESS_SRC
    assert '"ready_for_oco_one_share_canary"' in OCO_READINESS_SRC


def test_v_trailing_stop_preflight_is_no_broker_write_and_compares_hashes():
    assert "protective_stop_2fa_preflight.py" in str(ROOT / "scripts" / "protective_stop_2fa_preflight.py")
    assert "create_order_evidence_approval" in PREFLIGHT_SRC
    assert "revalidate_before_submit" in PREFLIGHT_SRC
    assert "approved_order_spec_hash" in PREFLIGHT_SRC
    assert "submit_order_spec_hash" in PREFLIGHT_SRC
    assert "broker_submitted\": False" in PREFLIGHT_SRC or '"broker_submitted": False' in PREFLIGHT_SRC
    assert "client.place_order" not in PREFLIGHT_SRC
    assert "psp.submit" not in PREFLIGHT_SRC
    assert "schwab_transport" not in PREFLIGHT_SRC
