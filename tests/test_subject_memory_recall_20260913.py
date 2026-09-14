"""Chat remembers what was said about a company, keyed by its subject GUID.

2026-09-13: operator questions and agent replies were already stored in
operator_conversation_turns with subject_guid (the 21:59 Visa question and its
reply, both CONFIRMED to Visa's GUID), but the desk never read them, so every
question about a company started from nothing. The operator asked to connect
recall per GUID. These tests pin:

* GUIDs come from the intent's resolved subjects, then the identity registry
* the read is scoped to the subject GUID and this chat, excludes the question
  being answered, pairs each question with the agent reply to it, and is bounded
* a disabled flag, no chat or no GUID reads nothing
* the reply shows what was asked, what was answered (without the old Sources or
  authority lines), "no reply on record" when none, and the price move since
* the Sources line names the conversation memory
* the store is declared in the source-of-truth registry with the operator grant

Offline: injected rows, no database.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import lib.cio_operator_desk_loop as desk  # noqa: E402

COVERS = ["scripts/lib/cio_operator_desk_loop.py", "scripts/lib/reply_provenance.py"]

VISA_GUID = "d1871bc6-0000-5000-8000-000000000001"
INTENT = {"intent": "research", "needs": ["research", "analyst_view"], "symbols": ["V"],
          "subjects": [{"symbol": "V", "guid": VISA_GUID, "kind": "company", "matched": "Visa"}]}

ROWS = [
    {"message_id": 51691, "occurred_at": "2026-09-13T21:59:45-04:00", "symbol": "V", "subject_guid": VISA_GUID,
     "question": "How is Visa doing what's the supporting research what are the analyst recommendations",
     "answer": ("Research on file (options_desk):\n- V 2026-09-13 Options: covered call: V Sell Covered Call: "
                "$395.0 2026-10-16 · edge 67.61000000000001\nSources: CIO snapshot | hermes_research_intelligence\n"
                "READ_ONLY_ADVISORY")},
    {"message_id": 90000, "occurred_at": "2026-09-06T11:47:48-04:00", "symbol": "V", "subject_guid": VISA_GUID,
     "question": "Alex what is the analyst target for Visa, the latest support", "answer": None},
]
PRICE = {"V": {"close": 372.10, "price_date": "2026-09-15", "change_30d_pct": 2.0,
               "bars": [["2026-09-10", 367.23], ["2026-09-11", 370.45], ["2026-09-15", 372.10]]}}


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_SUBJECT_FLASH", "0")
    monkeypatch.setenv("CIO_REENTRY_FLASH", "0")
    monkeypatch.delenv("CIO_SUBJECT_MEMORY", raising=False)
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"registered": 0})
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda *a, **k: {"ok": True})


def _capture(monkeypatch, rows):
    calls = []

    def fake(sql, params=None, fetch="all"):
        calls.append((" ".join(str(sql).split()), params))
        return rows
    monkeypatch.setattr(desk, "_research_db_query", fake)
    return calls


def test_guids_come_from_resolved_subjects_first():
    assert desk._subject_guids(INTENT) == {"V": VISA_GUID}


def test_the_read_is_scoped_to_guid_and_chat_excludes_this_question_and_pairs_replies(monkeypatch):
    calls = _capture(monkeypatch, ROWS)
    mem = desk.subject_memory(INTENT, chat_id="6993102664", message_id="51700")
    sql, params = calls[0]
    assert "o.role = 'operator'" in sql and "a.role = 'agent'" in sql
    assert "a.reply_to_message_id = o.message_id" in sql and "a.chat_id = o.chat_id" in sql
    assert "o.subject_guid = ANY(%s::uuid[])" in sql and "o.message_id IS DISTINCT FROM %s" in sql
    assert params == ([VISA_GUID], "6993102664", 51700, 30, 3)
    assert [e["message_id"] for e in mem["V"]] == [51691, 90000]
    assert mem["V"][1]["answer"] is None


@pytest.mark.parametrize("setup", ["flag_off", "no_chat", "no_guid"])
def test_nothing_is_read_without_a_flag_a_chat_or_a_guid(monkeypatch, setup):
    calls = _capture(monkeypatch, ROWS)
    intent, chat = INTENT, "c"
    if setup == "flag_off":
        monkeypatch.setenv("CIO_SUBJECT_MEMORY", "0")
    elif setup == "no_chat":
        chat = ""
    else:
        intent = {**INTENT, "subjects": [], "symbols": ["ZZZZ"]}
        monkeypatch.setattr(desk, "_subject_guids", lambda i: {})
    assert desk.subject_memory(intent, chat_id=chat, message_id="1") == {}
    assert calls == []


def test_the_block_shows_questions_answers_and_the_move_since(monkeypatch):
    avail = {"subject_memory": {"V": [
        {"asked_at": r["occurred_at"], "question": r["question"], "answer": r["answer"], "message_id": r["message_id"]}
        for r in ROWS]}, "subject_price": PRICE}
    block = desk.format_subject_memory(["V"], avail)
    assert block.startswith("Earlier on V (from our conversation):")
    assert 'you asked: "How is Visa doing' in block
    assert 'I answered then: "Research on file (options desk): - V 2026-09-13 Options' in block
    assert "Sources:" not in block and "READ_ONLY" not in block and "67.61000000000001" not in block
    assert "No reply to it is on record." in block
    assert "Since you last asked (Sep 13): close $370.45 on Sep 11, now $372.10 (+0.4%)." in block


def test_no_memory_renders_nothing():
    assert desk.format_subject_memory(["V"], {"subject_memory": {}}) == ""


def test_memory_reaches_the_reply_and_its_sources(monkeypatch):
    import scripts.lib.data_broker.cio_portfolio as cp

    monkeypatch.setattr(cp, "get_cio_snapshot", lambda max_age_s=60: {"domains": {}})
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: {**INTENT, "source": "heuristic", "text": text})
    monkeypatch.setattr(desk, "subject_research", lambda symbols, **k: [
        {"symbol": "V", "research_type": "deep_research_local", "topic": "V deep research",
         "summary": "Covered-call idea on V at a $390 strike.", "as_of": "2026-09-09"}])
    monkeypatch.setattr(desk, "subject_analyst_view", lambda symbols, **k: [])
    monkeypatch.setattr(desk, "subject_price_facts", lambda symbols, **k: PRICE)
    monkeypatch.setattr(desk, "_subject_levels", lambda symbols: ({}, None, None))
    seen = {}

    def fake_memory(intent, *, chat_id, message_id, **k):
        seen.update(chat_id=chat_id, message_id=message_id)
        return {"V": [{"asked_at": ROWS[0]["occurred_at"], "question": ROWS[0]["question"],
                       "answer": ROWS[0]["answer"], "message_id": 51691}]}
    monkeypatch.setattr(desk, "subject_memory", fake_memory)
    res = desk.handle_operator_desk_question("How is Visa doing now", chat_id="6993102664", message_id="51700")
    text = res.get("text") or ""
    assert seen == {"chat_id": "6993102664", "message_id": "51700"}
    assert "Earlier on V (from our conversation):" in text and "Price $372.10" in text
    assert "conversation memory (operator_conversation_turns)" in text
    assert res.get("memory_recall") == {"V": 1}


def test_the_store_is_declared_with_the_operator_grant():
    import check_data_source_authority as gate

    auth = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    dom = next(d for d in auth["domains"] if d.get("domain") == "operator_conversation")
    assert dom["store"]["table"] == "operator_conversation_turns"
    assert dom["writer"] == "scripts/lib/inbound_identity_tagger.py"
    assert all(str(dom["approval"].get(k) or "").strip() for k in ("approved_by", "approved_on", "reference", "scope"))
    files = [p for p in (ROOT / "scripts").rglob("*")
             if p.suffix in (".py", ".sh") and p.is_file() and "__pycache__" not in p.parts]
    assert gate.count_writers(auth, files)["operator_conversation_turns"] == 1
