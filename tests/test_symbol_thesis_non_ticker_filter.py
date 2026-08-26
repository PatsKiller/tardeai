"""P1.5 — NON_TICKER filter in Universe & Theses projection."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_non_ticker_bucket_other_and_cusip_preserved():
    from scripts.lib.symbol_thesis_cc import (
        NON_TICKER_SYMBOLS,
        _is_cusip,
        _is_non_ticker,
        _membership_bucket,
    )

    assert "HEALTH" in NON_TICKER_SYMBOLS
    assert _is_non_ticker("HEALTH")
    assert _is_non_ticker("health")
    assert not _is_non_ticker("SCHG")
    assert _is_cusip("12507E201")
    assert _membership_bucket({"symbol": "HEALTH", "memberships": ["HELD"]}) == "OTHER"
    assert _membership_bucket({"symbol": "12507E201", "memberships": ["HELD"]}) == "BONDS_UNRESOLVED"
    assert _membership_bucket({"symbol": "SCHG", "memberships": ["HELD"]}) == "HELD"


def test_universe_projection_excludes_health_from_material_cards(monkeypatch, tmp_path):
    from scripts.lib import symbol_thesis_cc as cc

    monkeypatch.setattr(
        cc,
        "universe_metrics",
        lambda **k: {
            "material": 3,
            "universe_union": 3,
            "current": 0,
            "research_required": 3,
            "stale": 0,
            "conflicted": 0,
            "insufficient_data": 0,
            "role_unknown": 1,
            "coverage_pct_material": 0,
            "desk": {},
        },
    )
    monkeypatch.setattr(
        cc,
        "build_coverage_report",
        lambda **k: {
            "rows": [
                {
                    "symbol": "SCHG",
                    "material": True,
                    "memberships": ["HELD"],
                    "coverage_state": "RESEARCH_REQUIRED",
                    "portfolio_role": {"portfolio_role": "GROWTH", "source": "operator"},
                    "research_gaps": [],
                },
                {
                    "symbol": "HEALTH",
                    "material": True,
                    "memberships": ["HELD"],
                    "coverage_state": "RESEARCH_REQUIRED",
                    "portfolio_role": {"portfolio_role": "SPECULATIVE", "source": "inferred"},
                    "research_gaps": [],
                },
                {
                    "symbol": "12507E201",
                    "material": True,
                    "memberships": ["HELD"],
                    "coverage_state": "INSUFFICIENT_DATA",
                    "portfolio_role": {"portfolio_role": "UNKNOWN", "source": "none"},
                    "research_gaps": [],
                },
            ],
        },
    )
    monkeypatch.setattr(cc, "daily_thesis_changes", lambda **k: {"changes": []})
    monkeypatch.setattr(cc, "propose_prioritized_research", lambda **k: {"counts": {"proposed": 0}})

    out = cc.build_universe_theses_projection(root=tmp_path, include_proposed_research=False)
    syms = [c["symbol"] for c in out["symbols"]]
    assert "HEALTH" not in syms
    assert "SCHG" in syms
    assert "12507E201" in syms  # CUSIP kept (bucketed BONDS_UNRESOLVED)
    assert out["metrics"]["non_ticker_excluded"] == 1
    bond = next(c for c in out["symbols"] if c["symbol"] == "12507E201")
    assert bond["bucket"] == "BONDS_UNRESOLVED"
