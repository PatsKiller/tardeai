"""P1-WS3 Operator S0 workflow — failure battery (tmp_path, no network).

Authority: READ_ONLY_ADVISORY. MBI=0. INTERDICT left as found.
Covers: duplicate / out-of-order / missing / late messages · restart-safe
converse + turn state · question/ack/defer/reject/S0 mint · InstrumentRecord
operator_turns · would_send/CC under INTERDICT.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_notification_policy as policy
from scripts.lib.cio_instrument_record import new_record
from scripts.lib.cio_rehydrate import attach_operator_turn
from scripts.lib.cio_s0_operator_loop import (
    ACK,
    DEFER,
    QUESTION,
    REJECT,
    SITUATION_TYPE,
    classify_intent,
    last_turn_for,
    load_turns,
    persist_turn,
    route_turn,
)
from scripts.lib.cio_telegram_converse import (
    mark_message_seen,
    message_seen,
    process_telegram_message,
)
from scripts.lib.instrument_record import build_instrument_record


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
SCHD_S6 = {
    "plan_id": "plan_schd_s6",
    "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
    "symbols": ["SCHD"],
    "status": "proposed",
    "created_ts": "2026-08-01",
}


@pytest.fixture
def dedup(tmp_path: Path) -> Path:
    return tmp_path / "cio_telegram_msg_dedup.jsonl"


# ------------------------------------------------------------------ flows


@pytest.mark.parametrize(
    "text,intent,action",
    [
        ("what about RTX", QUESTION, "mint"),
        ("ack SCHD", ACK, "attach"),
        ("SCHD defer until earnings", DEFER, "attach"),
        ("reject SCHD please", REJECT, "attach"),
    ],
)
def test_ws3_flow_matrix_question_ack_defer_reject(text, intent, action):
    r = route_turn(text, plans=[SCHD_S6], now=NOW)
    assert classify_intent(text) == intent
    assert r["intent"] == intent
    assert r["action"] == action
    if action == "mint":
        assert r["mint_situation_type"] == SITUATION_TYPE
        assert r["symbol"] == "RTX"
    else:
        assert r["plan_id"] == "plan_schd_s6"


def test_ws3_s0_escalation_mints_operator_converse():
    r = route_turn("what about NVDA", plans=[], now=NOW)
    assert r["action"] == "mint"
    assert r["mint_situation_type"] == "S0_OPERATOR_CONVERSE"
    assert r["symbol"] == "NVDA"
    assert r["authority"] == "READ_ONLY_ADVISORY"
    assert r["memory_behavior_influence"] == 0
    assert r["financial_action"] is False


# ---------------------------------------------------------- message battery


def test_ws3_duplicate_message_id_rejected(dedup: Path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "999001")
    monkeypatch.setenv("CIO_TELEGRAM_CONVERSE", "1")
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "")

    key = "telegram:42"
    mark_message_seen(key, "999001", path=dedup)
    assert message_seen(key, path=dedup) is True

    msg = {
        "message_id": 42,
        "chat": {"id": 999001},
        "text": "What about SCHD?",
        "from": {"id": 1},
    }
    r = process_telegram_message(
        msg, dedup_path=dedup, msg_map_path=dedup.parent / "map.jsonl",
        rate_path=dedup.parent / "rate.jsonl", dry_run=True,
    )
    assert r["handled"] is False
    assert r["reason"] == "duplicate_message_id"


def test_ws3_out_of_order_and_missing_and_late_message_ids(dedup: Path):
    """No sequence gate: unique ids win; gaps and late arrivals are fine."""
    chat = "999001"
    # Arrive as 101, 103, missing 102, then late 102
    order = [101, 103, 102]
    for mid in order:
        key = f"telegram:{mid}"
        assert message_seen(key, path=dedup) is False
        mark_message_seen(key, chat, path=dedup)
        assert message_seen(key, path=dedup) is True

    # Duplicates of any of them fail closed
    for mid in order:
        assert message_seen(f"telegram:{mid}", path=dedup) is True

    rows = [
        json.loads(line)
        for line in dedup.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {r["message_id"] for r in rows} == {
        "telegram:101", "telegram:102", "telegram:103",
    }


def test_ws3_dedup_restart_safe(dedup: Path, tmp_path: Path):
    mark_message_seen("telegram:77", "999001", path=dedup)
    # Simulate process restart: new path object, same file
    reloaded = tmp_path / "cio_telegram_msg_dedup.jsonl"
    assert reloaded == dedup
    assert message_seen("telegram:77", path=reloaded) is True
    assert message_seen("telegram:78", path=reloaded) is False


# ------------------------------------------------------------- turn store


def test_ws3_turn_store_restart_mid_conversation(tmp_path: Path):
    t0 = NOW
    t1 = NOW + timedelta(minutes=5)
    persist_turn(tmp_path, route_turn("what about RTX", plans=[], now=t0))
    persist_turn(
        tmp_path,
        route_turn("RTX defer until earnings", plans=[], now=t1),
    )
    # New "process" — only the path survives
    last = last_turn_for("RTX", tmp_path)
    assert last is not None
    assert last["intent"] == DEFER
    assert len(load_turns(tmp_path)) == 2


def test_ws3_out_of_order_turn_append_uses_created_at(tmp_path: Path):
    """File order is not authority — created_at is."""
    newer = NOW + timedelta(hours=1)
    older = NOW
    persist_turn(
        tmp_path,
        route_turn("SCHD defer", plans=[SCHD_S6], now=newer),
    )
    persist_turn(
        tmp_path,
        route_turn("ack SCHD", plans=[SCHD_S6], now=older),
    )
    last = last_turn_for("SCHD", tmp_path)
    assert last is not None
    assert last["intent"] == DEFER
    assert last["created_at"] == newer.isoformat()


def test_ws3_turn_store_keeps_hash_not_raw_text(tmp_path: Path):
    persist_turn(
        tmp_path,
        route_turn("RTX secret operator note xyzzy", plans=[], now=NOW),
    )
    blob = (tmp_path / "data/cio/cio_operator_turns.jsonl").read_text(
        encoding="utf-8",
    )
    assert "secret operator note" not in blob
    assert "xyzzy" not in blob
    assert "text_hash" in blob


# ----------------------------------------------------- InstrumentRecord


def test_ws3_instrument_record_operator_turns():
    rec = new_record("HELD", "SCHD", symbols=["SCHD"], thesis_ref="desk@v5")
    rec, changed = attach_operator_turn(
        rec,
        intent="defer",
        text="wait for price buffer",
        plan_id="plan_schd_s6",
        now=NOW,
        strict=False,
    )
    assert rec["last_operator_turn"]["intent"] == "defer"
    assert rec["last_operator_turn"]["plan_id"] == "plan_schd_s6"
    assert "text_hash" in rec["last_operator_turn"]

    turn = {
        "turn_id": "turn_ws3_demo",
        "intent": "question",
        "feedback_id": "fb_1",
    }
    ir = build_instrument_record(
        {"symbol": "SCHD", "canonical_entity_id": "ent_schd"},
        operator_turns=[turn],
    )
    assert ir["operator_turns"][0]["turn_id"] == "turn_ws3_demo"
    assert "turn_ws3_demo" in ir["operator_turn_ids"]


# ----------------------------------------------------------- INTERDICT


def test_ws3_interdict_aware_would_send_matrix(monkeypatch):
    monkeypatch.delenv("CIO_SITUATION_NOTIFY", raising=False)
    monkeypatch.delenv("CIO_SITUATIONS_NOTIFY", raising=False)
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)

    env = policy.notify_env_state()
    assert env["interdicted"] is True
    assert env["notify_enabled"] is False

    r = policy.decide(
        {
            "plan_id": "s0_ws3",
            "situation_type": SITUATION_TYPE,
            "material": True,
        },
        now=NOW,
    )
    assert r["decision"] == policy.SUPPRESSED
    assert r["reason"] == "s0_operator_turn_default_suppressed"
    assert r["would_send"] is False
    assert r["env"]["interdicted"] is True

    from scripts.lib.cio_command_center import build_notification_block

    block = build_notification_block(
        [
            {
                "plan_id": "s0_ws3",
                "situation_type": SITUATION_TYPE,
                "symbols": ["RTX"],
                "status": "draft",
                "material": True,
                "title": "Operator converse: what about RTX",
            },
            SCHD_S6,
        ],
        now=NOW,
    )
    assert block["s0_open_n"] == 1
    assert block["would_send_any"] is False


# -------------------------------------------------------------- rails


def test_ws3_battery_module_has_no_telegram_network_calls():
    """Scan executable lines only; forbid live Telegram / HTTP send sites."""
    src = Path(__file__).read_text(encoding="utf-8")
    # Drop module docstring + comments so the forbid-list literals below do not
    # self-match when we scan this file.
    code = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", src, count=1)
    code = "\n".join(
        ln for ln in code.splitlines()
        if not ln.lstrip().startswith("#")
        and "assert bad not in" not in ln
        and "for bad in" not in ln
        and "bad =" not in ln
    )
    fragments = [
        ("api", ".telegram.", "org"),
        ("Real", "Telegram", "Adapter"),
        ("requests", ".post"),
        ("url", "open"),
        ("send_cio", "_message("),
    ]
    for parts in fragments:
        bad = "".join(parts)
        assert bad not in code, bad


def test_ws3_s0_module_still_has_no_send_sites():
    src = (
        Path(__file__).resolve().parents[1]
        / "scripts/lib/cio_s0_operator_loop.py"
    ).read_text(encoding="utf-8")
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", src))
    fragments = [
        ("send_cio", "_message"),
        ("api", ".telegram.", "org"),
        ("requests", ".post"),
    ]
    for parts in fragments:
        bad = "".join(parts)
        assert bad not in code, bad


def test_ws3_telegram_token_empty_in_battery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "")
    from scripts.lib.cio_telegram_converse import cio_bot_token

    assert cio_bot_token() == ""
    # Do not invent a network call when token is empty — rails check only.
    assert os.environ.get("TELEGRAM_CIO_BOT_TOKEN") == ""
