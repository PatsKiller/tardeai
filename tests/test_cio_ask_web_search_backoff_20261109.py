#!/usr/bin/env python3
"""LQ-20261107-1592 — the paid web-search leg backs off, and the answer says it is unavailable.

The defect: ``cio_ask_web_search`` spent its ``daily_cost_cap_usd`` (1.00) during the ET evening, and the
credit book paces a process by the UTC day, so every later subject re-attempted the bridge and logged
another refusal — 91 ``CREDIT_PROCESS_CAP`` + 4 ``UNAVAILABLE`` and zero answers in 24 h — while the Ask
answer mentioned none of it (the source was merely ``no_data``, counted as another gap).

Hermetic: a fake transport, a ``tmp_path`` cooldown file and a pinned ``now``. No bridge, no network, no
DB, and nothing is written outside the test's own directory.
"""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import lib.anthropic_web_search as ws  # noqa: E402
import lib.cio_ask_research as car  # noqa: E402

NOW = datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc)  # 00:00 ET — the UTC day just rolled over
MIDNIGHT = "2026-11-10T00:00:00+00:00"


@pytest.fixture()
def state(tmp_path):
    return tmp_path / "web_search_cooldown.json"


def _stamp(value):
    return datetime.fromisoformat(value)


def _envelope(code: str, status: int, *, refusal: str | None, message: str = "RealProvider failure") -> dict:
    """The bridge's real error body (``GovernedBridgeHandler.do_POST`` sends ``_error(...)`` as-is).

    A credit refusal is an *outer* ``PROVIDER_ERROR`` (500) or ``PROVIDER_UNAVAILABLE`` (503): the token
    an operator can act on is the ``credit_refusal`` the bridge put on the lane receipt, not ``code``.
    """
    receipt = {"lane": "anthropic", "provider": "anthropic", "attempted": True, "outcome": "credit_refused"}
    if refusal:
        receipt["credit_refusal"] = refusal
    return {"error": {"code": code, "message": message, "status": status, "route_receipts": [receipt]}}


def _http_error(status: int = 500, *, code: str = "PROVIDER_ERROR", refusal: str | None = "CREDIT_PROCESS_CAP",
                message: str = "RealProvider failure") -> HTTPError:
    payload = json.dumps(_envelope(code, status, refusal=refusal, message=message)).encode()
    return HTTPError("http://127.0.0.1:8766/v1/chat/completions", status, "Internal Server Error", None, io.BytesIO(payload))


def _refusing(refusal: str):
    def transport(_url, _body, _timeout):
        raise _http_error(refusal=refusal)

    return transport


def _answering(title: str = "a result"):
    def transport(_url, _body, _timeout):
        return {"content_blocks": [{
            "type": "web_search_tool_result",
            "content": [{"type": "web_search_result", "title": title, "url": "https://example.invalid/x"}],
        }]}

    return transport


# ── the decision: which refusal, which window ────────────────────────────────

def test_a_cap_refusal_opens_until_the_next_utc_midnight(state):
    record = ws.record_failure("CREDIT_PROCESS_CAP", state_path=state, now=NOW)
    assert record["state"] == "cap"
    assert record["retry_at"] == MIDNIGHT
    assert record["failures"] == 1
    assert record["reason"] == "CREDIT_PROCESS_CAP"


def test_an_unavailable_is_a_transient_fifteen_minute_backoff(state):
    record = ws.record_failure("UNAVAILABLE", state_path=state, now=NOW)
    assert record["state"] == "transient"
    assert _stamp(record["retry_at"]) == NOW + timedelta(minutes=15)


def test_a_transient_streak_doubles_and_caps_at_six_hours(state):
    moment, delays = NOW, []
    for _ in range(8):
        record = ws.record_failure("URLError: Connection refused", state_path=state, now=moment)
        delays.append((_stamp(record["retry_at"]) - moment).total_seconds() / 60)
        moment = _stamp(record["retry_at"]) + timedelta(seconds=1)  # let the window expire
    assert delays[:4] == [15, 30, 60, 120]
    assert max(delays) == ws.MAX_BACKOFF_HOURS * 60 == 360


def test_a_burst_of_subjects_is_one_window_not_one_doubling_each(state):
    """The Ask lane calls this once per subject, concurrently: five subjects must not mean 15→240 min."""
    first = ws.record_failure("UNAVAILABLE", state_path=state, now=NOW)
    second = ws.record_failure("UNAVAILABLE", state_path=state, now=NOW + timedelta(seconds=4))
    assert second == first
    assert second["failures"] == 1


def test_a_cap_refusal_does_not_inflate_a_later_transient_streak(state):
    ws.record_failure("CREDIT_PROCESS_CAP", state_path=state, now=NOW)
    later = NOW + timedelta(hours=20)  # the cap window has rolled
    record = ws.record_failure("UNAVAILABLE", state_path=state, now=later)
    assert record["failures"] == 1
    assert _stamp(record["retry_at"]) == later + timedelta(minutes=15)


# ── the call: nothing is posted while the window is open ─────────────────────

def test_the_refused_call_names_the_cause_and_the_retry_time(state):
    refused = ws.search("MU earnings", transport=_refusing("CREDIT_PROCESS_CAP"), state_path=state, now=NOW)
    assert refused["ok"] is False
    # the 500 status alone named a server fault; the bridge's typed code is what an operator can act on
    assert refused["error"] == "CREDIT_PROCESS_CAP"
    assert refused["skipped"] is False
    assert refused["retry_at"] == MIDNIGHT


def test_the_open_window_stops_the_next_subject_posting(state):
    ws.search("first subject", transport=_refusing("CREDIT_PROCESS_CAP"), state_path=state, now=NOW)
    posted: list[tuple] = []

    def counting(_url, body, _timeout):
        posted.append((body,))
        return {}

    skipped = ws.search("second subject", transport=counting, state_path=state,
                        now=NOW + timedelta(minutes=20))
    assert posted == [], "a bridge call was posted while the cooldown was open"
    assert skipped["ok"] is False and skipped["skipped"] is True and skipped["backoff"] is True
    assert skipped["error"] == "CREDIT_PROCESS_CAP"
    assert skipped["retry_at"] == MIDNIGHT


def test_the_body_is_read_only_for_the_typed_code(state):
    """The bridge body can quote the question; only the lane receipt's ``credit_refusal`` token is taken."""
    body = _envelope("PROVIDER_ERROR", 500, refusal="CREDIT_PROCESS_CAP",
                     message="question: should I buy MU " + "x" * 400)
    def transport(_url, _body, _timeout):
        raise HTTPError("http://127.0.0.1:8766/v1", 500, "Internal Server Error", None,
                        io.BytesIO(json.dumps(body).encode()))
    refused = ws.search("q", transport=transport, state_path=state, now=NOW)
    assert refused["error"] == "CREDIT_PROCESS_CAP"
    assert "should I buy MU" not in json.dumps(refused)


def test_a_credit_refusal_as_503_names_the_credit_cause_not_the_class(state):
    """The transport_unavailable branch sends 503 PROVIDER_UNAVAILABLE with the refusal on the receipt."""
    def transport(_url, _body, _timeout):
        raise _http_error(503, code="PROVIDER_UNAVAILABLE", refusal="UNAVAILABLE")

    refused = ws.search("q", transport=transport, state_path=state, now=NOW)
    assert refused["error"] == "UNAVAILABLE"
    assert refused["cooldown_state"] == "transient"


def test_a_plain_provider_error_with_no_receipt_token_names_the_class(state):
    """An ordinary provider fault is still nameable (the 2026-11-07 fix), and backs off as transient."""
    def transport(_url, _body, _timeout):
        raise _http_error(500, refusal=None)

    refused = ws.search("q", transport=transport, state_path=state, now=NOW)
    assert refused["error"] == "PROVIDER_ERROR"
    assert refused["cooldown_state"] == "transient"
    assert _stamp(refused["retry_at"]) == NOW + timedelta(minutes=15)


def test_an_unshaped_body_yields_the_status_line_not_free_text(state):
    """A body that is not our envelope (an auth page, HTML) names nothing; the status stays the cause."""
    def transport(_url, _body, _timeout):
        raise HTTPError("http://127.0.0.1:8766/v1", 502, "Bad Gateway", None, io.BytesIO(b"<html>oops</html>"))

    refused = ws.search("q", transport=transport, state_path=state, now=NOW)
    assert refused["error"] == "HTTP 502 Bad Gateway"
    assert refused["retry_at"]  # still backed off: the leg is down


def test_a_success_closes_the_window_and_a_later_call_posts_again(state):
    ws.search("q", transport=_refusing("UNAVAILABLE"), state_path=state, now=NOW)
    after = NOW + timedelta(minutes=16)
    good = ws.search("q", transport=_answering(), state_path=state, now=after)
    assert good["ok"] is True and good["results"][0]["title"] == "a result"
    assert json.loads(state.read_text())["state"] == "closed"

    posted: list[str] = []

    def counting(_url, body, _timeout):
        posted.append("posted")
        return {"content_blocks": []}

    ws.search("q", transport=counting, state_path=state, now=after + timedelta(minutes=1))
    assert posted == ["posted"]


def test_a_corrupt_state_file_never_blocks_the_call(state):
    # nosemgrep: tq-py-nonatomic-store-write -- a deliberately corrupt file under pytest tmp_path, read back at once, never a store
    state.write_text("{not json")
    assert ws.open_cooldown(state_path=state, now=NOW) is None
    good = ws.search("q", transport=_answering(), state_path=state, now=NOW)
    assert good["ok"] is True


# ── the Ask source and the answer carry the honest state ─────────────────────

def test_the_ask_source_carries_the_retry_time(monkeypatch):
    monkeypatch.setattr(ws, "search", lambda *_a, **_k: {
        "ok": False, "provider": "anthropic", "results": [], "error": "CREDIT_PROCESS_CAP",
        "reason": "CREDIT_PROCESS_CAP", "backoff": True, "skipped": True,
        "retry_at": MIDNIGHT, "cooldown_state": "cap",
    })
    ent = car.Entity(label="MU", kind="listed", symbol="MU")
    facts = car._src_anthropic_search(ent, car.ResearchContext(question="what is the catalyst"))
    assert facts.outcome["degraded"] is True
    assert facts.outcome["reason"] == "CREDIT_PROCESS_CAP"
    assert facts.outcome["retry_at"] == MIDNIGHT
    assert facts.outcome["skipped"] is True


def _answer(source_runs):
    ctx = SimpleNamespace(
        request=SimpleNamespace(ask_id="ask-1", depth="deep"), thread_id="thread-1", version=1, house_facts={}
    )
    internal = {
        "entities": [], "facts": [], "prospectus": [], "refusals": [], "gaps": [],
        "source_runs": source_runs, "cost": {}, "conflicts": [], "panel": [], "conflicts_seen": [],
    }
    return car.to_contract_answer(internal, ctx)


def test_the_answer_summary_says_web_search_is_unavailable():
    answer = _answer([{
        "source": "web.anthropic", "status": "no_data", "degraded": True,
        "reason": "CREDIT_PROCESS_CAP", "retry_at": MIDNIGHT, "skipped": True,
    }])
    assert f"Web search unavailable (CREDIT_PROCESS_CAP; retry after {MIDNIGHT})" in answer.summary
    assert "store" in answer.summary or "other sources" in answer.summary


def test_a_healthy_run_gets_no_unavailable_line():
    answer = _answer([{"source": "web.anthropic", "status": "ok", "facts": 3}])
    assert "Web search unavailable" not in answer.summary


def test_the_note_prefers_the_first_degraded_web_row():
    note = car.web_search_unavailable_note([
        {"source": "web", "status": "ok"},
        {"source": "web.anthropic", "status": "no_data", "degraded": True, "reason": "UNAVAILABLE"},
    ])
    assert note == "Web search unavailable (UNAVAILABLE). Other sources answered from stored data."


def test_the_gate_registration_exists():
    """tq test_registration: every test file has a CI gate naming it."""
    gates = list((ROOT / "config" / "ci_gates").glob("CIO_ASK_WEB_SEARCH_BACKOFF_*.json"))
    assert gates, "config/ci_gates/CIO_ASK_WEB_SEARCH_BACKOFF_20261109.json is missing"
