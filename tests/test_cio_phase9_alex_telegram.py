"""Phase 9 — Alex Telegram product: materiality, decision dedupe, DEFER, canary gate.

REAL TELEGRAM SENDS: 0 under pytest. No general-channel routing.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


@pytest.fixture
def alex_iso(tmp_path, monkeypatch):
    dedupe = tmp_path / "dedupe.jsonl"
    defer = tmp_path / "defer.jsonl"
    receipt = tmp_path / "receipts.jsonl"
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(dedupe))
    monkeypatch.setenv("CIO_DEFER_LINEAGE_PATH", str(defer))
    monkeypatch.setenv("CIO_TELEGRAM_RECEIPT_PATH", str(receipt))
    monkeypatch.delenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", raising=False)
    monkeypatch.delenv("CIO_TELEGRAM_CANARY_APPROVAL", raising=False)
    monkeypatch.delenv("CIO_TELEGRAM_CANARY_ENABLE", raising=False)
    monkeypatch.setenv("CIO_THESIS_TELEGRAM", "0")
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "000000:FAKE_CIO_TOKEN_PHASE9")
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "11112222")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000000:GENERAL_MUST_NOT_USE")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999999")
    return {"dedupe": dedupe, "defer": defer, "receipt": receipt}


def _decision(**over):
    base = {
        "decision_id": "dec_abc123phase9test",
        "symbol": "SCHD",
        "action": "Trim",
        "stance": "Trim",
        "stance_code": "TRIM",
        "delta_usd": -22592.0,
        "weight_pct": 17.6,
        "why_now": "Advisory TRIM — SCHD concentration above single-name cap",
        "counter_thesis": "Income sleeve may tolerate concentration longer",
        "what_changes_call": "Weight falls under cap or multi-desk thesis revalidates",
        "next_review": "2026-08-21",
        "urgency": "high",
        "status": "open",
    }
    base.update(over)
    return base


def test_pytest_zero_live_sends(alex_iso):
    from lib import cio_alex_telegram as ax
    from lib import cio_telegram_transport as tg

    assert tg.under_pytest() is True
    res = ax.deliver_decision(_decision(), dry_run=False)
    assert res["delivered"] is False
    # even with dry_run False, pytest interdicts transport
    assert res.get("reason") in (
        "dry_run_or_interdicted", "network_interdicted_pytest_or_flag", "live_not_authorized",
    ) or res.get("interdicted") or not res["delivered"]


def test_thesis_proactive_still_zero_by_default(alex_iso):
    from lib import cio_telegram_transport as t
    out = t.notify_thesis_published("desk", 9, "A long enough thesis summary for materiality check here")
    assert out["delivered"] is False
    assert "disabled" in out["reason"] or out["attempted"] is False


def test_material_decision_and_non_material_hold(alex_iso):
    from lib import cio_alex_telegram as ax

    m = ax.is_material_event(kind="decision", decision=_decision())
    assert m["material"] is True

    hold = ax.is_material_event(kind="decision", decision=_decision(
        action="Hold", stance="Hold", stance_code="HOLD", delta_usd=0,
        why_now="no new desk signal; hold", risk="within single-name cap",
    ))
    assert hold["material"] is False

    noise = ax.is_material_event(kind="heartbeat")
    assert noise["material"] is False


def test_cio_message_is_cio_speak(alex_iso):
    from lib import cio_alex_telegram as ax

    body = ax.format_cio_message(_decision())
    assert "Alex · CIO call" in body
    assert "SCHD" in body
    assert "Why now" in body
    assert "What changes my mind" in body
    assert "dec_abc123phase9test" in body
    assert "ACK" in body


def test_second_identical_cycle_dedupes(alex_iso):
    from lib import cio_alex_telegram as ax

    d = _decision()
    cycle = ax.cycle_without_duplicate(d)
    assert cycle["first_would_send"] is True
    assert cycle["second_deduped"] is True
    assert cycle["second_would_send"] is False
    assert cycle["duplicate_suppressed"] is True


def test_state_change_allows_resend(alex_iso):
    from lib import cio_alex_telegram as ax
    from lib import cio_telegram_transport as tg

    d1 = _decision(delta_usd=-20000)
    k1 = ax.decision_dedupe_key(d1)
    tg.mark_sent(k1, meta={"decision_id": d1["decision_id"]})
    # unchanged → duplicate
    assert ax.would_duplicate(d1) is True
    # material state change (delta) → new key
    d2 = _decision(delta_usd=-30000)
    assert ax.decision_dedupe_key(d2) != k1
    assert ax.would_duplicate(d2) is False


def test_defer_lineage_reopens_same_decision_id(alex_iso):
    from lib import cio_alex_telegram as ax

    d = _decision()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    lin = ax.record_defer(d, revisit_at=past, reason="operator_defer")
    assert lin["ok"] is True
    assert lin["decision_id"] == d["decision_id"]
    assert lin["parent_decision_id"] == d["decision_id"]

    due = ax.due_defers()
    assert any(x["decision_id"] == d["decision_id"] for x in due)

    reopened = ax.reopen_deferred(lin, decision=d)
    assert reopened["decision_id"] == d["decision_id"]
    assert reopened["lifecycle"] == "reopened_from_defer"
    assert reopened["lineage_id"] == lin["lineage_id"]


def test_canary_package_never_sends(alex_iso, monkeypatch):
    from lib import cio_alex_telegram as ax

    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    pkg = ax.prepare_canary_package()
    assert pkg["live_send"] is False
    assert pkg["REAL_TELEGRAM_SENDS"] == 0
    assert pkg["status"] == "AWAITING_EXPLICIT_OPERATOR_APPROVAL"
    assert pkg["message_body"]
    assert pkg["dedupe_key"]
    assert pkg["destination_identity"]["general_chat_fallback"] is False
    assert "TELEGRAM_CIO" in pkg["destination_identity"]["bot"]
    assert pkg["proof_general_cannot_receive"]["transport_uses_cio_token_only"] is True

    # execute without approval phrase → blocked
    res = ax.execute_canary_send()
    assert res["delivered"] is False
    assert res["REAL_TELEGRAM_SENDS"] == 0
    assert "approval" in res["reason"]

    # in-process force cannot bypass env gate
    res2 = ax.execute_canary_send(force_approve_in_process=True)
    assert res2["delivered"] is False
    assert res2["REAL_TELEGRAM_SENDS"] == 0


def test_canary_still_blocked_under_pytest_even_with_env(alex_iso, monkeypatch):
    from lib import cio_alex_telegram as ax
    from lib import cio_telegram_transport as tg

    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    monkeypatch.setenv("CIO_TELEGRAM_CANARY_ENABLE", "1")
    monkeypatch.setenv("CIO_TELEGRAM_CANARY_APPROVAL", ax.CANARY_APPROVAL_PHRASE)
    # pytest interdicts network
    assert tg.network_interdicted() is True
    assert ax.canary_approval_granted() is False  # interdicted
    res = ax.execute_canary_send()
    assert res["delivered"] is False
    assert res["REAL_TELEGRAM_SENDS"] == 0


def test_outbox_dedupe_includes_decision_id(alex_iso):
    from lib.cio_notification_outbox import build_dedupe_key

    a = build_dedupe_key({
        "decision_id": "dec_shared_1",
        "material_state": "abc",
        "message_class": "advisory",
    })
    b = build_dedupe_key({
        "decision_id": "dec_shared_1",
        "material_state": "abc",
        "message_class": "advisory",
        "cio_action_id": "different_action",
    })
    # Same decision_id + state should dominate (keys include both but decision first)
    c = build_dedupe_key({
        "decision_id": "dec_shared_1",
        "material_state": "CHANGED",
        "message_class": "advisory",
    })
    assert a != c  # state change → new key
    assert len(a) == 32


def test_general_credentials_never_used_for_destination(alex_iso, monkeypatch):
    from lib import cio_alex_telegram as ax
    from lib import cio_telegram_transport as t

    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999999")
    dest = ax.canary_destination_identity()
    assert dest["allowlist_count"] == 0
    assert t.cio_chat_ids() == []
    assert dest["general_chat_fallback"] is False
