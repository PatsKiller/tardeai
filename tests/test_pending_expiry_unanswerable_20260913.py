"""A promise the desk cannot keep must be refused up front or retracted, never
left open forever.

On 2026-09-13 the operator asked "what's the outlook for SpaceX, what are
options closing, what are analysts expecting". The desk opened
opr_5bc20393b457 and promised a follow-up. the name did not resolve (SpaceX is SPCX; the name index lacked it): no symbol
resolved, so no quote, chain, analyst row or research could ever arrive.
try_fulfill_pending_replies skipped the incomplete pending with a bare
`continue` on every pass, so the operator waited 72 minutes for a reply that
was never going to come, and would have waited indefinitely.

Two fixes, both tested here against injected state, never the live ledger:

1. is_answerable(intent) — a market need with no resolvable instrument is
   unanswerable, and handle_operator_desk_question says so immediately
   instead of opening a pending.
2. PENDING_EXPIRY_HOURS — an answerable pending whose evidence has not
   arrived inside the window is retracted with status "expired" and the
   operator is told. An answerable, fresh pending is still left alone.

The negative control disables is_answerable and shows the old behaviour
returns: a pending is opened for the SpaceX question.
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

COVERS = ["scripts/lib/cio_operator_desk_loop.py"]

SPACEX_INTENT = {
    "intent": "market",
    "symbols": [],
    "needs": ["analyst_view", "reentry_ready", "hermes_research"],
    "text": "what's the outlook for SpaceX, what are options closing, what are analysts expecting",
}
WMT_INTENT = {**SPACEX_INTENT, "symbols": ["WMT"]}
INCOMPLETE = {
    "complete": False,
    "gaps": [{"domain": "hermes_research", "reason": "no_research"}],
    "blocking_gaps": [{"domain": "hermes_research", "reason": "no_research", "symbol": None}],
    "sources": [],
}

#: Routing fixture, not a credential: passed into desk calls and asserted back
#: out unchanged, so its identity is irrelevant. tg_chat_ids.chat_ids() is not
#: used -- it reads TELEGRAM_CHAT_ID from the environment and returns a LIST,
#: which would break these equality assertions and make an offline test depend
#: on the host.
OPERATOR_CHAT = "6993102664"  # hardcode-ok: routing fixture, not a credential


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: dict(INCOMPLETE))
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda *a, **k: {"ok": True})


class _Sender:
    def __init__(self):
        self.sent: list[tuple[str, str, object]] = []

    def __call__(self, chat_id, text, reply_to=None):
        self.sent.append((chat_id, text, reply_to))
        return {"ok": True}


def _open_row(pending_id: str, intent: dict, age_hours: float) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {
        "pending_id": pending_id,
        "chat_id": OPERATOR_CHAT,
        "message_id": "42",
        "channel": "telegram",
        "operator_text": intent["text"],
        "intent": intent,
        "status": "open",
        "ts": ts.isoformat().replace("+00:00", "Z"),
    }


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


# ── is_answerable ─────────────────────────────────────────────────────────────


def test_market_need_without_symbol_is_unanswerable():
    ok, why = desk.is_answerable(SPACEX_INTENT)
    assert ok is False
    assert "no tradable instrument" in why


def test_market_need_with_symbol_is_answerable():
    assert desk.is_answerable(WMT_INTENT) == (True, "")


def test_non_market_need_without_symbol_is_answerable():
    assert desk.is_answerable({"needs": ["attention"], "symbols": []}) == (True, "")


# ── handle_operator_desk_question: refuse up front ────────────────────────────


def test_spacex_question_is_refused_not_promised(monkeypatch):
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: dict(SPACEX_INTENT))
    res = desk.handle_operator_desk_question(SPACEX_INTENT["text"], chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] == "unanswerable"
    assert res["pending_id"] is None
    assert "can't answer that from Trade-AI" in res["reply_preview"]
    assert "send its ticker" in res["reply_preview"]
    assert desk.AUTHORITY in res["reply_preview"]
    assert _rows(desk.PENDING_PATH) == [], "no pending may be opened for an unanswerable ask"


def test_negative_control_without_is_answerable_a_pending_is_opened(monkeypatch):
    """The pre-fix behaviour: the question is deferred and a ticket is issued."""
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: dict(SPACEX_INTENT))
    monkeypatch.setattr(desk, "is_answerable", lambda intent: (True, ""))
    res = desk.handle_operator_desk_question(SPACEX_INTENT["text"], chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] != "unanswerable"
    assert res["pending_id"]
    rows = _rows(desk.PENDING_PATH)
    assert rows and rows[-1]["status"] == "open"


def test_answerable_gap_still_opens_a_pending(monkeypatch):
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: dict(WMT_INTENT))
    res = desk.handle_operator_desk_question("outlook for WMT", chat_id=OPERATOR_CHAT, message_id="7")
    assert res["kind"] != "unanswerable"
    assert res["pending_id"]
    assert _rows(desk.PENDING_PATH)[-1]["status"] == "open"


# ── try_fulfill_pending_replies: retract, don't abandon ───────────────────────


def test_unanswerable_pending_is_expired_immediately_and_operator_told():
    desk._append_jsonl(desk.PENDING_PATH, _open_row("opr_5bc20393b457", SPACEX_INTENT, age_hours=0.1))
    sender = _Sender()
    out = desk.try_fulfill_pending_replies(sender)
    assert out["expired"] == 1 and out["fulfilled"] == 0 and out["failed"] == 0
    assert len(sender.sent) == 1
    chat_id, text, reply_to = sender.sent[0]
    assert chat_id == OPERATOR_CHAT and reply_to == "42"
    assert "Closing" in text and "opr_5bc20393b457" in text
    last = _rows(desk.PENDING_PATH)[-1]
    assert last["status"] == "expired"
    assert last["pending_id"] == "opr_5bc20393b457"
    assert "no tradable instrument" in last["expiry_reason"]


def test_answerable_but_overdue_pending_is_expired():
    desk._append_jsonl(desk.PENDING_PATH, _open_row("opr_old", WMT_INTENT, age_hours=desk.PENDING_EXPIRY_HOURS + 0.5))
    sender = _Sender()
    out = desk.try_fulfill_pending_replies(sender)
    assert out["expired"] == 1
    assert len(sender.sent) == 1
    last = _rows(desk.PENDING_PATH)[-1]
    assert last["status"] == "expired"
    assert f"within the {desk.PENDING_EXPIRY_HOURS:g}-hour limit" in last["expiry_reason"]
    assert last["age_hours"] >= desk.PENDING_EXPIRY_HOURS


def test_answerable_fresh_pending_is_left_open():
    desk._append_jsonl(desk.PENDING_PATH, _open_row("opr_fresh", WMT_INTENT, age_hours=0.2))
    sender = _Sender()
    out = desk.try_fulfill_pending_replies(sender)
    assert out == {"ok": True, "checked": 1, "fulfilled": 0, "expired": 0, "failed": 0, "authority": desk.AUTHORITY}
    assert sender.sent == []
    assert [r["status"] for r in _rows(desk.PENDING_PATH)] == ["open"]


def test_expired_pending_is_not_retracted_twice():
    desk._append_jsonl(desk.PENDING_PATH, _open_row("opr_5bc20393b457", SPACEX_INTENT, age_hours=0.1))
    sender = _Sender()
    desk.try_fulfill_pending_replies(sender)
    again = desk.try_fulfill_pending_replies(sender)
    assert again["checked"] == 0 and again["expired"] == 0
    assert len(sender.sent) == 1, "one retraction per pending"


def test_unparseable_timestamp_does_not_expire_an_answerable_pending():
    row = _open_row("opr_bad_ts", WMT_INTENT, age_hours=0.1)
    row["ts"] = "not-a-time"
    desk._append_jsonl(desk.PENDING_PATH, row)
    sender = _Sender()
    out = desk.try_fulfill_pending_replies(sender)
    assert out["expired"] == 0 and sender.sent == []
    assert desk._pending_age_hours(row) is None


def test_expiry_window_is_two_hours():
    assert desk.PENDING_EXPIRY_HOURS == 2.0
