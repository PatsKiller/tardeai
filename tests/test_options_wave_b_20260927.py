"""Options Wave B (2026-09-27): per-leg liquidity, combined same-symbol exposure, one honest
lifecycle (policy blocks lead, EV withheld on non-tradeable quotes, "fully researched" needs a
stance), and symbol-level research reuse (DELL ran 11 requests in 26h)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import options_economics as oe  # noqa: E402
from scripts.lib.options_exposure import combined_exposure, leg_liquidity  # noqa: E402
from scripts.lib import options_thesis_lifecycle as otl  # noqa: E402

CSP = {"id": "a", "symbol": "DELL", "strategy": "cash_secured_put", "strike": 490.0, "premium": 21.57,
       "underlying_price": 563.0, "iv_used": 0.45, "dte": 54, "contracts": 1, "account": "schwab_taxable"}
SPR = {"id": "b", "symbol": "DELL", "strategy": "credit_spread", "strike": 522.5, "short_strike": 522.5,
       "long_strike": 497.5, "premium": 8.1, "net_credit": 8.1, "underlying_price": 563.0, "iv_used": 0.45,
       "dte": 54, "contracts": 1, "account": "schwab_taxable"}


def test_leg_liquidity_reports_each_leg_and_never_guesses():
    leg = leg_liquidity({"bid": 7.9, "ask": 8.3, "oi": 412, "volume": 38}, role="short put", strike=522.5)
    assert leg["mid"] == 8.1 and leg["spread_pct"] == 4.9 and leg["open_interest"] == 412
    empty = leg_liquidity(None, role="long put", strike=497.5)
    assert empty["bid"] is None and empty["spread_pct"] is None and empty["strike"] == 497.5


def test_two_dell_puts_are_one_correlated_bet_with_combined_scenarios():
    ps = [dict(CSP, economics=oe.economics(CSP)), dict(SPR, economics=oe.economics(SPR))]
    c = combined_exposure(ps, cash_by_account={"schwab_taxable": 60000.0}, shares_by_symbol={"DELL": 0})["DELL"]
    assert c["correlated"] is True and c["directions"] == ["bullish"]
    assert c["capital_committed_total"] == 49000.0 + 2500.0
    assert c["committed_pct_of_cash"] == round(100 * 51500 / 60000, 1)
    down30 = next(r for r in c["scenarios"] if r["move_pct"] == -30)
    px = 563.0 * 0.7
    want = ((21.57 - (490 - px)) + (8.1 - (522.5 - px) + (497.5 - px))) * 100
    assert abs(down30["combined_pl_at_expiry"] - round(want, 2)) < 0.02
    assert "same bet" in c["note"]
    assert combined_exposure([dict(CSP)], cash_by_account={}) == {}  # a lone idea gets no block


def test_expected_pl_is_withheld_on_non_tradeable_quotes_but_arithmetic_stays():
    xlb = {"strategy": "protective_put", "strike": 47.5, "premium": 0.69, "underlying_price": 49.8,
           "iv_used": 0.5252, "dte": 40, "contracts": 5}
    live = oe.economics(xlb)
    assert live["expected_pl_at_expiry"] > 300  # the weekend 52% IV makes the $345 put look rich
    wk = oe.economics(xlb, quote_issues=["OI 0 < 50", "spread 185.5% > 12.0%"])
    assert wk["expected_pl_at_expiry"] is None and "withheld" in wk["expected_pl_status"]
    assert wk["floor_value_after_premium"] == live["floor_value_after_premium"]


def test_policy_block_is_named_before_the_weekend_quote_block():
    import options_engine as eng
    ent = {"blocks": ["daily leveraged fund: resets daily and decays", "awaiting live quotes (market weekend): OI 0"]}
    assert eng._not_approvable_reason({}, [], ent) == "leveraged fund policy"


def test_fully_researched_requires_a_stance():
    from scripts.lib.options_plain_english import committee_memo
    t = {"symbol_thesis_version": "symbol_pur@v1", "thesis_state": "CURRENT", "evidence_for": ["ev_1"],
         "thesis_stance": ""}
    p = {"strategy": "cash_secured_put", "symbol": "PUR", "strike": 30, "premium": 3.35}
    assert committee_memo(p, t, {}).get("research_status") != "FULLY_RESEARCHED"
    # Operator 2026-09-27: a stance alone is not enough either -- research must be on file.
    assert committee_memo(p, dict(t, thesis_stance="watch"), {}).get("research_status") != "FULLY_RESEARCHED"
    p_runs = dict(p, cio_view={"research": {"count": 1}})
    assert committee_memo(p_runs, dict(t, thesis_stance="watch"), {}).get("research_status") == "FULLY_RESEARCHED"


def _req(rid, created, status, first, sym="DELL"):
    return {"research_id": rid, "created_ts": created.isoformat(), "status": status, "symbols": [sym],
            "questions": [{"text": first}]}


def test_same_symbol_thesis_research_is_reused_across_strikes():
    now = datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc)
    q = otl.research_questions({"symbol": "DELL", "strategy": "cash_secured_put", "expiration": "x", "dte": 30})[0]["text"]
    q2 = otl.research_questions({"symbol": "DELL", "strategy": "cash_secured_put", "expiration": "y", "dte": 54})[0]["text"]
    assert q == q2  # the first question never names the strike or expiry
    reqs = [_req("old", now - timedelta(hours=30), "completed", q), _req("hit", now - timedelta(hours=5), "completed", q),
            _req("fail", now - timedelta(hours=1), "failed", q), _req("hood", now, "queued", q, sym="HOOD")]
    got = otl.reusable_request(reqs, symbol="DELL", first_text=q, kind="thesis", now=now, hours=24)
    assert got["research_id"] == "hit"
    assert otl.reusable_request(reqs[:1], symbol="DELL", first_text=q, kind="thesis", now=now, hours=24) is None


def test_followups_join_an_in_flight_request_only():
    now = datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc)
    f = "DELL" + otl.FOLLOWUP_MARK + " (do not restate it): no thesis"
    done = _req("done", now - timedelta(hours=1), "completed", f)
    flying = _req("fly", now - timedelta(hours=2), "queued", f)
    stale = _req("stale", now - timedelta(hours=9), "queued", f)
    assert otl.reusable_request([done, stale], symbol="DELL", first_text="", kind="followup", now=now, hours=6) is None
    assert otl.reusable_request([done, flying], symbol="DELL", first_text="", kind="followup", now=now, hours=6)["research_id"] == "fly"


class _Store:
    def __init__(self):
        self.events = []

    def lifecycle(self, guid):
        return {"created_at": "2026-09-27T19:00:00+00:00"}

    def append_event(self, guid, kind, **kw):
        self.events.append((guid, kind, kw))


def test_advance_asks_once_for_two_dell_strikes_in_one_pass():
    now = datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc)
    calls = []

    def request_research(p, qs=None):
        calls.append(p["option_strategy_guid"])
        return {"research_id": f"res_{len(calls)}", "plan_id": "plan"}

    ps = [dict(CSP, option_strategy_guid=g, options_thesis={"pin": "x", "missing_required": ["catalysts"]},
               expiration=e) for g, e in (("g1", "2026-10-16"), ("g2", "2026-11-20"))]
    store = _Store()
    rep = otl.advance(ps, store, {}, request_research=request_research, research_status=lambda rid: {},
                      review_fn=lambda p, m: {}, record_decision=lambda r: None, apply=True, now=now,
                      recent_requests=lambda sym: [])
    assert calls == ["g1"]
    assert [s["action"] for s in rep] == ["REQUEST_RESEARCH", "REUSE_RESEARCH"]
    assert store.events[1][2]["research_id"] == "res_1" and store.events[1][2]["reused"] is True
