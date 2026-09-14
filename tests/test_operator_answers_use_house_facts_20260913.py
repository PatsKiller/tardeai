"""Operator answers come from the house's own stores, scoped to what was asked,
and say where they came from.

Three litmus tests on 2026-09-13 (18:50-18:58), all with the poller on that
day's release:

1. "Is now a good time to get back into schg" got the WHOLE re-entry book. The
   intent analyzer only recognised UPPER-CASE tickers, so "schg" resolved to no
   symbol, the desk built the book-wide card, and Phase 7 saw no gap to resolve.
   The desk row for SCHG had everything: zone, gates, levels, held flag,
   advisory "Monitor / No Action".
2. "How does the market normally perform in September ... what sectors should I
   concentrate on" got model seasonality prose plus "your holdings, weights and
   cash are not available ... all empty". The CIO snapshot carried total_cash
   $710,933, sector weights and the investment policy; the freeform builder read
   the wrong keys and never read those domains.
3. Neither reply said where its content came from.

These tests are offline: desk rows, holdings and the snapshot are injected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import lib.cio_operator_desk_loop as desk  # noqa: E402
from lib.cio_telegram_converse import format_reentry_symbol_reply  # noqa: E402

SCHG_ROW = {
    "symbol": "SCHG", "held": True, "price": 35.155,
    "price_as_of": "2026-09-11T23:34:15.930825-04:00", "price_age_h": 43.3,
    "price_source": "data_broker.market_quotes:alpaca",
    "entry_low": 34.55, "entry_high": 34.85, "stop": 34.35, "target": 36.4,
    "resistance": {"state": "BELOW", "level": 35.855}, "rr": 1.55, "rsi": 49.38, "rsi_status": "BULLISH",
    "sma_20": 35.39, "sma_50": 34.89, "wash_blocked": False,
    "why": ["Price is +0.9% from the entry zone (near threshold 3%).",
            "RSI 49.4 is in the constructive band (40 ≤ RSI < 70)."],
    "gates": [{"id": "fresh", "pass": True, "value": "43h"}, {"id": "zone", "pass": False, "value": "+0.9% vs zone"},
              {"id": "rsi", "pass": True, "value": "49.4"}, {"id": "not_held", "pass": False, "value": "held"},
              {"id": "wash", "pass": True, "value": "clear"}],
    "advisory": {"date": "2026-09-13", "action": "Monitor / No Action"},
    "intel": {"state": "NEAR ENTRY"},
}
OTHER_ROW = {**SCHG_ROW, "symbol": "ADBE", "held": False, "price": 252.32, "entry_low": 248.85, "entry_high": 252.0,
             "intel": {"state": "READY TO REVIEW"}, "advisory": {"date": "2026-09-13", "action": "Buy-limit in zone"}}
HOLDING = {"shares": 0.2294, "market_value": 8.07, "account": "schwab_taxable"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_REENTRY_FLASH", "0")
    monkeypatch.setattr(desk, "_known_symbols", lambda ttl_s=0: frozenset({"SCHG", "ADBE", "NOC", "RTX"}))
    monkeypatch.setattr(desk, "_held_positions_map", lambda: {"SCHG": HOLDING, "NOC": {"shares": 10, "market_value": 5000, "account": "schwab_rollover_ira"}})
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda *a, **k: {"ok": True})

    def _no_db(*a, **k):
        raise RuntimeError("offline test: no database")
    # topic research reads the DB through the broker; offline it has no rows
    monkeypatch.setattr(desk, "_research_db_query", _no_db)


# ── 1. the symbol is recognised whatever its case, and the question is re-entry ──


@pytest.mark.parametrize("text", [
    "Is now a good time to get back into schg",
    "is it a good time to get back into SCHG",
    "should I buy back schg",
    "re-enter schg?",
])
def test_lower_case_known_symbol_makes_a_symbol_scoped_reentry_intent(text):
    i = desk.analyze_operator_intent(text)
    assert i["symbols"] == ["SCHG"], i
    assert i["intent"] == "reentry" and "reentry_ready" in i["needs"]


def test_unknown_lower_case_words_are_not_symbols():
    i = desk.analyze_operator_intent("is now a good time to get back into growth funds")
    assert i["symbols"] == []


def test_negative_control_the_old_rule_needed_upper_case(monkeypatch):
    monkeypatch.setattr(desk, "_known_symbols", lambda ttl_s=0: frozenset())
    assert desk._extract_symbols("get back into schg") == []
    assert desk._extract_symbols("get back into SCHG") == ["SCHG"]


# ── 2. the answer is that symbol's own row, not the book ────────────────────


def _rows_fixture(monkeypatch):
    """The desk imports the converse module under BOTH spellings (lib.* and
    scripts.lib.*); patch whichever objects exist so the live desk file is never read."""
    import importlib
    fake = lambda: ([SCHG_ROW, OTHER_ROW], "2026-09-13T22:52:35", Path("/x/reentry_decision_desk_latest.json"))
    for name in ("lib.cio_telegram_converse", "scripts.lib.cio_telegram_converse"):
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        monkeypatch.setattr(mod, "load_reentry_desk_rows", fake)


def test_symbol_card_carries_zone_gates_levels_holding_and_verdict():
    card = format_reentry_symbol_reply(SCHG_ROW, holding=HOLDING, computed_at="2026-09-13T22:52:35")
    for needle in ("SCHG — re-entry check", "$35.16", "43h old", "alpaca", "zone $34.55–$34.85", "+0.9% above zone",
                   "stop $34.35", "target $36.40", "R:R 1.55", "RSI 49.38", "resistance $35.85 (BELOW)",
                   "zone ✗ (+0.9% vs zone)", "not_held ✗ (held)", "wash ✓",
                   "you still hold 0.2294 sh (~$8.07) in schwab_taxable", "Monitor / No Action",
                   "READ_ONLY_ADVISORY"):
        assert needle in card, needle
    assert "ADBE" not in card, "another symbol's row must never leak into this card"


def test_evidence_for_a_named_symbol_builds_its_card_and_curate_uses_it(monkeypatch):
    _rows_fixture(monkeypatch)
    intent = desk.analyze_operator_intent("Is now a good time to get back into schg")
    ev = desk.gather_tradeai_evidence(intent)
    assert set(ev["available"]["reentry_symbol_cards"]) == {"SCHG"}
    curated = desk._curate_from_evidence("Is now a good time to get back into schg", ev)
    assert "SCHG — re-entry check" in curated["text"]
    assert "ADBE" not in curated["text"] and "READY TO REVIEW" not in curated["text"], "no book dump"
    assert curated["source"] == "tradeai_deterministic", "exact numbers are not sent to Flash for polish"


def test_negative_control_without_a_symbol_the_book_card_is_still_the_answer(monkeypatch):
    _rows_fixture(monkeypatch)
    intent = desk.analyze_operator_intent("what is ready to buy back right now")
    ev = desk.gather_tradeai_evidence(intent)
    assert "reentry_symbol_cards" not in ev["available"]
    assert "reentry_card" in ev["available"]


def test_a_named_symbol_missing_from_the_desk_is_a_blocking_gap_not_a_book_dump(monkeypatch):
    _rows_fixture(monkeypatch)
    intent = desk.analyze_operator_intent("get back into NOC?")
    ev = desk.gather_tradeai_evidence(intent)
    assert "reentry_symbol_cards" not in ev["available"]
    assert any(g.get("symbol") == "NOC" and g.get("field") == "row" for g in ev["blocking_gaps"]), ev["blocking_gaps"]


def test_full_desk_turn_answers_about_schg_with_a_sources_line(monkeypatch):
    _rows_fixture(monkeypatch)
    res = desk.handle_operator_desk_question("Is now a good time to get back into schg", chat_id="6993102664", message_id="1")
    assert res["kind"] == "answered"
    txt = res["text"]
    assert "SCHG — re-entry check" in txt and "Monitor / No Action" in txt
    assert "Sources: " in txt and "re-entry desk" in txt
    assert txt.rstrip().endswith("READ_ONLY_ADVISORY")


# ── 3. freeform answers read the house facts that exist ─────────────────────

SNAP = {
    "domains": {
        "portfolio": {"total_value": 1268140.59, "holdings_count": 30, "day_change_pct": None, "as_of": "2026-09-13T08:00:24-04:00"},
        "cash_buying_power": {"quality_state": "PARTIAL", "data": {
            "total_cash": 710933.07, "total_buying_power_estimate": 710933.07,
            "cash_positions": [{"symbol": "CASH", "market_value": 661748.21, "account": "schwab_rollover_ira"},
                               {"symbol": "CASH", "market_value": 42712.15, "account": "schwab_taxable"}],
            "source": "derived_from_holdings_NOT_verified_broker_buying_power", "as_of": "2026-09-13T08:00:24-04:00"}},
        "risk": {"portfolio_heat_pct": 0.08, "positions_at_risk": 0, "stops_active": 26},
        "sectors": {"state": "AVAILABLE", "total_value": 1268140.59, "sectors": [
            {"sector": "Industrials", "value": 85864.86, "weight_pct": 6.77, "position_count": 7, "symbols": ["NOC", "RTX", "SPCX", "BAH", "XLI", "XAR", "SPCX"]},
            {"sector": "Financial Services", "value": 48723.38, "weight_pct": 3.84, "position_count": 4, "symbols": ["PFLT", "CSWC"]}]},
        "investment_policy": {"status": "ACTIVE", "risk_level": "MODERATE_AGGRESSIVE", "max_drawdown_pct": 25.0,
                              "primary_objective": "Long-term growth with income generation — AI/technology sector tilt", "max_single_position_pct": 8},
        "holdings_detail": {"positions": []},
    }
}


def test_freeform_context_reads_cash_sectors_and_policy_from_the_snapshot(monkeypatch):
    import scripts.lib.data_broker.cio_portfolio as cp
    monkeypatch.setattr(cp, "get_cio_snapshot", lambda max_age_s=60: SNAP)
    monkeypatch.setattr(desk, "_thematic_research_status", lambda q: "Trade-AI holds no research on this topic yet. (dry-run)")
    intent = desk.analyze_operator_intent("How does the market normally perform in September and what sectors should I concentrate on")
    assert intent["intent"] == "freeform" and intent["symbols"] == []
    ev = desk.gather_tradeai_evidence(intent)
    facts = ev["available"]["freeform_context"]
    assert facts["cash"]["total_cash"] == 710933.07
    assert facts["cash"]["cash_pct"] == 56.1
    assert facts["cash"]["by_account"][0]["account"] == "schwab_rollover_ira"
    assert facts["sector_exposure"][0]["sector"] == "Industrials" and facts["sector_exposure"][0]["weight_pct"] == 6.77
    assert facts["investment_policy"]["risk_level"] == "MODERATE_AGGRESSIVE"
    assert facts["research_status"].startswith("Trade-AI holds no research on this topic yet")
    assert not any(g["domain"] == "cash_buying_power" for g in ev["gaps"]), "cash is present; no gap may claim otherwise"


def test_negative_control_the_old_cash_keys_were_never_in_the_payload():
    data = SNAP["domains"]["cash_buying_power"]["data"]
    assert "cash_pct" not in data and "buying_power" not in data, "the old builder read keys that do not exist"


def test_failsoft_freeform_reply_states_cash_sectors_policy_and_research_status(monkeypatch):
    import scripts.lib.data_broker.cio_portfolio as cp
    monkeypatch.setattr(cp, "get_cio_snapshot", lambda max_age_s=60: SNAP)
    monkeypatch.setattr(desk, "_thematic_research_status", lambda q: "Trade-AI holds no research on this topic yet. (dry-run)")
    monkeypatch.setenv("CIO_FREEFORM_FLASH", "0")
    intent = desk.analyze_operator_intent("what sectors should I concentrate on going into Q4")
    ev = desk.gather_tradeai_evidence(intent)
    out = desk._format_freeform_failsoft(ev["available"]["freeform_context"], ev["available"].get("soft_gaps") or [])
    assert "Industrials 6.77%" in out and "MODERATE_AGGRESSIVE" in out and "no research on this topic" in out


def test_flash_prompt_requires_labelling_general_knowledge_and_forbids_false_empty_claims():
    src = Path(desk.__file__).read_text(encoding="utf-8")
    a = src.index("def answer_freeform_with_flash("); b = src.index("\ndef ", a + 10)
    src = src[a:b]
    # the literal is split across two adjacent string constants in the source
    assert "General market history (model knowledge, not " in src and "Trade-AI data):'" in src
    assert "Never say a field is" in src and "empty when TRADE_AI_FACTS carries it" in src
    assert "research_status" in src


# ── sources footer ───────────────────────────────────────────────────────────


def test_sources_footer_names_stores_and_the_model_and_sits_above_the_authority_line():
    ev = {"sources": ["get_cio_snapshot", "/x/reentry_decision_desk_latest.json"],
          "available": {"freeform_context": {"cash": {"total_cash": 1}, "sector_exposure": [{}]}, "reentry_as_of": "2026-09-13T22:52:35"}}
    txt = desk._with_sources_footer("Some answer.\nREAD_ONLY_ADVISORY", ev, {"source": "deepseek_flash", "model": "deepseek-v4-flash"})
    lines = txt.splitlines()
    assert lines[-1] == "READ_ONLY_ADVISORY"
    assert lines[-2].startswith("Sources: ")
    assert "CIO snapshot (cash, sector_exposure)" in lines[-2]
    assert "re-entry desk · computed 2026-09-13 22:52" in lines[-2]
    assert "deepseek-v4-flash — general knowledge where labelled" in lines[-2]


def test_sources_footer_is_silent_when_there_is_nothing_to_cite():
    assert desk._with_sources_footer("hi", {"sources": [], "available": {}}, {"source": "x"}) == "hi"
