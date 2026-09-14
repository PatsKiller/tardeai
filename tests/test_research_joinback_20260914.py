"""Hermes research reaches the operator: joined to the pending by id, answered now, followed up.

2026-09-14 09:12 ET "Do some more research on HPE ...". Hermes completed the
request at 09:16 (critic VALID) and wrote hermes_research_results.jsonl. The
pending opr_74cc87d6ae62 waited for a PROMOTED hermes_research_intelligence row
that the Hermes CIO worker never writes, so the answer could not be delivered;
the pending would have been retracted as "could not answer" at 11:12. The
operator got a queue ticket and no facts although the dossier was on file.

Pinned here, offline (temp ledgers, fake Hermes projection and results, no DB,
no model, no Telegram):

* the operator's own question is what Hermes is asked, in Hermes-sized pieces
* the gap-request ledger carries the plan id AND the research id (reuse path)
* a completed Hermes result closes the research gap and is sent as a follow-up
  that quotes the question, carries Hermes' answer with 🟣 lines and names
  Hermes as an outside source in the provenance
* a failed Hermes run closes the pending straight away with the reason
* no result yet → the pending stays open (negative control)
* a research-only ask answers NOW with the house facts plus a queued line
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

QUESTION = ("Do some more research on hpe on what's a good entry support resistance with an "
            "analyst saying and how long has his volume been more than normal")
INTENT = {"intent": "research", "needs": ["research", "analyst_view"], "symbols": ["HPE"], "text": QUESTION}
RESEARCH_GAP = {"domain": "hermes_research", "symbol": "HPE", "field": "research",
                "reason": "no promoted research for HPE", "gap_type": "missing_research"}
INCOMPLETE = {
    "ok": True, "complete": False,
    "available": {"subject_symbols": ["HPE"], "subject_price": {"HPE": {"close": 62.08}}},
    "gaps": [RESEARCH_GAP], "blocking_gaps": [RESEARCH_GAP], "sources": ["ticker_prices"],
}
RESULT = {
    "event": "HERMES_RESEARCH_COMPLETED", "result_id": "rr_test1", "research_id": "res_test1",
    "plan_id": "plan_test1", "status": "completed", "symbol": "HPE", "model": "deepseek-flash",
    "completed_ts": "2026-09-14T13:15:56+00:00", "confidence": 0.55, "thesis_stance": "WATCH",
    "evidence_links": ["ev_1", "ev_2"],
    "answers": [{"question_id": "q1", "summary": "Entry only on a hold above the ~$55.99 breakout level.",
                 "detail": "long", "confidence": 0.55, "citations": ["ev_1"], "status": "answered"}],
    "findings": [{"id": "f1", "kind": "risk", "severity": "high", "text": "The Q3 beat is unverified as durable."},
                 {"id": "f2", "kind": "catalyst", "severity": "low", "text": "Minor note."}],
    "research_gaps_remaining": ["Q3 segment margins", "Backlog and orders"],
    "limitations": ["No primary evidence in the packet."],
    "summary": "fallback summary",
}


class _Sender:
    def __init__(self):
        self.sent: list[tuple[str, str, object]] = []

    def __call__(self, chat_id, text, reply_to=None):
        self.sent.append((chat_id, text, reply_to))
        return {"ok": True}


class _FakeHermes:
    def __init__(self, tmp: Path, metas: dict, results: list[dict]):
        self.RESULT_PATH = tmp / "hermes_research_results.jsonl"
        self.RESULT_PATH.write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")
        self._proj = {"by_research_id": metas}

    def _load_projection(self):
        return self._proj


@pytest.fixture
def ledgers(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "OPERATOR_GAP_REQUESTS_PATH", tmp_path / "gap_requests.jsonl")
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: json.loads(json.dumps(INCOMPLETE)))
    monkeypatch.setattr(desk, "_curate_from_evidence", lambda text, ev: {
        "ok": True, "source": "tradeai_deterministic", "model": None,
        "text": "*HPE*\nPrice $62.08\n"
                + ("Research on file: Hermes\n" if (ev.get("available") or {}).get("hermes_research") else "")
                + "READ_ONLY_ADVISORY"})
    return tmp_path


def _open_pending(tmp: Path, *, age_min: float = 10, plan_id="plan_test1", research_id=None):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).isoformat()
    row = {"pending_id": "opr_test1", "status": "open", "ts": ts, "chat_id": "42", "message_id": "7",
           "channel": "telegram", "operator_text": QUESTION, "intent": INTENT,
           "blocking_gaps": [RESEARCH_GAP], "eta_seconds": 1800}
    (tmp / "pending.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    ask = {"pending_id": "opr_test1", "kind": "hermes_operator_forced", "plan_id": plan_id,
           "research_id": research_id, "symbols": ["HPE"]}
    (tmp / "gap_requests.jsonl").write_text(json.dumps(ask) + "\n", encoding="utf-8")


def _statuses(tmp: Path) -> list[str]:
    return [json.loads(line)["status"] for line in (tmp / "pending.jsonl").read_text().splitlines()]


# ── questions ────────────────────────────────────────────────────────────────

def test_hermes_is_asked_the_operators_question_in_pieces_it_will_accept():
    qs = desk.operator_research_questions(["HPE"], QUESTION)
    op = [q for q in qs if q["intent"] == "operator_question"]
    assert op and all(len(q["text"]) <= 220 for q in qs)
    joined = " ".join(q["text"] for q in op)
    for word in ("entry", "support", "resistance", "analyst", "volume"):
        assert word in joined
    assert qs[-1]["intent"] == "thesis_check"


def test_no_text_keeps_the_hermes_default_questions():
    assert desk.operator_research_questions(["HPE"], "  ") is None


# ── join-back ────────────────────────────────────────────────────────────────

def test_completed_hermes_result_is_delivered_as_a_follow_up(ledgers, monkeypatch):
    _open_pending(ledgers)
    fake = _FakeHermes(ledgers, {"res_test1": {"plan_id": "plan_test1", "status": "completed",
                                               "latest_result_id": "rr_test1",
                                               "completed_ts": RESULT["completed_ts"]}}, [RESULT])
    monkeypatch.setattr(desk, "_hermes_store", lambda: fake)
    send = _Sender()
    out = desk.try_fulfill_pending_replies(send)
    assert out["fulfilled"] == 1 and _statuses(ledgers) == ["open", "fulfilled"]
    body = send.sent[0][1]
    assert "Hermes research landed" in body and "You asked" in body
    assert "🟣 AI model: Entry only on a hold above the ~$55.99 breakout level." in body
    assert body.index("Finding (high)") < body.index("Finding (low)")
    assert "Still unknown: Q3 segment margins; Backlog and orders" in body
    # A model is not outside data: Hermes is named once, on the 🟣 model role.
    origin = next(ln for ln in body.split("\n") if ln.startswith("Origin:"))
    assert "🟣 AI model (DeepSeek): Hermes research over Trade-AI evidence" in origin
    assert "🔵 Looked up outside Trade-AI: nothing" in origin and "Went outside:" not in body
    assert body.rstrip().endswith("READ_ONLY_ADVISORY")


def test_follow_up_does_not_repeat_the_dossier(ledgers, monkeypatch):
    _open_pending(ledgers)
    fake = _FakeHermes(ledgers, {"res_test1": {"plan_id": "plan_test1", "status": "completed",
                                               "latest_result_id": "rr_test1"}}, [RESULT])
    monkeypatch.setattr(desk, "_hermes_store", lambda: fake)
    seen = {}

    def gather(intent):
        ev = json.loads(json.dumps(INCOMPLETE))
        ev["available"]["subject_dossier_text"] = "*HPE — full picture*"
        return ev
    monkeypatch.setattr(desk, "gather_tradeai_evidence", gather)
    monkeypatch.setattr(desk, "_curate_from_evidence",
                        lambda text, ev: seen.update(ev["available"]) or {"ok": True, "text": "x", "source": None})
    desk.try_fulfill_pending_replies(_Sender())
    assert "subject_dossier_text" not in seen and "hermes_result" in seen


def test_a_reused_request_is_found_by_research_id(ledgers, monkeypatch):
    _open_pending(ledgers, plan_id="plan_other", research_id="res_test1")
    fake = _FakeHermes(ledgers, {"res_test1": {"plan_id": "plan_elsewhere", "status": "completed",
                                               "latest_result_id": "rr_test1"}}, [RESULT])
    monkeypatch.setattr(desk, "_hermes_store", lambda: fake)
    assert desk.hermes_result_for_pending("opr_test1")["result_id"] == "rr_test1"


def test_no_result_yet_leaves_the_pending_open(ledgers, monkeypatch):
    _open_pending(ledgers)
    fake = _FakeHermes(ledgers, {"res_test1": {"plan_id": "plan_test1", "status": "running"}}, [])
    monkeypatch.setattr(desk, "_hermes_store", lambda: fake)
    send = _Sender()
    out = desk.try_fulfill_pending_replies(send)
    assert out["fulfilled"] == 0 and out["expired"] == 0 and send.sent == []
    assert _statuses(ledgers) == ["open"]


def test_failed_hermes_run_closes_the_pending_now_with_the_reason(ledgers, monkeypatch):
    _open_pending(ledgers, age_min=5)
    fake = _FakeHermes(ledgers, {"res_test1": {"plan_id": "plan_test1", "status": "failed",
                                               "error": "bridge timeout"}}, [])
    monkeypatch.setattr(desk, "_hermes_store", lambda: fake)
    send = _Sender()
    out = desk.try_fulfill_pending_replies(send)
    assert out["expired"] == 1 and _statuses(ledgers) == ["open", "expired"]
    assert "Hermes research run failed (bridge timeout)" in send.sent[0][1]


def test_join_removes_only_the_research_gap():
    other = {"domain": "reentry_decision_desk", "symbol": "HPE", "field": "row"}
    ev = {**INCOMPLETE, "gaps": [RESEARCH_GAP, other], "blocking_gaps": [RESEARCH_GAP, other]}
    joined = desk.join_hermes_result(ev, RESULT)
    assert joined["blocking_gaps"] == [other] and joined["complete"] is False
    assert joined["available"]["hermes_research"]["items"][0]["research_type"] == "hermes_operator_research"


# ── answer now ───────────────────────────────────────────────────────────────

def test_research_only_ask_answers_now_and_keeps_the_pending(ledgers, monkeypatch):
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: dict(INTENT))
    monkeypatch.setattr(desk, "_gap_resolver_enabled", lambda: False)
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"registered": 0})
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda **k: {"ok": True, "plan_id": "plan_x"})
    monkeypatch.setattr(desk, "_emit_telegram_desk_payload", lambda *a, **k: None)
    out = desk.handle_operator_desk_question(QUESTION, chat_id="42", message_id="7")
    assert out["kind"] == "answered" and out["pending_id"] and out["research_queued"] is True
    assert "Price $62.08" in out["text"] and "Deeper research queued: Hermes" in out["text"]
    assert out["text"].index("Deeper research queued") < out["text"].index("READ_ONLY_ADVISORY")
    assert _statuses(ledgers) == ["open"]


def test_answer_now_can_be_switched_off(ledgers, monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_RESEARCH_ANSWER_NOW", "0")
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: dict(INTENT))
    monkeypatch.setattr(desk, "_gap_resolver_enabled", lambda: False)
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"registered": 0})
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda **k: {"ok": True})
    monkeypatch.setattr(desk, "_emit_telegram_desk_payload", lambda *a, **k: None)
    out = desk.handle_operator_desk_question(QUESTION, chat_id="42", message_id="7")
    assert out["kind"] == "deferred"
