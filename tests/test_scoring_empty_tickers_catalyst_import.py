"""score_all must not UnboundLocalError when Finviz returns 0 tickers.

Regression for 2026-07-24: attach_catalyst_exception_tags was imported inside the
per-row loop; empty tickers skipped the import and the post-loop call crashed the
orchestrator, leaving /api/v2/trade-ai/scanner on a prior run.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scoring import score_all  # noqa: E402


def test_score_all_empty_tickers_returns_empty_list():
    out = score_all([], {}, project_root=str(ROOT), use_llm=False)
    assert out == []


def test_score_all_one_ticker_still_scores():
    """Non-empty path still runs (no regression on import relocation)."""
    row = {
        "symbol": "TEST",
        "price": 5.0,
        "change_percent": "2",
        "gap_percent": "3",
        "relative_volume": 2.0,
        "float_m": 15.0,
        "sector": "Technology",
        "industry": "Software",
        "company": "Test Co",
    }
    out = score_all([row], {}, project_root=str(ROOT), use_llm=False)
    assert isinstance(out, list)
    assert len(out) >= 1
    assert str(out[0].get("symbol", "")).upper() == "TEST"
    # Attach path is a no-op for most rows; just prove score_all completed.
    assert "score" in out[0] or out[0].get("disqualified") is True
