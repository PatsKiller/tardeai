#!/usr/bin/env python3
"""The multidimensional decision packet, its blind-review path, and the BETA fixture.

BETA is a FIXTURE, not a special case. Nothing in the code under test names it,
and these tests would pass identically for any symbol with the same shape:
a credible long-term thesis, an extended tape, a scheduled event, and a stale
packet. Fixtures 2-6 exist to prove the architecture generalises rather than
having been fitted to one ticker that happened to go up.

Pure: no network, no database, no broker, no order.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import blind_review as br  # noqa: E402
import decision_packet as dp  # noqa: E402
import trade_blueprints as tb  # noqa: E402


# ── Dimensional independence ──────────────────────────────────────────────────

def _packet(**over):
    base = {
        "symbol": "TEST", "evaluated_at": "2026-07-20T13:16:30Z",
        "horizons": {
            "tactical": {"direction": "MILDLY_BULLISH", "timing": "WAIT_FOR_PULLBACK",
                         "confidence": 0.55, "trigger": "pullback into 17.5-18.5",
                         "invalidation": "close below 15.15"},
            "swing": {"direction": "BULLISH", "timing": "BREAKOUT_CONFIRMATION",
                      "confidence": 0.5, "trigger": "close above 19.75 then retest",
                      "invalidation": "close below 17.00"},
            "long_term": {"thesis_state": "SPECULATIVE_CONSTRUCTIVE", "direction": "BULLISH",
                          "confidence": 0.6, "thesis": "backlog + cash runway",
                          "invalidation": "backlog cancellations or failed certification"},
        },
        "event_state": {"impact": "CAUTION", "earnings": {"date": "2026-08-12"}},
        "data_quality": {"state": "FRESH", "fields": []},
        "preferred_action": {"structure": "STAGED_SHARES"},
        "no_trade_is_valid": True,
    }
    base.update(over)
    return base


def test_a_good_company_can_be_a_bad_entry():
    """The single sentence this whole architecture exists to make expressible."""
    p = _packet()
    assert p["horizons"]["long_term"]["thesis_state"] == "SPECULATIVE_CONSTRUCTIVE"
    assert p["horizons"]["tactical"]["timing"] == "WAIT_FOR_PULLBACK"
    assert dp.validate(p) == []


def test_headline_is_composed_never_one_word():
    head = dp.compose_headline(_packet())
    assert "·" in head, "headline must carry multiple dimensions"
    assert head.upper() not in dp.RETIRED_LABELS
    assert "wait for pullback" in head.lower()
    assert "2026-08-12" in head, "a scheduled event belongs in the headline"


def test_all_three_horizons_required():
    p = _packet()
    del p["horizons"]["swing"]
    assert any("swing" in e for e in dp.validate(p))


def test_directional_view_requires_invalidation():
    """An unfalsifiable call can never be learned from."""
    p = _packet()
    p["horizons"]["tactical"]["invalidation"] = ""
    assert any("invalidation" in e for e in dp.validate(p))


def test_wait_state_requires_a_concrete_trigger():
    p = _packet()
    p["horizons"]["tactical"]["trigger"] = ""
    assert any("trigger" in e for e in dp.validate(p))


# ── Retiring IGNORE / AVOID ───────────────────────────────────────────────────

@pytest.mark.parametrize("label", ["IGNORE", "AVOID", "ignore", " avoid "])
def test_retired_labels_refused(label):
    with pytest.raises(dp.DecisionPacketError) as e:
        dp.assert_not_retired(label)
    assert "retired" in str(e.value).lower()


def test_no_action_reasons_are_specific():
    assert "POOR_LONG_TERM_THESIS" in dp.NO_ACTION_REASONS
    assert "TACTICALLY_EXTENDED" in dp.NO_ACTION_REASONS
    # The two must be distinguishable — collapsing them is the BETA defect.
    assert len(set(dp.NO_ACTION_REASONS)) == len(dp.NO_ACTION_REASONS)


# ── Stale data may not masquerade as a current conclusion ─────────────────────

def test_stale_packet_cannot_present_an_actionable_verdict():
    p = _packet(data_quality={"state": "STALE", "fields": ["technicals 2.9d old"]})
    errs = dp.validate(p)
    assert any("prior_thesis_label" in e for e in errs)


def test_stale_packet_is_fine_when_labelled_as_prior():
    p = _packet(data_quality={"state": "STALE", "fields": []},
                preferred_action={"structure": "STAGED_SHARES",
                                  "prior_thesis_label": dp.PRIOR_THESIS_LABEL})
    assert dp.validate(p) == []


def test_unknown_event_fails_closed():
    ok, why = dp.is_actionable(_packet(event_state={"impact": "UNKNOWN"}))
    assert not ok and "EVENT_BLOCKED" in why


# ── Provenance: a model may not author arithmetic ─────────────────────────────

def test_model_authored_payoff_is_refused():
    errs = dp.validate(_packet(), provenance={"maximum_loss": "model"})
    assert any("deterministic-only" in e for e in errs)


def test_model_authored_narrative_is_fine():
    assert dp.validate(_packet(), provenance={"thesis": "model", "maximum_loss": "deterministic"}) == []


# ── Vague language ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "consider calls", "consider a spread", "wait for breakout",
    "hedge the position", "sell premium", "buy on weakness",
])
def test_vague_language_without_mechanics_is_refused(phrase):
    with pytest.raises(dp.DecisionPacketError):
        dp.assert_no_vague_language(f"We should {phrase} here.", has_blueprint=False)


def test_same_phrase_is_fine_with_a_blueprint():
    dp.assert_no_vague_language("Consider a spread — see blueprint.", has_blueprint=True)


# ── Blind review ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("poison", [
    {"recommendation": "IGNORE"},
    {"verdict": "AVOID"},
    {"confidence": 0.45},
    {"committee_verdict": "HOLD"},
    {"nested": {"cio_verdict": "SELL"}},
    {"list": [{"prior_verdict": "BUY"}]},
])
def test_blind_pass_refuses_any_anchor(poison):
    with pytest.raises(br.BlindnessViolation):
        br.assert_blind({"symbol": "TEST", "price": {"last": 19.10}, **poison})


def test_clean_facts_packet_passes():
    br.assert_blind({"symbol": "TEST", "price": {"last": 19.10},
                     "technicals": {"rsi": 60.29}, "events": {"earnings": "2026-08-12"}})


def test_blind_prompt_contains_no_verdict_vocabulary():
    prompt = br.build_blind_prompt({"symbol": "TEST", "price": {"last": 19.1}})
    # The old prompt's grammar made an independent view unsayable.
    for token in ("AGREE", "DISAGREE", "the local model", "second opinion"):
        assert token not in prompt, f"blind prompt leaked reviewer framing: {token!r}"
    assert "SEPARATELY" in prompt


def test_anchored_badge_must_disclose_itself():
    agree = br.measure_agreement({"grok": {"long_term_thesis": {"state": "CONSTRUCTIVE"}},
                                  "chatgpt": {"long_term_thesis": {"state": "CONSTRUCTIVE"}}})
    badge = br.consensus_badge(agree, blind=False)
    assert badge["may_claim_independence"] is False
    assert "anchor" in badge["caveat"].lower()


def test_agreement_is_measured_per_dimension():
    """Agreeing on the company while splitting on timing is the NORMAL case, and
    one badge cannot carry it."""
    outs = {
        "grok": {"long_term_thesis": {"state": "CONSTRUCTIVE"},
                 "tactical_timing": {"state": "WAIT_FOR_PULLBACK"}},
        "chatgpt": {"long_term_thesis": {"state": "CONSTRUCTIVE"},
                    "tactical_timing": {"state": "READY"}},
        "committee": {"long_term_thesis": {"state": "CONSTRUCTIVE"},
                      "tactical_timing": {"state": "EXTENDED"}},
    }
    dims = br.measure_agreement(outs)["dimensions"]
    assert dims["long_term_thesis"]["agreement"] == "UNANIMOUS"
    assert dims["long_term_thesis"]["display"] == "3/3"
    assert dims["tactical_timing"]["agreement"] == "SPLIT"
    assert dims["tactical_timing"]["display"] == "1/3"


def test_single_lane_is_not_a_consensus():
    """BETA's stored row said consensus=IGNORE with chatgpt=null. One model is
    not a consensus, and the badge must not imply otherwise."""
    dims = br.measure_agreement({"grok": {"long_term_thesis": {"state": "NEUTRAL"}},
                                 "chatgpt": {}})["dimensions"]
    assert dims["long_term_thesis"]["agreement"] == "SINGLE_SOURCE"
    assert dims["long_term_thesis"]["display"] == "1/1"


# ── Trade construction ────────────────────────────────────────────────────────

def _q(occ, strike, bid, ask, **kw):
    kw.setdefault("open_interest", 500)
    kw.setdefault("volume", 100)
    kw.setdefault("expiration", "2026-08-21")
    return tb.Quote(occ_symbol=occ, strike=strike, bid=bid, ask=ask, **kw)


def test_staged_shares_produces_real_levels_not_prose():
    bp = tb.staged_shares(symbol="TEST", current_price=19.10, atr=1.11,
                          support=[15.15, 13.43], resistance=[19.75],
                          thesis_state="SPECULATIVE_CONSTRUCTIVE", timing="EXTENDED",
                          account_equity=1_200_000, earnings_date="2026-08-12")
    assert bp["state"] == "ELIGIBLE"
    assert bp["starter_entry"]["allocation_pct"] == 25.0, "extended tape gets a small starter"
    assert bp["event_reserve"]["allocation_pct"] == 25.0
    assert bp["stop_or_invalidation"]["price"] < 15.15
    total = (bp["starter_entry"]["allocation_pct"]
             + sum(a["allocation_pct"] for a in bp["add_entries"])
             + bp["event_reserve"]["allocation_pct"])
    assert total == pytest.approx(100.0), "allocations must account for the whole position"
    assert any(a.get("retest_required") for a in bp["add_entries"])


def test_staged_shares_refuses_without_support():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.staged_shares(symbol="TEST", current_price=19.1, atr=1.11, support=[],
                         resistance=[19.75], thesis_state="CONSTRUCTIVE", timing="READY",
                         account_equity=1_000_000)
    assert "support" in str(e.value)


def test_call_spread_arithmetic_is_exact():
    bp = tb.call_debit_spread(
        long_leg=_q("TEST260821C00020000", 20.0, 1.95, 2.05, delta=0.45),
        short_leg=_q("TEST260821C00023000", 23.0, 0.95, 1.05, delta=0.28),
        contracts=2, underlying_price=19.10,
        trigger="close above 19.75 then retest", invalidation="close below 17.00",
        earnings_date="2026-08-12")
    assert bp["net_debit_mid"] == pytest.approx(1.0)
    assert bp["width"] == 3.0
    assert bp["maximum_loss"] == pytest.approx(200.0)     # 1.00 * 2 * 100
    assert bp["maximum_profit"] == pytest.approx(400.0)   # (3-1) * 2 * 100
    assert bp["breakeven"] == pytest.approx(21.0)         # 20 + 1
    assert bp["earnings_inside_contract"] is True


def test_spread_costing_more_than_its_width_is_refused():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.call_debit_spread(
            long_leg=_q("A", 20.0, 3.90, 4.10), short_leg=_q("B", 23.0, 0.45, 0.55),
            contracts=1, underlying_price=19.1, trigger="t", invalidation="i",
            earnings_date=None)
    assert "no profit is possible" in str(e.value)


def test_illiquid_legs_are_refused_with_named_reasons():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.call_debit_spread(
            long_leg=_q("A", 20.0, 1.50, 2.50, open_interest=3),
            short_leg=_q("B", 23.0, 0.90, 1.10),
            contracts=1, underlying_price=19.1, trigger="t", invalidation="i",
            earnings_date=None)
    msg = str(e.value)
    assert "spread" in msg and "open interest" in msg


def test_estimated_quotes_cannot_build_a_blueprint():
    """bs_estimate_only blocks at the gate; it must also block at construction,
    or the card renders numbers the gate will later refuse."""
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.long_option(kind="call", opt=_q("A", 20.0, 1.0, 1.1, source="bs_estimate"),
                       contracts=1, underlying_price=19.1, trigger="t", invalidation="i",
                       earnings_date=None, directional_setup_confirmed=True)
    assert "not a live chain" in str(e.value)


def test_csp_requires_willingness_to_own():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.cash_secured_put(symbol="TEST", put=_q("P", 15.0, 0.95, 1.05, delta=-0.25),
                            contracts=1, current_price=19.10, available_cash=50_000,
                            assignment_intent="UNWILLING", earnings_date="2026-08-12")
    assert "willingly own" in str(e.value)


def test_csp_shows_effective_price_and_gap_scenarios():
    bp = tb.cash_secured_put(symbol="TEST", put=_q("P", 15.0, 0.95, 1.05, delta=-0.25),
                             contracts=1, current_price=19.10, available_cash=50_000,
                             assignment_intent="WILLING", earnings_date="2026-08-12")
    assert bp["effective_acquisition_price"] == pytest.approx(14.0)
    assert bp["cash_required"] == pytest.approx(1500.0)
    assert bp["earnings_inside_contract"] is True
    assert "EARNINGS ASSIGNMENT RISK" in bp["management_plan"]
    worst = [g for g in bp["negative_gap_scenarios"] if g["gap_pct"] == -30][0]
    assert worst["assigned"] is True and worst["unrealised_total"] < 0


def test_csp_without_enough_cash_is_refused():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.cash_secured_put(symbol="TEST", put=_q("P", 15.0, 0.95, 1.05),
                            contracts=10, current_price=19.10, available_cash=500,
                            assignment_intent="WILLING", earnings_date=None)
    assert "cash" in str(e.value)


def test_long_call_into_earnings_is_refused():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.long_option(kind="call", opt=_q("C", 20.0, 1.95, 2.05, delta=0.45),
                       contracts=1, underlying_price=19.10,
                       trigger="t", invalidation="i", earnings_date="2026-08-12",
                       directional_setup_confirmed=True)
    assert "IV" in str(e.value)


def test_unknown_earnings_blocks_long_option():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.long_option(kind="call", opt=_q("C", 20.0, 1.95, 2.05),
                       contracts=1, underlying_price=19.1, trigger="t", invalidation="i",
                       earnings_date=None, directional_setup_confirmed=True)
    assert "unknown" in str(e.value).lower()


def test_buying_puts_is_not_a_bullish_entry():
    """The operator asked for 'puts or options to buy it'. The instrument does
    the opposite of what was asked, so the system must explain rather than fill
    the order shape."""
    out = tb.puts_are_not_a_bullish_entry("TEST")
    assert out["state"] == "NOT_APPLICABLE"
    assert any("BEARISH" in r for r in out["rejection_reasons"])
    alts = [a["structure"] for a in out["what_you_probably_want"]]
    assert "CASH_SECURED_PUT" in alts and "STAGED_SHARES" in alts


def test_weak_thesis_alone_does_not_justify_buying_puts():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.long_option(kind="put", opt=_q("P", 18.0, 1.95, 2.05, delta=-0.45),
                       contracts=1, underlying_price=19.1, trigger="t", invalidation="i",
                       earnings_date=None, directional_setup_confirmed=False)
    assert "not a bearish entry signal" in str(e.value)


# ── Bearish suitability is not the inverse of a weak thesis ───────────────────

def test_short_rejected_on_squeeze_risk_suggests_defined_risk_instead():
    out = tb.short_stock(symbol="TEST", current_price=19.1, atr=1.11,
                         support=[15.15], resistance=[19.75],
                         borrow_state="AVAILABLE", short_float_pct=34.0, rsi=55,
                         earnings_date=None, dte_intent=0, held_long=False)
    assert out["state"] == "REJECTED"
    assert any("squeeze" in r for r in out["rejection_reasons"])
    assert "PUT_DEBIT_SPREAD" in out["compare_instead"]


def test_short_rejected_when_borrow_unknown():
    out = tb.short_stock(symbol="TEST", current_price=19.1, atr=1.11, support=[15.15],
                         resistance=[19.75], borrow_state="UNKNOWN", short_float_pct=5.0,
                         rsi=55, earnings_date=None, dte_intent=0, held_long=False)
    assert out["state"] == "REJECTED"
    assert any("borrow" in r for r in out["rejection_reasons"])


def test_short_rejected_when_already_oversold():
    out = tb.short_stock(symbol="TEST", current_price=19.1, atr=1.11, support=[15.15],
                         resistance=[19.75], borrow_state="AVAILABLE", short_float_pct=5.0,
                         rsi=22, earnings_date=None, dte_intent=0, held_long=False)
    assert any("oversold" in r for r in out["rejection_reasons"])


def test_short_rejected_when_held_long():
    out = tb.short_stock(symbol="TEST", current_price=19.1, atr=1.11, support=[15.15],
                         resistance=[19.75], borrow_state="AVAILABLE", short_float_pct=5.0,
                         rsi=55, earnings_date=None, dte_intent=0, held_long=True)
    assert any("held long" in r for r in out["rejection_reasons"])


# ── Structure bookkeeping ─────────────────────────────────────────────────────

def test_rejected_structure_must_carry_reasons():
    p = _packet(bullish_structures=[{"structure": "LONG_CALL", "state": "REJECTED",
                                     "rejection_reasons": []}])
    assert any("without rejection_reasons" in e for e in dp.validate(p))


def test_conditional_structure_must_carry_a_trigger():
    p = _packet(bullish_structures=[{"structure": "CALL_DEBIT_SPREAD", "state": "CONDITIONAL",
                                     "activation_trigger": {}}])
    assert any("without activation_trigger" in e for e in dp.validate(p))


def test_research_only_structures_cannot_be_eligible():
    p = _packet(bullish_structures=[{"structure": "DIAGONAL_CALL", "state": "ELIGIBLE"}])
    assert any("research-only" in e for e in dp.validate(p))


def test_no_trade_must_always_be_expressible():
    p = _packet()
    del p["no_trade_is_valid"]
    assert any("no_trade_is_valid" in e for e in dp.validate(p))


def test_comparison_matrix_prefers_defined_risk():
    shares = tb.staged_shares(symbol="T", current_price=19.1, atr=1.11, support=[15.15],
                              resistance=[19.75], thesis_state="CONSTRUCTIVE",
                              timing="EXTENDED", account_equity=100_000)
    spread = tb.call_debit_spread(
        long_leg=_q("A", 20.0, 1.95, 2.05), short_leg=_q("B", 23.0, 0.95, 1.05),
        contracts=1, underlying_price=19.1, trigger="t", invalidation="i",
        earnings_date=None)
    m = tb.comparison_matrix(symbol="T", directional_view={"tactical": "MILDLY_BULLISH"},
                             structures=[shares, spread])
    assert m["preferred_structure"] == "CALL_DEBIT_SPREAD"  # $100 max loss beats the share block
    assert m["runner_up"] == "STAGED_SHARES"
    assert m["no_trade_is_valid"] is True


# ══ GENERALISED FIXTURES — the architecture must not be BETA-shaped ═══════════

def test_fixture_1_strong_thesis_extended_tape():
    """BETA's shape. Constructive company, extended tape, event ahead."""
    p = _packet()
    assert dp.validate(p) == []
    assert dp.compose_headline(p).upper() not in dp.RETIRED_LABELS


def test_fixture_2_weak_thesis_strong_momentum():
    """A bad company can be a good TRADE. The label must not forbid the trade."""
    p = _packet(horizons={
        "tactical": {"direction": "BULLISH", "timing": "BREAKOUT_CONFIRMATION",
                     "confidence": 0.7, "trigger": "held breakout on 3x volume",
                     "invalidation": "loss of breakout level"},
        "swing": {"direction": "NEUTRAL", "timing": "RANGE_BOUND", "confidence": 0.4,
                  "invalidation": "range break either side"},
        "long_term": {"thesis_state": "FUNDAMENTALLY_UNATTRACTIVE", "direction": "BEARISH",
                      "confidence": 0.7, "thesis": "cash burn, dilution",
                      "invalidation": "sustained FCF"},
    })
    assert dp.validate(p) == []
    assert p["horizons"]["tactical"]["direction"] == "BULLISH"
    assert p["horizons"]["long_term"]["thesis_state"] == "FUNDAMENTALLY_UNATTRACTIVE"


def test_fixture_3_strong_company_short_term_breakdown():
    p = _packet(horizons={
        "tactical": {"direction": "BEARISH", "timing": "NO_VALID_SETUP", "confidence": 0.6,
                     "invalidation": "reclaim of the 50-day"},
        "swing": {"direction": "MILDLY_BEARISH", "timing": "REVERSAL_WATCH", "confidence": 0.5,
                  "invalidation": "higher low"},
        "long_term": {"thesis_state": "STRONG_CONVICTION", "direction": "BULLISH",
                      "confidence": 0.85, "thesis": "durable moat",
                      "invalidation": "share loss to a structural competitor"},
    })
    assert dp.validate(p) == []


def test_fixture_4_bad_company_dangerous_to_short():
    out = tb.short_stock(symbol="T", current_price=8.0, atr=0.9, support=[6.0],
                         resistance=[9.0], borrow_state="UNAVAILABLE", short_float_pct=41.0,
                         rsi=24, earnings_date=None, dte_intent=0, held_long=False)
    assert out["state"] == "REJECTED"
    assert len(out["rejection_reasons"]) >= 3  # borrow, squeeze AND oversold


def test_fixture_5_range_bound_income_candidate():
    p = _packet(horizons={
        "tactical": {"direction": "NEUTRAL", "timing": "RANGE_BOUND", "confidence": 0.6},
        "swing": {"direction": "NEUTRAL", "timing": "RANGE_BOUND", "confidence": 0.6},
        "long_term": {"thesis_state": "NEUTRAL", "direction": "NEUTRAL", "confidence": 0.5,
                      "thesis": "fairly valued"},
    }, event_state={"impact": "CLEAR"},
       preferred_action={"structure": "CASH_SECURED_PUT"})
    assert dp.validate(p) == []
    ok, _ = dp.is_actionable(p)
    assert ok


def test_fixture_6_etf_where_stock_fundamentals_do_not_apply():
    p = _packet(horizons={
        "tactical": {"direction": "MILDLY_BULLISH", "timing": "READY", "confidence": 0.6,
                     "invalidation": "close below the 200-day"},
        "swing": {"direction": "BULLISH", "timing": "READY", "confidence": 0.6,
                  "invalidation": "trend break"},
        "long_term": {"thesis_state": "INSUFFICIENT_EVIDENCE", "direction": "NEUTRAL",
                      "confidence": 0.2,
                      "thesis": "ETF — single-company fundamentals are not applicable"},
    })
    assert dp.validate(p) == []


def test_no_fixture_is_symbol_specific():
    """The guarantee that BETA passes because the architecture is right, not
    because anything special-cases it."""
    for mod in (dp, tb, br):
        src = Path(mod.__file__).read_text()
        assert '"BETA"' not in src and "'BETA'" not in src, \
            f"{mod.__name__} contains a BETA-specific conditional"
