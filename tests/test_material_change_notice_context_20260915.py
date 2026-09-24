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


# Re-anchored 2026-09-24 (maturity review): provenance, strategy name, sector and thesis
# moved OFF the notice and into the Command Center; the notice carries direction, the
# relative size of the move, what explains it (or that nothing does), where price sits
# in the plan, and ONE reconciled CIO verdict. The 09-15 asks that survive are tested here.

FRESH = {"price": 0.0811, "quote_age_h": 0.2, "change_pct": -13.6}


def test_direction_is_stated(mod):
    assert mod._move_text(_row(), {}) == "-20.6% (4.3× its normal daily move)"
    up = _row(evidence_json={"move_pct_signed": 44.35}, symbol="PDSB", observed_value=44.35)
    assert mod._move_text(up, {}).startswith("+44.4%")


def test_direction_falls_back_to_the_watchlist_change_sign_for_older_rows(mod):
    old = _row(evidence_json={"source": "ticker_prices"})
    assert mod._move_text(old, {"change_pct": -13.6}).startswith("-20.6%")
    assert mod._move_text(old, {}).startswith("20.6% move")


def test_web_page_titles_are_not_quoted_as_catalysts(mod):
    rows = [("Top Forgent Power Solutions (FPS) Competitors 2026 - MarketBeat", "other"),
            ("UZX Stock Price and Chart — NASDAQ:UZX - tradingview.com", "news_momentum"),
            ("Should I buy PDS Biotechnology (PDSB) - Zacks Investment Research", "other")]
    assert mod.pick_headline(rows) is None
    assert mod._what_text(dict(INFO)) == "no news explains the move"


def test_a_typed_catalyst_beats_generic_news(mod):
    rows = [("Linkage Global shares jump on volume", "news_momentum"),
            ("Linkage Global announces $5M registered direct offering", "offering_dilution")]
    assert mod.pick_headline(rows) == ("Linkage Global announces $5M registered direct offering", "catalyst")
    assert mod.pick_headline(rows[:1]) == ("Linkage Global shares jump on volume", "news")


def test_the_digest_line_carries_price_age_move_and_one_cio_verdict(mod):
    info = dict(INFO, **FRESH, cio={"action": "HUMAN_REVIEW", "date": "2026-09-14"})
    route = mod.classify(_row(), info)
    assert route["route"] == mod.ROUTE_DIGEST and route["state"] == "MOVE"
    line = mod.digest_line(_row(), info, route)
    assert "UZX $0.08 (12m) · -20.6% (4.3× its normal daily move) · CIO: HUMAN REVIEW (2026-09-14)" in line


def test_a_plan_that_reached_its_target_says_so(mod):
    """price 0.60 against a 0.59 target is a plan that HIT ITS TARGET — never "stale"
    (2026-09-21). Not held, so it is the digest's 'already through the target'."""
    info = dict(INFO, price=0.60, quote_age_h=0.2, plan={"entry": 0.20, "stop": 0.13, "target": 0.59})
    route = mod.classify(_row(symbol="PDSB"), info)
    assert route["state"] == "TARGET_PASSED" and route["route"] == mod.ROUTE_DIGEST
    line = mod.digest_line(_row(symbol="PDSB"), info, route)
    assert "target $0.59 passed" in line and "stale" not in line.lower(), line


def test_rich_page_carries_the_catalyst_without_advice_words(mod):
    info = dict(INFO, **FRESH, holding={"shares": 50.0, "accounts": ["Taxable"]},
                headline="Linkage Global announces $5M registered direct offering", headline_kind="catalyst")
    text = mod.render_rich([_row()], {"g-1": info})["text"]
    for phrase in ("BIG MOVE — UZX (held, 50 sh)", "-20.6%", "catalyst: Linkage Global announces"):
        assert phrase in text
    for banned in ("buy", "sell", "trim", "add to"):
        assert banned not in text.lower()


def test_detector_records_the_signed_move():
    src = (ROOT / "scripts" / "material_change_detector.py").read_text(encoding="utf-8")
    assert "(close_price - prev) / nullif(prev, 0) * 100.0 AS signed_move_pct" in src
    assert '"move_pct_signed"' in src
