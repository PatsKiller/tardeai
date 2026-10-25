"""Independent source-accounting and missing-data controls for TradeInView.

COVERS = ["scripts/api_v3_trade_journey.py", "scripts/lib/data_broker/trade_journey.py",
          "scripts/lib/data_broker/trade_calendar.py", "scripts/lib/data_broker/holding_history.py",
          "scripts/lib/data_broker/trade_replay.py", "scripts/lib/data_broker/tradeinview_sources.py",
          "scripts/lib/data_broker/catalog.py", "config/schemas/tradeinview_projection_v1.schema.json"]
"""
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
from lib.data_broker import trade_replay as replay
from lib.data_broker import trade_journey as journeys

NOW = datetime(2026, 11, 4, 17, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_projection_cache(monkeypatch):
    monkeypatch.setattr(src, "_SNAPSHOT_CACHE", {})


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


def test_calendar_pages_material_without_changing_month_week_or_day_totals():
    data = snapshot()
    data['sources']['schwab_round_trips']['rows'] = [roundtrip(id=n, dedupe_key=f'fixture-{n}') for n in range(170)]
    data['sources']['catalyst_events']['rows'] = [
        {'id':n,'symbol':'TSTA','catalyst_type':'catalyst','published_at':'2026-11-02T15:00:00Z',
         'headline':f'Fixture publication {n}','source':'fixture publisher'} for n in range(350)]
    before = deepcopy(data)
    first = cal.build_calendar(data, {'month':'2026-11'}, now=NOW)
    second = cal.build_calendar(data, {'month':'2026-11','event_offset':'50','day':'2026-11-02',
                                      'trade_offset':'50','trade_limit':'50','day_event_offset':'50'}, now=NOW)
    assert first['summary'] == second['summary'] and first['weeks'] == second['weeks']
    assert first['summary']['trade_count'] == 170 and first['summary']['realized_pl'] == 4675
    assert len(first['events']) == 50 and first['events_paging']['known_total'] == 350
    assert not {e['id'] for e in first['events']} & {e['id'] for e in second['events']}
    day = next(d for d in first['days'] if d['date']=='2026-11-02')
    expanded = next(d for d in second['days'] if d['date']=='2026-11-02')
    assert day['trade_count'] == expanded['trade_count'] == 170
    assert len(day['trades']) == 10 and len(day['events']) == 3
    assert len(expanded['trades']) == len(expanded['events']) == 50
    assert expanded['trades_paging']['next_offset'] == 100
    assert day['event_counts'] == {'catalyst':350}
    assert data == before


def test_calendar_truncated_event_source_exposes_observed_count_not_complete_count():
    data=snapshot()
    data['sources']['catalyst_events'].update(truncated=True, rows=[{
        'id':1,'symbol':'TSTA','catalyst_type':'catalyst','published_at':'2026-11-02T15:00:00Z',
        'headline':'Fixture event','source':'fixture publisher'}])
    out=cal.build_calendar(data, {'month':'2026-11'}, now=NOW)
    assert out['events_paging']['known_total']==1 and out['events_paging']['total_count'] is None
    assert out['summary']['trade_count']==0  # event completeness never changes closed-trip totals


@pytest.mark.parametrize('query',[
    {'event_offset':'-1'},{'event_limit':'0'},{'event_limit':'101'},
    {'day':'2026-10-31'},{'day':'2026-11-99'},{'trade_limit':True},
])
def test_calendar_refuses_invalid_page_or_cross_month_day(query):
    out=cal.build_calendar(snapshot(), {'month':'2026-11',**query}, now=NOW)
    assert out['ok'] is False and out['error']=='invalid_paging_or_day'


def replay_snapshot():
    data=snapshot()
    data['sources']['schwab_round_trips']['rows']=[roundtrip()]
    data['replay_bars']={'status':'ok','table':'market_ohlcv_bars','rows':[
        {'time':'2026-10-20T00:00:00Z','open':200,'high':250,'low':190,'close':220},
        {'time':'2026-10-28T00:00:00Z','open':41,'high':44,'low':40,'close':43},
        {'time':'2026-11-02T00:00:00Z','open':43,'high':45,'low':42,'close':43.75},
        {'time':'2026-11-03T00:00:00Z','open':2,'high':3,'low':1,'close':2},
    ]}
    data['sources']['stop_last_known']={'status':'ok','rows':[]}
    data['sources']['cio_opportunity_history']={'status':'ok','rows':[]}
    return data


def test_stored_replay_uses_session_key_and_only_held_range_for_server_metrics():
    data=replay_snapshot();before=deepcopy(data)
    out=replay.build_replay(data, {'trade_id':'rt:fixture-ledger-trip'}, now=NOW)
    assert out['ok'] and out['kind']=='candles' and out['available_intervals']==['1D']
    assert [b['time'] for b in out['bars']]==['2026-10-20','2026-10-28','2026-11-02','2026-11-03']
    assert out['bars'][1]['observed_at']=='2026-10-28T00:00:00+00:00'
    assert out['stats']['max_gain_pct']==round((45/41.25-1)*100,4)
    assert out['stats']['max_drawdown_pct']==round((40/41.25-1)*100,4)
    assert 'proxy' in out['stats']['metrics_basis']
    assert out['stats']['exit_kind']=='unknown'
    assert [m['kind'] for m in out['markers']]==['buy','sell']
    assert out['markers'][0]['at']=='2026-10-28T14:15:00+00:00'
    assert data==before and out['provider_calls']==out['writes']==0


def test_replay_close_only_never_fabricates_candles_and_unsupported_interval_refuses():
    data=replay_snapshot()
    data['replay_bars']={'status':'ok','table':'ticker_prices','rows':[{'time':'2026-10-28','close':42}]}
    out=replay.build_replay(data, {'trade_id':'rt:fixture-ledger-trip'}, now=NOW)
    assert out['kind']=='closes' and out['bars'][0]['high'] is None
    assert 'close-only proxy' in out['stats']['metrics_basis']
    denied=replay.build_replay(data, {'trade_id':'rt:fixture-ledger-trip','interval':'5m'}, now=NOW)
    assert denied['ok'] is False and denied['error']=='interval_not_stored'
    assert denied['available_intervals']==['1D'] and denied['bars']==[]


def test_replay_unknown_basis_missing_bars_remain_unmeasured():
    data=replay_snapshot();data.pop('replay_bars')
    data['sources']['schwab_round_trips']['rows'][0].update(basis_status='basis_unknown',net_pnl=999)
    out=replay.build_replay(data, {'trade_id':'rt:fixture-ledger-trip'}, now=NOW)
    assert out['kind']=='none' and out['trade']['realized_pl'] is None
    assert out['stats']['max_gain_pct'] is out['stats']['max_drawdown_pct'] is None
    assert any('bar coverage' in g['reason'] for g in out['gaps'])


def test_replay_annotations_match_account_symbol_and_actual_holding_instants():
    data=replay_snapshot()
    data['sources']['stop_last_known']['rows']=[
        {'symbol':'TSTA','account':'schwab_roth_ira','stop_price':40,'captured_at':'2026-10-28T14:20:00Z'},
        {'symbol':'TSTA','account':'schwab_roth','stop_price':100,'captured_at':'2026-10-28T14:00:00Z'},
        {'symbol':'TSTA','account':'schwab_taxable','stop_price':200,'captured_at':'2026-10-28T14:20:00Z'},
        {'symbol':'OTHER','account':'schwab_roth','stop_price':300,'captured_at':'2026-10-28T14:20:00Z'},
    ]
    data['sources']['cio_opportunity_history']['rows']=[
        {'symbol':'TSTA','written_at':'2026-10-29T16:00:00Z','assessment':{'stance':'watch','conviction':52}},
        {'symbol':'OTHER','written_at':'2026-10-29T16:00:00Z','assessment':{'stance':'avoid','conviction':1}},
    ]
    out=replay.build_replay(data, {'trade_id':'rt:fixture-ledger-trip'}, now=NOW)
    assert [m['price'] for m in out['markers'] if m['kind']=='stop']==[40]
    cio=[m for m in out['markers'] if m['kind']=='cio'];assert len(cio)==1 and '52' in cio[0]['label']


def test_derived_canary_copy_cannot_reenter_real_calendar_history_or_replay():
    data=snapshot();data['sources']['schwab_round_trips']['rows']=[roundtrip(canary=True)]
    data['sources']['trade_closed']['rows']=[{'id':20,'dedupe_key':'srt:901','symbol':'TSTA',
        'account':'schwab_roth','close_date':'2026-11-02','pnl':777,'buy_price':1}]
    out=cal.build_calendar(data, {'month':'2026-11'}, now=NOW)
    assert out['summary']['trade_count']==0 and out['summary']['realized_pl']==0
    assert replay.build_replay(data, {'trade_id':'rt:fixture-ledger-trip'}, now=NOW)['ok'] is False


def test_success_receipt_requires_successful_instant_never_file_generation_clock():
    missing={'status':'missing','written_at':NOW.isoformat()}
    assert journeys._successful_receipt(missing,NOW)[0] is None
    failed={'status':'ok','document':{'status':'failed','finished_at':NOW.isoformat(),'ok_at':NOW.isoformat()}}
    assert journeys._successful_receipt(failed,NOW)[0] is None
    future={'status':'ok','document':{'status':'ok','finished_at':'2026-11-05T17:00:00Z'}}
    assert journeys._successful_receipt(future,NOW)[0] is None
    undated={'status':'ok','document':{'status':'ok','finished_at':'2026-11-04'}}
    assert journeys._successful_receipt(undated,NOW)[0] is None
    real={'status':'ok','document':{'status':'ok','finished_at':'2026-11-04T16:00:00Z'}}
    assert journeys._successful_receipt(real,NOW)==('2026-11-04T16:00:00+00:00',None)


def test_registered_sync_uses_expression_and_dst_safe_clock_not_a_fixed_15_min_eta():
    registry={'lanes':[{'lane_id':'fixture_ingest','state':'ACTIVE','scheduler':{
        'kind':'cron','match':'scripts/schwab_transaction_ingest.py --apply','expression':'3,18,33,48 9-16 * * 1-5'}}]}
    friday=datetime(2026,10,30,20,49,tzinfo=timezone.utc)
    out=journeys._next_registered_sync(registry,friday)
    assert out['at']=='2026-11-02T09:03:00-05:00' and out['lane_id']=='fixture_ingest'
    assert 'intent' in out['basis']
    registry['lanes'][0]['state']='PAUSED'
    assert journeys._next_registered_sync(registry,friday)['at'] is None


def test_unknown_basis_journey_never_falls_back_to_sale_proceeds_as_profit():
    trade={'trade_id':'rt:unknown','symbol':'TSTA','status':'closed','basis_status':'basis_unknown',
           'entry_ref':0,'exit_ref':20,'fill_qty':100,'pl_amount':2000,'pl_pct':100}
    out=journeys.build_journey(trade,now=NOW)
    assert out['pl']['amount'] is out['pl']['pct'] is None and 'basis unknown' in out['pl']['note']


def test_history_discloses_mapping_sync_and_taxlot_disagreements_without_repair():
    data=snapshot();data['sources']['schwab_round_trips']['rows']=[roundtrip(),roundtrip(id=902,dedupe_key='second')]
    data['files']['holdings']['document']['holdings']=[{'symbol':'TSTA','account':'schwab_roth','shares':10,'cost_basis':300}]
    data['files']['tax_lots']={'status':'ok','document':{'fixture':[{
        'symbol':'TSTA','account':'schwab_roth_ira','shares_remaining':9,'cost_per_share':20,'closed':False}]}}
    out=hist.build_history(data, {'symbol':'TSTA'},now=NOW)
    reasons=[g['reason'] for g in out['gaps']]
    assert any('Fidelity mapping' in r for r in reasons) and any('successful sync receipt' in r for r in reasons)
    assert 'stored share quantities disagree' in reasons and 'stored cost basis disagrees' in reasons
    assert out['detail']['stats']['times_held'] is None
    assert out['symbols'][0]['accounts'][0]['held_quantity']==10


def schema_check(payload):
    import json
    from jsonschema import Draft202012Validator
    path=Path(__file__).resolve().parents[1]/'config/schemas/tradeinview_projection_v1.schema.json'
    Draft202012Validator(json.loads(path.read_text())).validate(payload)
    json.dumps(payload,allow_nan=False)


def test_actual_projection_api_wrappers_validate_schema_and_never_load_legacy_provider(monkeypatch):
    import api_v3_trade_journey as api
    import types
    provider=types.SimpleNamespace(trade_chart=lambda *_a,**_kw:pytest.fail('legacy provider reached'))
    monkeypatch.setitem(sys.modules,'ohlc_charts',provider)
    data=replay_snapshot()
    monkeypatch.setattr(src,'collect_snapshot',lambda **kw:deepcopy(data))
    calendar=api.get_calendar({'month':'2026-11'})
    history=api.get_history({'symbol':'TSTA','range':'all'})
    replay_out=api.get_replay({'trade_id':'rt:fixture-ledger-trip','stored_only':'1'})
    for out in [calendar,history,replay_out]:
        schema_check(out);assert out['provider_calls']==out['writes']==0
    assert replay_out['kind']=='candles' and replay_out['trade_id']=='rt:fixture-ledger-trip'


def test_invalid_calendar_history_or_missing_trade_id_refuses_before_collection(monkeypatch):
    import api_v3_trade_journey as api
    monkeypatch.setattr(src,'collect_snapshot',lambda **kw:pytest.fail('invalid request collected sources'))
    assert api.get_calendar({'month':'bad'})['ok'] is False
    assert api.get_history({'range':'recent'})['ok'] is False
    assert api.get_replay({})['ok'] is False


def test_collector_uses_only_injected_selects_and_creates_no_state(monkeypatch,tmp_path):
    import json
    root=tmp_path/'copy';root.mkdir()
    (root/'data/portfolios/state').mkdir(parents=True)
    (root/'data/portfolios/state/holdings.json').write_text(json.dumps({'holdings':[]}))
    before=sorted(str(p.relative_to(root)) for p in root.rglob('*'))
    seen=[]
    def read(sql,params=None):
        assert sql.lstrip().upper().startswith('SELECT ')
        seen.append((sql,params))
        if 'FROM schwab_round_trips' in sql:return [roundtrip()]
        if 'FROM market_ohlcv_bars' in sql:return [{'time':'2026-10-28','open':41,'high':44,'low':40,'close':43}]
        return []
    data=src.collect_snapshot(kind='replay',query={'trade_id':'rt:fixture-ledger-trip'},
                              db_query=read,state_root=root,repo_root=root,now=NOW)
    assert data['replay_bars']['table']=='market_ohlcv_bars'
    assert any('FROM stop_last_known' in sql for sql,_ in seen)
    assert any('FROM market_ohlcv_bars' in sql for sql,_ in seen)
    assert before==sorted(str(p.relative_to(root)) for p in root.rglob('*'))
    assert data['provider_calls']==data['writes']==0


def test_journey_redesign_separates_success_sync_observation_and_schedule_clocks(monkeypatch):
    import lib.cio_market_aware_freshness as freshness
    monkeypatch.setattr(freshness,'market_is_open',lambda now:True)
    row=journeys.build_journey({'trade_id':'open:schwab_roth_ira:TSTA','symbol':'TSTA','account':'schwab_roth',
        'status':'open','fill_qty':11,'entry_ref':41,'mark_ref':39,'mark_at':'2026-11-04T16:59:00Z'},
        stops=[{'stop_price':40,'status':'WORKING','captured_at':'2026-11-04T16:30:00Z'}],now=NOW)
    payload={'journeys':[row],'counts':{'open':1,'closed':0}}
    inputs={'trades_at':'2026-11-03T15:00:00Z','redesign_inputs':{
        'holdings_written_at':'2026-11-04T16:55:00Z',
        'ingest_receipt':{'status':'ok','document':{'status':'ok','finished_at':'2026-11-04T16:45:00Z'}},
        'stop_health_receipt':{'status':'ok','document':{'status':'ok','finished_at':'2026-11-04T16:00:00Z'}},
        'registry':{'status':'ok','document':{'lanes':[]}}}}
    out=journeys._add_redesign_fields(payload,inputs,NOW)
    chips={c['key']:c for c in out['freshness_chips']}
    assert chips['last_closing_fill']['at']=='2026-11-03T15:00:00Z'
    assert chips['ledger_sync']['at']=='2026-11-04T16:45:00+00:00'
    assert chips['holdings_sync']['at']=='2026-11-04T16:55:00Z'
    assert chips['stop_monitor']['tone']=='warning'
    assert chips['next_broker_sync']['at'] is None
    assert len(out['journeys'][0]['reconciliation_facts'])==3
    assert out['journeys'][0]['account_label']=='Schwab Roth IRA'
    assert out['counts']['all']==1 and out['counts']['awaiting_fill']==1
    assert out['journeys'][0]['exit_cause']['label']=='Awaiting fill'
    assert out['journeys'][0]['exit_cause']['tone']=='info'
    assert out['journeys'][0]['exit_cause']['confirmed'] is False
    assert out['journeys'][0]['re_entry']['condition_counts']['total'] is None


def test_catalog_declares_new_stored_read_projections_and_contracts():
    from lib.data_broker.catalog import PROJECTIONS
    rows={r['id']:r for r in PROJECTIONS}
    for key,schema in [('trade_calendar','TradeCalendar@v1'),('holding_history','HoldingHistory@v1'),('trade_replay','TradeReplay@v1')]:
        assert rows[key]['read_only'] is True and rows[key]['provider_calls']==0
        assert rows[key]['contract_version']==schema and rows[key]['http']


def test_snapshot_cache_bounds_broad_screens_and_preserves_original_collection_time(monkeypatch):
    import api_v3_trade_journey as api
    data=snapshot();data['as_of']='2026-11-04T16:00:00Z';calls=[];clock=[10.0]
    monkeypatch.setattr(src.time,'monotonic',lambda:clock[0])
    def collect(**kw):
        calls.append(kw['kind']);return deepcopy(data)
    monkeypatch.setattr(src,'collect_snapshot',collect)
    first=api.get_calendar({'month':'2026-11'})
    page=api.get_calendar({'month':'2026-11','event_offset':'50'})
    assert calls==['calendar'] and first['as_of']==page['as_of']==data['as_of']
    clock[0]+=61
    api.get_calendar({'month':'2026-11'})
    assert calls==['calendar','calendar']
    src.cached_snapshot(kind='history')
    assert set(src._SNAPSHOT_CACHE)=={'calendar','history'}
    src.cached_snapshot(kind='replay',query={'trade_id':'one'})
    assert set(src._SNAPSHOT_CACHE)=={'calendar','history'}  # no per-trade cache growth


def test_journey_holdings_clock_is_bound_to_the_document_actually_read(monkeypatch,tmp_path):
    import json,os
    from lib import portfolio_positions as pp
    root=tmp_path/'state';root.mkdir()
    path=root/'holdings.json';doc={'holdings':[{'symbol':'TSTA','account':'schwab_roth','shares':11}]}
    path.write_text(json.dumps(doc));os.utime(path,(1_793_720_000,1_793_720_000))
    monkeypatch.setattr(pp,'store_path',lambda:path)
    monkeypatch.setattr(journeys,'_state_root',lambda:root)
    result=journeys._redesign_inputs(NOW)
    assert result['holdings_document']==doc
    assert datetime.fromisoformat(result['holdings_written_at']).timestamp()==path.stat().st_mtime
    original=pp.load_store
    def changed(p=None):
        answer=original(p);path.write_text(json.dumps({'holdings':[]}));return answer
    monkeypatch.setattr(pp,'load_store',changed)
    drift=journeys._redesign_inputs(NOW)
    assert drift['holdings_document']==doc and drift['holdings_written_at'] is None
    assert 'changed during read' in drift['holdings_missing_reason']


def test_ci_declares_pinned_schema_validator_without_changing_draft_triggers():
    import yaml
    root=Path(__file__).resolve().parents[1]
    assert 'jsonschema==4.19.2' in (root/'requirements-ci-tradeinview.txt').read_text()
    workflow=yaml.load((root/'.github/workflows/cio-full-suite-sharded.yml').read_text(),Loader=yaml.BaseLoader)
    assert 'ready_for_review' in workflow['on']['pull_request']['types']
    for job in workflow['jobs'].values():
        for step in job.get('steps',[]):
            script=step.get('run','')
            if 'pip install pytest' in script:
                assert 'pip install -r requirements-ci-tradeinview.txt' in script
    assert workflow['concurrency']['cancel-in-progress']


def test_history_snapshot_only_dates_and_group_clocks_are_not_request_time():
    row={'symbol':'TSTA','account':'schwab_roth','shares':11,'broker_position_as_of':'2026-10-30'}
    group=hist._observed_segments([], [row], {'schwab_roth_ira'}, NOW)[0]
    assert group['as_of'] is None and group['generated_at']==NOW.isoformat()
    assert group['segments'][0]['start_date']=='2026-10-30'
    assert group['segments'][0]['start_at'] is None
    row['provider_observed_at']='2026-10-30T20:00:00Z'
    group=hist._observed_segments([], [row], {'schwab_roth_ira'}, NOW)[0]
    assert group['as_of']=='2026-10-30T20:00:00+00:00'


def test_calendar_unknown_name_scope_cannot_claim_complete_event_population():
    data=snapshot()
    data['sources']['catalyst_events']['rows']=[{'id':1,'symbol':'TSTA','catalyst_type':'catalyst',
        'published_at':'2026-11-02T15:00:00Z','headline':'Fixture event','source':'fixture publisher'}]
    data['operator_membership']['sources']={'starred':{'status':'error'}}
    data['files']['holdings']['status']='missing';data['files']['reentry']['status']='missing'
    out=cal.build_calendar(data,{'month':'2026-11'},now=NOW)
    assert out['events_paging']['known_total']==1 and out['events_paging']['total_count'] is None
    assert {g['source'] for g in out['gaps']} >= {'held-name scope','operator watchlist scope','reentry wash windows'}
    # Financial-source completeness is a separate denominator.
    assert out['summary']['trade_count']==0


def test_named_stored_document_malformed_shape_is_not_successful_source(tmp_path):
    path=tmp_path/'receipt.json';path.write_text('["invalid document shape"]')
    entry=src.bounded_json(path)
    assert entry['status']=='missing' and 'document' not in entry


@pytest.mark.parametrize('source',[None,'trade_closed','schwab_round_trips'])
def test_journey_never_invents_broker_or_table_provenance_when_origin_is_absent(source):
    trade={'trade_id':'fixture-source','symbol':'TSTA','status':'closed','fill_qty':11,
        'entry_at':'2026-10-28T14:15:00Z','exit_at':'2026-11-02T15:25:00Z','entry_ref':41.25,
        'exit_ref':43.75,'entry_source':source,'exit_source':source}
    row=journeys.build_journey(trade,now=NOW)
    payload=journeys._add_redesign_fields({'journeys':[row],'counts':{}},{},NOW)
    facts={f['key']:f for f in payload['journeys'][0]['reconciliation_facts']}
    assert facts['fills']['source'] is source and facts['holdings']['source'] is source
    event=next(e for e in payload['journeys'][0]['timeline'] if e['kind']=='exit_fill')
    assert event['source'] is source
    if source is None:
        assert 'origin' in facts['fills']['missing_reason'] and 'source unavailable' in facts['holdings']['missing_reason']
    else:
        assert facts['fills']['missing_reason'] is None
    schema_check({**payload,'schema':'TradeJourneys@v1','ok':True,'as_of':NOW.isoformat(),
        'provider_calls':0,'writes':0,'read_only':True,'gaps':[]})


def test_central_api_routes_reach_stored_projections_and_never_the_legacy_provider(monkeypatch):
    """Batch-28 coordinator: the owner-integration patch is applied in scripts/api_v2.py."""
    import types
    import api_v2
    provider=types.SimpleNamespace(trade_chart=lambda *_a,**_kw:pytest.fail('legacy provider reached'))
    monkeypatch.setitem(sys.modules,'ohlc_charts',provider)
    data=replay_snapshot()
    monkeypatch.setattr(src,'collect_snapshot',lambda **kw:deepcopy(data))
    status,calendar=api_v2.handle('/api/v3/data-broker/trade-calendar',method='GET',body=None,query={'month':['2026-11']})
    assert status==200 and calendar['schema']=='TradeCalendar@v1'
    status,history=api_v2.handle('/api/v3/data-broker/holding-history',method='GET',body=None,query={'symbol':['TSTA'],'range':['all']})
    assert status==200 and history['schema']=='HoldingHistory@v1'
    status,bad=api_v2.handle('/api/v3/data-broker/trade-calendar',method='GET',body=None,query={'month':['bad']})
    assert status==400 and bad['ok'] is False
    status,wrapped=api_v2.handle('/api/v2/trade-chart',method='GET',body=None,
                                 query={'trade_id':['rt:fixture-ledger-trip'],'stored_only':['1'],'interval':['1D']})
    assert status==200 and wrapped['data']['schema']=='TradeReplay@v1'
    assert wrapped['data']['kind']=='candles' and wrapped['data']['provider_calls']==0
    status,missing=api_v2.handle('/api/v2/trade-chart',method='GET',body=None,query={'stored_only':['1']})
    assert status==200 and missing['data']['ok'] is False
