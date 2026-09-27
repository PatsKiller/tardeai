"""Options fill truth (operator work order 2026-09-27).

The desk advertised credit spreads at the leg-midpoint credit (DELL $8.10, ETON $0.89) while
selling at the displayed bid and buying at the displayed ask gave $6.35 and a $2.00 DEBIT; the
payoff, breakeven and expected P/L were all priced from that midpoint. Protective puts showed the
put's own max loss / breakeven on a card presented as insurance for held stock. Combined exposure
counted an ARCHIVED idea. "POSITIVE" sat beside BLOCKED and "fully researched" beside 0 runs.
Hermetic: no network, no psycopg2."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import options_economics as oe  # noqa: E402
from scripts.lib.options_exposure import combined_exposure, leg_liquidity  # noqa: E402

DELL_SHORT = {"strike": 522.5, "exp": "2026-11-20", "bid": 31.75, "ask": 34.05, "mid": 32.9, "oi": 366, "volume": 168,
              "quote_time": "2026-09-25T20:00:00+00:00", "dte": 54}
DELL_LONG = {"strike": 497.5, "exp": "2026-11-20", "bid": 24.2, "ask": 25.4, "mid": 24.8, "oi": 666, "volume": 127,
             "quote_time": "2026-09-25T20:00:00+00:00", "dte": 54}
ETON_SHORT = {"strike": 52.5, "exp": "2026-10-16", "bid": 0.95, "ask": 3.9, "mid": 2.42, "oi": 0, "volume": 2}
ETON_LONG = {"strike": 50.0, "exp": "2026-10-16", "bid": 0.1, "ask": 2.95, "mid": 1.53, "oi": 0, "volume": 0}


def test_spread_credit_is_priced_from_an_explicit_fill_assumption():
    q = oe.spread_quote(DELL_SHORT, DELL_LONG, session="WEEKEND")
    assert q["mid_credit"] == 8.1 and q["executable_credit"] == 6.35 and q["credit_haircut"] == 1.75
    assert q["credit_basis"] == "executable" and q["is_credit"] is True
    assert q["quotes_as_of"] == "2026-09-25T20:00:00+00:00" and q["market_session"] == "WEEKEND"
    assert [leg["role"] for leg in q["legs"]] == ["short put", "long put"]
    assert "bid" in q["fill_assumption"] and "ask" in q["fill_assumption"]


def test_eton_crossing_the_displayed_quotes_is_a_debit_not_a_credit():
    q = oe.spread_quote(ETON_SHORT, ETON_LONG)
    assert q["mid_credit"] == 0.89 and q["executable_credit"] == -2.0 and q["is_credit"] is False


def test_spread_payoff_uses_the_executable_credit_and_labels_the_midpoint():
    p = {"strategy": "credit_spread", "short_strike": 522.5, "long_strike": 497.5, "strike": 522.5,
         "premium": 6.35, "net_credit": 6.35, "executable_credit": 6.35, "mid_credit": 8.1,
         "credit_basis": "executable", "underlying_price": 563.0, "dte": 54, "iv_used": 0.45, "contracts": 1}
    e = oe.economics(p, session="WEEKEND")
    assert (e["credit_total"], e["max_loss_total"], e["breakeven"]) == (635.0, 1865.0, 516.15)
    assert (e["credit_total_at_mid"], e["max_loss_total_at_mid"], e["breakeven_at_mid"]) == (810.0, 1690.0, 514.4)
    assert e["credit_haircut_total"] == 175.0 and e["credit_basis"] == "executable"
    # The EV is a model number on a closed-market quote and says so.
    assert e["expected_pl_at_expiry"] is not None
    assert "closed-market" in e["ev_caveat"] and "weekend" in e["ev_caveat"]
    assert e["ev_inputs"]["credit_or_premium"] == 6.35 and e["ev_inputs"]["credit_basis"] == "executable"
    # Legacy callers (net_credit only) keep the old arithmetic and are labelled midpoint.
    legacy = oe.economics({"strategy": "credit_spread", "short_strike": 522.5, "long_strike": 497.5, "strike": 522.5,
                           "premium": 8.10, "underlying_price": 563.0, "dte": 54, "iv_used": 0.45})
    assert legacy["credit_total"] == 810.0 and legacy["credit_basis"] == "midpoint"
    assert "midpoint" in legacy["ev_caveat"]


def test_protective_put_headline_is_the_hedged_position_not_the_put_alone():
    xar = oe.economics({"strategy": "protective_put", "strike": 230, "premium": 7.25, "underlying_price": 239.46,
                        "dte": 54, "contracts": 1, "iv_used": 0.25}, shares_held=100)
    assert xar["hedged_max_loss_from_mark"] == 1671.0 == xar["downside_to_floor_from_mark"]
    assert xar["option_max_loss"] == 725.0 and xar["put_breakeven"] == 222.75
    assert xar["uninsured_downside_note"] is None
    xlb = oe.economics({"strategy": "protective_put", "strike": 47.5, "premium": 0.69, "underlying_price": 49.8,
                        "dte": 40, "contracts": 5, "iv_used": 0.2}, shares_held=504.031)
    assert xlb["uninsured_shares"] == 4.031 and "4.031 shares" in xlb["uninsured_downside_note"]


def test_plain_english_worst_case_for_a_hedge_is_the_floor_not_the_premium():
    from scripts.lib.options_plain_english import explain
    p = {"strategy": "protective_put", "symbol": "XAR", "strike": 230, "premium": 7.25, "premium_total": 725.0,
         "underlying_price": 239.46, "dte": 54, "contracts": 1, "expiration": "2026-11-20", "pop_pct": 70.0,
         "shares_held": 100}
    p["economics"] = oe.economics(p, shares_held=100)
    text = str(explain(p))
    assert "22,275" in text and "1,671" in text
    assert "most this position can cost" not in text


def test_combined_exposure_skips_archived_ideas_and_names_them():
    csp = {"id": "a", "symbol": "DELL", "strategy": "cash_secured_put", "strike": 490.0, "premium": 21.57,
           "underlying_price": 563.0, "iv_used": 0.45, "dte": 54, "contracts": 1, "account": "t",
           "thesis_abandoned": "CIO asked for more research 3 times"}
    spr = {"id": "b", "symbol": "DELL", "strategy": "credit_spread", "strike": 522.5, "short_strike": 522.5,
           "long_strike": 497.5, "premium": 6.35, "net_credit": 6.35, "executable_credit": 6.35,
           "underlying_price": 563.0, "iv_used": 0.45, "dte": 54, "contracts": 1, "account": "t"}
    assert combined_exposure([csp, spr], cash_by_account={}) == {}  # one live idea: no block at all
    spr2 = dict(spr, id="c", strike=510.0, short_strike=510.0, long_strike=485.0)
    c = combined_exposure([csp, spr, spr2], cash_by_account={})["DELL"]
    assert [i["id"] for i in c["ideas"]] == ["b", "c"]
    assert c["excluded_ideas"] == [{"id": "a", "strategy": "cash_secured_put", "strike": 490.0, "reason": "archived"}]
    staged = dict(csp, thesis_abandoned=None, lifecycle={"stage": "ARCHIVED_ABANDONED"})
    assert combined_exposure([staged, spr, spr2], cash_by_account={})["DELL"]["excluded_ideas"][0]["id"] == "a"


def test_leg_liquidity_carries_the_quote_time_and_two_sidedness():
    leg = leg_liquidity(DELL_SHORT, role="short put", strike=522.5)
    assert leg["quote_time"] == "2026-09-25T20:00:00+00:00" and leg["two_sided"] is True
    one_sided = leg_liquidity({"bid": 0, "ask": 1.2, "oi": 0}, role="long put", strike=50.0)
    assert one_sided["two_sided"] is False


def test_blocked_card_severity_is_blocked_not_positive(monkeypatch):
    import options_engine as eng
    monkeypatch.setattr(eng, "_market_session_now", lambda: "WEEKEND")
    p = {"strategy": "credit_spread", "symbol": "DELL", "severity": "positive", "edge_score": 80,
         "enterprise": {"blocks": ["awaiting live quotes (market weekend): x"]}}
    eng._stamp_truth_flags(p)
    assert p["approvable"] is False and p["severity"] == "blocked" and p["edge_severity"] == "positive"
    ok = {"strategy": "credit_spread", "symbol": "DELL", "severity": "positive", "enterprise": {}}
    eng._stamp_truth_flags(ok)
    assert ok["approvable"] is True and ok["severity"] == "positive"


def test_lane_membership_is_not_research():
    from scripts.lib.options_research_universe import merge_research_rows
    rows = merge_research_rows([{"symbol": "PUR", "source_lanes": ["watchlist_buy_strong_buy"]}])
    assert rows[0]["research_qualified"] is True
    assert rows[0]["research_status"] == "lane_qualified" and rows[0]["research_lane_status"] == "lane_qualified"
    researched = merge_research_rows([{"symbol": "DELL", "source_lanes": ["fused_signal"], "research_artifact_id": "ra_1"}])
    assert researched[0]["research_status"] == "researched"
    explicit = merge_research_rows([{"symbol": "P", "source": "watchlist", "research_status": "researched"},
                                    {"symbol": "P", "source": "reentry"}])
    assert explicit[0]["research_status"] == "researched" and "_explicit_researched" not in explicit[0]


def _chain(short, long_, exp):
    def side(c):
        return {"side": "put", "exp": exp, **{k: c.get(k) for k in ("strike", "bid", "ask", "last", "oi", "volume", "iv", "delta")}}
    return {"status": "ok", "underlying_price": 563.0, "fetched_at": "2026-09-27T21:00:00+00:00",
            "expirations": [{"exp": exp, "dte": 54, "strikes": [side(short), side(long_)]}]}


def test_validate_requotes_both_legs_and_recomputes_the_executable_credit():
    from scripts.lib.options_validate import validate
    now = datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc)
    p = {"id": "x", "symbol": "DELL", "strategy": "credit_spread", "strike": 522.5, "short_strike": 522.5,
         "long_strike": 497.5, "expiration": "2026-11-20", "premium": 6.35, "executable_credit": 6.35,
         "underlying_price": 563.0, "contracts": 1, "data_source": "schwab_chain"}
    v = validate(p, chain_fn=lambda sym, strikes: _chain(DELL_SHORT, DELL_LONG, "2026-11-20"), session="REGULAR", now=now)
    assert v["status"] == "VALIDATED" and v["recomputed"]["net_credit"] == 6.35
    assert v["recomputed"]["max_loss"] == 1865.0 and v["recomputed"]["breakeven"] == 516.15
    assert v["live"]["schema"] == "OptionsSpreadQuote@v1" and v["live"]["quotes_as_of"] == "2026-09-27T21:00:00+00:00"
    # Priced at $8.10 (the old midpoint), the same live legs are a material change, not a match.
    old = validate(dict(p, premium=8.1, executable_credit=None), chain_fn=lambda sym, strikes: _chain(DELL_SHORT, DELL_LONG, "2026-11-20"),
                   session="REGULAR", now=now)
    assert old["status"] == "CHANGED" and "executable credit 8.1 -> 6.35" in old["material_changes"][0]


def test_validate_refuses_a_spread_that_is_not_a_credit():
    from scripts.lib.options_validate import validate
    p = {"id": "y", "symbol": "ETON", "strategy": "credit_spread", "strike": 52.5, "short_strike": 52.5,
         "long_strike": 50.0, "expiration": "2026-10-16", "premium": 0.89, "underlying_price": 55.0,
         "contracts": 1, "data_source": "schwab_chain"}
    v = validate(p, chain_fn=lambda sym, strikes: _chain(ETON_SHORT, ETON_LONG, "2026-10-16"), session="WEEKEND")
    assert v["status"] == "NOT_A_CREDIT" and v["recomputed"]["cash_flow"] == "debit"
    assert any("= -2" in c for c in v["material_changes"]) and v["liquidity_issues"]


def test_chain_normalizer_keeps_quote_times_and_stamps_fetched_at():
    import schwab_transport as st
    raw = {"symbol": "DELL", "underlyingPrice": 563.0,
           "putExpDateMap": {"2026-11-20:54": {"522.5": [{"bid": 31.75, "ask": 34.05, "last": 33.0, "mark": 32.9,
                                                          "volatility": 45.0, "delta": -0.3, "openInterest": 366,
                                                          "totalVolume": 168, "daysToExpiration": 54,
                                                          "quoteTimeInLong": 1790020800000}]}}}
    out = st.normalize_option_chain(raw)
    row = out["expirations"][0]["strikes"][0]
    assert row["mark"] == 32.9 and row["quote_time"].startswith("2026-09-2") and out["fetched_at"]


def test_enterprise_layer_gates_both_legs_of_a_spread(monkeypatch):
    import options_engine as eng
    monkeypatch.setattr(eng, "_schwab_chain", lambda sym, strikes=12: {})
    import options_desk_enterprise as ent
    monkeypatch.setattr(ent, "earnings_blackout_check", lambda sym, dte=30, strategy="": {"in_blackout": False})
    monkeypatch.setattr(ent, "load_desk_config", lambda: {"min_open_interest": 50, "min_volume": 5,
                                                          "max_bid_ask_spread_pct": 12.0, "closed_market_liquidity": "drop"})
    from scripts.lib.options_exposure import leg_liquidity as ll
    base = {"symbol": "ETON", "strategy": "credit_spread", "data_source": "bs_estimate", "strike": 52.5,
            "short_strike": 52.5, "long_strike": 50.0, "premium": 0.5, "dte": 20, "underlying_price": 55.0,
            "edge_score": 70, "risk_reward": 0.5,
            "legs_liquidity": [ll(ETON_SHORT, role="short put", strike=52.5), ll(ETON_LONG, role="long put", strike=50.0)]}
    out = eng._apply_enterprise_layer([dict(base)])[0]
    legs = out["enterprise"]["liquidity"]["legs"]
    assert len(legs) == 2 and all(g["pass"] is False for g in legs)
    assert out["enterprise"]["live_eligible"] is False and out["enterprise_blocked"] is True
    assert any("long put 50" in i for i in out["enterprise"]["liquidity"]["issues"])
    good = dict(base, symbol="DELL", legs_liquidity=[ll(DELL_SHORT, role="short put", strike=522.5),
                                                     ll(DELL_LONG, role="long put", strike=497.5)])
    out2 = eng._apply_enterprise_layer([good])[0]
    assert all(g["pass"] for g in out2["enterprise"]["liquidity"]["legs"])
