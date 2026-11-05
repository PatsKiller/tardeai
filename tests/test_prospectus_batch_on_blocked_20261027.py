"""Regression: a gate-blocked Watch row during batch submit must park the row, not crash the run (2026-10-27)."""
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_on_blocked_callback_matches_submit_due_call_shape():
    src = (ROOT / "scripts/prospectus_build.py").read_text(encoding="utf-8")
    assert "on_blocked=lambda sym, exc: handle_blocked(base, sym, exc)" in src
    from scripts.lib.prospectus import pipeline
    assert list(inspect.signature(pipeline.handle_blocked).parameters)[:3] == ["base", "sym", "exc"]
    batch_src = (ROOT / "scripts/lib/prospectus/batch.py").read_text(encoding="utf-8")
    assert "on_blocked(sym, exc)" in batch_src
