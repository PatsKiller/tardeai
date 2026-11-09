"""Tests for the CIO overnight brief generator (LQ-20261107-1257).

Every fixture here is synthetic: ZZ-prefixed symbols, invented prices. The real holdings never
enter a test file. No database, no provider, no network: the DB loaders and the research/LLM
functions are stubs, and the clock is fixed.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.cio_overnight_brief as B  # noqa: E402

ET = ZoneInfo("America/New_York")


# ── fixtures (synthetic) ─────────────────────────────────────────────────────────────────────


def holdings_doc() -> dict:
    return {
        "holdings": [
            {"symbol": "ZRKT", "account": "acct_a", "broker_shares": 600, "market_value": 60000, "is_cash": False},
            {"symbol": "ZRKT", "account": "acct_b", "broker_shares": 200, "market_value": 20000, "is_cash": False},
            {"symbol": "ZNET", "account": "acct_a", "broker_shares": 200, "market_value": 30000, "is_cash": False},
            {"symbol": "ZQUIET", "account": "acct_a", "broker_shares": 100, "market_value": 10000, "is_cash": False},
            {"symbol": "CASH", "account": "acct_a", "broker_shares": 5000, "market_value": 5000, "is_cash": True},
            {"symbol": "ZZERO", "account": "acct_a", "broker_shares": 0, "market_value": 0, "is_cash": False},
        ],
        "portfolio_totals": {"broker_market_value_total": 120000.0},
    }


def quotes() -> dict:
    return {
        "ZRKT": {"price": 100.0, "change_pct": 8.62, "source": "finviz_elite"},
        "ZNET": {"price": 150.0, "change_pct": 7.31, "source": "finviz_elite"},
        "ZQUIET": {"price": 100.0, "change_pct": 0.4, "source": "finviz_elite"},
    }


def news() -> dict:
    return {
        "ZRKT": [
            {
                "title": "ZRKT raises guidance",
                "summary": "Management lifted the revenue outlook.",
                "source": "Wire",
                "source_url": "https://example.invalid/zrkt",
                "published_at": datetime(2026, 11, 6, 21, 0, tzinfo=ET),
            }
        ],
        "ZQUIET": [
            {
                "title": "ZQUIET names a director",
                "summary": "",
                "source": "Wire",
                "source_url": "https://example.invalid/zquiet",
                "published_at": datetime(2026, 11, 6, 18, 0, tzinfo=ET),
            }
        ],
    }


def stops() -> dict:
    # account_a: one resting stop on 600 of 800 shares; account_b: nothing. A replaced order
    # must not count as coverage.
    return {
        "ZRKT": [
            {"account": "acct_a", "order_id": "1", "stop": 90.0, "qty": 600, "status": "pending_activation"},
            {"account": "acct_a", "order_id": "2", "stop": 88.0, "qty": 600, "status": "replaced"},
        ],
        "ZNET": [
            {"account": "acct_a", "order_id": "3", "stop": 149.0, "qty": 200, "status": "pending_activation"},
        ],
    }


def bars(close: float = 100.0, n: int = 30) -> dict:
    out = {}
    for symbol in ("ZRKT", "ZNET", "ZQUIET"):
        rows = []
        for i in range(n):
            c = close if symbol == "ZRKT" else (150.0 if symbol == "ZNET" else 100.0)
            rows.append({"open": c, "high": c + 2, "low": c - 2, "close": c, "volume": 1_000_000})
        out[symbol] = rows
    return out


def risk() -> dict:
    return {"regime_label": "risk_off", "regime_score": -0.4, "volatility_state": "elevated", "source": "market_regime_snapshots"}


def calendar() -> dict:
    return {
        "macro": [{"date": "2026-11-10", "event": "CPI (Oct)", "time_et": "08:30", "importance": "high"}],
        "earnings": [{"symbol": "ZZEARN", "date": "2026-11-12"}],
        "notes": [],
    }


def positions():
    """positions_current shape — the broker sync the book line reads first."""
    rows = [
        {"account": "acct_a", "symbol": "ZRKT", "qty": 600, "market_value": 60000, "is_cash": False},
        {"account": "acct_b", "symbol": "ZRKT", "qty": 200, "market_value": 20000, "is_cash": False},
        {"account": "acct_a", "symbol": "ZNET", "qty": 200, "market_value": 30000, "is_cash": False},
        {"account": "acct_a", "symbol": "ZQUIET", "qty": 100, "market_value": 10000, "is_cash": False},
        {"account": "acct_a", "symbol": "CASH", "qty": 6500, "market_value": 6500, "is_cash": True},
    ]
    for r in rows:
        r["as_of"] = "2026-11-08T18:00:05-05:00"
    return {"as_of": "2026-11-08T18:00:05-05:00", "rows": rows, "source": "positions_current"}


def market_risk(tier="RED", as_of="2026-11-08T18:00:02-05:00"):
    return {
        "as_of": as_of,
        "tier": tier,
        "score": 59.6,
        "shock": {
            "class": "SECTOR",
            "label": "sector / theme",
            "headline": "Technology and semis stressed; 9 of 11 sectors holding",
        },
        "deescalates_if": "RED -> ORANGE if the score falls below 75 and fewer than 5 categories are at WARN or STRESS",
    }


def reentry_desk(near=0, ready=0):
    rows = []
    for i in range(near):
        rows.append({"symbol": f"ZNEAR{i}", "intel": {"state": "NEAR ENTRY"}})
    for i in range(ready):
        rows.append({"symbol": f"ZREADY{i}", "intel": {"state": "READY TO REVIEW"}})
    rows.append({"symbol": "ZWAIT", "intel": {"state": "WAIT"}})
    return {"computed_at": "2026-11-08T18:00:48-05:00", "rows": rows}


def build(as_of: datetime, **over):
    kw = dict(
        as_of=as_of,
        holdings_doc=holdings_doc(),
        quotes=quotes(),
        news_by_symbol=news(),
        filings_by_symbol={"ZNET": [
            {"form": "Form 4", "filer": "A. Founder", "shares": 260000, "value": 44_400_000,
             "filed": "2026-11-06", "url": "https://example.invalid/144"}
        ]},
        stops_by_symbol=stops(),
        bars_by_symbol=bars(),
        decisions={"ZNET": {"action": "MONITOR_ONLY", "status": "proposed", "decided_at": "2026-11-06T15:22:10-05:00"}},
        risk=risk(),
        calendar=calendar(),
        session_service=None,
        research_fn=None,
        narrative_fn=None,
        budget=None,
        max_research=B.RESEARCH_PER_RUN_DEFAULT,
        positions=positions(),
        risk_market=market_risk(),
        reentry_desk=reentry_desk(),
    )
    kw.update(over)
    return B.build_brief(**kw)


AS_OF = datetime(2026, 11, 9, 5, 50, tzinfo=ET)  # Monday pre-market


# ── deterministic analysis ──────────────────────────────────────────────────────────────────


def test_holdings_aggregate_per_symbol_and_drop_cash_and_zero():
    held = B.aggregate_holdings(holdings_doc()["holdings"])
    assert set(held) == {"ZRKT", "ZNET", "ZQUIET"}
    assert held["ZRKT"]["shares"] == 800
    assert held["ZRKT"]["per_account"] == {"acct_a": 600.0, "acct_b": 200.0}
    assert held["ZRKT"]["market_value"] == 80000.0


def test_replaced_stop_is_not_coverage_and_uncovered_shares_are_named():
    held = B.aggregate_holdings(holdings_doc()["holdings"])
    cov = B.stop_coverage(held["ZRKT"], stops()["ZRKT"])
    assert cov["covered_shares"] == 600.0
    assert cov["uncovered_shares"] == 200.0
    assert cov["uncovered_by_account"] == {"acct_b": 200.0}
    assert cov["fully_covered"] is False


def test_small_gap_is_a_reconcile_not_uncovered_exposure():
    # 100 stopped against 101.2948 held: a fractional-share artifact, not exposure
    cov = B.stop_coverage(
        {"per_account": {"acct_a": 101.2948}},
        [{"account": "acct_a", "order_id": "1", "stop": 400.0, "qty": 100, "status": "pending_activation"}],
    )
    assert cov["uncovered_shares"] == 0.0
    assert cov["reconcile_by_account"] == {"acct_a": 1.2948}
    assert cov["fully_covered"] is True
    action = B.advisory_action(410.0, cov, {"band": "moderate", "stop": 400.0}, 5.0)
    assert "reconcile the stop quantity" in action


def test_working_stops_excludes_terminal_statuses():
    rows = [
        {"symbol": "ZRKT", "account": "a", "order_id": "1", "stop_price": 90, "qty": 100, "status": "pending_activation"},
        {"symbol": "ZRKT", "account": "a", "order_id": "2", "stop_price": 91, "qty": 100, "status": "replaced"},
        {"symbol": "ZRKT", "account": "a", "order_id": "3", "stop_price": 92, "qty": 100, "status": "canceled"},
        {"symbol": "ZRKT", "account": "a", "order_id": "4", "stop_price": 93, "qty": 100, "status": "filled"},
        {"symbol": "ZRKT", "account": "a", "order_id": "5", "stop_price": None, "qty": 100, "status": "active"},
    ]
    out = B.working_stops(rows)
    assert [s["order_id"] for s in out["ZRKT"]] == ["1"]


def test_atr14_uses_true_range_with_previous_close():
    flat = [{"high": 101, "low": 99, "close": 100} for _ in range(15)]
    assert B.atr14(flat) == pytest.approx(2.0)
    gapped = [{"high": 101, "low": 99, "close": 100} for _ in range(14)] + [{"high": 111, "low": 109, "close": 110}]
    # last bar's true range is max(2, |111-100|, |109-100|) = 11
    assert B.atr14(gapped) == pytest.approx((2.0 * 13 + 11.0) / 14)


def test_atr14_needs_enough_bars():
    assert B.atr14([{"high": 1, "low": 0, "close": 1}] * 5) is None


def test_cushion_bands_tight_moderate_wide():
    stop = [{"account": "a", "order_id": "1", "stop": 95.0, "qty": 10, "status": "active"}]
    tight = B.cushion(100.0, stop, 12.0)     # 5 points of cushion vs ATR 12 -> 0.42x
    assert tight["band"] == "tight"
    assert tight["cushion_pct"] == pytest.approx(5.0)   # the queue's (price - stop)/price
    assert tight["stop_pct"] == pytest.approx(-5.0)     # the blueprint's (stop - price)/price
    moderate = B.cushion(100.0, stop, 3.0)   # 5 vs 3 -> 1.67x
    assert moderate["band"] == "moderate"
    wide = B.cushion(100.0, stop, 1.5)       # 5 vs 1.5 -> 3.3x
    assert wide["band"] == "wide"


def test_cushion_prefers_the_stop_below_the_price():
    stops_ = [
        {"account": "a", "order_id": "1", "stop": 90.0, "qty": 10, "status": "active"},
        {"account": "a", "order_id": "2", "stop": 110.0, "qty": 10, "status": "active"},
    ]
    c = B.cushion(100.0, stops_, 2.0)
    assert c["stop"] == 90.0


def test_action_names_uncovered_shares():
    held = B.aggregate_holdings(holdings_doc()["holdings"])
    cov = B.stop_coverage(held["ZRKT"], stops()["ZRKT"])
    cush = B.cushion(100.0, stops()["ZRKT"], 12.0)
    action = B.advisory_action(100.0, cov, cush, 12.0)
    assert "cover the 200 sh" in action
    assert "Advisory only" in action


def test_tight_stop_never_suggests_moving_the_stop_down():
    stop = [{"account": "a", "order_id": "1", "stop": 97.0, "qty": 10, "status": "active"}]
    cush = B.cushion(100.0, stop, 6.0)          # 3 points vs ATR 6 -> 0.5x, tight
    action = B.advisory_action(100.0, {"uncovered_shares": 0}, cush, 6.0)
    assert "trim" in action
    assert "raise to about" not in action


def test_wide_stop_offers_a_raise_above_the_resting_stop():
    stop = [{"account": "a", "order_id": "1", "stop": 60.0, "qty": 10, "status": "active"}]
    cush = B.cushion(100.0, stop, 5.0)          # 40 points vs ATR 5 -> 8x, wide
    action = B.advisory_action(100.0, {"uncovered_shares": 0}, cush, 5.0)
    assert "raise to about 90.00" in action     # 2 ATR below price, above the 60 stop


def test_select_names_threshold_and_news_only():
    held = B.aggregate_holdings(holdings_doc()["holdings"])
    q = dict(quotes())
    q["ZQUIET"] = {"price": 100.0, "change_pct": 2.9, "source": "x"}
    sel = B.select_names(held, q, news())
    syms = [s["symbol"] for s in sel]
    assert syms == ["ZRKT", "ZNET", "ZQUIET"]  # ZQUIET by news, not by move
    assert sel[2]["reasons"] == ["news"]
    q["ZQUIET"] = {"price": 100.0, "change_pct": 2.9, "source": "x"}
    assert [s["symbol"] for s in B.select_names(held, q, {})] == ["ZRKT", "ZNET"]


def test_position_floor_skips_fractional_remnants():
    doc = holdings_doc()
    doc["holdings"].append(
        {"symbol": "ZDUST", "account": "acct_a", "broker_shares": 0.13, "market_value": 24.8, "is_cash": False}
    )
    q = dict(quotes())
    q["ZDUST"] = {"price": 190.0, "change_pct": 9.0, "source": "x"}
    held = B.aggregate_holdings(doc["holdings"])
    assert "ZDUST" not in [s["symbol"] for s in B.select_names(held, q, {})]
    assert B.selection_exclusions(held) == {"below_position_floor": 1}


def test_news_window_starts_at_the_previous_close():
    from scripts.lib.cio_market_session import get_session_service

    svc = get_session_service()
    close_date, _close = B.last_close_at(AS_OF, svc)
    assert close_date.isoformat() == "2026-11-06"          # Friday's close
    # the window opens at Thursday's close, so Friday's session news is inside it
    assert B.previous_close_at(close_date, svc).isoformat().startswith("2026-11-05T16:00")


def test_research_question_carries_evidence_and_demands_citations():
    held = B.aggregate_holdings(holdings_doc()["holdings"])
    sig = B.select_names(held, quotes(), news())[0]
    q = B.research_question(sig, [{"form": "Form 4", "filer": "A. Founder", "shares": 260000, "value": 1, "filed": "2026-11-06"}])
    assert "ZRKT raises guidance" in q
    assert "WHO" in q and "WHY" in q and "IMPACT" in q
    assert "Form 4" in q


def test_deterministic_fallback_still_cites_the_headline():
    held = B.aggregate_holdings(holdings_doc()["holdings"])
    sig = B.select_names(held, quotes(), news())[0]
    fb = B.deterministic_research_fallback(sig, [])
    assert "ZRKT raises guidance" in fb["text"]
    assert fb["source"] == "deterministic"
    assert any("Wire" in s for s in fb["sources"])


# ── the assembled brief ─────────────────────────────────────────────────────────────────────


def test_brief_shape_uses_the_last_exchange_close_and_five_sessions():
    doc = build(AS_OF)
    assert doc["schema"] == B.SCHEMA
    assert doc["advisory_only"] is True and doc["verdict_owner"] == "CIO"
    assert doc["last_close"]["session_date"] == "2026-11-06"   # Monday pre-market sees Friday's close
    assert len(doc["week_ahead"]["sessions"]) == 5
    assert doc["counts"] == {
        "held_names": 3,
        "selected": 3,
        "with_news": 2,
        "with_move": 2,
        # ZRKT has 200 uncovered shares; ZQUIET holds 100 with no resting stop at all
        "uncovered_positions": 2,
    }
    by = {h["symbol"]: h for h in doc["holdings"]}
    assert by["ZRKT"]["stops"]["coverage"]["uncovered_shares"] == 200.0
    assert by["ZRKT"]["stops"]["cushion"]["band"] == "wide"   # 10 points vs ATR 4 -> 2.5x
    assert by["ZRKT"]["research"]["status"] == "disabled"
    assert by["ZNET"]["filings"][0]["filer"] == "A. Founder"
    assert by["ZNET"]["cio_decision"]["action"] == "MONITOR_ONLY"


def test_research_disabled_does_not_call_anything():
    calls = []

    def never(sym, q, lanes):
        calls.append(sym)
        return {"status": "unanswered"}

    doc = build(AS_OF, research_fn=None)
    assert calls == []
    assert all(h["research"]["status"] == "disabled" for h in doc["holdings"])


def test_research_answer_is_quoted_with_sources():
    def answer(sym, q, lanes):
        assert sym and "WHO" in q
        return {"status": "answered", "lane": "chatgpt", "answer": "A. Founder sold under a 10b5-1 plan.",
                "evidence": [{"quote": "plan", "source": "Wire"}], "attempts": [{"lane": "chatgpt", "rc": 0}]}

    doc = build(AS_OF, research_fn=answer)
    h = {x["symbol"]: x for x in doc["holdings"]}
    assert h["ZRKT"]["research"]["status"] == "answered"
    assert "10b5-1" in h["ZRKT"]["research"]["text"]
    assert h["ZRKT"]["research"]["sources"]
    assert doc["research"]["answered"] == 3


def test_unanswered_research_falls_back_deterministically():
    def answer(sym, q, lanes):
        return {"status": "unanswered", "attempts": [{"lane": "grok", "rc": 0, "status": "refused"}]}

    doc = build(AS_OF, research_fn=answer)
    h = {x["symbol"]: x for x in doc["holdings"]}
    assert h["ZRKT"]["research"]["status"] == "unanswered_deterministic_fallback"
    assert "ZRKT raises guidance" in h["ZRKT"]["research"]["text"]
    assert doc["research"]["unanswered"] == 3


def test_research_budget_reservation_caps_the_run(tmp_path):
    budget = B.ResearchBudget(tmp_path / "budget.json", per_day=3, as_of=AS_OF)
    calls = []

    def answer(sym, q, lanes):
        calls.append(sym)
        return {"status": "answered", "answer": "x", "attempts": [{"lane": "chatgpt", "rc": 0}]}

    doc = build(AS_OF, research_fn=answer, budget=budget)
    # one call spends one of three reserved slots for the day; the remaining two slots cannot
    # fund another full lane chain, so the rest are budget-skipped rather than silently dropped
    assert len(calls) == 1
    assert doc["research"]["skipped_budget"] == 2
    assert {h["symbol"]: h for h in doc["holdings"]}["ZRKT"]["research"]["status"] == "answered"
    assert {h["symbol"]: h for h in doc["holdings"]}["ZNET"]["research"]["status"] == "budget_reserved_exhausted"


def test_budget_counter_is_per_day():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "budget.json"
        b1 = B.ResearchBudget(p, per_day=10, as_of=AS_OF)
        b1.spend(3)
        b2 = B.ResearchBudget(p, per_day=10, as_of=AS_OF)
        assert b2.used == 3 and b2.remaining() == 7
        b3 = B.ResearchBudget(p, per_day=10, as_of=datetime(2026, 11, 10, 5, 50, tzinfo=ET))
        assert b3.used == 0


def test_llm_narrative_fills_prose_but_never_the_action():
    def narr(packet):
        assert packet["names"]
        return {"summary": "Risk-off tape; one uncovered position.", "names": {"ZRKT": {"what_why": "Guidance raise.", "impact": "Mildly positive."}}}

    doc = build(AS_OF, narrative_fn=narr)
    assert doc["summary"]["source"] == "llm"
    h = {x["symbol"]: x for x in doc["holdings"]}
    assert h["ZRKT"]["what_why"] == "Guidance raise."
    assert "cover the 200 sh" in h["ZRKT"]["action_advisory"]   # action is still deterministic


def test_llm_narrative_garbage_leaves_the_deterministic_summary():
    doc = build(AS_OF, narrative_fn=lambda packet: {"summary": ""})
    assert doc["summary"]["source"] == "deterministic"
    assert "Market regime" in doc["summary"]["text"]


def test_summary_labels_the_regime_and_the_market_risk_tier_separately():
    # The regime snapshot (risk_off, -0.4) and the market-risk tier (RED, 59.6) are different
    # measures on different scales; one document must not print the same label for both.
    text = build(AS_OF)["summary"]["text"]
    assert "Market regime: risk_off" in text
    assert "market risk tier RED (59.6)" in text
    assert "Risk tier: risk_off" not in text


def test_synopsis_keeps_the_market_risk_tier_label():
    doc = build(AS_OF)
    assert "Risk tier RED (score 59.6)" in doc["synopsis"]["market"]["line"]


def test_empty_tape_is_an_honest_empty_not_an_error(tmp_path):
    doc = build(AS_OF, quotes={}, news_by_symbol={})
    assert doc["counts"]["selected"] == 0
    assert "No held name moved" in doc["summary"]["text"]


# ── stop_advice (AMENDMENT 1) ──────────────────────────────────────────────────────────────


def event_for(text: str, filings=None, sig_news=None):
    return B.classify_event({"news": sig_news or [], "move_pct": 7.31}, filings or [], text)


def test_plan_sale_is_neutral_and_gets_a_premise_correction():
    ev = event_for("Bechtolsheim sold 260,000 shares under a pre-arranged 10b5-1 plan: 0.14% of his stake.")
    assert ev["kind"] == "insider_plan_sale"
    assert ev["neutral"] is True
    assert "10b5-1" in ev["premise_correction"]
    assert "not a 10% exit" in ev["premise_correction"]


def test_raise_on_price_for_a_plan_sale():
    # ANET-like: a plan sale is neutral, but price is 16.7% above the stop after a +7.31% day
    ev = event_for("A pre-arranged 10b5-1 plan, 0.14% of his stake.", sig_news=[{"title": "Form 144"}])
    entry = B.stop_advice_for_account(
        symbol="ZNET", account="acct_a", held_qty=200, price=175.0, move_pct=7.31, atr=10.0,
        stops=[{"account": "acct_a", "order_id": "1", "stop": 150.0, "qty": 200, "status": "pending_activation"}],
        event=ev, source_ids=["news:1", "research:grok"], as_of="2026-11-09T05:50:00-05:00",
    )
    assert entry["answer"] == "RAISE"
    assert entry["suggested_stop"] == 165.0            # min(price - 1 ATR, price - 3%)
    assert entry["suggested_stop"] <= 175.0 * 0.97     # never closer than 3% below the close
    assert entry["suggested_stop"] > entry["stop_now"]
    assert "neutral" in entry["reason"]
    assert entry["premise_correction"]


def test_headline_alone_never_raises_a_stop():
    ev = event_for("A pre-arranged 10b5-1 plan.", sig_news=[{"title": "Insider sale"}])
    entry = B.stop_advice_for_account(
        symbol="ZNET", account="acct_a", held_qty=200, price=161.0, move_pct=1.2, atr=10.0,
        stops=[{"account": "acct_a", "order_id": "1", "stop": 150.0, "qty": 200, "status": "pending_activation"}],
        event=ev, source_ids=[], as_of="2026-11-09T05:50:00-05:00",
    )
    assert entry["answer"] == "HOLD"
    assert entry["suggested_stop"] is None


def test_uncovered_quantity_is_an_add_stop():
    entry = B.stop_advice_for_account(
        symbol="ZRKT", account="acct_b", held_qty=200, price=134.27, move_pct=8.62, atr=8.94,
        stops=[{"account": "acct_a", "order_id": "1", "stop": 120.46, "qty": 600, "status": "pending_activation"}],
        event={"kind": "news", "neutral": False, "summary": "x", "premise_correction": None},
        source_ids=["news:1"], as_of="2026-11-09T05:50:00-05:00",
    )
    assert entry["answer"] == "ADD_STOP"
    assert entry["stop_qty"] == 0.0 and entry["held_qty"] == 200.0
    assert entry["suggested_stop"] is not None


def test_over_cover_is_a_fix_qty():
    entry = B.stop_advice_for_account(
        symbol="ZV", account="acct_a", held_qty=101.0, price=410.0, move_pct=0.2, atr=5.0,
        stops=[{"account": "acct_a", "order_id": "1", "stop": 395.0, "qty": 130, "status": "pending_activation"}],
        event={"kind": "news", "neutral": False, "summary": "x", "premise_correction": None},
        source_ids=[], as_of="2026-11-09T05:50:00-05:00",
    )
    assert entry["answer"] == "FIX_QTY"
    assert entry["stop_qty"] == 130.0 and entry["held_qty"] == 101.0


def test_stop_advice_prose_uses_the_account_display_name_not_the_raw_key():
    # LQ-1391: the sentences are read by the operator; the canonical key is for joins and links.
    # config/account_display_names.json: schwab_taxable -> "Schwab Individual".
    ev = {"kind": "news", "neutral": False, "summary": "x", "premise_correction": None}
    add = B.stop_advice_for_account(
        symbol="ZRKT", account="schwab_taxable", held_qty=200, price=134.27, move_pct=8.62, atr=8.94,
        stops=[], event=ev, source_ids=[], as_of="2026-11-09T05:50:00-05:00",
    )
    assert add["answer"] == "ADD_STOP"
    assert add["account"] == "schwab_taxable"                    # the join key is unchanged
    assert add["account_label"] == "Schwab Individual"           # the row's one display name
    assert "Schwab Individual" in add["reason"]
    assert "schwab_taxable" not in add["reason"]
    fix = B.stop_advice_for_account(
        symbol="ZV", account="schwab_taxable", held_qty=101.0, price=410.0, move_pct=0.2, atr=5.0,
        stops=[{"account": "schwab_taxable", "order_id": "1", "stop": 395.0, "qty": 130, "status": "pending_activation"}],
        event=ev, source_ids=[], as_of="2026-11-09T05:50:00-05:00",
    )
    assert fix["answer"] == "FIX_QTY"
    assert "Schwab Individual" in fix["reason"] and "schwab_taxable" not in fix["reason"]


def test_an_unconfigured_account_key_is_title_cased_never_echoed_raw():
    assert B._acct("acct_a") == "Acct A"


def test_tiny_position_is_no_action():
    entry = B.stop_advice_for_account(
        symbol="ZDUST", account="acct_a", held_qty=0.13, price=190.0, move_pct=9.0, atr=3.0,
        stops=[], event={"kind": "move", "neutral": False, "summary": "x", "premise_correction": None},
        source_ids=[], as_of="2026-11-09T05:50:00-05:00",
    )
    assert entry["answer"] == "NO_ACTION"


def test_brief_carries_one_stop_advice_per_account_and_the_source_timestamps():
    doc = build(AS_OF)
    entries = {(e["symbol"], e["account"]) for e in doc["stop_advice"]}
    assert ("ZRKT", "acct_a") in entries and ("ZRKT", "acct_b") in entries
    for e in doc["stop_advice"]:
        assert e["answer"] in B.STOP_ADVICE_ANSWERS
        assert e["as_of"] == doc["as_of"]
        assert "premise_correction" in e and "source_ids" in e
    ts = doc["source_timestamps"]
    assert set(ts) == {"news", "positions", "risk", "quotes", "stops"}


def test_fractional_remnant_cannot_carry_a_stop():
    # 0.4985 sh at $410 is ~$204 — above the $100 floor, but no broker takes a stop on a fraction
    entry = B.stop_advice_for_account(
        symbol="ZV", account="acct_a", held_qty=0.4985, price=410.0, move_pct=0.01, atr=5.0,
        stops=[], event={"kind": "news", "neutral": False, "summary": "x", "premise_correction": None},
        source_ids=[], as_of="2026-11-09T05:50:00-05:00",
    )
    assert entry["answer"] == "NO_ACTION"
    assert "fractional" in entry["reason"]


def test_a_sub_share_gap_is_not_an_uncovered_quantity():
    # 100 covered of 100.796 held: a 0.8 sh remainder is not an order anyone can place
    entry = B.stop_advice_for_account(
        symbol="ZV", account="acct_a", held_qty=100.796, price=410.0, move_pct=0.5, atr=5.0,
        stops=[{"account": "acct_a", "order_id": "1", "stop": 407.72, "qty": 100, "status": "pending_activation"}],
        event={"kind": "news", "neutral": False, "summary": "x", "premise_correction": None},
        source_ids=[], as_of="2026-11-09T05:50:00-05:00",
    )
    assert entry["answer"] == "HOLD"


def test_an_insider_headline_is_the_event_even_without_a_filing_row():
    sig = {"news": [
        {"title": "ZNET: A. Founder plans to sell 260,000 ZNET shares, about $44.4M"},
        {"title": "ZNET stock sees modest fair value lift after analyst revisions"},
    ], "move_pct": 7.31}
    ev = B.classify_event(sig, [], "")
    assert ev["kind"] == "insider_sale"
    assert "plans to sell 260,000" in ev["summary"]
    assert ev["neutral"] is False          # no plan and no stake percentage on the record
    assert ev["premise_correction"] is None


# ── synopsis (AMENDMENT 2) ────────────────────────────────────────────────────────────────


def test_synopsis_posture_verdict_and_market_line_come_from_the_risk_read():
    syn = build(AS_OF)["synopsis"]
    assert syn["posture"] == "DEFENSIVE — HOLD CASH"
    assert syn["market"]["tier"] == "RED"
    assert syn["market"]["market_wide"] is False
    assert "sector" in syn["market"]["line"] and "not market-wide" in syn["market"]["line"]
    assert len(syn["verdict"]) <= B.VERDICT_MAX_CHARS
    assert syn["verdict"].endswith(".")
    assert "\n" not in syn["verdict"]
    assert syn["as_of"] == AS_OF.isoformat()
    assert syn["advisory_only"] is True


def test_synopsis_book_names_the_largest_unprotected_risk():
    syn = build(AS_OF)["synopsis"]
    book = syn["book"]
    assert book["positions"] == 4
    assert book["cash"] == 6500.0
    assert "positions_current:" in book["source_ids"][0]
    worst = book["largest_unprotected_risk"]
    # acct_b holds 200 ZRKT with no stop at all (~$20,000); ZQUIET's 100 uncovered sh are smaller
    assert worst["symbol"] == "ZRKT" and worst["account"] == "acct_b"
    assert worst["shares"] == 200.0 and worst["value"] == 20000.0
    assert "largest unprotected: ZRKT 200 sh" in book["line"]


def test_synopsis_falls_back_to_the_holdings_document_and_says_so():
    syn = build(AS_OF, positions=None)["synopsis"]
    assert syn["book"]["source_ids"][0].startswith("holdings.json:")
    assert syn["book"]["largest_unprotected_risk"]["symbol"] == "ZRKT"


def test_synopsis_reentry_says_dont_buy_back_yet_until_a_name_is_past_stage_1():
    quiet = build(AS_OF)["synopsis"]["reentry"]
    assert quiet["stage2"] == 0 and quiet["stage3"] == 0
    assert quiet["line"].startswith("Don't buy back yet")

    near = build(AS_OF, reentry_desk=reentry_desk(near=2))["synopsis"]["reentry"]
    assert near["stage2"] == 2 and near["max_stage"] == 2
    assert "past stage 1" in near["line"] and "not a buy call" in near["line"]
    assert "ZNEAR0" in near["line"]

    ready = build(AS_OF, reentry_desk=reentry_desk(near=1, ready=1))["synopsis"]["reentry"]
    assert ready["stage3"] == 1 and ready["max_stage"] == 3


def test_synopsis_do_now_references_the_first_actionable_stop_item():
    syn = build(AS_OF)["synopsis"]
    do_now = syn["do_now"]
    assert do_now["stop_advice_count"] == len(build(AS_OF)["stop_advice"])
    assert do_now["actionable_count"] >= 3          # one RAISE, two ADD_STOP in the fixture
    assert do_now["first"]["symbol"] == "ZRKT"
    assert do_now["first"]["answer"] == "RAISE"
    assert str(do_now["first"]["suggested_stop"]) in do_now["line"]
    assert do_now["source_ids"]


def test_synopsis_marks_a_source_stale_and_never_invents_a_posture():
    stale = build(AS_OF, risk_market=market_risk(as_of="2026-10-30T18:00:00-04:00"))["synopsis"]
    assert "stale" in stale["market"]["line"]

    blind = build(AS_OF, risk_market=None)["synopsis"]
    assert blind["posture"] == "NEUTRAL — AWAIT RISK READ"
    assert blind["market"]["tier"] is None
    assert "UNKNOWN" not in blind["verdict"]


def test_synopsis_source_ids_cover_every_section():
    syn = build(AS_OF)["synopsis"]
    joined = " ".join(syn["source_ids"])
    for needle in ("market_risk:", "positions_current:", "reentry_decision_desk:", "macro_calendar", "earnings_dates"):
        assert needle in joined
    for section in ("book", "market", "reentry", "this_week", "do_now"):
        assert syn[section]["source_ids"]
    assert "CPI (Oct)" in syn["this_week"]["line"] and "ZZEARN earnings" in syn["this_week"]["line"]
    assert "RED -> ORANGE" in syn["changes_if"]


# ── plumbing ───────────────────────────────────────────────────────────────────────────────


def test_write_brief_writes_latest_and_dated_copy(tmp_path):
    doc = build(AS_OF)
    written = B.write_brief(doc, tmp_path)
    assert sorted(p.name for p in written) == ["2026-11-09.json", "latest.json"]
    assert json.loads((tmp_path / "latest.json").read_text())["run_id"] == doc["run_id"]
    assert json.loads((tmp_path / "2026-11-09.json").read_text())["run_id"] == doc["run_id"]
    assert not list(tmp_path.glob("*.tmp"))


def test_parse_no_store_finds_the_json_after_the_packet_dump():
    stdout = (
        "=== Hermes External Researcher — lane=chatgpt mock ===\n"
        "REDACTED packet that WOULD be sent:\n"
        '{\n  "question": "x",\n  "context": {"a": 1}\n}\n'
        '{\n  "stored": false,\n  "sandbox": true,\n  "status": "sent",\n'
        '  "symbol": "ZRKT",\n  "recommendation": "A. Founder sold under a plan."\n}\n'
    )
    parsed = B._parse_no_store(stdout)
    assert parsed and parsed["status"] == "sent"
    assert parsed["recommendation"].startswith("A. Founder")


def test_parse_no_store_returns_none_when_absent():
    assert B._parse_no_store("nothing here\n") is None


def test_dry_run_writes_nothing_and_never_calls_a_provider(tmp_path, monkeypatch):
    root = tmp_path / "state"
    (root / "data" / "portfolios" / "state").mkdir(parents=True)
    (root / "data" / "portfolios" / "state" / "holdings.json").write_text(json.dumps(holdings_doc()))
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "data" / "runtime" / "macro_calendar.json").write_text(json.dumps({
        "dates": [{"date": "2026-11-10", "events": [{"name": "CPI (Oct)", "time_et": "08:30"}]}]
    }))
    (root / "data" / "portfolios" / "state" / "earnings_dates.json").write_text(
        json.dumps({"ZZEARN": {"earnings_date": "2026-11-12"}})
    )

    class DummyConn:
        def cursor(self):
            raise AssertionError("dry run must not reach the database in this test")

        def close(self):
            pass

    monkeypatch.setattr(B, "connect", lambda: DummyConn())
    for name, value in {
        "load_quotes": quotes(),
        "load_news": news(),
        "load_filings": {},
        "load_stops": stops(),
        "load_daily_bars": bars(),
        "load_cio_decisions": {},
        "load_risk_tier": risk(),
        "load_positions_current": {"as_of": None, "rows": []},
    }.items():
        monkeypatch.setattr(B, name, lambda *a, _v=value, **k: _v)

    rc = B.main(["--dry-run", "--as-of", "2026-11-09T05:50:00-05:00", "--state-root", str(root)])
    assert rc == 0
    assert not (root / "data" / "runtime" / "cio_overnight_brief").exists()
