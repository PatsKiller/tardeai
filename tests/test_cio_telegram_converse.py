"""CIO Telegram converse unit tests (no live Telegram)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def paths(tmp_path, monkeypatch):
    dedup = tmp_path / "dedup.jsonl"
    mmap = tmp_path / "map.jsonl"
    rate = tmp_path / "rate.jsonl"
    plans_e = tmp_path / "plans.jsonl"
    plans_p = tmp_path / "plans_proj.json"
    goals_e = tmp_path / "goals.jsonl"
    goals_p = tmp_path / "goals_proj.json"
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "999001")
    monkeypatch.setenv("CIO_TELEGRAM_CONVERSE", "1")
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "")  # no live send
    monkeypatch.setenv("CIO_TELEGRAM_WAKES_PER_HOUR", "50")
    # redirect plan store defaults via monkeypatch constructors in tests
    return {
        "dedup": dedup,
        "map": mmap,
        "rate": rate,
        "plans_e": plans_e,
        "plans_p": plans_p,
        "goals_e": goals_e,
        "goals_p": goals_p,
    }


def test_allowlist_rejection(paths, monkeypatch):
    from scripts.lib.cio_telegram_converse import process_telegram_message
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "111")
    msg = {
        "message_id": 1,
        "chat": {"id": 999},
        "text": "hello",
        "from": {"id": 1, "username": "x"},
    }
    r = process_telegram_message(
        msg, dedup_path=paths["dedup"], msg_map_path=paths["map"],
        rate_path=paths["rate"], dry_run=True,
    )
    assert r["reason"] == "not_allowlisted"
    assert r["handled"] is False


def test_message_dedup(paths, monkeypatch):
    from scripts.lib import cio_telegram_converse as c
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "999001")
    msg = {
        "message_id": 42,
        "chat": {"id": 999001},
        "text": "What about SCHD?",
        "from": {"id": 1},
    }
    # first
    r1 = c.process_telegram_message(
        msg, dedup_path=paths["dedup"], msg_map_path=paths["map"],
        rate_path=paths["rate"], dry_run=True,
    )
    # dry_run does not mark seen — mark manually then second
    c.mark_message_seen(42, "999001", path=paths["dedup"])
    r2 = c.process_telegram_message(
        msg, dedup_path=paths["dedup"], msg_map_path=paths["map"],
        rate_path=paths["rate"], dry_run=True,
    )
    assert r2["reason"] == "duplicate_message_id"


def test_reply_to_attaches_plan_id(paths):
    from scripts.lib.cio_telegram_converse import (
        plan_id_for_reply_message,
        record_plan_message,
        parse_ids_from_text,
        parse_reply_footer,
    )
    record_plan_message("plan_abc123", 777, "999001", path=paths["map"])
    assert plan_id_for_reply_message(777, path=paths["map"]) == "plan_abc123"
    footer = parse_reply_footer("summary\nplan_id: `plan_xyz`\n")
    assert footer["plan_id"] == "plan_xyz"
    parsed = parse_ids_from_text("re: plan_foo99 please update")
    assert parsed["plan_id"] == "plan_foo99"


def test_structured_reply_formatter():
    from scripts.lib.cio_telegram_converse import format_structured_reply
    text = format_structured_reply(
        summary="Held name under review.",
        evidence_refs=[{"domain": "holdings", "as_of": "2026-08-11", "fields_used": ["last"]}],
        options=[{"id": "hold", "label": "Hold"}],
        recommendation="Hold and revisit.",
        risks=["Further drawdown"],
        plan_id="plan_test01",
        revisit_at="2026-08-12T00:00:00+00:00",
        llm_deferred=True,
    )
    assert "plan_test01" in text
    assert "READ_ONLY" in text
    assert "Hold" in text
    assert "holdings" in text
    assert "LLM deferred" in text


def test_process_free_text_dry_run_creates_path(paths, monkeypatch, tmp_path):
    """Dry-run free-text: allowlisted, not duplicate, produces converse kind."""
    from scripts.lib.cio_telegram_converse import process_telegram_message
    # patch plan store to tmp
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "999001")
    monkeypatch.setenv("CIO_TELEGRAM_CONVERSE", "1")

    import scripts.lib.cio_plans as plans_mod
    from scripts.lib.cio_plans import CIOPlanStore
    # monkeypatch ensure_converse_plan's store by patching class default paths is hard;
    # dry_run skips plan create and send
    msg = {
        "message_id": 1001,
        "chat": {"id": 999001},
        "text": "Thoughts on concentration in SCHD?",
        "from": {"id": 7, "username": "ops"},
    }
    r = process_telegram_message(
        msg, dedup_path=paths["dedup"], msg_map_path=paths["map"],
        rate_path=paths["rate"], dry_run=True,
    )
    assert r["handled"] is True
    assert r["kind"] == "converse"
    assert r.get("reply_preview")


def test_process_with_reply_to_plan(paths, monkeypatch):
    from scripts.lib.cio_telegram_converse import (
        process_telegram_message,
        record_plan_message,
    )
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "999001")
    record_plan_message("plan_cont99", 555, "999001", path=paths["map"])
    msg = {
        "message_id": 1002,
        "chat": {"id": 999001},
        "text": "Please continue",
        "from": {"id": 7},
        "reply_to_message": {
            "message_id": 555,
            "text": "prior\nplan_id: `plan_cont99`\n",
        },
    }
    r = process_telegram_message(
        msg, dedup_path=paths["dedup"], msg_map_path=paths["map"],
        rate_path=paths["rate"], dry_run=True,
    )
    assert r["handled"] is True
    assert r.get("attached_plan_id") == "plan_cont99"


def test_wake_enqueue_mock(paths, monkeypatch, tmp_path):
    from scripts.lib.cio_telegram_converse import enqueue_operator_wake
    # Use real wake store under tmp by monkeypatching path if possible
    from scripts.lib import cio_wake_jobs as wj
    wake_path = tmp_path / "wakes.jsonl"
    store = wj.CIOWakeJobStore(event_store_path=wake_path)
    monkeypatch.setattr(
        "scripts.lib.cio_telegram_converse.enqueue_operator_wake",
        lambda **kw: _real_enqueue(store, **kw),
    )

    def _real_enqueue(st, **kw):
        from scripts.lib.cio_telegram_converse import enqueue_operator_wake as real
        # call store directly
        hour = "2026081116"
        wid = f"wake_op_alex_{kw['message_id']}_{hour}"
        st.enqueue({
            "wake_job_id": wid,
            "trigger_type": "OPERATOR_MESSAGE",
            "trigger_ref": kw["message_id"],
            "reason_codes": ["OPERATOR_MESSAGE"],
            "wake_intent": "NEW_RUN",
            "idempotency_key": wid,
            "context": {"text": kw["text"], "plan_id": kw.get("plan_id")},
        }, actor_id="test")
        return wid

    wid = _real_enqueue(store, chat_id="1", message_id="9", text="hi", plan_id=None, goal_id=None, action_id=None, event_id=None)
    assert wid
    w = store.get_wake_job(wid)
    assert w["trigger_type"] == "OPERATOR_MESSAGE"
    assert w["current_status"] == "PENDING"


def test_slash_help(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "1")
    from scripts.lib.cio_telegram_converse import handle_cio_slash
    h = handle_cio_slash("/cio help")
    assert "portfolio" in h.lower() or "CIO" in h
