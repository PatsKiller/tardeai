"""OPERATOR DECISION 2026-09-23: a GO/BUY with no CIO stance stays held AND forces a CIO review.

The review is the desk's CIO research pull (plan + Hermes request); these tests
inject the emitter so nothing touches the live plan or research stores.
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

from lib import cio_stance_review_request as rr  # noqa: E402
from lib import cio_telegram_stance_gate as sg  # noqa: E402

T0 = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "cio_stance_review_requests.jsonl"
    monkeypatch.setenv("CIO_STANCE_REVIEW_REQUESTS", str(path))
    monkeypatch.delenv("CIO_STANCE_REVIEW_DEDUPE_SECONDS", raising=False)
    monkeypatch.delenv("CIO_STANCE_REVIEW_RETRY_SECONDS", raising=False)
    monkeypatch.delenv("CIO_STANCE_REVIEW_DISABLE", raising=False)
    return path


class _Emitter:
    def __init__(self, ok=True):
        self.calls: list[tuple[str, str]] = []
        self.ok = ok

    def __call__(self, symbol, source):
        self.calls.append((symbol, source))
        if not self.ok:
            return {"ok": False, "error": "queue_down"}
        return {"ok": True, "reason": "created", "research_id": f"rr_{symbol.lower()}", "plan_id": "plan_x"}


def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def test_first_request_queues_and_is_recorded(ledger):
    em = _Emitter()
    out = rr.request_cio_review(
        "stld", source="check_investment_send", caller="send_telegram_proposal_alert", now=T0, emitter=em
    )
    assert out["review_requested"] is True
    assert out["review_request_id"] == "rr_stld"
    assert em.calls == [("STLD", "send_telegram_proposal_alert")]
    (row,) = _rows(ledger)
    assert row["symbol"] == "STLD" and row["ok"] is True and row["research_id"] == "rr_stld"
    assert row["mbi_behavior"] == 0 and row["authority"] == "READ_ONLY_ADVISORY"


def test_repeat_holds_within_window_do_not_requeue(ledger):
    em = _Emitter()
    rr.request_cio_review("STLD", source="send_telegram_proposal_alert", now=T0, emitter=em)
    for minutes in (2, 4, 60, 23 * 60):
        out = rr.request_cio_review(
            "STLD", source="send_telegram_proposal_alert", now=T0 + timedelta(minutes=minutes), emitter=em
        )
        assert out["review_status"] == "deduped"
        assert out["review_request_id"] == "rr_stld"
    assert len(em.calls) == 1
    assert len(_rows(ledger)) == 1
    rr.request_cio_review("STLD", source="send_telegram_proposal_alert", now=T0 + timedelta(hours=25), emitter=em)
    assert len(em.calls) == 2


def test_dedupe_window_is_configurable(ledger, monkeypatch):
    monkeypatch.setenv("CIO_STANCE_REVIEW_DEDUPE_SECONDS", "600")
    em = _Emitter()
    rr.request_cio_review("AES", source="screener_go_alerts", now=T0, emitter=em)
    rr.request_cio_review("AES", source="screener_go_alerts", now=T0 + timedelta(minutes=11), emitter=em)
    assert len(em.calls) == 2


def test_distinct_symbols_each_queue_once(ledger):
    em = _Emitter()
    for minute in range(0, 120, 2):
        for sym in ("STLD", "AES", "ALLE"):
            rr.request_cio_review(
                sym, source="send_telegram_proposal_alert", now=T0 + timedelta(minutes=minute), emitter=em
            )
    assert sorted(s for s, _ in em.calls) == ["AES", "ALLE", "STLD"]


def test_failed_enqueue_backs_off_then_retries(ledger):
    bad = _Emitter(ok=False)
    out = rr.request_cio_review("SLB", source="social_scalp_scanner", now=T0, emitter=bad)
    assert out["review_requested"] is False
    again = rr.request_cio_review("SLB", source="social_scalp_scanner", now=T0 + timedelta(minutes=2), emitter=bad)
    assert again["review_status"] == "retry_backoff"
    assert len(bad.calls) == 1
    good = _Emitter()
    rr.request_cio_review("SLB", source="social_scalp_scanner", now=T0 + timedelta(minutes=61), emitter=good)
    assert len(good.calls) == 1


def test_emitter_exception_never_raises(ledger):
    def boom(symbol, source):
        raise RuntimeError("store locked")

    out = rr.request_cio_review("HOOD", source="send_telegram_proposal_alert", now=T0, emitter=boom)
    assert out["review_requested"] is False
    assert out["review_status"].startswith("error:")


def test_canary_and_probe_sources_never_queue(ledger):
    em = _Emitter()
    for src in ("controlled_canary_current_tip", "maturity_agent_local_probe", "pytest"):
        out = rr.request_cio_review("STLD", source=src, now=T0, emitter=em)
        assert out["review_status"] == "source_not_eligible"
    assert em.calls == []


def test_pytest_without_explicit_path_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("CIO_STANCE_REVIEW_REQUESTS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    em = _Emitter()
    out = rr.request_cio_review("STLD", source="send_telegram_proposal_alert", now=T0, emitter=em)
    assert out["review_status"] == "disabled"
    assert em.calls == []
    assert not (tmp_path / ".local").exists()


def test_review_questions_ask_for_a_stance():
    qs = rr.review_questions("STLD")
    assert qs[0]["intent"] == "cio_stance"
    assert "STLD" in qs[0]["text"] and "BUY / WATCH / AVOID" in qs[0]["text"]


# --- wiring: the stance gate keeps the hold and records the review on the hold row ---


@pytest.fixture
def gate_env(tmp_path, monkeypatch, ledger):
    holds = tmp_path / "holds.jsonl"
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", str(holds))
    monkeypatch.setenv("CIO_STANCE_HOLD_DEDUPE_SECONDS", "0")
    calls: list[tuple[str, str]] = []

    def fake_request(symbol, *, source):
        calls.append((symbol, source))
        return {"review_requested": True, "review_status": "created", "review_request_id": "rr_x"}

    monkeypatch.setattr(sg, "request_missing_stance_review", fake_request)
    return holds, calls


def test_bullish_missing_stance_is_held_and_forces_review(gate_env):
    holds, calls = gate_env
    v = sg.check_investment_send(
        symbol="STLD",
        message_text="🔥 GO STLD",
        asserted_stance="bullish",
        cio_view={},
        source="send_telegram_proposal_alert",
    )
    assert v.allow is False and v.held_reason == sg.HELD_MISSING
    assert calls == [("STLD", "send_telegram_proposal_alert")]
    (row,) = _rows(holds)
    assert row["held_reason"] == "cio_decision_missing"
    assert row["review_requested"] is True and row["review_request_id"] == "rr_x"


def test_bearish_missing_stance_is_held_without_review(gate_env):
    holds, calls = gate_env
    v = sg.check_investment_send(
        symbol="STLD",
        message_text="STLD looks weak, SELL",
        asserted_stance="bearish",
        cio_view={},
        source="send_telegram_proposal_alert",
    )
    assert v.allow is False and v.held_reason == sg.HELD_MISSING
    assert calls == []
    (row,) = _rows(holds)
    assert "review_requested" not in row


def test_stance_on_file_never_requests_review(gate_env):
    _, calls = gate_env
    sg.check_investment_send(
        symbol="STLD",
        message_text="GO STLD",
        asserted_stance="bullish",
        cio_view={"action": "AVOID"},
        source="send_telegram_proposal_alert",
    )
    sg.check_investment_send(
        symbol="STLD",
        message_text="GO STLD",
        asserted_stance="bullish",
        cio_view={"action": "RESEARCH_MORE"},
        source="send_telegram_proposal_alert",
    )
    assert calls == []


def test_gate_normalizes_source_for_review(ledger, monkeypatch):
    seen: list[dict] = []

    def fake(symbol, *, source, caller=None, **_):
        seen.append({"symbol": symbol, "source": source, "caller": caller})
        return {"review_requested": True, "review_status": "created"}

    for name in ("lib.cio_stance_review_request", "scripts.lib.cio_stance_review_request"):
        mod = sys.modules.get(name)
        if mod is None:
            mod = __import__(name, fromlist=["request_cio_review"])
        monkeypatch.setattr(mod, "request_cio_review", fake)
    sg.request_missing_stance_review("STLD", source="send_telegram_proposal_alert")
    sg.request_missing_stance_review("NOC", source="maria_outbound_gate")
    assert seen == [
        {"symbol": "STLD", "source": "check_investment_send", "caller": "send_telegram_proposal_alert"},
        {"symbol": "NOC", "source": "maria_outbound_gate", "caller": None},
    ]


def test_maria_observe_mode_never_queues_a_review(tmp_path, monkeypatch):
    """Observe mode must be side-effect free: a missing-stance hold queues nothing."""
    from lib import maria_outbound_gate as mg

    SG = mg.SG  # patch the exact module object the Maria gate calls

    calls = []
    monkeypatch.setattr(SG, "request_missing_stance_review", lambda sym, *, source: calls.append(sym) or {})
    monkeypatch.setattr(SG, "record_hold", lambda *a, **k: None)
    no_row = lambda *a, **k: []  # noqa: E731 — no CIO decision on file
    resolve = lambda text: [{"symbol": "STLD", "guid": "g-stld"}]  # noqa: E731
    for mode, expected in (("observe", []), ("live", ["STLD"])):
        calls.clear()
        mg.handle(
            {"content": "STLD is a BUY here.", "to": "8797974247", "mode": mode},
            db_query=no_row,
            resolve=resolve,
            cio_dir=tmp_path,
        )
        assert calls == expected, mode
