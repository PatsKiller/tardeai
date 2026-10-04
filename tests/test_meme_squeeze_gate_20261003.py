"""Blocked-idea ledger counts each idea once per strategy.

2026-10-03: the per-gate ledger summary read "meme squeeze: 9 good moves blocked,
9 losers avoided", and the operator asked to fix the gate. One idea is usually
stopped by several gates of the same strategy (GLND 09-21 by four), so adding gate
rows counted it up to four times. Per idea, meme squeeze was 4 winners vs 6 losers
(30d) and 6 vs 12 (180d), median about -13% at 5 sessions: the gate was earning its
keep and was NOT changed. These tests pin the per-idea view that shows that.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import counterfactual_ledger as cl  # noqa: E402


def _row(gate: str, symbol: str, day: str, ret5):
    h5 = {"status": "MEASURED", "return_pct": ret5} if ret5 is not None else {"status": "PENDING"}
    return {"gate": gate, "symbol": symbol, "day": day,
            "horizons": {"1": {"status": "PENDING"}, "5": h5, "20": {"status": "PENDING"}}}


ROWS = [
    # one winning idea blocked by four gates of the same strategy
    *[_row(f"meme_squeeze_momentum:{g}", "GLND", "2026-09-21", 66.4)
      for g in ("SKIPPED_STRATEGY_CRITERIA", "SKIPPED_LOW_SCORE", "SKIPPED_NOT_GO", "SKIPPED_CRITIC_DOWNGRADE")],
    _row("meme_squeeze_momentum:SKIPPED_STRATEGY_CRITERIA", "KITT", "2026-09-25", -44.9),
    _row("meme_squeeze_momentum:SKIPPED_STRATEGY_CRITERIA", "AIFF", "2026-09-25", -30.6),
    _row("momentum_scalp:SKIPPED_LOW_SCORE", "GLND", "2026-09-21", 66.4),
]


def _h5(items, key, value):
    return next(g for g in items if g[key] == value and g["horizon_sessions"] == 5)


def test_per_gate_summary_counts_an_idea_under_every_gate():
    gates = [g for g in cl.summarize(ROWS) if g["gate"].startswith("meme_squeeze") and g["horizon_sessions"] == 5]
    assert sum(g["cost_good_moves_blocked"] for g in gates) == 4  # GLND counted four times


def test_per_idea_summary_counts_each_idea_once():
    meme = _h5(cl.summarize_ideas(ROWS), "strategy", "meme_squeeze_momentum")
    assert meme["ideas"] == 3 and meme["measured"] == 3
    assert meme["good_moves_blocked"] == 1 and meme["losers_avoided"] == 2
    assert meme["multi_gate_ideas"] == 1
    assert meme["median_return_pct"] == -30.6


def test_the_same_symbol_day_is_a_separate_idea_per_strategy():
    scalp = _h5(cl.summarize_ideas(ROWS), "strategy", "momentum_scalp")
    assert scalp["ideas"] == 1 and scalp["good_moves_blocked"] == 1


def test_pending_horizons_are_not_measured():
    rows = [_row("meme_squeeze_momentum:SKIPPED_LOW_SCORE", "VIDA", "2026-09-08", None)]
    meme = _h5(cl.summarize_ideas(rows), "strategy", "meme_squeeze_momentum")
    assert meme["ideas"] == 1 and meme["measured"] == 0 and meme["median_return_pct"] is None


def test_build_and_api_expose_the_per_idea_view(monkeypatch):
    out = cl.build(lambda *a, **k: [], days=1)
    assert "idea_summary" in out
    import scripts.api_v3_cio as api

    monkeypatch.setattr(cl, "latest_rows", lambda *a, **k: {str(i): r for i, r in enumerate(ROWS)})
    payload = api.get_cio_counterfactuals()
    meme = _h5(payload["idea_summary"], "strategy", "meme_squeeze_momentum")
    assert meme["ideas"] == 3
