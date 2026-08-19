"""Canary thesis publish gate + research queue projection (no live apply)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_queue_empty_on_db_failure(monkeypatch):
    from scripts.lib import symbol_thesis_queue as q

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(q, "load_symbol_research_queue", q.load_symbol_research_queue)
    out = q.load_symbol_research_queue("SCHG", conn=object())  # cursor will fail
    assert out["active_research"] == []
    assert out["recent_completed_research"] == []
    assert out["ok"] is False


def test_queue_splits_injected_rows():
    from scripts.lib.symbol_thesis_queue import load_symbol_research_queue
    out = load_symbol_research_queue(
        "SCHG",
        rows=[
            {"id": 1, "symbol": "SCHG", "status": "queued", "requested_agent": "maria",
             "request_type": "flash_narrative", "created_at": "2026-08-19T00:00:00+00:00"},
            {"id": 2, "symbol": "SCHG", "status": "completed", "requested_agent": "maria",
             "note": "done", "completed_at": "2026-08-19T01:00:00+00:00"},
        ],
    )
    assert len(out["active_research"]) == 1
    assert out["active_research"][0]["agent"] == "maria"
    assert len(out["recent_completed_research"]) == 1
    assert out["source"] == "watchlist_agent_jobs"


def test_card_uses_queue_not_hardcoded_empty(monkeypatch, tmp_path):
    from scripts.lib import symbol_thesis_cc as cc

    monkeypatch.setattr(
        cc,
        "load_symbol_research_queue",
        lambda _sym: {
            "active_research": [{"id": 9, "status": "queued", "agent": "maria"}],
            "recent_completed_research": [],
            "source": "watchlist_agent_jobs",
            "ok": True,
        },
    )
    monkeypatch.setattr(cc, "research_requests_for_symbol", lambda *a, **k: [])
    monkeypatch.setattr(
        cc,
        "thesis_fields_for_symbol",
        lambda *a, **k: {
            "symbol_thesis_id": "symbol_schg",
            "memberships": ["HELD"],
            "portfolio_role": "GROWTH",
            "thesis_state": "RESEARCH_REQUIRED",
            "research_gaps": ["living thesis"],
        },
    )

    class _Store:
        def list_versions(self, *_a, **_k):
            return []

    monkeypatch.setattr(cc, "CIOThesisStore", lambda **k: _Store())
    monkeypatch.setattr(cc, "reconcile_universe", lambda *_a, **_k: {"symbols": {}})
    monkeypatch.setattr(cc, "_cio_action_for_symbol", lambda *_a, **_k: None)
    card = cc.build_symbol_thesis_card("SCHG", root=tmp_path)
    assert card["active_research"][0]["id"] == 9
    assert card["recent_completed_research"] == []


def test_canary_default_dry_and_rejects_non_canary(tmp_path, monkeypatch):
    from scripts.lib.symbol_thesis_canary import plan_canary_publish, CANARY_SYMBOLS

    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_canary.thesis_fields_for_symbol",
        lambda sym, **k: {"thesis_summary": "", "thesis_state": "RESEARCH_REQUIRED", "symbol_thesis_id": f"symbol_{sym.lower()}"},
    )
    out = plan_canary_publish(["SCHG", "AAPL", "CSCO"], root=tmp_path, apply=False, env={})
    assert out["mode"] == "dry"
    assert out["apply_requested"] is False
    assert "AAPL" in out["rejected_not_canary"]
    assert [r["symbol"] for r in out["rows"]] == ["SCHG", "CSCO"]
    assert all(r["applied"] is False for r in out["rows"])
    assert set(CANARY_SYMBOLS) == {"SCHG", "CSCO", "ANET"}


def test_canary_apply_blocked_without_flag(tmp_path, monkeypatch):
    from scripts.lib.symbol_thesis_canary import plan_canary_publish

    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_canary.thesis_fields_for_symbol",
        lambda *a, **k: {"thesis_summary": "existing", "thesis_state": "CURRENT"},
    )
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not publish")

    monkeypatch.setattr("scripts.lib.symbol_thesis_canary.publish_symbol_thesis", boom)
    out = plan_canary_publish(["SCHG"], root=tmp_path, apply=True, env={})
    assert out["apply_blocked"] is True
    assert out["mode"] == "dry"
    assert called["n"] == 0
