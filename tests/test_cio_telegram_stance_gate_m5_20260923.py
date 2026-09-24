"""Verification for evaluate_cio_stance_gate.

Hard block is only a bullish proposal against CIO AVOID or SELL.
HOLD and epistemic gaps rewrite GO/BUY/ACCUMULATE to WATCH and still send.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.cio_telegram_stance_gate import evaluate_cio_stance_gate  # noqa: E402


def test_avoid_and_sell_trigger_hard_block():
    """Verify AVOID and SELL trigger hard suppression of a bullish GO."""
    for hard_stance in ["AVOID", "SELL"]:
        allow_send, action, reason, _ = evaluate_cio_stance_gate("S", "GO", hard_stance)
        assert allow_send is False
        assert action == "GO"
        assert reason == "cio_stance_conflict"


def test_hold_and_epistemic_gaps_rewrite_go_to_watch():
    """Verify HOLD, RESEARCH_MORE, and HUMAN_REVIEW rewrite GO to WATCH and pass through."""
    for soft_stance in ["HOLD", "RESEARCH_MORE", "HUMAN_REVIEW", "ADD_REVIEW", "NEUTRAL"]:
        allow_send, effective_action, reason, annotation = evaluate_cio_stance_gate(
            "S", "GO", soft_stance,
        )
        assert allow_send is True
        assert effective_action == "WATCH"
        assert reason == ""
        assert f"[CIO Stance: {soft_stance}" in annotation
        assert "Action rewritten to WATCH" in annotation


def test_unstated_rewrites_go_to_watch():
    allow_send, effective_action, reason, annotation = evaluate_cio_stance_gate("S", "GO", None)
    assert allow_send is True
    assert effective_action == "WATCH"
    assert reason == ""
    assert "[CIO Stance: UNSTATED — Action rewritten to WATCH]" in annotation


def test_matching_stance_passes_unchanged():
    """Verify explicit BUY agreement passes without rewrite."""
    allow_send, effective_action, reason, annotation = evaluate_cio_stance_gate("S", "BUY", "BUY")
    assert allow_send is True
    assert effective_action == "BUY"
    assert reason == ""
    assert annotation == ""


# --- M5 step 2 (2026-09-23): unlisted non-bull stances, truthful rewrite, hold dedupe ---

import json  # noqa: E402

from lib.cio_telegram_stance_gate import (  # noqa: E402
    HELD_DISAGREEMENT,
    HELD_MISSING,
    apply_stance_rewrite,
    check_investment_send,
)


def _view(action, as_of="2026-09-23T12:00:00Z"):
    return {"symbol": "S", "action": action, "created_at": as_of}


def test_unlisted_non_bullish_cio_action_still_holds_bullish():
    """WAIT / NO_GO / TRIM are neither interdict nor listed soft gap: keep the hold."""
    for action in ("WAIT", "NO_GO", "TRIM", "EXIT", "SOMETHING_NEW"):
        v = check_investment_send(
            symbol="S", message_text="GO S", asserted_stance="bullish", cio_view=_view(action),
        )
        assert v.allow is False, action
        assert v.held_reason == HELD_DISAGREEMENT, action


def test_missing_cio_row_stays_fail_closed():
    v = check_investment_send(
        symbol="S", message_text="GO S", asserted_stance="bullish", db_query=lambda *a, **k: [],
    )
    assert v.allow is False
    assert v.held_reason == HELD_MISSING


def test_blank_action_on_existing_row_is_unstated_soft_rewrite():
    v = check_investment_send(
        symbol="S", message_text="GO S", asserted_stance="bullish", cio_view=_view(""),
    )
    assert v.allow is True
    assert v.effective_action == "WATCH"
    assert "UNSTATED" in v.annotation_text


def test_rewrite_covers_tier_headline_and_labelled_decision():
    v = check_investment_send(
        symbol="S", message_text="A+ S", asserted_stance="bullish", cio_view=_view("RESEARCH_MORE"),
    )
    out = apply_stance_rewrite("🔥 A+ S — momentum scalp setup\nDecision: GO", "S", v)
    assert "A+" not in out
    assert "Decision: WATCH" in out
    assert out.rstrip().endswith("[CIO Stance: RESEARCH_MORE — Action rewritten to WATCH]")


def test_rewrite_of_go_before_symbol():
    v = check_investment_send(
        symbol="S", message_text="GO S", asserted_stance="bullish", cio_view=_view("HOLD"),
    )
    out = apply_stance_rewrite("✅ GO S — momentum scalp setup", "S", v)
    assert out.startswith("✅ WATCH S")


def test_footer_does_not_claim_rewrite_when_no_verb_changed():
    v = check_investment_send(
        symbol="S", message_text="S entry card", asserted_stance="bullish", cio_view=_view("ADD_REVIEW"),
    )
    out = apply_stance_rewrite("S entry card · zone 24–25", "S", v)
    assert "rewritten" not in out
    assert out.rstrip().endswith("[CIO Stance: ADD_REVIEW]")


def _rows(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _held(sym="S", as_of="2026-09-23T12:00:00Z"):
    return check_investment_send(
        symbol=sym, message_text=f"GO {sym}", asserted_stance="bullish",
        cio_view={"symbol": sym, "action": "AVOID", "created_at": as_of},
        source="send_telegram_proposal_alert",
    )


def test_identical_holds_write_one_row_per_window_but_every_run_is_held(tmp_path, monkeypatch):
    receipt = tmp_path / "holds.jsonl"
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", str(receipt))
    monkeypatch.setenv("CIO_STANCE_HOLD_DEDUPE_SECONDS", "3600")
    verdicts = [_held() for _ in range(5)]
    assert all(v.allow is False for v in verdicts)
    rows = _rows(receipt)
    assert len(rows) == 1
    assert rows[0]["cio_as_of"] == "2026-09-23T12:00:00Z"


def test_new_cio_decision_or_symbol_records_a_new_row(tmp_path, monkeypatch):
    receipt = tmp_path / "holds.jsonl"
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", str(receipt))
    _held()
    _held(as_of="2026-09-23T15:00:00Z")
    _held(sym="NOC")
    assert len(_rows(receipt)) == 3


def test_row_after_window_carries_repeat_count(tmp_path, monkeypatch):
    import lib.cio_telegram_stance_gate as gate

    receipt = tmp_path / "holds.jsonl"
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", str(receipt))
    monkeypatch.setenv("CIO_STANCE_HOLD_DEDUPE_SECONDS", "60")
    _held()
    _held()
    _held()
    state_path = gate._dedupe_state_path(receipt)
    state = json.loads(state_path.read_text())
    for v in state.values():
        v["last_row_ts"] -= 120
    state_path.write_text(json.dumps(state))
    _held()
    rows = _rows(receipt)
    assert len(rows) == 2
    assert rows[1]["repeats_since_last_row"] == 2


def test_dedupe_window_zero_disables(tmp_path, monkeypatch):
    receipt = tmp_path / "holds.jsonl"
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", str(receipt))
    monkeypatch.setenv("CIO_STANCE_HOLD_DEDUPE_SECONDS", "0")
    _held()
    _held()
    assert len(_rows(receipt)) == 2
