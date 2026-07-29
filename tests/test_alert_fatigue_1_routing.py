"""Tests for ALERT-FATIGUE-1 routing."""
import sys, os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))


def test_stop_crossed_suppressed():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("ATP REVIEW ALERT -- STOP CROSSED PENDING\nSymbol: ASPN")

def test_large_move_suppressed():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("ATP REVIEW ALERT -- LARGE MOVE BEFORE REVIEW\nSymbol: NWG")

def test_proposal_rejected_suppressed():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("PROPOSAL REJECTED: BCS")

def test_proposal_deferred_suppressed():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("PROPOSAL DEFERRED: MUD")

def test_approval_blocked_suppressed():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("Approval: BLOCKED\nNo order submitted")

def test_dry_run_suppressed():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("dry_run_approved: CMCSA")

def test_trade_opened_queues_digest_or_dashboard():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("TRADE OPENED: CMCSA 120 shares @ $24.97")

def test_trade_closed_queues_digest_or_dashboard():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("TRADE CLOSED: INFU — target hit")

def test_stop_hit_queues_digest_unless_unresolved_protection():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("STOP HIT: GCTS — stopped @ $1.37")

def test_trailing_stop_trigger_queues_digest_unless_approval_required():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("TRAILING STOP TRIGGERED: FLYW")

def test_entry_filled_not_immediate_without_operator_action():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("ENTRY_FILLED: NWG 189 shares")

def test_exit_filled_not_immediate_without_operator_action():
    from telegram_alert_router import should_send_telegram
    assert not should_send_telegram("EXIT_FILLED: ASPN 553 shares")

def test_no_trading_in_router():
    src = open(f"{PROJECT_ROOT}/scripts/telegram_alert_router.py").read()
    assert "submit_order" not in src
    assert "create_order" not in src
    assert "cancel_order" not in src
