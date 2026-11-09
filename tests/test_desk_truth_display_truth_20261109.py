"""Display truth (LQ-20261107-1646) — does the page show the thing itself?

The operator's defects (2026-11-09): a book total that did not move while its marks did (LQ-1645), a stopped-out
advice row the broker had already satisfied (LQ-1644), a header VIX that disagreed with the CIO card (LQ-1610) and a
badge tier painted against its own meter (LQ-1642). Each is a displayed value that disagrees with an independent
recomputation, and none of them is visible to a check that only asks "did the lane succeed".

Hermetic: the DB, the clock and the files are injected. Synthetic symbols and numbers only — the repository is public.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import desk_truth_monitor as DTM  # noqa: E402
from scripts.lib import since_close_card as SCC  # noqa: E402

CFG = DTM.load_config()
D = CFG["display_truth"]
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)   # Wed 14:00 ET: a trading day, in session
ALWAYS = lambda _now: True  # noqa: E731
NEVER = lambda _now: False  # noqa: E731

#: 100 x 10.00 + 50 x 10.00 + $1,234 cash = $2,734; day = 100 x (10.00 - 9.50) = $50
POSITIONS = [
    {"account_key": "schwab_taxable", "symbol": "ZQAA", "qty": 100, "is_cash": False, "asset_type": "equity",
     "as_of": "2026-10-21T17:55:00+00:00"},
    {"account_key": "schwab_rollover_ira", "symbol": "ZQAB", "qty": 50, "is_cash": False, "asset_type": "equity",
     "as_of": "2026-10-21T17:55:00+00:00"},
    {"account_key": "schwab_taxable", "symbol": "ZQCASH", "qty": 1234.0, "is_cash": True, "asset_type": "CASH",
     "as_of": "2026-10-21T17:55:00+00:00"},
]
QUOTES = [
    {"symbol": "ZQAA", "source": "finviz", "price": 10.0, "prev_close": 9.5, "fetched_at": "2026-10-21T17:58:00+00:00"},
    {"symbol": "ZQAB", "source": "finviz", "price": 10.0, "prev_close": 10.0, "fetched_at": "2026-10-21T17:58:00+00:00"},
]
STOPS = [
    {"symbol": "ZQAA", "account": "schwab_taxable", "order_id": "o-1", "stop_price": 8.0, "qty": 100,
     "status": "working", "captured_at": "2026-10-21T17:59:00+00:00"},
    {"symbol": "ZQAB", "account": "schwab_rollover_ira", "order_id": "o-2", "stop_price": 8.0, "qty": 50,
     "status": "working", "captured_at": "2026-10-21T17:59:00+00:00"},
]
OVERVIEW = {"total_value": 2734.0, "day_pnl": 50.0, "as_of": "2026-10-21T17:59:30+00:00",
            "accounts": [{"account": "schwab_taxable", "market_value": 2234.0},
                         {"account": "schwab_rollover_ira", "market_value": 500.0}]}


def _run(*, positions=None, quotes=None, stops=None, displayed=None, previous=None, session=True,
         now=NOW) -> dict:
    return DTM.display_truth(positions if positions is not None else POSITIONS,
                             quotes if quotes is not None else QUOTES,
                             stops if stops is not None else STOPS,
                             displayed if displayed is not None else {"overview": OVERVIEW},
                             D, now=now, session=session, previous=previous,
                             reconcile=SCC.reconcile_stop_advice)


def _codes(rep: dict) -> list[str]:
    return sorted(f["code"] for f in rep["findings"])


def _replay(*, overview=None, previous=None, stops=None, position_rows=None, quote_rows=None) -> dict:
    return _run(displayed={"overview": OVERVIEW if overview is None else overview}, previous=previous, stops=stops,
                positions=position_rows, quotes=quote_rows)


# ── the verdict matrix ──────────────────────────────────────────────────────────────────────────────────────────


def test_a_card_that_agrees_with_the_recomputation_is_ok_when_the_render_leg_is_on():
    cfg = json.loads(json.dumps(CFG))
    cfg["display_truth"]["render"]["enabled"] = True
    rep = DTM.display_truth(POSITIONS, QUOTES, STOPS, {"overview": OVERVIEW, "render": {"state": "OK"}},
                            cfg["display_truth"], now=NOW, session=True, reconcile=SCC.reconcile_stop_advice)
    assert rep["verdict"] == "OK" and rep["findings"] == []
    assert rep["recomputed"]["total"] == 2734.0 and rep["recomputed"]["cash"] == 1234.0
    assert rep["recomputed"]["day_pnl"] == 50.0


def test_a_new_alert_finding_is_degraded_and_a_survivor_is_broken():
    bad = dict(OVERVIEW, total_value=3234.0)                       # $500 off, over the $250 bound
    first = _replay(overview=bad)
    assert [f["code"] for f in first["findings"] if f["alert"]] == ["DT_TOTAL_MISMATCH"]
    assert first["verdict"] == "DEGRADED" and first["verdict_reason"].startswith("1 new alert finding")
    second = _replay(overview=bad, previous=first["carry"])          # same key on the next run: it survived
    assert second["verdict"] == "BROKEN"
    assert second["survived_after_heal"] == ["total"]


def test_a_stale_positions_snapshot_is_unverifiable_and_never_a_mismatch():
    stale = [dict(p, as_of="2026-10-21T15:00:00+00:00") for p in POSITIONS]   # 3 h old, bound 1 h
    rep = _replay(position_rows=stale, overview=dict(OVERVIEW, total_value=99999.0))
    assert rep["recomputed"]["status"] == "NOT_MEASURED"
    assert rep["recomputed"]["reason"] == "positions_snapshot_stale"
    assert rep["findings"] == []                     # nothing is compared against a book that is not current truth
    assert rep["verdict"] == "UNVERIFIABLE"


def test_nothing_displayed_readable_is_unverifiable_not_ok():
    rep = _run(displayed={"overview": None, "since_close": None})
    assert rep["verdict"] == "UNVERIFIABLE" and rep["verdict_reason"] == "nothing displayed was readable"


# ── the book ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_quote_that_is_missing_or_stale_leaves_the_books_not_measured():
    no_quote = _replay(overview=dict(OVERVIEW, total_value=1.0), quote_rows=[QUOTES[0]])
    assert no_quote["recomputed"]["status"] == "NOT_MEASURED"
    assert no_quote["recomputed"]["reason"] == "quotes_missing" and no_quote["recomputed"]["unpriced_symbols"] == ["ZQAB"]
    assert "DT_TOTAL_MISMATCH" not in _codes(no_quote)
    old = [dict(q, fetched_at="2026-10-21T17:20:00+00:00") for q in QUOTES]   # 40 min, bound 20
    stale = _replay(quote_rows=old, overview=dict(OVERVIEW, total_value=1.0))
    assert stale["recomputed"]["status"] == "NOT_MEASURED" and "DT_TOTAL_MISMATCH" not in _codes(stale)
    # outside the session an old quote is not by itself a reason to stop measuring the book
    overnight = _run(quotes=old, displayed={"overview": OVERVIEW}, session=False)
    assert overnight["recomputed"]["status"] == "MEASURED"


def test_one_account_value_other_than_the_book_is_an_account_mismatch():
    bad = dict(OVERVIEW, accounts=[{"account": "schwab_taxable", "market_value": 1200.0},
                                   {"account": "schwab_rollover_ira", "market_value": 500.0}])
    rep = _replay(overview=bad)
    assert _codes(rep) == ["DT_ACCOUNT_MISMATCH"]
    assert rep["findings"][0]["key"] == "account:schwab_taxable"


def test_a_day_pnl_that_was_never_remarked_is_a_mismatch():
    # marks say +$2.00 on ZQAA ($8.00 prev close): qty x (price - prev_close) = $200, the card still says $0
    rep = _replay(overview=dict(OVERVIEW, day_pnl=0.0),
                  quote_rows=[dict(QUOTES[0], prev_close=8.0), QUOTES[1]])
    assert _codes(rep) == ["DT_DAY_PNL_MISMATCH"]


def test_a_frozen_total_while_the_marks_moved_is_dt_frozen():
    prior = {"at": "2026-10-21T17:50:00+00:00", "displayed_total": 2734.0, "recomputed_total": 2734.0}
    moved = [dict(QUOTES[0], price=13.0), QUOTES[1]]                 # ZQAA moved $3: the book is $3,034 now
    rep = _run(quotes=moved, displayed={"overview": OVERVIEW}, previous=prior)
    assert "DT_FROZEN" in _codes(rep) and "DT_TOTAL_MISMATCH" in _codes(rep)
    frozen = [f for f in rep["findings"] if f["code"] == "DT_FROZEN"][0]
    assert frozen["evidence"]["prior_recomputed"] == 2734.0 and frozen["evidence"]["recomputed"] == 3034.0


def test_a_frozen_total_inside_the_gap_window_is_not_yet_a_finding():
    prior = {"at": "2026-10-21T17:58:00+00:00", "displayed_total": 2734.0, "recomputed_total": 2734.0}   # 2 min
    moved = [dict(QUOTES[0], price=13.0), QUOTES[1]]
    assert "DT_FROZEN" not in _codes(_run(quotes=moved, displayed={"overview": OVERVIEW}, previous=prior))


# ── the stop advice (LQ-1644 replayed) ────────────────────────────────────────────────────────────────────────


def _since_close(advice, stop_read=None) -> dict:
    return {"generated_at": "2026-10-21T17:01:00+00:00",
            "cio_brief": {"stop_advice": advice, "stop_read": stop_read}}


def _advice(symbol="ZQAA", account="schwab_taxable", answer="RAISE", held=100.0, suggested=9.0, **over):
    row = {"symbol": symbol, "account": account, "answer": answer, "held_qty": held, "suggested_stop": suggested}
    row.update(over)
    return row


def test_an_advice_row_the_broker_already_answers_is_a_satisfied_stop_advice():
    rep = _run(displayed={"overview": OVERVIEW, "since_close": _since_close([_advice(suggested=7.5)])})
    assert "DT_STOP_ADVICE_SATISFIED" in _codes(rep)
    f = [x for x in rep["findings"] if x["code"] == "DT_STOP_ADVICE_SATISFIED"][0]
    assert f["key"] == "advice:schwab_taxable:ZQAA" and f["evidence"]["best_stop"] == 8.0


def test_an_advice_the_book_does_not_answer_is_not_a_finding():
    rep = _run(displayed={"overview": OVERVIEW, "since_close": _since_close([_advice(suggested=9.0)])})   # stop 8.0
    assert "DT_STOP_ADVICE_SATISFIED" not in _codes(rep)
    # and a row the writer already settled is not re-reported: the card is not asking for it any more
    rep2 = _run(displayed={"overview": OVERVIEW,
                           "since_close": _since_close([_advice(suggested=7.5, state="done")])})
    assert "DT_STOP_ADVICE_SATISFIED" not in _codes(rep2)


def test_an_as_of_that_is_the_check_time_is_a_mislabel():
    read = {"status": "read", "as_of": "2026-10-21T18:00:00Z", "as_of_text": "Wed 10-21 · 2:00 PM ET",
            "checked_at": "2026-10-21T18:00:00Z", "rows": 2}
    rep = _run(displayed={"overview": OVERVIEW, "since_close": _since_close([_advice(suggested=9.0)], read)})
    assert "DT_ASOF_MISLABEL" in _codes(rep)
    honest = {"status": "read", "as_of": "2026-10-21T17:57:00Z", "as_of_text": "Wed 10-21 · 1:57 PM ET",
              "checked_at": "2026-10-21T18:00:00Z", "rows": 2}
    rep2 = _run(displayed={"overview": OVERVIEW, "since_close": _since_close([_advice(suggested=9.0)], honest)})
    assert "DT_ASOF_MISLABEL" not in _codes(rep2)


def test_a_position_without_a_working_stop_is_a_warn_never_an_alert():
    rep = _run(stops=[STOPS[0]], displayed={"overview": OVERVIEW})      # ZQAB uncovered
    assert "DT_STOP_UNCOVERED" in _codes(rep)
    f = [x for x in rep["findings"] if x["code"] == "DT_STOP_UNCOVERED"][0]
    assert f["alert"] is False and f["key"] == "uncovered:schwab_rollover_ira:ZQAB"
    assert rep["verdict"] == "DEGRADED" and rep["verdict_reason"].startswith("1 warn finding")


# ── the other two families ─────────────────────────────────────────────────────────────────────────────────────


def test_a_header_card_split_is_read_from_the_header_lanes_own_receipt():
    broken = {"verdict": "BROKEN", "contracts": {"vix": "BROKEN", "regime": "OK"},
              "reasons": {"vix": "header serves 18.2 while the card serves 19.4"}}
    rep = _run(displayed={"overview": OVERVIEW, "header_health": broken})
    assert _codes(rep) == ["DT_HEADER_CARD_SPLIT"] and "18.2" in rep["findings"][0]["detail"]
    assert rep["displayed"]["header_health_state"] == "BROKEN"
    # a DEGRADED vix contract (stale/undated headline) is that lane's finding, not a header/card split
    ok = _run(displayed={"overview": OVERVIEW, "header_health": {"contracts": {"vix": "DEGRADED"}}})
    assert "DT_HEADER_CARD_SPLIT" not in _codes(ok)
    # no receipt yet: the leg is missing, and a missing leg never invents a split
    assert _run(displayed={"overview": OVERVIEW})["displayed"]["header_health_state"] == "missing"


def test_a_badge_tier_painted_against_its_meter_is_a_contradiction():
    dom = {"drivers": [{"driver": "volatility", "tier": "low", "segment_state": "danger"},
                       {"driver": "breadth", "tier": "high", "segment_state": "red"}]}
    rep = _run(displayed={"overview": OVERVIEW, "dom": dom})
    assert _codes(rep) == ["DT_TIER_COLOR_CONTRADICTION"]
    assert rep["findings"][0]["evidence"] == {"driver": "volatility", "tier": "low", "segment_state": "danger"}


# ── the catalog, the heal plan and the wiring ──────────────────────────────────────────────────────────────────


def test_every_code_this_check_emits_is_in_the_catalog_and_the_catalog_has_no_orphans():
    emitted = {
        "DT_TOTAL_MISMATCH", "DT_ACCOUNT_MISMATCH", "DT_DAY_PNL_MISMATCH", "DT_FROZEN", "DT_STOP_ADVICE_SATISFIED",
        "DT_ASOF_MISLABEL", "DT_HEADER_CARD_SPLIT", "DT_TIER_COLOR_CONTRADICTION", "DT_STOP_UNCOVERED",
    }
    catalog = set(D["catalog"])
    assert emitted == catalog, f"catalog drift: only in code {emitted - catalog}, only in config {catalog - emitted}"
    assert {"DT_STOP_UNCOVERED"} == {c for c, v in D["catalog"].items() if not v["alert"]}


def test_the_heal_asks_the_owning_lane_to_re_run_and_never_writes_a_value():
    plan = DTM.plan_display_heal(
        ["DT_TOTAL_MISMATCH", "DT_STOP_ADVICE_SATISFIED", "DT_TIER_COLOR_CONTRADICTION"], D)
    assert plan["lanes"] == {"DT_STOP_ADVICE_SATISFIED": "since-close-snapshot", "DT_TOTAL_MISMATCH": "overview-projection"}
    assert plan["dispatch_lanes"] == ["overview-projection", "since-close-snapshot"]
    assert plan["unhealable"] == ["DT_TIER_COLOR_CONTRADICTION"]


def test_a_repeat_of_the_same_finding_queues_no_new_intent_and_a_fixed_card_is_clean():
    bad = dict(OVERVIEW, total_value=3234.0)
    first = _run(displayed={"overview": bad})
    report = {"alertable": first["carry"]["alertable"]}
    alert = DTM.plan_alert(report, [])                     # first sighting: one intent
    assert alert["queue"] and alert["gained"] == ["total"]
    second = _replay(overview=bad, previous=first["carry"])
    again = DTM.plan_alert({"alertable": second["carry"]["alertable"]}, alert["keys"])
    assert again["queue"] is False                         # a repeat is the same finding, not a new alert
    # the heal re-ran the owning lane and the projection now agrees: no finding, nothing survives
    cfg = json.loads(json.dumps(CFG))
    cfg["display_truth"]["render"]["enabled"] = True
    healed = DTM.display_truth(POSITIONS, QUOTES, STOPS, {"overview": OVERVIEW, "render": {"state": "OK"}},
                               cfg["display_truth"], now=NOW, session=True, previous=first["carry"],
                               reconcile=SCC.reconcile_stop_advice)
    assert healed["findings"] == [] and healed["verdict"] == "OK" and healed["survived_after_heal"] == []
    assert healed["heal"] == {"lanes": {}, "dispatch_lanes": [], "unhealable": []}


def test_the_check_is_a_dispatcher_lane_with_its_own_intent_route():
    assert DTM.CHECKS["display-truth"]["lane"] == "display-truth-monitor"
    routes = json.loads((ROOT / "config" / "host_comms_intent_routes.json").read_text(encoding="utf-8"))
    row = [r for r in routes["routes"] if r.get("producer") == "desk_truth_monitor"
           and r.get("kind") == DTM.CHECKS["display-truth"]["kind"]]
    assert row and row[0]["tier"] == "DIGEST" and row[0]["domain"] == DTM.CHECKS["display-truth"]["domain"]


def test_run_check_reports_the_display_truth_verdict_and_carries_its_totals():
    sources = {
        "positions_current": lambda: POSITIONS,
        "stop_last_known": lambda: STOPS,
        "market_quotes": lambda: QUOTES,
        "displayed": lambda: {"overview": OVERVIEW, "render": {"state": "SKIPPED"}},
        "previous_display": lambda: None,
    }
    rep = DTM.run_check("display-truth", now=NOW, cfg=CFG, sources=sources, trading_day=ALWAYS)
    assert rep["schema"] == "DeskTruthCheck@v1" and rep["check"] == "display-truth"
    assert rep["lane_id"] == "display-truth-monitor" and rep["verdict"] == "DEGRADED"
    assert rep["carry"]["displayed_total"] == 2734.0 and rep["carry"]["recomputed_total"] == 2734.0
    assert rep["alertable"] == [] and rep["heal"]["dispatch_lanes"] == []


def test_an_unreadable_positions_source_is_dependency_unavailable_never_clean():
    def boom():
        raise RuntimeError("db down")

    rep = DTM.run_check("display-truth", now=NOW, cfg=CFG,
                        sources={"positions_current": boom, "previous_display": lambda: None}, trading_day=ALWAYS)
    assert rep["error"].startswith("positions_current_unreadable") and "verdict" not in rep


def test_the_stop_read_built_for_the_advice_check_matches_the_briefs_working_set():
    assert set(D["working_stop_statuses"]) == set(SCC.WORKING_STOP_STATUSES)
    read = DTM._stop_read(STOPS + [{"symbol": "ZQAA", "account": "schwab_taxable", "stop_price": 8.0, "qty": 100,
                                    "status": "canceled", "captured_at": "2026-10-21T17:59:30+00:00"}], D, now=NOW)
    assert [s["account"] for s in read["stops"]["ZQAA"]] == ["schwab_taxable"]
    assert read["as_of"].isoformat().startswith("2026-10-21T17:59:30")
