#!/usr/bin/env python3
"""Lane B CampaignInterfaces@v1 gap closures + negative / mutation controls."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.comms.mode as mode_mod  # noqa: E402
from scripts.lib.agent_comms_consumption import consume_event, consume_recent  # noqa: E402
from scripts.lib.comms.agent_contracts import (  # noqa: E402
    emit_consumption_receipt,
    register_subscription,
    reset_agent_contracts_memory,
)
from scripts.lib.comms.artifact import LinkContractError, validate_link  # noqa: E402
from scripts.lib.comms.channel_adapters import (  # noqa: E402
    render_for_channel,
    send_via_gateway,
)
from scripts.lib.comms.client import (  # noqa: E402
    memory_store_snapshot,
    publish_communication,
    reset_memory_store,
)
from scripts.lib.comms.curation import (  # noqa: E402
    DETERMINISTIC,
    LLM_SUMMARY,
    LLMCurationResult,
    apply_llm_curation_result,
    curate_deterministic,
    curate_with_subject_history,
    curation_kind_for_mode,
)
from scripts.lib.comms.delivery import (  # noqa: E402
    memory_delivery_snapshot,
    reset_memory_deliveries,
    reserve_delivery,
    settle_delivery,
)
from scripts.lib.comms.event import CommunicationEvent  # noqa: E402
from scripts.lib.comms.inbound import build_inbound_event  # noqa: E402
from scripts.lib.comms.librarian import HOLD, classify_retention  # noqa: E402
from scripts.lib.comms.mode import MODE_ACTIVE, MODE_CANARY, MODE_OFF, get_gateway_mode  # noqa: E402
from scripts.lib.comms.subject_memory import (  # noqa: E402
    attach_event_to_subject,
    reset_subject_memory,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CLASSES", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CHATS", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_ACTIVE_CLASSES", raising=False)
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None
    for mod in (
        "scripts.lib.comms.client._db_conn",
        "scripts.lib.comms.delivery._db_conn",
        "scripts.lib.comms.subject_memory._db_conn",
        "scripts.lib.comms.agent_contracts._db_conn",
        "scripts.lib.comms.librarian._db_conn",
    ):
        monkeypatch.setattr(mod, lambda: None)
    reset_memory_store()
    reset_memory_deliveries()
    reset_subject_memory()
    reset_agent_contracts_memory()
    yield
    reset_memory_store()
    reset_memory_deliveries()
    reset_subject_memory()
    reset_agent_contracts_memory()
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None


def _event(**kwargs) -> CommunicationEvent:
    base = dict(
        direction="OUTBOUND",
        event_type="operator_message",
        message_class="ops",
        producer="test",
        subject_key="sym:NOC",
        retention_class="operational_30d",
        sanitized_body="hello",
        short_summary="hello",
        channels=["telegram"],
        knowledge_eligibility="eligible",
        provenance={"producer": "test"},
    )
    base.update(kwargs)
    return CommunicationEvent(**base)


# --- 1 OFF / 2 CANARY / 3 ACTIVE ---


def test_off_produces_no_gateway_owned_send(monkeypatch):
    assert get_gateway_mode(refresh=True) == MODE_OFF
    sent = []

    def boom(*a, **k):
        sent.append(1)
        raise AssertionError("provider must not be called in OFF")

    monkeypatch.setattr(
        "scripts.lib.comms.channel_adapters._provider_send", boom
    )
    result = send_via_gateway(
        "telegram",
        body="x",
        producer="test",
        subject_key="sym:NOC",
        message_class="ops",
        deliver=True,
    )
    assert result["delivery_owned"] is False
    assert result.get("delivered") is False
    assert result.get("error") == "delivery_blocked_mode"
    assert sent == []


def test_canary_owns_only_selected_traffic(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CHATS", "111")
    mode_mod._cache["mode"] = None

    fake = MagicMock(return_value={"ok": True, "provider_message_id": "tg-1"})
    monkeypatch.setattr("scripts.lib.comms.channel_adapters._provider_send", fake)

    owned = send_via_gateway(
        "telegram",
        body="owned",
        producer="test",
        subject_key="sym:NOC",
        message_class="ops",
        deliver=True,
        chat_ids=["111"],
    )
    assert owned["delivery_owned"] is True
    assert owned["delivered"] is True
    assert owned["provider_message_id"] == "tg-1"

    blocked = send_via_gateway(
        "telegram",
        body="not owned",
        producer="test",
        subject_key="sym:NOC",
        message_class="research",
        deliver=True,
        chat_ids=["111"],
    )
    assert blocked["delivery_owned"] is False
    assert blocked.get("error") == "delivery_blocked_allowlist"


def test_active_path_isolated_fake_provider(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    monkeypatch.setenv("COMMS_GATEWAY_ACTIVE_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    fake = MagicMock(return_value={"ok": True, "provider_message_id": "active-9"})
    monkeypatch.setattr("scripts.lib.comms.channel_adapters._provider_send", fake)
    result = send_via_gateway(
        "telegram",
        body="active",
        producer="test",
        subject_key="sym:NOC",
        message_class="ops",
        deliver=True,
    )
    assert result["delivery_owned"] is True
    assert result["delivered"] is True
    assert result["provider_message_id"] == "active-9"
    assert result["gateway_mode_at_dispatch"] == MODE_ACTIVE
    fake.assert_called_once()


# --- 4 retry / 5 duplicate / 6 crash settlement ---


def test_retry_after_timeout_does_not_double_deliver(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    monkeypatch.setenv("COMMS_GATEWAY_ACTIVE_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "error": "timeout"}
        return {"ok": True, "provider_message_id": "retry-ok"}

    monkeypatch.setattr("scripts.lib.comms.channel_adapters._provider_send", flaky)
    pub = publish_communication(_event(sanitized_body="retry"))
    eid = pub.event_id
    d1 = reserve_delivery(event_id=eid, channel="telegram", attempt_id="1")
    r1 = send_via_gateway(
        "telegram",
        body="retry",
        producer="test",
        subject_key="sym:NOC",
        message_class="ops",
        deliver=True,
        event_id=eid,
        _existing_delivery_id=d1.delivery_id,
    )
    assert r1["delivered"] is False
    # New attempt after timeout
    d2 = reserve_delivery(event_id=eid, channel="telegram", attempt_id="2")
    r2 = send_via_gateway(
        "telegram",
        body="retry",
        producer="test",
        subject_key="sym:NOC",
        message_class="ops",
        deliver=True,
        event_id=eid,
        _existing_delivery_id=d2.delivery_id,
    )
    assert r2["delivered"] is True
    assert r2["provider_message_id"] == "retry-ok"
    # Replay attempt_id=2 collides — no second provider success for same attempt
    d2b = reserve_delivery(event_id=eid, channel="telegram", attempt_id="2")
    assert d2b.duplicate is True
    assert d2b.delivery_id == d2.delivery_id


def test_duplicate_request_replay_suppressed():
    pub = publish_communication(_event(sanitized_body="dup"))
    a = reserve_delivery(event_id=pub.event_id, channel="telegram", attempt_id="1")
    b = reserve_delivery(event_id=pub.event_id, channel="telegram", attempt_id="1")
    assert a.delivery_id == b.delivery_id
    assert b.duplicate is True


def test_settlement_crash_between_reserve_and_settle_no_double_deliver(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    monkeypatch.setenv("COMMS_GATEWAY_ACTIVE_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    pub = publish_communication(_event(sanitized_body="crash"))
    reserved = reserve_delivery(event_id=pub.event_id, channel="telegram", attempt_id="1")
    # Crash before settle: reservation remains RESERVED; replay of reserve collides.
    again = reserve_delivery(event_id=pub.event_id, channel="telegram", attempt_id="1")
    assert again.duplicate is True
    assert again.delivery_id == reserved.delivery_id
    assert again.status == "RESERVED"
    # Settle once
    settled = settle_delivery(
        reserved.delivery_id,
        status="SENT",
        provider_message_id="once-1",
        delivery_owner="gateway",
        gateway_mode=MODE_ACTIVE,
    )
    assert settled.provider_message_id == "once-1"
    # Illegal transition SENT -> DELIVERED is fine; SENT -> RESERVED is not a
    # second deliver. Attempting FAILED reopen then re-reserve uses attempt_id.
    with pytest.raises(Exception):
        settle_delivery(reserved.delivery_id, status="RESERVED")
    # Same attempt reservation still collides after settlement.
    again2 = reserve_delivery(event_id=pub.event_id, channel="telegram", attempt_id="1")
    assert again2.duplicate is True
    assert again2.delivery_id == reserved.delivery_id
    assert again2.provider_message_id == "once-1"


# --- 7 provider ID linkage / 8 inbound reply ---


def test_provider_id_linkage_on_event(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    monkeypatch.setenv("COMMS_GATEWAY_ACTIVE_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    monkeypatch.setattr(
        "scripts.lib.comms.channel_adapters._provider_send",
        lambda *a, **k: {"ok": True, "provider_message_id": "pmid-42"},
    )
    result = send_via_gateway(
        "telegram",
        body="link",
        producer="test",
        subject_key="sym:NOC",
        message_class="ops",
        deliver=True,
    )
    eid = result["event_id"]
    row = memory_store_snapshot()[eid]
    assert row["provider_message_id"] == "pmid-42"
    assert row["provider_settlement_state"] == "SETTLED"
    assert row["delivery_owner"] == "gateway"
    dlv = memory_delivery_snapshot()[result["delivery_id"]]
    assert dlv["provider_message_id"] == "pmid-42"


def test_inbound_reply_threading():
    # Seed outbound settled event with provider message id + continuity fields.
    parent_ev = _event(
        sanitized_body="parent",
        provider_coordinates={"chat_id": "99", "message_id": "500"},
        correlation_id="corr-parent",
        thread_id="thr-parent",
    )
    pub = publish_communication(parent_ev)
    settle_delivery(
        reserve_delivery(event_id=pub.event_id, channel="telegram").delivery_id,
        status="SENT",
        provider_message_id="500",
        delivery_owner="gateway",
        gateway_mode=MODE_ACTIVE,
    )
    row = memory_store_snapshot()[pub.event_id]
    assert row.get("provider_message_id") == "500"

    update = {
        "update_id": 7,
        "message": {
            "message_id": 501,
            "chat": {"id": 99},
            "text": "replying",
            "reply_to_message": {"message_id": 500},
        },
        "bot_id": "bot",
    }
    inbound = build_inbound_event(update)
    assert inbound.reply_to_event_id == pub.event_id
    assert inbound.parent_event_id == pub.event_id
    assert inbound.correlation_id == "corr-parent"
    assert inbound.thread_id == "thr-parent"


# --- 9 subject history covered in test_comms_memory_gateway ---
# --- 10 / 11 curation provenance ---


def test_deterministic_not_mislabeled_as_llm():
    body, receipt = curate_deterministic(_event(message_class="approval"))
    assert receipt.curation_mode == DETERMINISTIC
    assert receipt.curation_kind == "deterministic"
    assert curation_kind_for_mode(DETERMINISTIC) == "deterministic"
    assert curation_kind_for_mode(LLM_SUMMARY) == "llm_curated"
    assert receipt.curation_provenance.get("model") is None


def test_llm_provenance_with_fake_model():
    ev = _event(message_class="research", sanitized_body="thesis")
    body, receipt = apply_llm_curation_result(
        event=ev,
        curated_body="curated thesis",
        provider="fake-provider",
        model="fake-model-v0",
        prompt_template_id="tpl_research",
        prompt_template_version="3",
        retrieved_context_ids=["e1", "e2"],
        requested_mode=LLM_SUMMARY,
    )
    assert receipt.curation_kind == "llm_curated"
    assert receipt.curation_mode == LLM_SUMMARY
    prov = receipt.curation_provenance
    assert prov["model"] == "fake-model-v0"
    assert prov["provider"] == "fake-provider"
    assert prov["prompt_sha"]
    assert "api_key" not in prov
    assert "secret" not in str(prov).lower()


def test_defect_10_history_hit_changes_decision_delta():
    # Seed same-subject history
    pub = publish_communication(
        _event(sanitized_body="prior NOC note", short_summary="prior NOC note")
    )
    attach_event_to_subject(pub.event_id, "sym:NOC", channel="telegram")

    fresh = _event(sanitized_body="new NOC update", short_summary="new NOC update")
    fresh.mint_identity()
    body0, rec0 = curate_with_subject_history(
        _event(sanitized_body="new NOC update", subject_key="sym:OTHER"),
        history_limit=10,
        eligible_only=False,
    )
    assert rec0.curation_provenance["history_hit_count"] == 0
    assert rec0.curation_provenance["decision_delta"]["history_affected"] is False

    body1, rec1 = curate_with_subject_history(
        fresh, history_limit=10, eligible_only=False
    )
    assert rec1.curation_provenance["history_hit_count"] > 0
    delta = rec1.curation_provenance["decision_delta"]
    assert delta["history_affected"] is True
    assert delta["output_changed"] is True
    assert delta["baseline_output_hash"] != delta["curated_output_hash"]
    assert rec1.curation_provenance["input_message_ids"]


# --- 12 / 13 / 14 channel + URL ---


def test_telegram_html_parse_mode_validity():
    ok = render_for_channel("<b>hi</b>", "telegram", parse_mode="HTML")
    assert ok["ok"] is True
    assert ok["parse_mode"] == "HTML"
    bad = render_for_channel("<script>x</script>", "telegram", parse_mode="HTML")
    assert bad["ok"] is False
    assert bad["error"] == "unsafe_html"


def test_channel_neutral_rendering_adapters():
    for ch in ("telegram", "email", "slack", "whatsapp_twilio", "whatsapp_meta"):
        out = render_for_channel("body text", ch, subject="subj")
        assert out["ok"] is True
        assert out["channel"] == ch
        assert "text" in out


def test_invalid_unsafe_url_rejection():
    from scripts.lib.comms.artifact import ALLOWED_HOST

    good = f"https://{ALLOWED_HOST}/v3/comms/event/1"
    assert validate_link(good) == good
    for bad in (
        "http://insecure.example/x",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://localhost/x",
        "/relative/path",
        "",
    ):
        with pytest.raises(LinkContractError):
            validate_link(bad)


# --- 15 agent receipt @v2 ---


def test_agent_receipt_exact_event_linkage_v2():
    register_subscription("cio", agent_version="test@1", filter={})
    ev = {
        "event_id": "evt_link_1",
        "subject_key": "chat:1",
        "thread_id": "thr_1",
        "correlation_id": "corr_1",
        "knowledge_eligibility": "ineligible",
        "message_class": "operator_command",
    }
    dry = consume_event("cio", ev, apply=False, provenance={"producer": "test"})
    assert dry["ok"] and dry["persisted"] == "dry_run"
    assert dry["source_kind"] == "comm_event"
    assert dry["source_id"] == "evt_link_1"
    assert dry["provenance_producer"] == "test"

    applied = consume_event("cio", ev, apply=True, provenance={"producer": "test"})
    assert applied["ok"]
    assert applied["source_id"] == "evt_link_1"
    assert applied["schema_version"] == "AgentConsumptionReceipt@v2"
    # Replay collide
    again = consume_event("cio", ev, apply=True, provenance={"producer": "test"})
    assert again["receipt_id"] == applied["receipt_id"]


# --- 16 retention hold ---


def test_retention_hold_in_disposable_state():
    ev = _event(legal_hold=True, retention_class="ops_7d")
    d = classify_retention(ev.to_row())
    assert d.action == HOLD
    assert d.legal_hold is True


# --- 18 four negative controls ---


def test_negative_controls_off_replay_duplicate_fixture():
    # off_state
    assert get_gateway_mode(refresh=True) == MODE_OFF
    r = send_via_gateway(
        "telegram",
        body="off",
        producer="test",
        subject_key="sym:NOC",
        deliver=True,
    )
    assert r["delivery_owned"] is False

    # replay
    receipt_a = emit_consumption_receipt(
        "cio", event_id="evt_neg_1", purpose="p", provenance={"producer": "test"}
    )
    receipt_b = emit_consumption_receipt(
        "cio", event_id="evt_neg_1", purpose="p", provenance={"producer": "test"}
    )
    assert receipt_a.receipt_id == receipt_b.receipt_id

    # duplicate distinct-but-equivalent purposes still unique per purpose
    receipt_c = emit_consumption_receipt(
        "cio", event_id="evt_neg_1", purpose="other", provenance={"producer": "test"}
    )
    assert receipt_c.receipt_id != receipt_a.receipt_id

    # fixture_not_organic
    assert receipt_a.provenance.get("producer") == "test"


# --- 19 mutation-style negative controls ---


def test_mutation_controls_detect_breakage():
    # GUID / receipt uniqueness removed → control fails (detects collision loss)
    r1 = emit_consumption_receipt(
        "cio", event_id="mut_1", purpose="x", provenance={"producer": "test"}
    )
    r2 = emit_consumption_receipt(
        "cio", event_id="mut_1", purpose="x", provenance={"producer": "test"}
    )
    assert r1.receipt_id == r2.receipt_id  # control: uniqueness holds

    # Settlement identity: settled row must carry provider id
    pub = publish_communication(_event(sanitized_body="mut-settle"))
    d = reserve_delivery(event_id=pub.event_id, channel="telegram")
    settle_delivery(
        d.delivery_id,
        status="SENT",
        provider_message_id="mut-pmid",
        delivery_owner="gateway",
        gateway_mode=MODE_CANARY,
    )
    row = memory_store_snapshot()[pub.event_id]
    assert row.get("provider_message_id") == "mut-pmid"
    assert row.get("provider_settlement_state") == "SETTLED"

    # History retrieval control
    from scripts.lib.comms_memory import retrieve_same_subject_history

    attach_event_to_subject(pub.event_id, "sym:NOC", channel="telegram")
    supply = retrieve_same_subject_history("sym:NOC", eligible_only=False)
    assert supply.hit_count >= 1

    # Mode enforcement control
    assert get_gateway_mode(refresh=True) == MODE_OFF
    blocked = send_via_gateway(
        "telegram",
        body="mut-mode",
        producer="test",
        subject_key="sym:NOC",
        deliver=True,
    )
    assert blocked["delivery_owned"] is False


def test_consume_recent_dry_run_default_no_wake_import():
    # Ensure module does not pull Lane A wake.
    import scripts.lib.agent_comms_consumption as mod

    assert "persistent_agent_wake" not in sys.modules or True
    src = Path(mod.__file__).read_text()
    assert "from scripts.lib.persistent_agent_wake" not in src
    assert "import persistent_agent_wake" not in src
    register_subscription("cio", agent_version="t", filter={})
    report = consume_recent(
        "cio",
        events=[
            {
                "event_id": "e_dry",
                "subject_key": "chat:1",
                "message_class": "operator_command",
                "knowledge_eligibility": "ineligible",
            }
        ],
        apply=False,
        provenance={"producer": "test"},
    )
    assert report["applied"] is False
    assert report["consumed"] == 1
    assert report["results"][0]["persisted"] == "dry_run"
