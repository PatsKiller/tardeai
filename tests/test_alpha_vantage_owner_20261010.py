"""Alpha Vantage owner (operator 2026-10-10: "let's use Alpha Vantage for the gaps and prioritize which
gaps that really make sense").

One gateway, one budget (<= 23/day on both the UTC and the ET day, per-job allotments, >= 12 s
spacing), refusals up front (scope not granted, allotment, cap, provider exhausted, spacing), dry
runs that send and write nothing, receipts for every decision, projections with the read envelope,
and every former caller rerouted.

Hermetic: fake transport, fake key, tmp state dir. No network, no database, no real key.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import alpha_vantage_owner as avo  # noqa: E402

import alpha_vantage_owner as job  # noqa: E402  (scripts/alpha_vantage_owner.py)

CFG = avo.load_config()
KEY = "SECRETKEY123"
T0 = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)  # Mon 10:00 ET


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class Http:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, params, timeout):
        self.calls.append(dict(params))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _registry(tmp_path, supplies=("fundamentals",)):
    reg = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    reg["providers"]["alpha_vantage"]["supplies"] = list(supplies)
    p = tmp_path / "reg.json"
    p.write_text(json.dumps(reg))
    return p


def _owner(tmp_path, *, http=None, supplies=("fundamentals", "news_sentiment", "earnings_calendar"),
           clock=None, cfg=None, dry_run=False, key=KEY, sleeps=None, **kw):
    reports = kw.pop("reports", [])
    return avo.AlphaVantageOwner(
        config=cfg or copy.deepcopy(CFG), state=tmp_path / "av", http=http or Http(),
        key_loader=lambda: key, clock=clock or Clock(), sleeper=(sleeps.append if sleeps is not None else (lambda s: None)),
        registry_path=_registry(tmp_path, supplies), dry_run=dry_run,
        report=lambda *a, **k: reports.append((a, k)), **kw)


OK_QUOTE = (200, json.dumps({"Global Quote": {"05. price": "1.0"}}))
OK_OVERVIEW = (200, json.dumps({"Symbol": "AAA", "SharesFloat": "12500000"}))
QUOTA = (200, json.dumps({"Information": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."}))


# ── config invariants ────────────────────────────────────────────────────────


def test_committed_config_holds_every_budget_invariant():
    b = CFG["budget"]
    assert b["hard_daily_cap"] <= 23 and b["min_spacing_s"] >= 12
    assert sum(j["daily_allotment"] for j in CFG["jobs"].values()) <= b["hard_daily_cap"]
    assert CFG["jobs"]["earnings_calendar"]["daily_allotment"] == 1
    assert CFG["jobs"]["top_movers"]["daily_allotment"] == 0
    assert "let's use Alpha Vantage for the gaps" in CFG["operator_direction"]["quote"]


@pytest.mark.parametrize("mut", [
    lambda c: c["budget"].update(hard_daily_cap=24),
    lambda c: c["budget"].update(min_spacing_s=5),
    lambda c: c["jobs"]["news_sentiment_window"].update(daily_allotment=20),
    lambda c: c.update(schema="x"),
])
def test_config_that_breaks_an_invariant_is_refused(mut):
    c = copy.deepcopy(CFG)
    mut(c)
    with pytest.raises(avo.OwnerConfigError):
        avo.validate_config(c)


# ── refusals (never counted, never sent) ─────────────────────────────────────


def test_scope_not_granted_is_refused_up_front(tmp_path):
    http = Http()
    o = _owner(tmp_path, http=http, supplies=("fundamentals",))
    r = o.request("news_sentiment_window", {"time_from": "20261012T0900"})
    assert r.outcome == "refused_scope_not_granted" and not r.counted and http.calls == []
    assert not o.ledger_path.exists()
    rec = json.loads(o.receipts_path(T0).read_text().splitlines()[-1])
    assert rec["outcome"] == "refused_scope_not_granted" and rec["counted"] is False


def test_the_committed_registry_grants_fundamentals_only_today():
    assert avo.granted_domains() == {"fundamentals"}


@pytest.mark.parametrize("jobname,params,outcome", [
    ("nope", {}, "refused_unknown_job"),
    ("fundamentals_overview", {"function": "NEWS_SENTIMENT"}, "refused_wrong_function"),
    ("top_movers", {}, "refused_job_disabled"),
])
def test_job_rules(tmp_path, jobname, params, outcome):
    http = Http()
    assert _owner(tmp_path, http=http).request(jobname, params).outcome == outcome
    assert http.calls == []


def test_missing_key_is_refused(tmp_path):
    http = Http()
    assert _owner(tmp_path, http=http, key="").request("fundamentals_overview", {"symbol": "A"}).outcome == "refused_no_key"
    assert http.calls == []


def test_allotment_spent_refuses_and_does_not_count(tmp_path):
    clock = Clock()
    http = Http(OK_QUOTE)
    o = _owner(tmp_path, http=http, clock=clock)
    assert o.request("key_check", {"symbol": "IBM"}).ok
    clock.t += timedelta(minutes=5)
    r = o.request("key_check", {"symbol": "IBM"})
    assert r.outcome == "refused_job_allotment_spent" and not r.counted and len(http.calls) == 1
    u, e = avo.day_keys(clock.t)
    assert o.read_ledger()["days"][u]["total"] == 1


def test_hard_cap_counts_against_both_the_utc_and_the_et_day(tmp_path):
    # 22:00 ET Monday = 02:00 UTC Tuesday. The ET day already spent 23; the UTC day spent none.
    late = datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc)
    o = _owner(tmp_path, http=Http(), clock=Clock(late))
    u, e = avo.day_keys(late)
    assert (u, e) == ("2026-10-13", "2026-10-12")
    led = avo._empty_ledger()
    led["days"] = {e: {"total": 23, "jobs": {}}}
    o.state.mkdir(parents=True)
    o.ledger_path.write_text(json.dumps(led))
    r = o.request("fundamentals_overview", {"symbol": "A"})
    assert r.outcome == "refused_hard_cap" and not r.counted


def test_quota_notice_marks_the_day_and_the_next_call_is_refused(tmp_path):
    clock = Clock()
    http = Http(QUOTA)
    o = _owner(tmp_path, http=http, clock=clock)
    r = o.request("fundamentals_overview", {"symbol": "A"})
    assert r.outcome == "quota_notice" and r.counted and not r.ok
    clock.t += timedelta(minutes=1)
    assert o.request("fundamentals_overview", {"symbol": "B"}).outcome == "refused_provider_exhausted"
    assert len(http.calls) == 1


def test_spacing_waits_for_the_slot_and_refuses_beyond_max_wait(tmp_path):
    sleeps = []
    clock = Clock()
    o = _owner(tmp_path, http=Http(OK_OVERVIEW, OK_OVERVIEW), clock=clock, sleeps=sleeps)
    assert o.request("fundamentals_overview", {"symbol": "A"}).ok
    clock.t += timedelta(seconds=2)
    assert o.request("fundamentals_overview", {"symbol": "B"}).ok
    assert sleeps and abs(sleeps[0] - 10.0) < 0.01
    cfg = copy.deepcopy(CFG)
    cfg["budget"]["max_wait_s"] = 5
    o2 = _owner(tmp_path, http=Http(), clock=Clock(clock.t + timedelta(seconds=1)), cfg=cfg)
    assert o2.request("fundamentals_overview", {"symbol": "C"}).outcome == "refused_spacing_wait_exceeded"


# ── counted calls ────────────────────────────────────────────────────────────


def test_a_call_is_counted_before_it_is_sent_and_reported(tmp_path):
    http = Http(OK_OVERVIEW)
    reports = []
    o = _owner(tmp_path, http=http, reports=reports)
    r = o.request("fundamentals_overview", {"symbol": "AAA"})
    assert r.ok and r.counted and r.payload["Symbol"] == "AAA"
    assert http.calls == [{"function": "OVERVIEW", "symbol": "AAA", "apikey": KEY}]
    led = o.read_ledger()
    u, e = avo.day_keys(T0)
    assert led["days"][u]["jobs"]["fundamentals_overview"] == 1 and led["days"][e]["total"] == 1
    assert led["last_success"]["function"] == "OVERVIEW"
    assert reports and reports[0][0][:2] == ("alpha_vantage", True)


def test_network_error_is_counted_and_the_key_is_scrubbed(tmp_path):
    o = _owner(tmp_path, http=Http(ConnectionError(f"GET https://www.alphavantage.co/query?apikey={KEY} failed")))
    r = o.request("fundamentals_overview", {"symbol": "A"})
    assert r.outcome == "network_error" and r.counted
    assert KEY not in r.detail and "<KEY>" in r.detail
    blob = "".join(p.read_text() for p in o.state.iterdir() if p.is_file())
    assert KEY not in blob, "the key must never reach the ledger or receipts"


@pytest.mark.parametrize("status,text,outcome", [
    (200, "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\nI,n,f,o,r,m,a\n", "notice_in_csv"),
    (200, "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\nAAPL,Apple,2026-10-30,2026-09-30,1.6,USD,post-market\n", "ok"),
    (200, json.dumps({"Information": "Please consider spreading out your free API requests (1 request per second)"}), "burst_notice"),
    (200, json.dumps({"Information": "The **demo** API key is for demo purposes only. Please claim your free API key"}), "key_rejected"),
    (200, json.dumps({"Error Message": "the parameter apikey is invalid or missing"}), "key_rejected"),
    (200, json.dumps({"Information": "This is a premium endpoint."}), "information_notice"),
    (200, QUOTA[1], "quota_notice"),
    (200, "{}", "empty"),
    (503, "", "http_error"),
])
def test_classify(status, text, outcome):
    assert avo.classify(status, text)[0] == outcome


# ── dry run: decides everything, sends and writes nothing ────────────────────


def test_dry_run_sends_nothing_and_creates_nothing(tmp_path):
    def boom(params, timeout):
        raise AssertionError("dry run sent a request")
    o = avo.AlphaVantageOwner(config=copy.deepcopy(CFG), state=tmp_path / "av", http=boom, key_loader=lambda: KEY,
                              clock=Clock(), dry_run=True, scope_override={"fundamentals", "news_sentiment", "earnings_calendar"})
    for name in ("earnings_calendar", "news_sentiment_window", "fundamentals_overview"):
        r = o.request(name, {})
        assert r.outcome == "dry_run_would_call" and not r.counted
    assert o.requests_sent == 0 and not (tmp_path / "av").exists()


def test_scope_override_is_dry_run_only(tmp_path):
    with pytest.raises(ValueError):
        avo.AlphaVantageOwner(config=copy.deepcopy(CFG), state=tmp_path, http=Http(), key_loader=lambda: KEY,
                              dry_run=False, scope_override={"news_sentiment"})


def test_cli_dry_run_preview_spends_zero_and_writes_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADEAI_AV_OWNER_DIR", str(tmp_path / "av"))
    monkeypatch.setattr(avo, "_default_key", lambda: KEY)
    assert job.main(["--job", "all", "--preview-granted-scope"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["mode"] == "dry_run" and rep["requests_sent"] == 0
    assert rep["ledger_sha256_before"] is None and rep["ledger_sha256_after"] is None
    assert {j["outcome"] for j in rep["jobs"]} == {"dry_run_would_call"}
    assert not (tmp_path / "av").exists()
    assert KEY not in json.dumps(rep)


def test_cli_dry_run_without_the_grant_refuses_news_and_earnings(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADEAI_AV_OWNER_DIR", str(tmp_path / "av"))
    monkeypatch.setattr(avo, "_default_key", lambda: KEY)
    assert job.main(["--job", "all"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert {j["outcome"] for j in rep["jobs"]} == {"refused_scope_not_granted"} and rep["requests_sent"] == 0


def test_cli_refuses_a_live_preview():
    assert job.main(["--job", "all", "--apply", "--preview-granted-scope"]) == 2


# ── jobs: parse and publish ──────────────────────────────────────────────────

CAL = ("symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\n"
       "AAPL,Apple Inc,2026-10-30,2026-09-30,1.62,USD,post-market\n"
       "JPM,JPMorgan,2026-10-14,2026-09-30,4.9,USD,pre-market\n"
       "AAPL,Apple Inc,2027-01-29,2026-12-31,2.4,USD,post-market\n"
       "BAD,Bad,not-a-date,,,,\n")


def test_run_earnings_publishes_the_earliest_report_per_symbol(tmp_path):
    o = _owner(tmp_path, http=Http((200, CAL)))
    out = job.run_earnings(o, T0)
    assert out["published"] and out["rows"] == 2
    doc = json.loads((o.state / "earnings_calendar_latest.json").read_text())
    assert doc["schema"] == "EarningsCalendar@v1" and doc["by_symbol"]["AAPL"]["report_date"] == "2026-10-30"
    assert doc["by_symbol"]["JPM"]["time_of_day"] == "pre-market" and doc["with_time_of_day"] == 2


def test_run_earnings_keeps_the_previous_calendar_on_a_csv_notice(tmp_path):
    o = _owner(tmp_path, http=Http((200, CAL), (200, "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\nI,n,f,o,r,m,a\n")))
    job.run_earnings(o, T0)
    before = (o.state / "earnings_calendar_latest.json").read_text()
    o.cfg["jobs"]["earnings_calendar"]["daily_allotment"] = 2
    o._clock = Clock(T0 + timedelta(minutes=1))
    out = job.run_earnings(o, T0 + timedelta(minutes=1))
    assert out["outcome"] == "notice_in_csv" and out["published"] is False
    assert (o.state / "earnings_calendar_latest.json").read_text() == before


def _feed(*arts):
    return (200, json.dumps({"items": str(len(arts)), "feed": list(arts)}))


def _art(url, t, tickers, overall=0.1):
    return {"title": url, "url": url, "source": "Src", "time_published": t, "overall_sentiment_score": overall,
            "overall_sentiment_label": "Neutral", "topics": [{"topic": "Earnings"}],
            "ticker_sentiment": [{"ticker": s, "relevance_score": str(r), "ticker_sentiment_score": str(sc),
                                  "ticker_sentiment_label": "x"} for s, r, sc in tickers]}


def test_run_news_cursor_dedupe_and_weighted_index(tmp_path):
    clock = Clock()
    a1 = _art("u1", "20261012T133000", [("AAPL", 0.9, 0.5), ("MSFT", 0.2, -0.9)])
    a2 = _art("u2", "20261012T134500", [("AAPL", 0.3, -0.1)])
    http = Http(_feed(a1, a2), _feed(a2, _art("u3", "20261012T150000", [("NVDA", 0.8, 0.4)])))
    o = _owner(tmp_path, http=http, clock=clock)
    first = job.run_news(o, clock.t)
    assert first["published"] and first["cursor_gap"] is True
    assert http.calls[0]["time_from"] == (T0 - timedelta(hours=24)).strftime("%Y%m%dT%H%M")
    assert "tickers" not in http.calls[0], "a multi-ticker query is an AND; broad pulls carry no ticker filter"
    clock.t = T0 + timedelta(hours=1)
    second = job.run_news(o, clock.t)
    assert http.calls[1]["time_from"] == http.calls[0]["time_to"], "windows are contiguous"
    assert second["new"] == 1 and second["cursor_gap"] is False
    idx = json.loads((o.state / "news_sentiment_latest.json").read_text())
    aapl = idx["by_ticker"]["AAPL"]
    assert aapl["articles"] == 2 and aapl["weighted_score"] == round((0.9 * 0.5 + 0.3 * -0.1) / 1.2, 4)
    assert "MSFT" not in idx["by_ticker"], "relevance below 0.3 does not count"
    hist = list(o.state.glob("news_sentiment_articles_*.jsonl"))[0].read_text().splitlines()
    assert len(hist) == 3, "append-only history holds each article once"


def test_label_bands():
    assert [job.label_for(x) for x in (-0.5, -0.2, 0.0, 0.2, 0.5, None)] == [
        "Bearish", "Somewhat-Bearish", "Neutral", "Somewhat-Bullish", "Bullish", None]


def test_due_jobs_serves_each_slot_once():
    now = datetime(2026, 10, 12, 13, 50, tzinfo=timezone.utc)  # 09:50 ET
    due = job.due_jobs(CFG, now, {})
    assert ("earnings_calendar", "2026-10-12 06:05") in due and ("news_sentiment_window", "2026-10-12 09:45") in due
    assert job.due_jobs(CFG, now, dict(due)) == []


# ── projections ──────────────────────────────────────────────────────────────


def test_projections_read_the_files_with_the_envelope(tmp_path):
    from lib.data_broker import earnings_calendar as ec
    from lib.data_broker import news_sentiment as ns
    missing = ec.get_earnings(["AAPL"], base=tmp_path, now=T0)
    assert missing["symbols"] == {"AAPL": None} and missing["gap"]["kind"] == "no_coverage"
    assert missing["gap"]["declared_behaviour"] == "say_so" and missing["stale"] is True
    o = _owner(tmp_path, http=Http((200, CAL), _feed(_art("u1", "20261012T133000", [("AAPL", 0.9, 0.5)]))))
    job.run_earnings(o, T0)
    job.run_news(o, T0)
    e = ec.get_earnings(["aapl", "ZZZ"], base=o.state, now=T0 + timedelta(hours=2))
    assert e["symbols"]["AAPL"]["time_of_day"] == "post-market" and e["symbols"]["ZZZ"] is None
    assert e["stale"] is False and e["age_hours"] == 2.0 and e["source"]["writer"] == "scripts/alpha_vantage_owner.py"
    assert [r["symbol"] for r in ec.upcoming(3, base=o.state, now=datetime(2026, 10, 12, tzinfo=timezone.utc))["reports"]] == ["JPM"]
    s = ns.get_sentiment(["AAPL"], base=o.state, now=T0 + timedelta(hours=4))
    assert s["symbols"]["AAPL"]["label"] == "Bullish" and s["stale"] is True, "4 h old inside the trading window is stale"
    night = datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)  # 00:00 ET
    assert ns.get_sentiment(["AAPL"], base=o.state, now=night)["stale_after_hours"] == ns.STALE_AFTER_HOURS_CLOSED
    arts = ns.get_articles("AAPL", base=o.state, now=T0)
    assert arts["articles"][0]["ticker_score"] == 0.5


def test_catalog_advertises_both_projections():
    from lib.data_broker.catalog import PROJECTIONS
    by = {p["id"]: p for p in PROJECTIONS}
    for pid in ("earnings_calendar", "news_sentiment"):
        assert by[pid]["provider_calls"] == 0 and by[pid]["read_only"] is True and "PROPOSED" in by[pid]["authority_domain"]


# ── every former caller goes through the owner ───────────────────────────────


def test_alphavantage_host_appears_only_in_the_owner():
    hits = []
    for p in (ROOT / "scripts").rglob("*.py"):
        if "alphavantage.co" in p.read_text(encoding="utf-8", errors="replace"):
            hits.append(p.relative_to(ROOT).as_posix())
    assert hits == ["scripts/lib/alpha_vantage_owner.py"], hits


def test_catalyst_enrichment_reads_the_store_and_never_calls(monkeypatch, tmp_path):
    import catalyst_enrichment as ce
    monkeypatch.setattr(ce.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    monkeypatch.setattr(ce, "_env", lambda k, d="": {"ENABLE_ALPHA_VANTAGE_CATALYST": "true"}.get(k, d))
    from lib.data_broker import news_sentiment as ns
    monkeypatch.setattr(ns, "_load", lambda base: None)
    assert ce._fetch_alpha_vantage("AAPL") == [], "no store -> nothing, not a live call"
    o = _owner(tmp_path, http=Http(_feed(_art("u1", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"), [("AAPL", 0.9, 0.5)]))))
    job.run_news(o, datetime.now(timezone.utc))
    doc = json.loads((o.state / "news_sentiment_latest.json").read_text())
    monkeypatch.setattr(ns, "_load", lambda base: doc)
    got = ce._fetch_alpha_vantage("AAPL")
    assert got and got[0]["provider"] == "alpha_vantage" and got[0]["sentiment_score"] == 0.5


def test_overview_callers_go_through_the_owner(monkeypatch):
    import external_market_data_ingest as emdi
    seen = []

    class FakeOwner:
        def request(self, jobname, params):
            seen.append((jobname, params))
            return avo.OwnerResult(False, "refused_job_allotment_spent", jobname, "OVERVIEW", detail="spent")

    monkeypatch.setattr(avo, "AlphaVantageOwner", FakeOwner)
    data = emdi._av_overview("AAA", "ignored")
    assert "Symbol" not in data and "refused_job_allotment_spent" in data["Information"]
    import scalp_float_lookup as sfl
    assert sfl.alpha_vantage_float("BBB") is None
    assert seen == [("fundamentals_overview", {"symbol": "AAA"}), ("scalp_float", {"symbol": "BBB"})]


def test_key_checks_use_the_owner_last_success_and_spend_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_AV_OWNER_DIR", str(tmp_path / "av"))
    monkeypatch.setattr(avo, "_default_key", lambda: KEY)
    st = tmp_path / "av"
    st.mkdir()
    led = avo._empty_ledger()
    led["last_success"] = {"at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(), "job": "fundamentals_overview",
                           "function": "OVERVIEW", "outcome": "ok", "http_status": 200}
    (st / "budget_ledger.json").write_text(json.dumps(led))
    monkeypatch.setattr(avo, "_default_http", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    import credential_monitor as cm
    r = cm.check_alpha_vantage()
    assert r["status"] == "ok" and "no request spent" in r["detail"]
    import secret_validators as sv
    ok, detail = sv._alphavantage("unused")
    assert ok is True and KEY not in detail


def test_key_check_spends_one_from_the_reserve_only_when_unknown(tmp_path):
    http = Http(OK_QUOTE)
    o = _owner(tmp_path, http=http)
    ok, detail = avo.validate_key_via_owner(o)
    assert ok is True and http.calls[0]["function"] == "GLOBAL_QUOTE"
    ok2, _ = avo.validate_key_via_owner(o)
    assert ok2 is True and len(http.calls) == 1, "the second check reads the owner's success"


def test_newsapi_validator_sends_the_key_in_a_header(monkeypatch):
    import secret_validators as sv
    seen = {}

    class R:
        status_code = 200

        def json(self):
            return {"status": "ok"}

    def fake_get(url, headers=None):
        seen.update(url=url, headers=headers)
        return R()

    monkeypatch.setattr(sv, "_get", fake_get)
    ok, detail = sv._newsapi("NEWSKEY")
    assert ok and "NEWSKEY" not in seen["url"] and seen["headers"] == {"X-Api-Key": "NEWSKEY"}


def test_validator_exception_text_never_carries_the_key(monkeypatch):
    import secret_validators as sv
    monkeypatch.setattr(sv, "_key", lambda n: "LEAKME")
    monkeypatch.setitem(sv.VALIDATORS, "FRED_API_KEY", lambda k: (_ for _ in ()).throw(RuntimeError(f"GET ...&api_key={k} failed")))
    r = sv.validate("FRED_API_KEY")
    assert r["status"] == "check_failed" and "LEAKME" not in r["detail"]


# ── the registry proposal ────────────────────────────────────────────────────


def _apply_proposal(fill: bool) -> dict:
    reg = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    prop = json.loads((ROOT / "config" / "policy_proposals" / "data_source_authority_alpha_vantage_scope_20261010.json").read_text())
    grant = {"approved_by": "operator", "approved_on": "2026-10-11", "reference": "test grant"}
    for ch in prop["changes"]:
        if ch["id"] == "A1":
            new = copy.deepcopy(ch["set"])
            if fill:
                new["approval"].update(grant)
            else:
                new["approval"].update(approved_by="", approved_on="", reference="")
            reg["providers"]["alpha_vantage"].update(new)
        elif ch["id"] in ("A2", "A3"):
            row = copy.deepcopy(ch["row"])
            if fill:
                row["approval"].update(grant)
            else:
                row["approval"].update(approved_by="", approved_on="", reference="")
            reg["domains"].append(row)
    return reg


def test_proposal_rows_pass_the_gate_once_granted_and_fail_without_the_grant():
    import check_data_source_authority as gate
    granted = _apply_proposal(fill=True)
    assert gate.check_approvals(granted) == []
    assert gate.check_domains(granted) == []
    ungranted = _apply_proposal(fill=False)
    names = {f["name"] for f in gate.check_approvals(ungranted)}
    assert names == {"alpha_vantage", "earnings_calendar", "news_sentiment"}


def test_proposal_records_the_operator_quote_and_does_not_recommend_unretiring_newsapi():
    prop = json.loads((ROOT / "config" / "policy_proposals" / "data_source_authority_alpha_vantage_scope_20261010.json").read_text())
    assert prop["operator_direction"]["quote"] == CFG["operator_direction"]["quote"]
    n1 = next(c for c in prop["changes"] if c["id"] == "N1")
    assert n1["decision"].startswith("NOT RECOMMENDED") and re.search(r"24\.01 h", n1["why_not"])
