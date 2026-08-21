"""Phase D: research queue open_count + oldest wait age (fail-soft)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_human_age_units():
    from scripts.lib.symbol_thesis_queue import _human_age

    assert _human_age(None) is None
    assert _human_age(0) == "0m"
    assert _human_age(59) == "0m"
    assert _human_age(720) == "12m"
    assert _human_age(3 * 3600) == "3h"
    assert _human_age(2 * 86400) == "2d"


def test_age_seconds_iso_variants():
    from scripts.lib.symbol_thesis_queue import _age_seconds

    now = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    assert _age_seconds("2026-08-21T11:00:00Z", now=now) == 3600
    assert _age_seconds("2026-08-21T11:00:00+00:00", now=now) == 3600
    assert _age_seconds("2026-08-21T11:00:00", now=now) == 3600
    assert _age_seconds("not-a-date", now=now) is None
    assert _age_seconds(None, now=now) is None


def test_open_count_and_oldest_wait_from_rows(monkeypatch):
    from scripts.lib import symbol_thesis_queue as q

    fixed_now = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(q, "datetime", _FixedDatetime)

    older = "2026-08-21T09:00:00+00:00"  # 3h
    newer = "2026-08-21T11:48:00+00:00"  # 12m
    out = q.load_symbol_research_queue(
        "UBER",
        rows=[
            {
                "id": 1,
                "symbol": "UBER",
                "status": "queued",
                "requested_agent": "maria",
                "created_at": newer,
            },
            {
                "id": 2,
                "symbol": "UBER",
                "status": "processing",
                "requested_agent": "hermes",
                "created_at": older,
            },
            {
                "id": 3,
                "symbol": "UBER",
                "status": "completed",
                "requested_agent": "maria",
                "created_at": older,
                "completed_at": newer,
            },
        ],
    )
    assert out["open_count"] == 2
    assert len(out["active_research"]) == 2
    assert out["oldest_wait_seconds"] == 3 * 3600
    assert out["oldest_wait_human"] == "3h"
    ages = {r["id"]: r.get("waiting_age_seconds") for r in out["active_research"]}
    assert ages[1] == 720
    assert ages[2] == 3 * 3600
    humans = {r["id"]: r.get("waiting_age_human") for r in out["active_research"]}
    assert humans[2] == "3h"
    assert humans[1] == "12m"


def test_empty_rows_zero_open_none_wait():
    from scripts.lib.symbol_thesis_queue import load_symbol_research_queue

    out = load_symbol_research_queue("SCHG", rows=[])
    assert out["open_count"] == 0
    assert out["oldest_wait_seconds"] is None
    assert out["oldest_wait_human"] is None
    assert out["active_research"] == []
    assert out["ok"] is True


def test_get_symbol_intelligence_includes_research_queue(monkeypatch):
    import types

    import scripts.api_v3_cio as api

    def _fake_assemble(symbol, **kwargs):
        return {
            "schema": "SymbolIntelligenceObject@v1",
            "symbol": str(symbol).upper(),
            "authority": "READ_ONLY_ADVISORY",
        }

    sio = types.ModuleType("scripts.lib.cio_symbol_intelligence")
    sio.assemble_symbol_intelligence = _fake_assemble
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_symbol_intelligence", sio)

    fb = types.ModuleType("scripts.lib.cio_operator_ticker_feedback")
    fb.journal_for_symbol = lambda *_a, **_k: []
    fb.latest_feedback = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_operator_ticker_feedback", fb)

    fake_queue = {
        "active_research": [
            {
                "id": 11,
                "status": "queued",
                "agent": "maria",
                "waiting_age_seconds": 720,
                "waiting_age_human": "12m",
            }
        ],
        "recent_completed_research": [],
        "open_count": 1,
        "oldest_wait_seconds": 720,
        "oldest_wait_human": "12m",
        "source": "watchlist_agent_jobs",
        "ok": True,
    }

    import scripts.lib.symbol_thesis_queue as qmod

    monkeypatch.setattr(qmod, "load_symbol_research_queue", lambda *_a, **_k: fake_queue)

    got = api.get_symbol_intelligence("UBER")
    assert got["ok"] is True
    assert got["symbol"] == "UBER"
    rq = got["research_queue"]
    assert rq["open_count"] == 1
    assert rq["oldest_wait_seconds"] == 720
    assert rq["oldest_wait_human"] == "12m"
    assert rq["active_research"][0]["id"] == 11
    assert rq["ok"] is True
    assert rq["source"] == "watchlist_agent_jobs"
    assert got["authority"] == "READ_ONLY_ADVISORY"
    assert got["financial_action"] is False


def test_get_symbol_intelligence_queue_fail_soft(monkeypatch):
    import types

    import scripts.api_v3_cio as api

    sio = types.ModuleType("scripts.lib.cio_symbol_intelligence")
    sio.assemble_symbol_intelligence = lambda symbol, **k: {"symbol": symbol}
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_symbol_intelligence", sio)

    fb = types.ModuleType("scripts.lib.cio_operator_ticker_feedback")
    fb.journal_for_symbol = lambda *_a, **_k: []
    fb.latest_feedback = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_operator_ticker_feedback", fb)

    import scripts.lib.symbol_thesis_queue as qmod

    def _boom(*_a, **_k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(qmod, "load_symbol_research_queue", _boom)

    got = api.get_symbol_intelligence("SCHG")
    assert got["ok"] is True
    rq = got["research_queue"]
    assert rq["open_count"] == 0
    assert rq["oldest_wait_seconds"] is None
    assert rq["oldest_wait_human"] is None
    assert rq["active_research"] == []
    assert rq["ok"] is False
