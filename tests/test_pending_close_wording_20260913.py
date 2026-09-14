"""A closed pending question tells the operator what actually happened.

2026-09-13 21:55 EDT, right after the bot restarted onto the routing fix, the
operator received:

    📭 Closing opr_5bc20393b457 — I could not answer this.
    the required Trade-AI data did not arrive within 2h.
    Ask again if you want me to retry.

The question (SpaceX outlook) had been open 9.4 hours, not 2. The message did
not say what was missing, and "ask again" was offered without checking whether
that could work (it could: SpaceX now resolves to SPCX). These tests pin the
new message: the question and when it was asked, the real time open, why it
closed, what was missing, and retry advice from the deterministic subject
resolver. Offline: temp ledger, injected evidence, patched resolver.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import lib.cio_operator_desk_loop as desk  # noqa: E402
import lib.operator_subject_resolver as subjects  # noqa: E402

COVERS = ["scripts/lib/cio_operator_desk_loop.py"]

SPACEX_Q = ("What's the outlook for SpaceX in the next 3 months and what has its performance "
            "been over the last month what are options closing")
SPACEX_INTENT = {"intent": "market", "symbols": [], "needs": ["analyst_view", "hermes_research"], "text": SPACEX_Q}
WMT_INTENT = {"intent": "market", "symbols": ["WMT"], "needs": ["analyst_view"], "text": "analyst view on WMT"}
RESEARCH_GAP = {"domain": "hermes_research", "field": "research", "reason": "no subject named to research", "symbol": None}


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "gather_tradeai_evidence",
                        lambda intent: {"complete": False, "gaps": [], "blocking_gaps": [], "sources": []})


def _row(pid, intent, age_h, **extra):
    return {
        "pending_id": pid, "status": "open", "chat_id": "c", "message_id": "m",
        "operator_text": intent["text"], "intent": intent, "blocking_gaps": [RESEARCH_GAP],
        "ts": (datetime.now(timezone.utc) - timedelta(hours=age_h)).replace(microsecond=0).isoformat(),
        **extra,
    }


def _close(monkeypatch, row, resolved):
    if isinstance(resolved, Exception):
        def _boom(text, **k):
            raise resolved
        monkeypatch.setattr(subjects, "resolve_subjects", _boom)
    else:
        monkeypatch.setattr(subjects, "resolve_subjects", lambda text, **k: resolved)
    desk._append_jsonl(desk.PENDING_PATH, row)
    sent = []
    out = desk.try_fulfill_pending_replies(lambda chat, body, mid: sent.append(body) or {"ok": True})
    rows = [json.loads(line) for line in desk.PENDING_PATH.read_text().splitlines() if line.strip()]
    return out, (sent[0] if sent else ""), rows[-1]


def test_spacex_close_names_duration_missing_data_and_that_retry_now_works(monkeypatch):
    out, text, last = _close(monkeypatch, _row("opr_5bc20393b457", SPACEX_INTENT, 9.4),
                             [{"symbol": "SPCX", "kind": "company", "matched": "SpaceX"}])
    assert out["expired"] == 1 and last["status"] == "expired"
    assert "Closing" in text and "opr_5bc20393b457" in text
    assert "You asked at " in text and "\"What's the outlook for SpaceX" in text
    assert "It was open 9.4 hours." in text
    assert "Why: no tradable instrument resolved" in text
    assert "Missing: no subject named to research." in text
    assert "now resolves to SPCX" in text
    assert "within 2h" not in text and desk.AUTHORITY in text


def test_time_limit_close_states_the_real_limit(monkeypatch):
    _, text, last = _close(monkeypatch, _row("opr_wmt", WMT_INTENT, 3.0), [{"symbol": "WMT", "kind": "ticker"}])
    assert "It was open 3.0 hours." in text
    assert "Why: the data it needed did not arrive within the 2-hour limit." in text
    assert "Ask again to retry WMT" in text
    assert last["expiry_reason"] == "the data it needed did not arrive within the 2-hour limit"


def test_eta_close_says_it_waited_for_the_eta(monkeypatch):
    _, text, _ = _close(monkeypatch, _row("opr_eta", WMT_INTENT, 8.0, eta_seconds=6 * 3600),
                        [{"symbol": "WMT", "kind": "ticker"}])
    assert "did not arrive by its ETA plus grace (7 hours)" in text


def test_unresolvable_question_says_asking_again_will_not_help(monkeypatch):
    _, text, _ = _close(monkeypatch, _row("opr_vague", SPACEX_INTENT, 0.2), [{"symbol": None, "kind": "topic"}])
    assert "won't help" in text and "Name the ticker" in text
    assert "It was open 12 minutes." in text


def test_resolver_failure_falls_back_to_plain_retry(monkeypatch):
    _, text, _ = _close(monkeypatch, _row("opr_err", SPACEX_INTENT, 0.2), RuntimeError("resolver down"))
    assert "Ask again if you want me to retry." in text


def test_markdown_characters_in_the_question_cannot_break_the_message(monkeypatch):
    intent = {**WMT_INTENT, "text": "is *WMT* a_good [buy] `now`"}
    _, text, _ = _close(monkeypatch, _row("opr_md", intent, 3.0), [{"symbol": "WMT", "kind": "ticker"}])
    quoted = next(line for line in text.splitlines() if line.startswith("You asked")).split(": ", 1)[1]
    assert not any(ch in quoted for ch in "*_`[]"), quoted


def test_duration_wording():
    assert desk._open_for_text(None) == "for an unknown time"
    assert desk._open_for_text(0.25) == "15 minutes"
    assert desk._open_for_text(9.38) == "9.4 hours"
