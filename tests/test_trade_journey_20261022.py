"""TradeInView per-trade journey (operator directive 2026-10-22) — the ``trade_journey`` projection.

ANCHOR: TRADE_JOURNEY_20261022. Operator, verbatim: "navn was one of the top picks with the highest conviction. I got
into it a few days ago. I got stopped out today. I want to make sure that the trade and view actually tracks where that
stock came from. I didn't pick it on my own. It came from internal. It examines the ups and downs and what was the cause
of getting out and advises me on when to get back in. All on the same data backend. Not a separate work stream."

lib/data_broker/trade_journey.py builds one TradeJourney@v1 row per trade: origin (internal surface + rank +
conviction at entry + CIO entry call, the operator's pick, or unknown — never guessed), stop path, conviction/stance
changes, exit cause (stop-out / trailing ratchet / target / manual / stop likely filled), review (facts first, model
prose labelled advisory), re-entry (the re-entry desk record Watch reads) and conflicts (shown, never resolved).

The NAVN fixture below is also the frontend fixture (apps/command-center-v3/src/fixtures/tradeJourneys.fixture.ts):
``test_frontend_fixture_is_the_projection_output`` fails when the two drift. Regenerate with
``python tests/test_trade_journey_20261022.py --write-fixture``.

Fakes only: no database, no network, no broker, no production state (AGENTS.md §24.6).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import trade_journey as tj  # noqa: E402
from lib.cio_instrument_record import BEHAVIOR_FIELDS  # noqa: E402

NOW = datetime(2026, 10, 22, 21, 0, tzinfo=timezone.utc)  # 17:00 ET, after the close
FIXTURE_TS = ROOT / "apps" / "command-center-v3" / "src" / "fixtures" / "tradeJourneys.fixture.ts"

# ── NAVN, 2026-10-22 — real values ──────────────────────────────────────────
# Read-only captures of 2026-10-22 (state files here; journal + stop read as captured on feat/cio-prospect-p0-p1-20261022
# in tests/fixtures/cio_prospect/navn_20261022.json):
#   round trip srt:607228 schwab_rollover_ira: bought 2026-10-19 11:01:04 ET @ $25.64, sold 2026-10-22 15:59:21 ET
#     @ $26.02, net +$189.73;
#   stop read (operator, relayed): 24.31 → 24.59 → 24.70 → 24.97 → 25.51 → 25.61 → 26.02, all REPLACED, the last
#     FILLED — order ids and times not relayed (seq gives the order);
#   CIO opportunity history v25 10-15 #30 78.3 WATCH; v26 2026-10-16 13:00Z #4 85.6 WATCH ("conviction 78→86, rank
#     band 30→4"); v27 2026-10-22 15:30Z #1 87.6 ADD owned;
#   CIO entry state BUY_READY 2026-10-16 17:40Z (cio_events watch.new_signal, price 24.98, R:R 4.08);
#   holdings still list 500 sh (cost basis $12,820 = $25.64) at 16:30 ET; re-entry desk zone 24.80–25.10,
#     invalidation 23.90, target 30.00, price 26.02.
# Illustrative: the desk state WAIT and its criteria (today's desk row says CURRENTLY HELD), RSI 61, the model note.

NAVN_STOP_LEVELS = [24.31, 24.59, 24.70, 24.97, 25.51, 25.61, 26.02]


def navn_stops(account="schwab_rollover_ira"):
    """The relayed stop read: no capture times, ``seq`` gives the order."""
    return [{"account": account, "symbol": "NAVN", "order_id": f"navn-stop-{i + 1}", "order_type": "STOP",
             "stop_price": px, "status": "REPLACED" if i < len(NAVN_STOP_LEVELS) - 1 else "FILLED", "seq": i + 1,
             "origin": "operator stop read (relayed)"} for i, px in enumerate(NAVN_STOP_LEVELS)]


def navn_stops_timed(account="schwab_rollover_ira"):
    """The same levels as stop_last_known would hold them (capture times illustrative)."""
    times = ["2026-10-19T15:10:00+00:00", "2026-10-20T14:05:00+00:00", "2026-10-20T19:40:00+00:00",
             "2026-10-21T14:30:00+00:00", "2026-10-21T18:15:00+00:00", "2026-10-22T13:45:00+00:00",
             "2026-10-22T16:20:00+00:00"]
    return [{**r, "captured_at": at, "seq": None} for r, at in zip(navn_stops(account), times)]


NAVN_OPP_HISTORY = [
    {"version": 25, "written_at": "2026-10-15T19:00:00+00:00", "change_reasons": ["rank band 59→30"], "conviction": 78.3,
     "rank": 30, "stance": "WATCH", "position_status": "watchlist"},
    {"version": 26, "written_at": "2026-10-16T13:00:00+00:00",
     "change_reasons": ["conviction 78→86", "rank band 30→4", "entry level moved", "invalidation level moved",
                        "target level moved"], "conviction": 85.6, "rank": 4, "stance": "WATCH",
     "position_status": "watchlist"},
    {"version": 27, "written_at": "2026-10-22T15:30:00+00:00", "change_reasons": ["stance WATCH→ADD", "type new_position→add_on"],
     "conviction": 87.6, "rank": 1, "stance": "ADD", "position_status": "owned"},
]
NAVN_ENTRY_STATES = [
    {"symbol": "NAVN", "state": "BUY_READY", "prior_state": "NOT_YET", "evaluated_at": "2026-10-16T17:40:13+00:00"},
]
NAVN_OPP_NOW = {"symbol": "NAVN", "company": "Navan Inc", "conviction": 87.6, "rank": 1, "stance": "ADD",
                "position_status": "owned", "as_of": "2026-10-22T20:30:16+00:00"}
NAVN_DESK = {
    "symbol": "NAVN", "price": 26.02, "price_as_of": "2026-10-22T20:30:06+00:00", "entry_low": 24.8, "entry_high": 25.1,
    "stop": 23.9, "target": 30.0, "rsi": 61.0, "wash_blocked": False, "wash_until": None,
    "intel": {"state": "WAIT", "action": "Wait for the zone", "reason": "Price is above the re-entry zone.",
              "distance_pct": 3.665},
    "advisory": {"criteria": [
        {"id": "ma_bounce", "met": False, "label": "Moving average bounce / hold",
         "detail": "Not within 1.5% of SMA20/50/200 and not holding above SMA20"},
        {"id": "support", "met": True, "label": "Support / zone validation", "detail": "Resistance ABOVE @ $22.55"},
        {"id": "rsi_reset", "met": True, "label": "Momentum oscillator reset (RSI)", "detail": "RSI 61 in 40–70"},
        {"id": "rr", "met": False, "label": "Reward-to-risk (≥2:1 preferred; 3:1 ideal)", "detail": "R:R 1.88:1"},
        {"id": "invalidation", "met": True, "label": "Invalidation stop below structure", "detail": "Stop $23.90"},
        {"id": "catalyst", "met": True, "label": "Catalyst / earnings window clear", "detail": "Next earnings 2026-12-14"},
        {"id": "wash", "met": True, "label": "Wash-sale window clear", "detail": "Clear (IRA)"}]},
}
NAVN_INSIGHT = {"symbol": "NAVN", "success": True, "provider": "deepseek", "model_used": "deepseek-flash",
                "generated_at": "2026-10-22T20:45:00+00:00",
                "analysis_parsed": {"stop_quality": "well_managed",
                                    "stop_quality_reason": "The stop was trailed up six times and the exit kept a gain.",
                                    "reentry_risk": "medium", "reentry_risk_reason": "Price is above the zone.",
                                    "key_observation": "The exit came one day after the high of the move."}}


# Daily closes 2026-07-20 … 10-22 (ticker_prices via GET /api/v3/opportunities/NAVN, captured read-only 2026-10-22
# 20:35Z in tests/fixtures/cio_prospect/navn_20261022.json on feat/cio-prospect-p0-p1-20261022).
NAVN_CLOSES = [
    ("07-20", 27.74), ("07-21", 26.62), ("07-22", 23.565), ("07-23", 22.2), ("07-24", 23.21), ("07-27", 25.765), ("07-28", 26.35), ("07-29", 26.56),
    ("07-30", 26.735), ("07-31", 26.66), ("08-03", 27.46), ("08-04", 27.87), ("08-05", 27.635), ("08-06", 27.855), ("08-07", 29.085), ("08-08", 29.085),
    ("08-10", 28.67), ("08-11", 28.93), ("08-12", 28.78), ("08-13", 29.72), ("08-14", 29.25), ("08-17", 28.71), ("08-18", 29.2), ("08-19", 29.18),
    ("08-20", 28.555), ("08-21", 29.15), ("08-24", 29.365), ("08-25", 29.305), ("08-26", 29.33), ("08-27", 30.585), ("08-28", 28.49), ("08-31", 29.035),
    ("09-01", 27.31), ("09-02", 26.875), ("09-03", 27.71), ("09-04", 27.765), ("09-07", 27.765), ("09-08", 26.64), ("09-09", 25.92), ("09-10", 20.27),
    ("09-11", 21.01), ("09-14", 21.37), ("09-15", 22.4), ("09-16", 22.55), ("09-17", 22.12), ("09-18", 21.35), ("09-21", 21.52), ("09-22", 20.96),
    ("09-23", 19.655), ("09-24", 19.425), ("09-25", 19.415), ("09-28", 19.985), ("09-29", 20.67), ("09-30", 21.0), ("10-01", 21.505), ("10-02", 21.44),
    ("10-05", 21.82), ("10-06", 21.335), ("10-07", 22.28), ("10-08", 23.08), ("10-09", 23.645), ("10-12", 23.565), ("10-13", 23.9), ("10-14", 24.015),
    ("10-15", 25.205), ("10-16", 25.38), ("10-19", 25.67), ("10-20", 26.295), ("10-21", 26.625), ("10-22", 26.03),
]


def navn_bars():
    return [{"time": f"2026-{d}", "close": c} for d, c in NAVN_CLOSES]


NAVN_CLOSED = {"trade_id": "rt:srt:607228", "round_trip_key": "srt:607228",
               "symbol": "NAVN", "account": "schwab_rollover_ira", "status": "closed", "fill_qty": 500.0,
               "entry_at": "2026-10-19T15:01:04+00:00", "exit_at": "2026-10-22T19:59:21+00:00", "entry_ref": 25.64,
               "exit_ref": 26.02, "pl_amount": 189.73, "pl_pct": 1.48, "entry_source": "schwab_round_trips",
               "exit_source": "schwab_round_trips", "entry_detail": "swing", "company": "Navan Inc"}
# Today's live state: holdings still show the 500 sh (11:10 resync) while the 26.02 stop is at the mark.
NAVN_OPEN_UNSYNCED = {"trade_id": "open:schwab_rollover_ira:NAVN", "symbol": "NAVN", "account": "schwab_rollover_ira",
                      "status": "open", "fill_qty": 500.0, "entry_ref": 25.64, "entry_at": "2026-10-19T15:01:04+00:00",
                      "mark_ref": 26.02, "mark_at": "2026-10-22T20:30:06+00:00", "entry_source": "trade_transactions",
                      "holding": {"fill_qty": 500.0, "as_of": "2026-10-22", "mark_at": "2026-10-22T20:30:06+00:00"}}
OWN = {"trade_id": "rt:schwab_taxable|BAH|2026-10-02", "round_trip_key": "schwab_taxable|BAH|2026-10-02", "symbol": "BAH",
       "account": "schwab_taxable", "status": "closed", "fill_qty": 9.0, "entry_at": "2026-10-02T15:00:00+00:00",
       "exit_at": "2026-10-20T15:00:00+00:00", "entry_ref": 77.60, "exit_ref": 79.10, "pl_amount": 13.5, "pl_pct": 1.93,
       "entry_source": "schwab_round_trips", "exit_source": "schwab_round_trips"}
OPEN_V = {"trade_id": "open:schwab_roth_ira:V", "symbol": "V", "account": "schwab_roth_ira", "status": "open",
          "fill_qty": 130.5, "entry_ref": 307.48, "entry_at": None, "mark_ref": 411.23, "mark_at": "2026-10-22T20:00:00+00:00",
          "entry_source": "holdings avg cost", "holding": {"fill_qty": 130.5, "as_of": "2026-10-22"}}


def fixture_inputs(*, links_ok=True):
    return {
        "days": 30, "link_status": "ok" if links_ok else "unavailable",
        "links": {OWN["round_trip_key"]: {"round_trip_key": OWN["round_trip_key"], "origin": "operator_initiated",
                                          "rec_id": None, "link_confidence": None}} if links_ok else {},
        "recs": {},
        "opp_history": {"NAVN": NAVN_OPP_HISTORY}, "opp_now": {"NAVN": NAVN_OPP_NOW},
        "opp_at": "2026-10-22T20:30:18+00:00",
        "entry_states": {"NAVN": NAVN_ENTRY_STATES},
        "stops": {"NAVN": navn_stops(), "V": [{"account": "schwab_roth_ira", "symbol": "V", "order_id": "v1",
                                               "stop_price": 399.82, "status": "open",
                                               "captured_at": "2026-10-21T14:00:00+00:00"}]},
        "stops_at": None,
        "bars": {"NAVN": navn_bars()},
        "bars_meta": {"NAVN": {"kind": "closes", "source": "ticker_prices", "as_of": "2026-10-22"}},
        "desk_rows": {"NAVN": NAVN_DESK}, "desk_at": "2026-10-22T20:33:57+00:00",
        "insights": {"NAVN": NAVN_INSIGHT},
        "identities": {"NAVN": {"security_guid": "sec-navn-0001", "status": "CONFIRMED"}},
        "trades_at": "2026-10-22T16:31:00+00:00", "holdings_at": "2026-10-22",
        "gaps": [], "reads": ["fixture"], "cio_prospect_status": "absent",
    }


def build_fixture_payload():
    return tj.build_trade_journeys([NAVN_CLOSED, OWN, OPEN_V], inputs=fixture_inputs(), now=NOW)


def _walk_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_keys(v)


# ── stops and exit cause ─────────────────────────────────────────────────────


def test_stop_path_is_the_operator_sequence():
    entry = tj._ts(NAVN_CLOSED["entry_at"])
    for rows in (navn_stops(), navn_stops_timed()):  # relayed (seq, no times) and stop_last_known (timed)
        path = tj.stop_path(rows, start=entry, end=tj._ts(NAVN_CLOSED["exit_at"]))
        assert [p["level_ref"] for p in path] == NAVN_STOP_LEVELS
        assert [p["kind"] for p in path] == ["initial"] + ["raise"] * 6
        assert tj.stop_chain_label(path) == "24.31 → 24.59 → 24.70 → 24.97 → 25.51 → 25.61 → 26.02"
    assert all(p["at"] is None for p in tj.stop_path(navn_stops(), start=entry, end=None))  # never an invented time


def test_stop_path_keeps_the_level_working_at_entry_and_dedupes_reobservations():
    stops = [{"stop_price": 10.0, "captured_at": "2026-10-01T00:00:00+00:00"},
             {"stop_price": 10.0, "captured_at": "2026-10-03T00:00:00+00:00"},
             {"stop_price": 10.5, "captured_at": "2026-10-04T00:00:00+00:00"},
             {"stop_price": 9.0, "captured_at": "2026-10-09T00:00:00+00:00"}]
    path = tj.stop_path(stops, start=tj._ts("2026-10-02T00:00:00+00:00"), end=tj._ts("2026-10-05T00:00:00+00:00"))
    assert [p["level_ref"] for p in path] == [10.0, 10.5]
    assert path[1]["prior_ref"] == 10.0 and path[1]["change_pct"] == 5.0


def test_exit_trailing_ratchet_stop_out_target_manual():
    path = tj.stop_path(navn_stops(), start=None, end=None)
    c = tj.classify_exit(closed=True, entry_ref=25.64, exit_ref=26.02, path=path)
    assert c["kind"] == "trailing_ratchet" and c["raises"] == 6 and c["level_ref"] == 26.02
    assert "raised 6×" in c["detail"] and "locked in a gain" in c["detail"]
    # a raised stop still below the entry: a trailing stop that cut the loss
    c2 = tj.classify_exit(closed=True, entry_ref=26.50, exit_ref=26.00, path=path)
    assert c2["kind"] == "trailing_ratchet" and "cut the loss" in c2["detail"]
    # a gap through the stop is still the stop
    assert tj.classify_exit(closed=True, entry_ref=25.64, exit_ref=24.10, path=path)["kind"] == "trailing_ratchet"
    # a single unraised stop → stop-out
    one = tj.stop_path([{"stop_price": 24.31, "captured_at": "2026-10-19T15:00:00+00:00"}], start=None, end=None)
    assert tj.classify_exit(closed=True, entry_ref=25.64, exit_ref=24.20, path=one)["kind"] == "stop_out"
    # above the last stop and at the plan target → target; above the stop, below target → manual
    assert tj.classify_exit(closed=True, entry_ref=25.64, exit_ref=30.0, path=path, target_ref=30.0)["kind"] == "target"
    m = tj.classify_exit(closed=True, entry_ref=25.64, exit_ref=27.10, path=path, target_ref=30.0)
    assert m["kind"] == "manual" and "not a stop fill" in m["detail"]
    assert tj.classify_exit(closed=True, entry_ref=25.0, exit_ref=None, path=[])["kind"] == "unknown"
    nostop = tj.classify_exit(closed=True, entry_ref=25.0, exit_ref=26.0, path=[])
    assert nostop["kind"] == "unknown" and "no stop history" in nostop["detail"]


def test_open_position_with_mark_at_the_stop_is_stop_likely_filled_not_confirmed():
    path = tj.stop_path(navn_stops(), start=None, end=None)
    c = tj.classify_exit(closed=False, entry_ref=25.64, exit_ref=None, path=path, mark_ref=26.02,
                         mark_at="2026-10-22T20:30:06+00:00")
    assert c["kind"] == "stop_likely_filled" and c["confirmed"] is False
    assert tj.classify_exit(closed=False, entry_ref=25.64, exit_ref=None, path=path, mark_ref=27.05)["kind"] == "open"


# ── origin ───────────────────────────────────────────────────────────────────


def test_origin_internal_from_cio_history_and_entry_call():
    o = tj.origin_block(entry_at=tj._ts(NAVN_CLOSED["entry_at"]), link=None, rec=None, opp_history=NAVN_OPP_HISTORY,
                        entry_states=NAVN_ENTRY_STATES, link_status="unavailable")
    assert o["kind"] == "internal"
    assert o["label"] == "Home #4 · conviction 86 · CIO BUY_READY 10-16"
    assert o["rank_at_entry"] == 4 and o["conviction_at_entry"] == 85.6 and o["stance_at_entry"] == "WATCH"
    # v27 (rank 1, after the entry) is NOT the origin: origin is what was in force when the trade was entered
    assert all("v27" not in e["detail"] for e in o["evidence"])


def test_origin_from_recommendation_link_wins_and_names_the_surface():
    link = {"origin": "recommendation", "rec_id": "rec_cio_navn_1", "link_confidence": "exact"}
    rec = {"rec_id": "rec_cio_navn_1", "source": "cio_opportunity", "conviction_at_issue": 87.7, "stance": "BUY_SETUP",
           "created_at": "2026-10-16T13:00:00+00:00", "payload": {"rank": 1}, "entry_low": 24.8, "entry_high": 25.1,
           "plan_stop": 23.9, "plan_target": 30.0}
    o = tj.origin_block(entry_at=tj._ts(NAVN_CLOSED["entry_at"]), link=link, rec=rec, opp_history=NAVN_OPP_HISTORY,
                        entry_states=NAVN_ENTRY_STATES, link_status="ok")
    assert o["label"] == "Home #1 · conviction 88 · CIO BUY_READY 10-16"
    assert o["rec_id"] == "rec_cio_navn_1" and o["link_confidence"] == "exact"
    assert o["plan"] == {"entry_low_ref": 24.8, "entry_high_ref": 25.1, "invalidation_ref": 23.9, "target_ref": 30.0}


def test_origin_operator_only_when_the_linker_says_so_else_unknown():
    entry = tj._ts(OWN["entry_at"])
    own = tj.origin_block(entry_at=entry, link={"origin": "operator_initiated"}, rec=None, opp_history=[],
                          entry_states=[], link_status="ok")
    assert own["kind"] == "operator" and own["label"].startswith("Your pick")
    unk = tj.origin_block(entry_at=entry, link=None, rec=None, opp_history=[], entry_states=[], link_status="unavailable")
    assert unk["kind"] == "unknown" and "not available" in unk["label"]
    # an entry call older than 10 days is not an origin
    old = [{"state": "BUY_READY", "evaluated_at": "2026-09-01T00:00:00+00:00"}]
    assert tj.origin_block(entry_at=entry, link=None, rec=None, opp_history=[], entry_states=old,
                           link_status="ok")["kind"] == "unknown"


# ── the whole journey ────────────────────────────────────────────────────────


def test_navn_closed_journey_end_to_end():
    p = build_fixture_payload()
    navn = next(j for j in p["journeys"] if j["symbol"] == "NAVN")
    assert navn["origin"]["kind"] == "internal" and navn["origin"]["surface"] == "Home"
    assert navn["exit_cause"]["kind"] == "trailing_ratchet"
    kinds = [e["kind"] for e in navn["timeline"]]
    assert kinds[0] == "origin" and kinds[-1] == "exit_fill"
    assert kinds.count("stop_change") == 7 and "entry_fill" in kinds
    # v27 (11:30 ET) came while still held (exit 12:31 ET): the CIO moved WATCH → ADD and #4 → #1 during the trade
    assert any(e["kind"] == "stance_change" and "stance WATCH → ADD" in e["label"] and "rank #4 → #1" in e["label"]
               for e in navn["timeline"])
    stops = [e for e in navn["timeline"] if e["kind"] == "stop_change"]
    assert stops[1]["label"] == "Stop raised $24.31 → $24.59"
    # untimed stops sit between the entry and the exit, in seq order
    kinds_in_order = [e["kind"] for e in navn["timeline"]]
    assert kinds_in_order.index("entry_fill") < kinds_in_order.index("stop_change") < kinds_in_order.index("exit_fill")
    # review: facts first, advisory labelled
    facts = {f["key"]: f for f in navn["review"]["facts"]}
    assert facts["high"]["value"].startswith("$26.62")  # peak close 26.625 on 10-21
    assert facts["low"]["value"].startswith("$25.67")
    assert facts["captured"]["value"].startswith("39%")  # (26.02-25.64)/(26.625-25.64)
    assert facts["noise"]["value"].startswith("noise — gave back 2.27% from the high, trend intact")
    assert navn["review"]["metrics"]["stop_raises"] == 6
    assert navn["review"]["advisory"]["label"].startswith("Advisory — model output")
    assert navn["review"]["advisory"]["model"] == "deepseek-flash"
    # re-entry: the desk record + the exit reclaim reference, and the alert seed
    re = navn["re_entry"]
    assert re["state"] == "WAIT" and re["zone_low_ref"] == 24.8 and re["zone_high_ref"] == 25.1
    assert re["invalidation_ref"] == 23.9 and re["reclaim_ref"] == 26.02
    assert re["conditions"][-1]["id"] == "reclaim_exit" and re["conditions"][-1]["met"] is True
    assert re["alert_seed"] == {"entryLow": 24.8, "entryHigh": 25.1, "price": 26.02, "rsi": 61.0}
    assert "same record as Watch" in re["source"]
    # chart band
    assert navn["chart"]["kind"] == "closes" and navn["chart"]["marks"]["exit_ref"] == 26.02
    assert [s["level_ref"] for s in navn["chart"]["marks"]["stops"]][-1] == 26.02
    # conflict: CIO still says owned after the exit
    assert any(c["field"] == "position_status" for c in navn["conflicts"])


def test_navn_today_unsynced_is_flagged_not_hidden():
    p = tj.build_trade_journeys([NAVN_OPEN_UNSYNCED], inputs=fixture_inputs(), now=NOW)
    j = p["journeys"][0]
    assert j["status"] == "open" and j["exit_cause"]["kind"] == "stop_likely_filled"
    assert any(c["field"] == "position" for c in j["conflicts"])
    assert j["timeline"][-1]["kind"] == "exit_fill" and j["timeline"][-1]["unconfirmed"] is True
    assert j["re_entry"]["reclaim_ref"] == 26.02


def test_payload_is_labelled_interim_and_counts_origins():
    p = build_fixture_payload()
    assert p["schema"] == "TradeJourneys@v1" and p["interim"] is True
    assert p["source_label"] == tj.INTERIM_LABEL and p["source"]["kind"] == "interim"
    assert p["counts"] == {"open": 1, "closed": 2, "internal": 1, "operator": 1, "unknown": 1, "conflicts": 1}
    chips = {c["key"]: c for c in p["freshness"]}
    assert set(chips) == {"fills", "holdings", "stops", "cio", "reentry", "links", "source"}
    assert all(c["tip"] for c in p["freshness"])
    assert p["provider_calls"] == 0 and p["writes"] == 0


def test_no_behavior_field_anywhere_in_the_payload():
    keys = set(_walk_keys(build_fixture_payload()))
    assert not (keys & set(BEHAVIOR_FIELDS)), keys & set(BEHAVIOR_FIELDS)


# The cio_prospect record's position-lifecycle blocks, in the shape cio_prospect_lifecycle builds them on
# feat/cio-prospect-p0-p1-20261022 (attribute_origin / stop_path / classify_exit / post_exit_review / reentry_advice /
# lifecycle_events; conflicts as builder._conflict).
NAVN_PROSPECT = {
    "symbol": "NAVN", "security_guid": "1b1fd2bf-78cf-5755-bdea-9248cd007907", "stage": "exit",
    "stage_phase": "exit_review", "conviction": 86.6, "stance": "WATCH",
    "origin": {"classification": "internal",
               "summary": "From internal: cio_opportunity_curator opp:NAVN:v26 (zone); 2 surface(s) showed it before the entry fill",
               "linkage": {"source": "linkage rules over the CIO's own records (learning-loop tables not read)",
                           "rec_id": "opp:NAVN:v26", "rec_source": "cio_opportunity_curator", "link_confidence": "zone",
                           "origin": "recommendation", "plan_entry_zone": [24.8, 25.1], "plan_stop": 23.9,
                           "plan_target": 30.0, "rec_issued_at": "2026-10-16T13:00:13+00:00"},
               "at_entry": {"entry_fill_at": "2026-10-19T15:01:04+00:00", "entry_fill_price": 25.64, "surfaces": [
                   {"surface": "Home · Best opportunities (preset top5)", "shown": True, "rank": 4, "conviction": 85.6,
                    "stance": "WATCH", "record": "data/cio/cio_opportunity_assessments.jsonl NAVN:v26",
                    "at": "2026-10-16T13:00:13+00:00"},
                   {"surface": "CIO entry state (Telegram HIGH CONVICTION ENTRY card source)", "shown": True,
                    "state": "BUY_READY", "record": "data/cio/cio_events.jsonl evt-cb6ad4a5e735",
                    "at": "2026-10-16T17:40:13+00:00"}]}},
    "position_lifecycle": {"status": "closed", "round_trip_key": "srt:607228",
                           "exit_cause": {"class": "trailing_ratchet",
                                          "evidence": "exit 26.02 = observed stop 26.02 (FILLED); stop raised 6x from 24.31; exit above entry 25.64"}},
    "post_exit_review": {"facts": {"entry_price": 25.64, "exit_price": 26.02, "exit_vs_entry_pct": 1.48,
                                   "peak": {"price": 26.625, "at": "2026-10-21", "basis": "daily_close"},
                                   "trough": {"price": 25.67, "at": "2026-10-19", "basis": "daily_close"},
                                   "giveback_from_peak_pct": 2.27, "observed_stop_path": NAVN_STOP_LEVELS},
                         "noise_vs_trend": {"verdict": "noise", "basis": "close-basis giveback 2.27% from the peak close"},
                         "prose": None},
    "reentry_advice": {"state": "WAIT", "action": "Wait", "reason": "Price above the zone", "distance_pct": 3.67,
                       "conditions": [{"id": "conviction_floor", "text": "CIO conviction >= 70", "met": True, "value": 86.6},
                                      {"id": "reclaim", "text": "or a daily close back above 26.02 (the exit / resistance level) on volume",
                                       "met": False, "value": 26.02}],
                       "levels": {"entry_zone": [24.8, 25.1], "reclaim": 26.02, "price": 26.02,
                                  "price_as_of": "2026-10-22T20:30:16+00:00", "rsi": None}},
    "lifecycle_events": [
        {"event_type": "origin_attributed", "at": "2026-10-19T15:01:04+00:00",
         "change": {"classification": "internal", "rec_id": "opp:NAVN:v26", "link_confidence": "zone"}},
        {"event_type": "entry_fill", "at": "2026-10-19T15:01:04+00:00", "change": {"fill_price": 25.64}},
    ] + [{"event_type": "stop_change", "at": "2026-10-19T15:01:04+00:00",
          "change": {"stop_price_observed": px, "status": "REPLACED"}} for px in NAVN_STOP_LEVELS] + [
        {"event_type": "conviction_change", "at": "2026-10-22T15:30:14+00:00",
         "change": {"conviction": 87.6, "stance": "ADD", "rank": 1}},
        {"event_type": "excursion", "at": "2026-10-22T19:59:21+00:00", "change": {}},
        {"event_type": "exit_fill", "at": "2026-10-22T19:59:21+00:00",
         "change": {"fill_price": 26.02, "cause": "trailing_ratchet"}}],
    "conflicts": [{"field": "held", "values": [{"value": "held", "source": "positions[holdings]", "at": "2026-10-22"},
                                               {"value": "closed", "source": "schwab_round_trips srt:607228 exit fill",
                                                "at": "2026-10-22T19:59:21+00:00"}],
                   "resolved": False, "note": "the round trip closed after the last buy fill but the holdings file still lists it"}],
}


def test_cio_prospect_record_replaces_the_interim_blocks_when_the_store_is_live():
    p = tj.build_trade_journeys([NAVN_CLOSED], inputs=fixture_inputs(), now=NOW, prospects={"NAVN": NAVN_PROSPECT})
    j = p["journeys"][0]
    assert p["interim"] is False and p["source_label"] == tj.CIO_LABEL
    assert j["stage"] == "exit_review" and j["conviction_now"] == 86.6 and j["stance_now"] == "WATCH"
    assert j["origin"]["kind"] == "internal"
    assert j["origin"]["label"] == "Home #4 · conviction 86 · CIO BUY_READY 10-16"  # same words as the interim adapter
    assert j["origin"]["plan"]["target_ref"] == 30.0 and j["origin"]["rec_id"] == "opp:NAVN:v26"
    assert j["exit_cause"]["kind"] == "trailing_ratchet" and "raised 6x" in j["exit_cause"]["detail"]
    kinds = [e["kind"] for e in j["timeline"]]
    assert kinds[0] == "origin" and kinds[-1] == "exit_fill" and kinds.count("stop_change") == 7
    assert "excursion" not in kinds
    facts = {f["key"]: f["value"] for f in j["review"]["facts"]}
    assert facts["noise"].startswith("noise") and facts["stops"].endswith("26.02")
    assert j["review"]["advisory"] is None  # prose null until a registered capability exists
    re = j["re_entry"]
    assert re["state"] == "WAIT" and re["reclaim_ref"] == 26.02 and re["invalidation_ref"] == 23.9  # desk value kept
    assert re["alert_seed"]["entryLow"] == 24.8 and "same record as Watch" in re["source"]
    assert {c["field"] for c in j["conflicts"]} >= {"held", "position_status"}  # added, never merged away
    held = next(c for c in j["conflicts"] if c["field"] == "held")
    assert held["a"]["value"] == "held" and held["b"]["source"].startswith("schwab_round_trips")
    assert not (set(_walk_keys(p)) & set(BEHAVIOR_FIELDS))


def test_cio_prospect_lifecycle_for_another_trade_does_not_overwrite_this_one():
    other = {**NAVN_PROSPECT, "position_lifecycle": {**NAVN_PROSPECT["position_lifecycle"], "round_trip_key": "srt:1"}}
    j = tj.build_trade_journeys([NAVN_CLOSED], inputs=fixture_inputs(), now=NOW, prospects={"NAVN": other})["journeys"][0]
    assert j["origin"]["evidence"][0]["source"] == "cio_opportunity_assessments"  # interim origin kept
    assert j["stage"] == "exit_review" and any(c["field"] == "held" for c in j["conflicts"])


# ── the live gather, against fakes ───────────────────────────────────────────


class FakeDB:
    def __init__(self):
        self.sql: list[str] = []

    def __call__(self, sql, params=None, fetch="all"):
        s = " ".join(sql.split())
        self.sql.append(s)
        assert s.lstrip().upper().startswith("SELECT"), s  # read-only
        if "FROM schwab_round_trips" in s:
            return [{"id": 607228, "account": "schwab_rollover_ira", "symbol": "NAVN", "entry_time": NAVN_CLOSED["entry_at"],
                     "exit_time": NAVN_CLOSED["exit_at"], "qty": 500, "entry_price": 25.64, "exit_price": 26.02,
                     "net_pnl": 189.73, "pnl_pct": 1.48, "classification": "swing",
                     "dedupe_key": NAVN_CLOSED["round_trip_key"]}]
        if "FROM trade_recommendation_links" in s:
            raise RuntimeError('relation "trade_recommendation_links" does not exist')
        if "FROM cio_entry_states" in s:
            return NAVN_ENTRY_STATES
        if "FROM stop_last_known" in s:
            return navn_stops()
        if "FROM trade_transactions" in s:
            return []
        if "FROM ui_prefs" in s:
            return [{"value": {"insights": {"NAVN:quality": NAVN_INSIGHT}, "generated_at": "2026-10-22T20:45:00+00:00"}}]
        return []


def test_gather_reads_only_and_degrades_to_labelled_gaps(monkeypatch):
    from lib import portfolio_positions as pp
    from lib import cio_opportunity_store as cos
    monkeypatch.setattr(pp, "load_store", lambda path=None: {"as_of": "2026-10-22", "holdings": []})
    monkeypatch.setattr(cos.CIOOpportunityStore, "read_projection",
                        lambda self: {"as_of": "2026-10-22T20:30:18+00:00", "items": {"NAVN": NAVN_OPP_NOW}})
    monkeypatch.setattr(tj, "load_opportunity_history", lambda syms, event_path=None: {"NAVN": NAVN_OPP_HISTORY})
    monkeypatch.setattr(tj, "load_desk_snapshot", lambda path=None: ({"NAVN": NAVN_DESK}, "2026-10-22T20:33:57+00:00"))
    db = FakeDB()
    trades, inputs = tj.gather(db, days=30, now=NOW)
    assert [t["trade_id"] for t in trades] == [NAVN_CLOSED["trade_id"]]
    assert inputs["link_status"] == "unavailable"
    assert any(g["input"] == "trade_recommendation_links" for g in inputs["gaps"])
    p = tj.build_trade_journeys(trades, inputs=inputs, now=NOW)
    j = p["journeys"][0]
    assert j["origin"]["label"] == "Home #4 · conviction 86 · CIO BUY_READY 10-16"
    assert j["exit_cause"]["kind"] == "trailing_ratchet"
    assert all(not any(w in s.upper() for w in ("INSERT ", "UPDATE ", "DELETE ")) for s in db.sql)
    assert not any("positions_current" in s or "position_lots" in s for s in db.sql)


def test_open_position_without_a_ledger_buy_gets_an_approximate_entry_and_still_an_origin():
    t = {k: v for k, v in NAVN_OPEN_UNSYNCED.items() if k != "entry_at"}
    t["entry_source"] = "holdings avg cost"
    tj.approximate_entries([t], stops={"NAVN": navn_stops_timed()}, opp_history={"NAVN": NAVN_OPP_HISTORY})
    assert t["entry_at"] == "2026-10-19T15:10:00+00:00"  # the first observed stop beats v27 (10-22)
    assert t["entry_at_basis"].startswith("approximate — first stop observed")
    j = tj.build_trade_journeys([t], inputs={**fixture_inputs(), "stops": {"NAVN": navn_stops_timed()}}, now=NOW)["journeys"][0]
    assert j["origin"]["label"] == "Home #4 · conviction 86 · CIO BUY_READY 10-16"
    entry = next(e for e in j["timeline"] if e["kind"] == "entry_fill")
    assert entry["approximate"] is True and entry["label"].endswith("(date approximate)")
    assert j["entry"]["at_basis"].startswith("approximate")
    # no stops: just before the first CIO version that marks it owned → the version before it is the origin
    t2 = {k: v for k, v in t.items() if k not in ("entry_at", "entry_at_basis")}
    tj.approximate_entries([t2], stops={}, opp_history={"NAVN": NAVN_OPP_HISTORY})
    assert t2["entry_at"].startswith("2026-10-22T15:29:59")
    j2 = tj.build_trade_journeys([t2], inputs={**fixture_inputs(), "stops": {}}, now=NOW)["journeys"][0]
    assert j2["origin"]["rank_at_entry"] == 4


def test_desk_snapshot_and_history_readers(tmp_path):
    snap = tmp_path / "desk.json"
    snap.write_text(json.dumps({"computed_at": "2026-10-22T20:33:57+00:00", "rows": [NAVN_DESK]}), encoding="utf-8")
    rows, at = tj.load_desk_snapshot(snap)
    assert rows["NAVN"]["entry_low"] == 24.8 and at.startswith("2026-10-22")
    assert tj.load_desk_snapshot(tmp_path / "missing.json") == ({}, None)
    ev = tmp_path / "hist.jsonl"
    ev.write_text("\n".join(json.dumps({"symbol": "NAVN", "version": h["version"], "written_at": h["written_at"],
                                        "change_reasons": h["change_reasons"],
                                        "assessment": {"conviction": h["conviction"], "rank": h["rank"],
                                                       "stance": h["stance"]}}) for h in NAVN_OPP_HISTORY)
                  + '\n{"symbol": "NAVNX", "version": 1}\nnot json\n', encoding="utf-8")
    hist = tj.load_opportunity_history(["navn"], ev)
    assert [h["version"] for h in hist["NAVN"]] == [25, 26, 27]


def test_route_catalog_and_http_module():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert src.count('base_path.startswith("/api/v3/data-broker/trade-journeys")') == 1
    # the trade-journeys block must come before the generic data-broker block, which 404s unknown paths
    assert src.index("/api/v3/data-broker/trade-journeys") < src.index("# Canonical Data Broker — catalog")
    from lib.data_broker.catalog import PROJECTIONS
    ids = [p["id"] for p in PROJECTIONS]
    assert ids.count("trade_journey") == 1
    entry = next(p for p in PROJECTIONS if p["id"] == "trade_journey")
    assert entry["read_only"] is True and entry["provider_calls"] == 0
    import importlib
    mod = importlib.import_module("api_v3_trade_journey")
    assert callable(mod.get_list) and callable(mod.get_detail)


def test_module_reaches_no_broker_or_sender():
    src = (ROOT / "scripts" / "lib" / "data_broker" / "trade_journey.py").read_text(encoding="utf-8")
    for bad in ("brokers.", "schwab_transport", "place_order", "send_telegram", "telegram_alert_router",
                "market_quote_provider", "get_best_quote", "build_decision_desk(", "positions_current"):
        assert bad not in src.split('"""', 2)[-1], bad  # code, not the docstring


# ── the frontend fixture is this projection's output ─────────────────────────


def _fixture_text(payload) -> str:
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return ("/** GENERATED by tests/test_trade_journey_20261022.py --write-fixture — do not edit by hand.\n"
            " *  The NAVN trade-journey payload (TradeJourneys@v1) built by scripts/lib/data_broker/trade_journey.py from\n"
            " *  the fixture inputs in that test. The e2e spec and the model unit test read it, so the page is tested\n"
            " *  against the projection's real output shape. */\n"
            f"export const TRADE_JOURNEYS_FIXTURE = {body}\n")


def test_frontend_fixture_is_the_projection_output():
    assert FIXTURE_TS.read_text(encoding="utf-8") == _fixture_text(build_fixture_payload()), (
        "frontend fixture drifted; run: python tests/test_trade_journey_20261022.py --write-fixture")


if __name__ == "__main__":
    if "--write-fixture" in sys.argv:
        FIXTURE_TS.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_TS.write_text(_fixture_text(build_fixture_payload()), encoding="utf-8")
        print(f"wrote {FIXTURE_TS.relative_to(ROOT)}")
    else:
        sys.exit(pytest.main([__file__, "-q"]))
