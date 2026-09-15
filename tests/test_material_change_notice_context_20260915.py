"""Operator 2026-09-15 on the material-change notice: "stuff has moved but what was the move, what was the
catalyst, I don't even know if these are on my watch list ... what strategy does it attach to — it's just
information." The notice now says the direction, a real catalyst or that none was found, how the name got on
the watchlist, its strategy and plan, and the CIO's view."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def mod():
    return pytest.importorskip("notify_material_change")


def _row(**kw):
    base = {"change_guid": "g-1", "symbol": "UZX", "kind": "price_excursion", "magnitude": 4.28, "baseline": 4.81,
            "observed_value": 20.6, "observed_at": "2026-09-15 00:00:00", "universe_reason": "watchlist",
            "subject_guid": None, "evidence_json": {"source": "ticker_prices", "move_pct_signed": -20.6}}
    base.update(kw)
    return base


INFO = {
    "watch": {"source": "ai_discovered", "reason": "hermes:intelligence: Consumer Cyclical", "since": "2026-05-19"},
    "price": 0.0811, "change_pct": -13.6, "strategy": None,
    "plan": {"entry": 0.08, "stop": 0.06, "target": 0.12}, "size": "Nano cap · $9M",
    "headline": None, "last_research": None,
}


def test_direction_is_stated(mod):
    assert "UZX — down 21%, 4x its normal daily range" in mod.render([_row()], {"g-1": {}})
    up = _row(evidence_json={"move_pct_signed": 44.35}, symbol="PDSB", observed_value=44.35)
    assert "PDSB — up 44%" in mod.render([up], {"g-1": {}})


def test_direction_falls_back_to_the_watchlist_change_sign_for_older_rows(mod):
    old = _row(evidence_json={"source": "ticker_prices"})
    assert "down 21%" in mod._headline_line(old, {"change_pct": -13.6})
    assert "moved 21%" in mod._headline_line(old, {})


def test_web_page_titles_are_not_quoted_as_catalysts(mod):
    rows = [("Top Forgent Power Solutions (FPS) Competitors 2026 - MarketBeat", "other"),
            ("UZX Stock Price and Chart — NASDAQ:UZX - tradingview.com", "news_momentum"),
            ("Should I buy PDS Biotechnology (PDSB) - Zacks Investment Research", "other")]
    assert mod.pick_headline(rows) is None
    msg = mod.render([_row()], {"g-1": dict(INFO)})
    assert "No news found that explains this move." in msg


def test_a_typed_catalyst_beats_generic_news(mod):
    rows = [("Linkage Global shares jump on volume", "news_momentum"),
            ("Linkage Global announces $5M registered direct offering", "offering_dilution")]
    assert mod.pick_headline(rows) == ("Linkage Global announces $5M registered direct offering", "catalyst")
    assert mod.pick_headline(rows[:1]) == ("Linkage Global shares jump on volume", "news")


def test_provenance_strategy_plan_and_cio_are_in_the_notice(mod):
    msg = mod.render([_row()], {"g-1": dict(INFO, cio={"action": "HUMAN_REVIEW", "date": "2026-09-14"})})
    assert "on your watchlist since 2026-05-19 — found by AI discovery (Consumer Cyclical)" in msg
    assert "Strategy: none assigned · plan entry $0.08 / stop $0.06 / target $0.12 · price is +1.4% from the entry" in msg
    assert "CIO: Human Review (2026-09-14)" in msg
    assert "$0.08 · Nano cap · $9M" in msg


def test_stale_plan_and_missing_cio_are_said_plainly(mod):
    info = dict(INFO, price=0.60, plan={"entry": 0.20, "stop": 0.13, "target": 0.59})
    msg = mod.render([_row(symbol="PDSB")], {"g-1": info})
    assert "plan is stale — price is +200% from its entry" in msg and "CIO: no view yet" in msg


def test_rich_notice_carries_the_same_lines_without_advice_words(mod):
    info = dict(INFO, headline="Linkage Global announces $5M registered direct offering", headline_kind="catalyst")
    text = mod.render_rich([_row()], {"g-1": info})["text"]
    for phrase in ("down 21%", "Catalyst: Linkage Global announces", "found by AI discovery", "Strategy: none assigned", "CIO: no view yet"):
        assert phrase in text
    for banned in ("buy", "sell", "trim", "add to"):
        assert banned not in text.lower()


def test_detector_records_the_signed_move():
    src = (ROOT / "scripts" / "material_change_detector.py").read_text(encoding="utf-8")
    assert "(close_price - prev) / nullif(prev, 0) * 100.0 AS signed_move_pct" in src
    assert '"move_pct_signed"' in src
