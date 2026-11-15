"""Synthetic source-contract and calendar checks; no portfolio/provider access."""
import importlib.util
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone

import pytest

FILE = Path(__file__).resolve().parents[1] / "scripts/lib/wealth_home_v2.py"
SPEC = importlib.util.spec_from_file_location("wealth_home_v2_under_test", FILE)
home = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = home
SPEC.loader.exec_module(home)
NOW = datetime(2026,11,16,16,tzinfo=timezone.utc)


def pos(symbol="SYN",account="synthetic_a",value=123.45,shares=.125,**kw):
    return {"symbol":symbol,"account_id":account,"account_label":"Synthetic account", "market_value":value,"shares":shares,**kw}


def source(cells=None):
    return {"portfolio":{"total_usd":1000,"cash_usd":600,"day_pl_usd":-12.5,"day_pl_pct":-1.234,"day_pl_complete":True,"valuation_as_of":NOW.isoformat(),"quote_as_of":NOW.isoformat(),"accounts":[]},"positions":{"as_of":NOW.isoformat(),"rows":cells or []}}


@pytest.mark.parametrize("at,key",[("2026-11-16T08:59:00-05:00","pre_market"),("2026-11-16T09:30:00-05:00","regular"),("2026-11-16T16:00:00-05:00","after_hours"),("2026-11-16T20:00:00-05:00","closed"),("2026-11-15T21:00:00-05:00","closed"),("2026-11-26T12:00:00-05:00","closed"),("2026-11-27T12:59:00-05:00","regular"),("2026-11-27T13:00:00-05:00","after_hours")])
def test_exchange_sessions(at,key):
    assert home.session_clock(datetime.fromisoformat(at))["key"]==key


def test_holiday_next_open_and_early_close():
    clock=home.session_clock(datetime.fromisoformat("2026-11-26T12:00:00-05:00"))
    assert clock["last_session_date"]=="2026-11-25"
    assert clock["next_open"]=="2026-11-27T14:30:00Z"
    early=home.session_clock(datetime.fromisoformat("2026-11-27T12:00:00-05:00"))
    assert early["regular_close"]=="2026-11-27T18:00:00Z"


@pytest.mark.parametrize("value",[None,"2026-11-16 11:00:00","not time"])
def test_unqualified_clock_never_becomes_fresh(value):
    meta=home.source_meta("synthetic",value,60,now=NOW)
    assert meta["verdict"]=="unknown"
    assert meta["age_s"] is None


def test_future_clock_not_clamped_fresh():
    assert home.source_meta("synthetic",NOW+timedelta(minutes=1),60,now=NOW)["verdict"]=="unknown"


def test_missing_zero_and_negative_are_distinct():
    assert home.money(None) is None
    assert home.money(0)=="$0.00"
    assert home.money(-2.5,True)=="-$2.50"
    assert home.money(2.5,True)=="+$2.50"
    assert home.number(True) is None
    assert home.number(float("nan")) is None


def test_duplicates_and_fractional_shares_are_not_multiplied():
    rows=[pos("SYNA",value=111.125),pos("SYNA",value=111.125),pos("SYNA",account="synthetic_b",value=22.375)]
    exposure,rejected=home.exposure_by_symbol(rows)
    assert exposure["SYNA"]["value"]==133.5
    assert exposure["SYNA"]["known"]==exposure["SYNA"]["total"]==2
    assert exposure["SYNA"]["complete"] is True
    assert not rejected
    unique,_=home.unique_positions(rows)
    assert unique[0]["shares"]==.125


def test_selective_double_count_regression_not_global_division():
    # Synthetic symbols and values model both single/multiple-account amplification and a correct row.
    base=[pos("SYN_A",value=200.25),pos("SYN_A",account="synthetic_b",value=10.125),pos("SYN_B",value=35.75),pos("SYN_C",value=.45),pos("SYN_D",value=73.5),pos("SYN_E",value=81.125)]
    duplicates=base+[dict(r) for r in base[:-1]]
    actual,_=home.exposure_by_symbol(duplicates)
    assert {k:v["value"] for k,v in actual.items()}=={"SYN_A":210.375,"SYN_B":35.75,"SYN_C":.45,"SYN_D":73.5,"SYN_E":81.125}


def test_conflicting_identity_is_not_arbitrarily_selected():
    rows,rejected=home.unique_positions([pos(value=10),pos(value=20),pos(value=20),pos(account="",value=10)])
    assert rows==[]
    assert len(rejected)==2


def test_unknown_position_value_not_zero():
    result,_=home.exposure_by_symbol([pos(value=None)])
    assert result["SYN"]["value"] is None
    assert result["SYN"]["known"]==0


def test_build_has_exact_eight_color_cells_and_five_tiles():
    result=home.build(cio=source(),now=NOW)
    assert set(result["header"]["cells"])=={"session","session_pl","account_value","temperature","regime","vix","operating_mode","health"}
    assert all(c["state"] in {"green","amber","red","grey"} for c in result["header"]["cells"].values())
    assert len(result["today"]["tiles"]["metrics"])==5
    assert result["header"]["cells"]["account_value"]["value"]["cash_pct"]==60
    assert result["header"]["cells"]["session_pl"]["value"]["verified"] is False
    assert result["header"]["cells"]["session_pl"]["value"]["interval"]["session_date"] is None


def test_partial_day_coverage_is_amber_estimate():
    cio=source();cio["portfolio"].update(day_pl_complete=False,day_pl_gap="Synthetic missing mark")
    result=home.build(cio=cio,now=NOW)["header"]["cells"]["session_pl"]
    assert result["verdict"]=="partial"
    assert result["state"]=="amber"
    assert result["display"]=="-$12.50"
    assert "estimate" in result["label"].lower()


def test_pending_is_not_active_and_account_links_preserve_scope():
    rows=[pos("SYNA",stop_state="pending_activation",stop_category="pending_activation",stop_price=5,stop_captured_at=NOW.isoformat()),pos("SYNA",account="synthetic_b",stop_state="none",stop_category="none")]
    result=home.build(cio=source(rows),now=NOW)["today"]["stops"]["rows"]
    assert result[0]["facts"][0]["value"]=="Pending activation"
    assert result[0]["state"]=="amber"
    assert result[1]["state"]=="grey"  # Canonical applicability was not retained; no new classifier.
    assert "hv_account=synthetic_a" in result[0]["href"]
    assert "hv_query=SYNA" in result[0]["href"]
    assert result[0]["facts"][-1]["value"]=="0.125"


def test_news_acronym_and_exchange_tags_are_unverified_not_ranked_advice():
    market={"material_news":{"items":[{"symbol":"SYN","headlines":[{"title":"SYN 5090 hardware card","source":"Synthetic publisher","url":"https://example.invalid/story","published_at":NOW.isoformat()},{"title":"SYN:CA different venue","url":"javascript:alert(1)"}]}]}}
    result=home.build(cio=source([pos()]),market=market,now=NOW)
    rows=result["today"]["news"]["rows"]
    assert len(rows)==2
    assert all(r["candidate"] and r["issuerVerified"] is False for r in rows)
    assert all("detail" not in r for r in rows)
    assert rows[0]["label"]=="SYN 5090 hardware card"
    assert rows[0]["links"]==[{"label":"Original source","href":"https://example.invalid/story"}]
    assert rows[1]["links"]==[]
    assert not any(f["label"]=="Exposure" for r in rows for f in r["facts"])


def test_vix_always_neutral_with_original_print_clock():
    result=home.build(scanner={"vix":23.5,"vix_source":"synthetic_quote","vix_observation_time":NOW.isoformat()},now=NOW)["header"]["cells"]["vix"]
    assert result["state"]=="grey"
    assert result["clock"]=="2026-11-16T16:00:00Z"


def test_serve_cannot_recompute_or_mutate(monkeypatch):
    result=home.build(cio=source(),market={"as_of":NOW.isoformat(),"tier":"RED","score":90},now=NOW)
    monkeypatch.setattr(home,"build",lambda **_:pytest.fail("GET called build"))
    monkeypatch.setattr(home,"collect",lambda *_args,**_kw:pytest.fail("GET called collect"))
    served=home.serve(result,now=NOW+timedelta(hours=2))
    assert served["header"]["cells"]["temperature"]["verdict"]=="stale"
    assert served["header"]["cells"]["temperature"]["display"]=="RED · 90"
    assert result["header"]["cells"]["temperature"]["verdict"]=="known"
    assert served["built_at"]==result["built_at"]


def test_expired_product_remains_grey_with_value_retained():
    result=home.build(cio=source(),now=NOW)
    result["_product"]={"status":"UNKNOWN","greyed":True}
    cell=home.serve(result,now=NOW)["header"]["cells"]["account_value"]
    assert cell["state"]=="grey" and cell["verdict"]=="stale"
    assert cell["display"]=="$1,000.00"


def test_missing_product_returns_all_panels_no_fake_counts():
    result=home.serve(None,now=NOW)
    assert set(result["today"])==set(home.TODAY)
    assert set(result["outlook"])==set(home.OUTLOOK)
    assert set(result["needs"])==set(home.NEEDS)
    assert all(not sec["available"] for sec in result["today"].values())
    assert result["header"]["cells"]["account_value"]["value"] is None
    assert "queue_total" not in result or result["queue_total"] is None


def test_header_only_payload_and_closed_polling():
    h=home.serve(None,now=datetime(2026,11,15,20,tzinfo=timezone.utc),header_only=True)
    assert h["schema"]=="WealthOperatingHeader@v1"
    assert h["poll_after_s"]==300
    assert "today" not in h


def test_unsafe_article_urls_not_published():
    for value in ("javascript:alert(1)","file:///tmp/x","https://user:pass@example.invalid/x","/relative"):
        assert home.safe_url(value) is None


def test_canonical_protection_fields_retained_in_real_projection():
    from scripts.lib.w7_pages import project_pages
    row=pos(protection_state="EXEMPT",protection={"state":"EXEMPT","reason":"Synthetic canonical exemption","counted":False})
    result=project_pages(source([row]))
    assert result["positions"]["rows"][0]["protection_state"]=="EXEMPT"
    assert result["positions"]["rows"][0]["protection"]==row["protection"]


def test_active_positive_control_uses_stored_threshold_and_partial_coverage():
    row=pos(stop_state="active",protection_state="PROTECTED",broker_protected=True,stop_price=5,stop_captured_at=NOW.isoformat(),stop_source="synthetic_broker_read",resting_loss_qty=.1,resting_coverage_shortfall_qty=.025)
    cio=source([row]);cio["stops"]={"stale_after_hours":1}
    result=home.build(cio=cio,now=NOW)["today"]["stops"]["rows"][0]
    assert result["state"]=="amber"
    assert result["facts"][0]["value"]=="Partial resting coverage"
    row["resting_coverage_shortfall_qty"]=0
    assert home.build(cio=cio,now=NOW)["today"]["stops"]["rows"][0]["state"]=="green"


def test_unknown_source_shapes_collect_as_unknown_without_raising(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from scripts.lib.cc_products import cio_pages_route as cr,product_route as pr
    monkeypatch.setattr(cr,"serve_cio_pages",lambda **k:{"portfolio":{"gap":"Synthetic source down"},"_product":{"status":"UNKNOWN"}})
    monkeypatch.setattr(pr,"serve_market_risk_latest",lambda **k:{})
    result=home.collect(SimpleNamespace(db_query_raising=lambda *a,**k:None,portfolio_state_dir=tmp_path),{},now=NOW)
    assert result["header"]["cells"]["account_value"]["display"] is None
    assert result["today"]["stops"]["verdict"]!="known"


def test_real_home_builder_emitted_clock_survives_stored_route(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from scripts.lib.cc_products import builders as b,product_route as pr
    from scripts.lib import wealth_home_v2 as real_home
    ctx=SimpleNamespace(code_root=FILE.parents[2],portfolio_state_dir=tmp_path,db_query=lambda *a,**k:None,db_query_raising=lambda *a,**k:None,get_conn=lambda:None)
    b._scripts_on_path(ctx)
    import lib.since_close_card as sc
    import lib.home_incidents as inc
    import lib.home_priorities_live as pri
    import lib.home_status_live as status
    import lib.home_v010_api as gates
    monkeypatch.setattr(sc,"load_json",lambda p:None)
    monkeypatch.setattr(inc,"build",lambda q:{"snapshot":{"computed_at":NOW.isoformat()}})
    monkeypatch.setattr(pri,"build",lambda *a,**k:{})
    monkeypatch.setattr(status,"serve",lambda *a,**k:{"trade_ready":{"computed_at":NOW.isoformat(),"read_from":"snapshot","verdict":"YES"}})
    monkeypatch.setattr(gates,"home_gates",lambda *a,**k:{})
    monkeypatch.setattr(real_home,"collect",lambda ctx,slices,now:real_home.validate_contract(real_home.build(now=now)))
    built=b.build_home(ctx);body=built["data"];clock=body["slice_clocks"]["wealth_v2"]
    assert home.timestamp(clock["as_of"])==home.timestamp(body["slices"]["wealth_v2"]["built_at"])
    assert clock["clock_basis"]=="build_time"
    at=home.timestamp(clock["as_of"])
    reader=lambda *a,**k:{"status":"OK","data":body}
    stored=pr.serve_home_slice("wealth_v2",read_product=reader,now=at,hot=None)
    assert stored["_product"]["slice_stale"] is False
    served=home.serve(stored,now=at)
    assert served["header"]["cells"]["session"]["verdict"]=="known"
    ttl=body["slice_stale_after_s"]["wealth_v2"]
    assert ttl in (180,9000)  # Existing Home market/off-hours policy, not a new threshold.
    expired=at+timedelta(seconds=ttl+1)
    old=pr.serve_home_slice("wealth_v2",read_product=reader,now=expired,hot=None)
    assert old["_product"]["slice_stale"] is True
    assert home.serve(old,now=expired)["today"]["tiles"]["verdict"]=="stale"


def test_stored_context_guarded_facts_not_raw_fallback():
    market={"as_of":NOW.isoformat(),"home_v007":{"symbols":{"SYN":{"quote":{"state":"unknown","value":99},"day_change":{"state":"unknown","value":{"pct":5}},"next_event":{"state":"measured","source":"synthetic_calendar","as_of":NOW.isoformat(),"value":{"kind":"earnings","date":"2026-11-17"}},"headlines":{"state":"measured","source":"synthetic_news","as_of":NOW.isoformat(),"value":[{"title":"SYN hardware story","source":"Synthetic","url":"https://example.invalid/article","published_at":NOW.isoformat()}]}}}}}
    result=home.build(cio=source([pos()]),market=market,now=NOW)
    assert result["today"]["movers"]["rows"]==[]
    assert result["today"]["week"]["rows"][0]["facts"][1]["value"]=="Unconfirmed date-only event"
    assert result["today"]["news"]["rows"][0]["issuerVerified"] is False
    assert result["today"]["news"]["rows"][0]["label"]=="SYN hardware story"


def test_contract_presence_rejects_missing_slice_elements():
    result=home.build(now=NOW);home.validate_contract(result)
    result["header"]["cells"].pop("vix")
    with pytest.raises(ValueError,match="eight cells"):home.validate_contract(result)


def test_queue_counts_require_qualified_nonnegative_integer_population():
    for stamp,counts in ((None,{"protect":0,"decide":0,"fix":0}),(NOW.isoformat(),{"protect":-2,"decide":1.5,"fix":False})):
        result=home.build(cio={"do_now":{"as_of":stamp,"counts":counts}},now=NOW)
        metrics={f["label"]:f["value"] for f in result["needs"]["summary"]["metrics"]}
        assert metrics["Protect money"] is None and metrics["Decide"] is None and metrics["Fix system"] is None


def test_financial_clock_not_valuation_build_or_borrowed_day_mark_clock():
    c=source();c["portfolio"].update(valuation_as_of=NOW.isoformat(),quote_as_of=(NOW-timedelta(days=2)).isoformat(),clock_provenance={"day_pnl":{"as_of":None,"status":"UNKNOWN"}})
    result=home.build(cio=c,now=NOW)
    assert home.timestamp(result["header"]["cells"]["account_value"]["clock"])==NOW-timedelta(days=2)
    assert result["header"]["cells"]["session_pl"]["clock"] is None
    assert result["header"]["cells"]["account_value"]["value"]["batch_built_at"]==home.iso(NOW)


def test_complete_sector_universe_and_bounded_up_down_samples():
    market={"sectors":{"groups":[{"key":"tech","label":"Technology","kind":"sector","state":"RESILIENT"}]}}
    scanner={"top_gainers":[{"symbol":"UP"+str(i),"change_pct":i} for i in range(8)]}
    result=home.build(market=market,scanner=scanner,now=NOW)
    sectors=result["outlook"]["sectors"]["rows"]
    assert len(sectors)==11
    assert sum(r["state"]=="grey" for r in sectors)==10
    assert len(result["outlook"]["marketMovers"]["rows"])==5
    assert "Down sample not served" in result["outlook"]["marketMovers"]["notes"]
