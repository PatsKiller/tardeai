"""2026-09-15: strategy cards carry the symbol's recent catalysts.

Every active card had catalyst_summary NULL — the writer passed a literal None — while 96 of 266
active symbols had catalyst_events in the last 30 days.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import materialize_watchlist_strategy_cards as mat  # noqa: E402


def _row(ctype, headline, day, impact=None):
    return {"catalyst_type": ctype, "headline": headline, "impact_score": impact,
            "source_url": None, "ts": datetime(2026, 9, day, 12, tzinfo=timezone.utc)}


def test_typed_catalyst_leads_over_generic_news():
    rows = [_row("other", "Stock moves on volume", 14), _row("contract_win", "Wins $1.2B Army contract", 12)]
    summary, items = mat.summarize_catalysts(rows)
    assert summary.startswith("Contract win: Wins $1.2B Army contract (2026-09-12)")
    assert [i["type"] for i in items] == ["contract_win"]


def test_generic_news_used_when_nothing_typed():
    summary, items = mat.summarize_catalysts([_row("other", "Blue Moon acquires water rights", 15)])
    assert summary == "News: Blue Moon acquires water rights (2026-09-15)"
    assert items[0]["label"] == "News"


def test_more_count_and_limit():
    rows = [_row("analyst_upgrade", "UBS raises target", 14), _row("earnings_beat", "Beats Q2", 10),
            _row("insider_buy", "CEO buys", 9), _row("merger_acquisition", "Acquires X", 8)]
    summary, items = mat.summarize_catalysts(rows)
    assert summary.endswith("· +2 more") and len(items) == 3


def test_no_catalysts_gives_none():
    assert mat.summarize_catalysts([]) == (None, [])
    assert mat.summarize_catalysts([_row("other", "   ", 1)]) == (None, [])


def test_writer_persists_summary_on_insert_and_update():
    src = (ROOT / "scripts" / "materialize_watchlist_strategy_cards.py").read_text(encoding="utf-8")
    assert "thesis[:500] if thesis else None, catalyst_summary," in src
    assert "catalyst_summary=EXCLUDED.catalyst_summary," in src
    assert '"catalysts": catalyst_items,' in src
    assert "thesis[:500] if thesis else None, None," not in src
