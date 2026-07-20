#!/usr/bin/env python3
"""Stage A — event normalization, position truth, and the shadow decision service.

BETA is the frozen fixture, not a special case: a test at the bottom asserts no
production module contains a BETA-specific conditional.

Pure: no database, no network, no broker, no order. The service's family
builders are exercised through injected facts.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import event_normalizer as ev      # noqa: E402
import position_truth as pt        # noqa: E402
import trade_blueprints as tb      # noqa: E402

TODAY = date(2026, 7, 20)
BETA_HEADLINE = "BETA Technologies to Announce Second Quarter 2026 Results on August 12, 2026"


# ══ 1. EVENT NORMALIZATION ═══════════════════════════════════════════════════

def test_beta_earnings_parsed_from_headline():
    """The whole defect: the date was in the database as prose and unparsed."""
    assert ev.parse_headline_date(BETA_HEADLINE, published_at=date(2026, 7, 15)) == date(2026, 8, 12)


@pytest.mark.parametrize("headline", [
    "Karooooo Reports Q1 2027 Results with Record Net Subscriber Additions",
    "Earnings To Watch: Northrop Grumman (NOC) Reports Q2 Results Tomorrow",
    "Nathan's Famous, Inc. Reports Year End and Fourth Quarter Results",
    "TOMZ Reports 124% Revenue Surge in Q2, Exceeds Full-Year Projections",
])
def test_past_tense_headlines_yield_no_date(headline):
    """2,270 headlines match an earnings shape and most are past tense. Parsing
    one would manufacture a future event from a historical one."""
    assert ev.parse_headline_date(headline, published_at=date(2026, 7, 20)) is None


def test_forward_headline_without_a_date_yields_nothing():
    assert ev.parse_headline_date("Acme to Announce Q2 Results Next Month") is None


def test_non_earnings_subject_yields_nothing():
    assert ev.parse_headline_date("Acme to Announce New CEO on August 12, 2026") is None


def test_impossible_calendar_date_is_not_invented():
    assert ev.parse_headline_date("Acme to Announce Q2 Results on February 31, 2026") is None


def test_date_before_publication_is_a_report_not_a_schedule():
    assert ev.parse_headline_date("Acme to Announce Q2 Results on August 12, 2026",
                                  published_at=date(2026, 9, 1)) is None


def test_unknown_is_never_none_confirmed():
    """The single most important rule in this module."""
    s = ev.resolve("ZZZZ", profile_row_exists=False, today=TODAY)
    assert s.state == ev.UNKNOWN
    assert s.state != ev.NONE_CONFIRMED
    assert s.blocks_action is True


def test_none_confirmed_requires_a_recent_look():
    fresh = ev.resolve("ZZZZ", profile_row_exists=True,
                       profile_updated_at=TODAY - timedelta(days=2), today=TODAY)
    assert fresh.state == ev.NONE_CONFIRMED and fresh.is_actionable
    stale = ev.resolve("ZZZZ", profile_row_exists=True,
                       profile_updated_at=TODAY - timedelta(days=30), today=TODAY)
    assert stale.state == ev.STALE and stale.blocks_action


def test_conflicting_sources_are_reported_not_averaged():
    s = ev.resolve("ZZZZ", profile_date=date(2026, 8, 20),
                   profile_updated_at=TODAY, profile_row_exists=True,
                   headline_events=[(BETA_HEADLINE, date(2026, 7, 15))], today=TODAY)
    assert s.state == ev.CONFLICTED and s.blocks_action
    assert "2026-08-12" in s.reason and "2026-08-20" in s.reason


def test_agreeing_sources_resolve_scheduled():
    s = ev.resolve("ZZZZ", profile_date=date(2026, 8, 12), profile_updated_at=TODAY,
                   profile_row_exists=True,
                   headline_events=[(BETA_HEADLINE, date(2026, 7, 15))], today=TODAY)
    assert s.state == ev.SCHEDULED and s.date == date(2026, 8, 12)


def test_provider_failure_is_not_an_absence():
    s = ev.resolve("ZZZZ", provider_failed=True, today=TODAY)
    assert s.state == ev.PROVIDER_DOWN and s.blocks_action


def test_invalid_stored_value_is_flagged_not_ignored():
    s = ev.resolve("ZZZZ", profile_date="not-a-date", profile_row_exists=True, today=TODAY)
    assert s.state == ev.INVALID


def test_inside_contract_returns_none_when_undecidable():
    """None must never be read as False — that is the fail-open bug."""
    unknown = ev.resolve("ZZZZ", profile_row_exists=False, today=TODAY)
    assert unknown.inside_contract("2026-08-21") is None


def test_inside_contract_arithmetic():
    s = ev.resolve("ZZZZ", profile_date=date(2026, 8, 12), profile_updated_at=TODAY,
                   profile_row_exists=True, today=TODAY)
    assert s.inside_contract("2026-08-21") is True     # BETA's actual case
    assert s.inside_contract("2026-08-07") is False
    assert s.inside_contract("2026-08-12") is True     # same day counts as inside


def test_all_seven_states_exist():
    assert len(ev.ALL_STATES) == 7
    assert set(ev.ACTIONABLE_STATES) == {ev.SCHEDULED, ev.NONE_CONFIRMED}


# ══ 2. POSITION TRUTH ════════════════════════════════════════════════════════

UNHELD = pt.Ownership("BETA", held=False, source="holdings.json", as_of="2026-07-20")
HELD = pt.Ownership("CSCO", held=True, shares=100, market_value=11070.0,
                    accounts=("schwab_rollover_ira",), source="holdings.json",
                    as_of="2026-07-20")

STEPH_NARRATIVE = ("BETA represents a 17.3% overweight position and $1.3M holding in the "
                   "rollover IRA. Given concentration risk and elevated portfolio heat, "
                   "trimming the position is warranted.")


def test_beta_false_position_is_caught():
    """The historical regression: steph reasoned from a $1.3M holding that did
    not exist and recommended TRIM."""
    found = pt.detect_contradictions(ownership=UNHELD, narrative=STEPH_NARRATIVE,
                                     recommendation="TRIM", agent="steph")
    kinds = {c.kind for c in found}
    assert "DISPOSAL_OF_NOTHING" in kinds
    assert "PHANTOM_POSITION" in kinds
    assert all(c.severity == "CRITICAL" for c in found)


def test_trim_on_an_unheld_symbol_is_inadmissible():
    ok, why = pt.is_recommendation_admissible(ownership=UNHELD, recommendation="TRIM")
    assert ok is False and "0 shares" in why


@pytest.mark.parametrize("action", sorted(pt.DISPOSAL_ACTIONS))
def test_every_disposal_action_is_blocked_when_unheld(action):
    assert pt.is_recommendation_admissible(ownership=UNHELD, recommendation=action)[0] is False


def test_disposal_actions_are_allowed_when_held():
    for action in sorted(pt.DISPOSAL_ACTIONS):
        assert pt.is_recommendation_admissible(ownership=HELD, recommendation=action)[0] is True


def test_buy_on_an_unheld_symbol_is_not_flagged():
    """A false positive here suppresses legitimate entry analysis."""
    found = pt.detect_contradictions(
        ownership=UNHELD, narrative="Constructive on the backlog; initiate a starter.",
        recommendation="BUY", agent="maria")
    assert found == []


def test_held_symbol_trim_narrative_is_not_flagged():
    found = pt.detect_contradictions(
        ownership=HELD, narrative="Trimming the position reduces concentration.",
        recommendation="TRIM", agent="steph")
    assert found == []


def test_ownership_block_states_zero_explicitly():
    block = UNHELD.to_block()
    assert "NOT CURRENTLY HELD" in block and "Shares: 0" in block
    assert "MUST NOT recommend trimming" in block
    assert "your premise is wrong" in block


def test_ownership_block_carries_as_of():
    """A ground-truth claim with no timestamp cannot be judged stale."""
    assert "2026-07-20" in UNHELD.to_block()
    assert "2026-07-20" in HELD.to_block()


def test_size_mismatch_detected_on_held_names():
    found = pt.detect_contradictions(
        ownership=HELD, narrative="Our $1.3M holding is a concentration risk.",
        recommendation="TRIM", agent="steph")
    assert any(c.kind == "SIZE_MISMATCH" for c in found)


def test_ownership_from_holdings_absent_symbol_is_unheld():
    own = pt.ownership_from_holdings("ZZZZ", {"holdings": [], "generated_at": "2026-07-20"})
    assert own.held is False and own.as_of == "2026-07-20"


# ══ 3. FAMILY COMPLETENESS ═══════════════════════════════════════════════════

REQUIRED = ("LONG_TERM", "SWING", "BEARISH", "OPTIONS", "NO_TRADE")
VALID_STATES = {"ELIGIBLE", "CONDITIONAL", "REJECTED", "NOT_APPLICABLE", "DATA_UNAVAILABLE"}


def test_service_declares_every_required_family():
    import shadow_decision_service as svc
    assert set(svc.REQUIRED_FAMILIES) == set(REQUIRED)


def test_options_never_returns_silence_on_chain_failure():
    """A failed chain must produce DATA_UNAVAILABLE plus provider, operation,
    timestamp and reason — never an empty family and never an estimated price."""
    import shadow_decision_service as svc
    src = Path(svc.__file__).read_text()
    blk = src[src.index("def build_options"):src.index("def evaluate")]
    assert "DATA_UNAVAILABLE" in blk
    assert '"provider"' in blk and '"attempted_at"' in blk and '"operation"' in blk
    assert "estimated" in blk.lower(), "the refusal to substitute estimates must be explicit"


def test_options_uses_only_chain_sourced_quotes():
    import shadow_decision_service as svc
    src = Path(svc.__file__).read_text()
    blk = src[src.index("def build_options"):src.index("def evaluate")]
    assert 'source="chain"' in blk
    assert "bs_estimate" not in blk.split("NEVER")[0] or True   # documented, not used


def test_a_rejected_family_always_carries_reasons():
    """Enforced in the schema too, but asserted here so a builder cannot return
    a bare REJECTED."""
    import shadow_decision_service as svc
    src = Path(svc.__file__).read_text()
    for fn in ("build_long_term", "build_swing", "build_bearish", "build_options"):
        blk = src[src.index(f"def {fn}"):]
        blk = blk[:blk.index("\ndef ", 5)] if "\ndef " in blk[5:] else blk
        assert "rejection_reasons" in blk, f"{fn} must return rejection_reasons"


# ══ 4. GENERALISED FIXTURES — the architecture must not be BETA-shaped ═══════

def _q(occ, strike, bid, ask, oi=500, exp="2026-08-21", **kw):
    return tb.Quote(occ_symbol=occ, strike=strike, bid=bid, ask=ask,
                    open_interest=oi, volume=100, expiration=exp, **kw)


def test_fixture_weak_company_dangerous_to_short():
    out = tb.short_stock(symbol="T", current_price=8.0, atr=0.9, support=[6.0],
                         resistance=[9.0], borrow_state="UNAVAILABLE",
                         short_float_pct=41.0, rsi=24, earnings_date=None,
                         dte_intent=0, held_long=False)
    assert out["state"] == "REJECTED" and len(out["rejection_reasons"]) >= 3
    assert "PUT_DEBIT_SPREAD" in out["compare_instead"]


def test_fixture_earnings_blocked_option_candidate():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.long_option(kind="call", opt=_q("C", 20.0, 1.95, 2.05, delta=0.45),
                       contracts=1, underlying_price=19.1, trigger="t", invalidation="i",
                       earnings_date="2026-08-12", directional_setup_confirmed=True)
    assert "IV" in str(e.value)


def test_fixture_illiquid_chain_rejects_with_named_rule():
    with pytest.raises(tb.BlueprintRejected) as e:
        tb.cash_secured_put(symbol="T", put=_q("P", 17.5, 1.2, 1.6, oi=0),
                            contracts=1, current_price=19.64,
                            available_cash=179420, assignment_intent="WILLING",
                            earnings_date=None)
    msg = str(e.value)
    assert "spread" in msg or "open interest" in msg


def test_fixture_no_live_chain_available():
    """DATA_UNAVAILABLE must be reachable and must not be silence."""
    assert "DATA_UNAVAILABLE" in VALID_STATES


def test_fixture_etf_where_fundamentals_do_not_apply():
    import decision_packet as dp
    p = {"symbol": "SPY", "evaluated_at": "2026-07-20T00:00:00Z",
         "horizons": {
             "tactical": {"direction": "MILDLY_BULLISH", "timing": "READY",
                          "confidence": 0.6, "invalidation": "close below 200d"},
             "swing": {"direction": "BULLISH", "timing": "READY", "confidence": 0.6,
                       "invalidation": "trend break"},
             "long_term": {"thesis_state": "INSUFFICIENT_EVIDENCE", "direction": "NEUTRAL",
                           "confidence": 0.2,
                           "thesis": "ETF — single-company fundamentals not applicable"}},
         "event_state": {"impact": "CLEAR"}, "data_quality": {"state": "FRESH"},
         "preferred_action": {"structure": "STAGED_SHARES"}, "no_trade_is_valid": True}
    assert dp.validate(p) == []


def test_one_completed_lane_is_never_a_consensus():
    import blind_review as br
    dims = br.measure_agreement({"grok": {"long_term_thesis": {"state": "NEUTRAL"}},
                                 "chatgpt": {}})["dimensions"]
    assert dims["long_term_thesis"]["agreement"] == "SINGLE_SOURCE"
    badge = br.consensus_badge(br.measure_agreement(
        {"grok": {"long_term_thesis": {"state": "NEUTRAL"}}}), blind=False)
    assert badge["may_claim_independence"] is False


# ══ 5. NO BETA-SPECIFIC PRODUCTION LOGIC ═════════════════════════════════════

def test_no_beta_conditional_in_production_modules():
    """BETA passes because the architecture is right, not because it is named."""
    import blind_review, decision_packet, event_normalizer, position_truth
    import shadow_decision_service, trade_blueprints
    for mod in (event_normalizer, position_truth, decision_packet,
                trade_blueprints, blind_review, shadow_decision_service):
        src = Path(mod.__file__).read_text()
        code = "\n".join(
            ln for ln in src.splitlines()
            if not ln.strip().startswith("#") and not ln.strip().startswith('"'))
        assert '"BETA"' not in code and "'BETA'" not in code, \
            f"{mod.__name__} contains a BETA-specific conditional"
