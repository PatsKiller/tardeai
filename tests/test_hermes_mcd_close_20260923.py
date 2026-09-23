"""MCD pullback ask, 2026-09-23 10:42 EDT.

Hermes refused a sufficiency diagnostic as execution language, then the desk
closed the pending and said no ticker resolved even though the intent held MCD.
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
from lib.hermes_research_backend import HermesBackendError, assert_no_execution_language  # noqa: E402

MCD_Q = "is mcdonalds a good investment on this pullback give perpective"
MCD_INTENT = {
    "intent": "analyst_view",
    "symbols": ["MCD"],
    "needs": ["analyst_view", "research"],
    "text": MCD_Q,
}
GUARD = (
    "execution language not allowed in research output: RAG retrieval is split "
    "8 supporting vs 8 contradictory with zero approved primary sources; "
    "sufficiency.sufficient_for_synthesis"
)
DIAGNOSTIC = (
    "RAG retrieval is split 8 supporting vs 8 contradictory with zero approved "
    "primary sources; a cited row says buy; sufficiency.sufficient_for_synthesis is false."
)
OPERATOR_CHAT = "6993102664"  # hardcode-ok: routing fixture, not a credential


def test_sufficiency_diagnostic_is_not_execution_language():
    assert_no_execution_language(DIAGNOSTIC)


def test_buy_now_still_refuses_and_names_the_match():
    with pytest.raises(HermesBackendError, match="matched 'buy now'|matched 'buy'"):
        assert_no_execution_language("we should buy now the dip")


def test_retry_advice_keeps_known_mcd_ticker():
    row = {"operator_text": MCD_Q}
    advice = desk._retry_advice(row, MCD_INTENT)
    assert "MCD" in advice
    assert "no ticker resolves" not in advice
    assert "Name the ticker" not in advice


def test_retry_advice_still_asks_for_a_ticker_when_none_is_known():
    row = {"operator_text": "what's the outlook for Nonesuch Holdings"}
    advice = desk._retry_advice(row, {"symbols": [], "text": row["operator_text"]})
    assert "no ticker resolves" in advice


def _open_row() -> dict:
    ts = datetime.now(timezone.utc) - timedelta(minutes=6)
    return {
        "pending_id": "opr_40a1c8f0876c",
        "chat_id": OPERATOR_CHAT,
        "message_id": "53912",
        "channel": "telegram",
        "operator_text": MCD_Q,
        "intent": MCD_INTENT,
        "status": "open",
        "ts": ts.isoformat().replace("+00:00", "Z"),
        "blocking_gaps": [{
            "domain": "hermes_research",
            "field": "research",
            "reason": "no promoted research for MCD",
            "symbol": "MCD",
        }],
    }


def _evidence() -> dict:
    return {
        "ok": True,
        "complete": False,
        "available": {
            "subject_symbols": ["MCD"],
            "subject_price": {"MCD": {"close": 300.0, "price_date": "2026-09-23"}},
        },
        "gaps": [],
        "blocking_gaps": [{
            "domain": "hermes_research",
            "symbol": "MCD",
            "field": "research",
            "reason": "no promoted research for MCD",
        }],
        "sources": ["ticker_prices (daily closes)"],
    }


@pytest.fixture
def _offline(monkeypatch, tmp_path):
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: _evidence())
    monkeypatch.setattr(desk, "hermes_result_for_pending", lambda pending_id: None)
    monkeypatch.setattr(desk, "hermes_failure_for_pending", lambda pending_id: GUARD)
    monkeypatch.setattr(
        desk, "_curate_from_evidence",
        lambda text, evidence: {
            "ok": True,
            "text": "*MCD*\nPrice 300.00 (close 2026-09-23)\nREAD_ONLY_ADVISORY",
            "source": "tradeai_deterministic",
            "model": None,
        },
    )


def test_failed_research_with_house_price_is_answered(_offline):
    desk._append_jsonl(desk.PENDING_PATH, _open_row())
    sent = []

    def send(chat_id, text, reply_to=None):
        sent.append(text)
        return {"ok": True}

    out = desk.try_fulfill_pending_replies(send)
    assert out["fulfilled"] == 1 and out["expired"] == 0
    assert sent and "MCD" in sent[0]
    assert "no approved primary source" in sent[0]
    assert "execution language" not in sent[0]
    assert "no ticker resolves" not in sent[0]
    assert "RAG" not in sent[0]
    rows = [json.loads(line) for line in desk.PENDING_PATH.read_text().splitlines() if line.strip()]
    assert rows[-1]["status"] == "fulfilled"


def test_failed_research_without_house_facts_closes_without_naming_a_missing_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: {
        "complete": False,
        "available": {},
        "blocking_gaps": [{"domain": "hermes_research", "symbol": "MCD", "reason": "no promoted research for MCD"}],
        "sources": [],
    })
    monkeypatch.setattr(desk, "hermes_result_for_pending", lambda pending_id: None)
    monkeypatch.setattr(desk, "hermes_failure_for_pending", lambda pending_id: GUARD)
    desk._append_jsonl(desk.PENDING_PATH, _open_row())
    sent = []
    desk.try_fulfill_pending_replies(lambda chat, text, reply_to=None: sent.append(text) or {"ok": True})
    assert sent
    assert "no ticker resolves" not in sent[0]
    assert "MCD" in sent[0]
    assert "execution language" not in sent[0]
    assert "no approved primary source" in sent[0]
