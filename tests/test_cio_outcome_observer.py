"""Thin disposition → matured outcome observer."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cio_outcome_observer import learning_summary, record_disposition_outcome


def test_disposition_matures_and_shows_in_learning(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    out = record_disposition_outcome(
        decision_or_plan_id="decision_test_1",
        disposition="done",
        lineage_id="lin_test",
        rating=4,
        note="useful",
        symbol="SCHD",
    )
    assert out["ok"] is True
    assert out["matured"] is True
    summ = learning_summary()
    assert summ["ok"] is True
    assert summ["matured_count"] >= 1
    assert summ["memory_behavior_influence"] == 0
    assert summ["eligible_runs"] == 0


def test_defer_not_immediately_matured(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    out = record_disposition_outcome(
        decision_or_plan_id="decision_defer_1",
        disposition="defer",
    )
    assert out["ok"] is True
    assert out["matured"] is False
