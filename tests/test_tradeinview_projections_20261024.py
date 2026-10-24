"""Independent source-accounting and missing-data controls for TradeInView."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.data_broker import trade_calendar as cal
from lib.data_broker import tradeinview_sources as src
from lib.data_broker import holding_history as hist

NOW = datetime(2026, 11, 4, 17, tzinfo=timezone.utc)


def snapshot():
    return {"sources": {k: {"status": "ok", "rows": [], "truncated": False}
                        for k in ("schwab_round_trips", "trade_closed", "catalyst_events")},
            "files": {"holdings": {"status": "ok", "document": {"holdings": []}},
                      "reentry": {"status": "ok", "document": {"rows": []}}},
            "operator_membership": {"names": {"TSTA": {}}, "sources": {}}}


def roundtrip(**changes):
    return {"id": 901, "dedupe_key": "fixture-ledger-trip", "account": "schwab_roth",
            "symbol": "TSTA", "entry_time": "2026-10-28T14:15:00+00:00",
            "exit_time": "2026-11-02T15:25:00+00:00", "qty": 11,
            "entry_price": 41.25, "exit_price": 43.75, "net_pnl": 27.5,
            "pnl_pct": (43.75 / 41.25 - 1) * 100, "basis_status": None,
            "canary": False, **changes}


def test_explicit_month_uses_et_exit_instant_not_broker_trade_date_or_30_day_window():
    data = snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip(
        exit_time="2026-11-01T03:45:00+00:00", exit_trade_date="2026-11-01")]
    before = deepcopy(data)
    october = cal.build_calendar(data, {"month": "2026-10"}, now=NOW)
    november = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert october["summary"]["trade_count"] == 1
    assert october["summary"]["realized_pl"] == 27.5
    assert next(d for d in october["days"] if d["date"] == "2026-10-31")["trade_count"] == 1
    assert november["summary"]["trade_count"] == 0
    assert data == before


def test_derived_trade_closed_srt_link_does_not_double_count_and_retains_both_sources():
    data = snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip()]
    data["sources"]["trade_closed"]["rows"] = [{"id": 312, "dedupe_key": "srt:901",
        "symbol": "TSTA", "account": "schwab_roth_ira", "shares": 11, "pnl": 27.5}]
    out = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert out["summary"]["trade_count"] == 1 and out["summary"]["realized_pl"] == 27.5
    trade = next(d for d in out["days"] if d["known_trade_count"])["trades"][0]
    assert {p["source"] for p in trade["provenance"]} == {"schwab_round_trips", "trade_closed"}
    assert trade["account_id"] == "schwab_roth_ira"
    assert trade["account_label"] == "Schwab Roth IRA"


def test_similar_price_and_date_without_explicit_link_never_collapses_distinct_trades():
    data = snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip()]
    data["sources"]["trade_closed"]["rows"] = [{"id": 313, "dedupe_key": "separate-lot",
        "symbol": "TSTA", "account": "schwab_roth", "open_date": "2026-10-28",
        "close_date": "2026-11-02", "buy_price": 41.25, "sell_price": 43.75, "shares": 11, "pnl": 27.5}]
    out = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert out["summary"]["trade_count"] == 2


def test_disagreeing_explicit_copy_is_flagged_and_not_added_as_second_profit():
    data = snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip()]
    data["sources"]["trade_closed"]["rows"] = [{"id": 312, "dedupe_key": "srt:901",
        "symbol": "TSTA", "account": "schwab_roth", "shares": 11, "pnl": -4}]
    out = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert out["summary"]["realized_pl"] == 27.5
    assert any(g["reason"] == "derived SRT copy disagrees" for g in out["gaps"])


def test_unknown_basis_is_not_a_zero_profit_or_a_calibrated_win_rate():
    data = snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip(), roundtrip(
        id=902, dedupe_key="outside-ledger", entry_price=None, basis_status="basis_unknown", net_pnl=999)]
    out = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert out["summary"]["trade_count"] == 2
    assert out["summary"]["realized_pl"] is None
    assert out["summary"]["known_realized_pl"] == 27.5
    assert out["summary"]["green_days"] is None
    assert out["summary"]["unpriced_trade_count"] == 1


def test_successful_empty_collection_differs_from_unavailable_collection():
    data = snapshot()
    empty = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert empty["summary"]["trade_count"] == 0 and empty["summary"]["realized_pl"] == 0
    data["sources"]["schwab_round_trips"] = {"status": "missing", "reason": "database unavailable", "rows": []}
    missing = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert missing["summary"]["trade_count"] is None and missing["summary"]["realized_pl"] is None
    assert "schwab_round_trips" in missing["summary"]["coverage"]["missing_sources"]


@pytest.mark.parametrize("month", [None, "", "2026-13", "2026-1", "2026-11-01", "not-a-date"])
def test_month_is_explicit_and_validated(month):
    assert cal.build_calendar(snapshot(), {"month": month}, now=NOW)["ok"] is False


def test_account_alias_filter_and_source_reported_days_are_server_computed():
    data = snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip(), roundtrip(
        id=903, dedupe_key="another-account", account="schwab_rollover_ira", net_pnl=-9)]
    out = cal.build_calendar(data, {"month": "2026-11", "account": "schwab_roth"}, now=NOW)
    assert out["summary"]["realized_pl"] == 27.5
    assert out["summary"]["active_days"] == out["summary"]["green_days"] == 1
    assert len(out["weeks"][0]["days"]) == 5


def test_publication_without_an_earnings_date_never_becomes_an_earnings_day():
    data = snapshot()
    data["sources"]["catalyst_events"]["rows"] = [{"id": 801, "symbol": "TSTA",
        "catalyst_type": "earnings", "headline": "Stored report", "published_at": "2026-11-02T14:00:00Z"}]
    out = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert not out["events"]
    assert any(g["reason"] == "event date not recorded" for g in out["gaps"])


def test_dividend_is_not_guessed_to_be_ex_dividend_and_unknown_types_stay_other():
    data = snapshot()
    data["sources"]["catalyst_events"]["rows"] = [{"id": 802, "symbol": "TSTA",
        "catalyst_type": "dividend", "headline": "Stored dividend publication",
        "published_at": "2026-11-02T14:00:00Z", "created_at": "2026-11-02T14:01:00Z"}]
    out = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert out["events"][0]["type"] == "other"
    assert out["events"][0]["source_event_type"] == "dividend"
    assert out["events"][0]["missing_reason"] == "origin source not recorded"


def test_naive_timestamps_and_missing_dates_do_not_get_invented_close_times():
    assert src.instant("2026-11-02") is None
    assert src.instant("2026-11-02T10:12:00") is None
    assert src.day("2026-11-02") == "2026-11-02"
    assert src.number(True) is None and src.number(float("nan")) is None


def test_canary_trades_are_excluded_and_real_zero_return_is_preserved():
    data = snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip(canary=True), roundtrip(
        id=904, dedupe_key="actual-flat", net_pnl=0, pnl_pct=0)]
    out = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    assert out["summary"]["trade_count"] == 1 and out["summary"]["realized_pl"] == 0
    assert out["summary"]["green_days"] == 0


def test_calendar_uses_actual_reentry_window_end_and_preserves_the_producer_clock():
    data = snapshot()
    data["files"]["reentry"]["document"] = {
        "computed_at": "2026-11-02T14:12:00Z",
        "rows": [{"symbol": "TSTA", "wash_blocked": True, "wash_until": "2026-11-16"}],
    }
    out = cal.build_calendar(data, {"month": "2026-11"}, now=NOW)
    event, = [e for e in out["events"] if e["type"] == "wash_sale"]
    assert event["date"] == "2026-11-16"
    assert event["as_of"] == "2026-11-02T14:12:00+00:00"
    assert event["source"] == "reentry_decision_desk_latest.json"
    assert data["files"]["reentry"]["document"]["rows"][0]["wash_blocked"] is True


def history_snapshot():
    data = snapshot()
    data["sources"].update({n: {"status": "ok", "rows": [], "truncated": False}
                            for n in ("trade_transactions", "position_transfer_history")})
    data["files"].update({"legacy_journal": {"status": "ok", "document": {"closed_trades": []}},
                          "tax_lots": {"status": "ok", "document": {}}})
    return data


def old_trip(**changes):
    return {"symbol": "TSTA", "account": "schwab_roth_ira", "open_date": "2022-08-12",
            "close_date": "2022-10-05", "shares": 3, "buy_price": 12.5, "sell_price": 13,
            "cost_basis": 37.5, "pnl": 1.5, "pnl_pct": 4, **changes}


def test_history_merges_older_journal_and_current_ledger_without_a_30_day_default():
    data = history_snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip()]
    data["files"]["legacy_journal"]["document"]["closed_trades"] = [old_trip()]
    data["company_facts"] = {"TSTA": {"company": {"value": "Stored issuer name"}}}
    before = deepcopy(data)
    out = hist.build_history(data, {"range": "all", "symbol": "TSTA"}, now=NOW)
    assert out["range"]["start_date"] == "2022-08-12"
    assert out["detail"]["stats"]["round_trip_count"] == 2
    assert out["detail"]["stats"]["realized_pl"] == 29
    assert out["detail"]["company_name"] == "Stored issuer name"
    assert {r["source"] for r in out["detail"]["trips"]} == {"schwab_round_trips", "legacy_journal.closed_trades"}
    assert out["detail"]["stats"]["times_held"] is None, 'lot matches cannot prove holding transitions'
    assert data == before and out["provider_calls"] == out["writes"] == 0


def test_history_ever_account_membership_uses_aliases_and_transfer_evidence():
    data = history_snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip()]
    data["sources"]["position_transfer_history"]["rows"] = [{"symbol": "TSTA",
        "from_account": "schwab_roth", "to_account": "schwab_rollover_ira", "status": "recorded"}]
    out = hist.build_history(data, {"symbol": "TSTA"}, now=NOW)
    row, = out["symbols"]
    assert row["account_count"] == 2
    assert {a["account_label"] for a in row["accounts"]} == {"Schwab Roth IRA", "Schwab Rollover IRA"}
    assert row["held_now"] is None
    assert all(a["held_quantity"] is None for a in row["accounts"])


def test_history_never_uses_a_stored_mark_or_sale_proceeds_as_unknown_profit():
    data = history_snapshot()
    data["files"]["legacy_journal"]["document"]["closed_trades"] = [old_trip(), old_trip(
        open_date="2023-01-01", close_date="2023-02-01", cost_basis=None, pnl=9999)]
    out = hist.build_history(data, {"symbol": "TSTA"}, now=NOW)
    assert out["symbols"][0]["basis_unknown"] is True
    assert out["detail"]["stats"]["realized_pl"] is None
    assert out["detail"]["stats"]["known_realized_pl"] == 1.5
    assert out["detail"]["stats"]["win_rate_pct"] is None


def test_history_equal_legacy_occurrences_are_not_guessed_to_be_duplicate_trades():
    data = history_snapshot()
    data["files"]["legacy_journal"]["document"]["closed_trades"] = [old_trip(), old_trip()]
    out = hist.build_history(data, {"symbol": "TSTA"}, now=NOW)
    assert out["detail"]["stats"]["round_trip_count"] == 2
    assert len({r["trade_id"] for r in out["detail"]["trips"]}) == 2
    assert {r["provenance"][0]["occurrence"] for r in out["detail"]["trips"]} == {1, 2}


def test_history_unlinked_journal_ledger_overlap_retains_rows_but_withholds_a_complete_total():
    data = history_snapshot()
    data["sources"]["schwab_round_trips"]["rows"] = [roundtrip()]
    data["files"]["legacy_journal"]["document"]["closed_trades"] = [old_trip(close_date="2026-11-02")]
    out = hist.build_history(data, {"symbol": "TSTA"}, now=NOW)
    assert len(out["detail"]["trips"]) == 2
    assert out["detail"]["stats"]["round_trip_count"] is None
    assert out["detail"]["stats"]["realized_pl"] is None
    assert out["detail"]["stats"]["known_realized_pl"] is None
    assert out["detail"]["stats"]["observed_trip_rows"] == 2
    assert any('without an explicit trade link' in g["reason"] for g in out["gaps"])


def test_history_explicit_range_uses_source_dates_not_current_session():
    data = history_snapshot()
    data["files"]["legacy_journal"]["document"]["closed_trades"] = [old_trip(), old_trip(
        open_date="2023-01-01", close_date="2023-02-01")]
    out = hist.build_history(data, {"range": "dates", "start": "2022-01-01", "end": "2022-12-31",
                                    "symbol": "TSTA"}, now=NOW)
    assert out["detail"]["stats"]["round_trip_count"] == 1
    assert out["detail"]["trips"][0]["exit_date"] == "2022-10-05"
    assert hist.build_history(data, {"range": "dates"}, now=NOW)["ok"] is False


def test_history_current_quantity_uses_holdings_facts_without_promoting_snapshot_time_to_entry():
    data = history_snapshot()
    data["files"]["legacy_journal"]["document"]["closed_trades"] = [old_trip(), old_trip(
        open_date="2023-01-01", close_date="2023-02-01")]
    data["files"]["holdings"]["document"]["holdings"] = [{"symbol": "TSTA", "account": "schwab_roth",
        "shares": 7, "current_price": 9999, "provider_observed_at": "2026-11-02T16:00:00Z"}]
    out = hist.build_history(data, {"symbol": "TSTA"}, now=NOW)
    assert out["symbols"][0]["held_now"] is True
    assert out["symbols"][0]["accounts"][0]["held_quantity"] == 7
    observed, = [r for r in out["detail"]["account_segments"][0]["segments"]
                 if r["status"] == "current_holding_observation"]
    assert observed["start_at"] == observed["end_at"] == "2026-11-02T16:00:00+00:00"
    assert observed["precision"] == "snapshot only"
    assert out["detail"]["stats"]["realized_pl"] == 3
