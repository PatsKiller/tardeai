"""Scalp float from Finviz via the data broker; Alpha Vantage OVERVIEW refused; health says idle.

Operator 2026-10-16, option A: "stop calling Alpha Vantage OVERVIEW for float; use the float data we
already have from Finviz via the data broker". Evidence: the owner's ``scalp_float`` job made 10
counted OVERVIEW calls 2026-10-12..16, every one "This is a premium endpoint" (classified as a generic
information_notice), 8 more were refused by its own allotment, 0 succeeded — and data_source_health
showed "alpha_vantage failing: last success 164h ago" although no caller could ever succeed.

Hermetic: injected broker cache / fake transport / tmp state dir. No network, no database, no key,
no Alpha Vantage or Finviz request.
"""
from __future__ import annotations

import copy
import inspect
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

for _name, _attrs in (("psycopg2", {"connect": lambda *a, **k: None}),
                      ("psycopg2.extras", {"RealDictCursor": object})):
    try:
        __import__(_name)
    except Exception:  # noqa: BLE001
        _m = types.ModuleType(_name)
        for _k, _v in _attrs.items():
            setattr(_m, _k, _v)
        sys.modules[_name] = _m

import scalp_float_lookup as sfl  # noqa: E402
import scalp_shadow_logger as ssl  # noqa: E402
from lib import alpha_vantage_owner as avo  # noqa: E402
from lib import data_source_health_view as dsv  # noqa: E402
from lib.data_broker import finviz_enrichment_snapshot as fes  # noqa: E402
import check_data_source_health as cdh  # noqa: E402

CFG = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text())
CFG["universe"]["shared_feeds"] = {**(CFG["universe"].get("shared_feeds") or {}), "enabled": False}
U = CFG["universe"]
AV_CFG = avo.load_config()
REGISTRY = json.loads((ROOT / "config" / "data_source_authority.json").read_text())

NOW = datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc)
PREMIUM_TEXT = ("Thank you for using Alpha Vantage! This is a premium endpoint. You may subscribe to any of "
                "the premium plans at https://www.alphavantage.co/premium/ to instantly unlock all premium endpoints")


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


# The Finviz enrichment cache as its writer stores it (float_m in millions; 0.0 = absent).
CACHE = {
    "SKYA": {"symbol": "SKYA", "float_m": 25.26, "cached_at": _iso(2)},
    "CWST": {"symbol": "CWST", "float_m": 62.23, "cached_at": _iso(30)},
    "TLX": {"symbol": "TLX", "float_m": 0.0, "cached_at": _iso(3)},          # Finviz shows no float
    "COLA": {"symbol": "COLA", "float_m": 2.77, "cached_at": _iso(24 * 9)},  # older than the window
    "EARN": {"symbol": "EARN", "float_m": 4.1},                              # no cached_at
}


def _broker(calls=None):
    """The real projection over an injected cache (no file, no provider)."""
    def b(symbols, *, max_age_hours, now):
        if calls is not None:
            calls.append((list(symbols), max_age_hours))
        return fes.get_enrichment_batch(symbols, max_age_hours=max_age_hours, now=now, cache=CACHE)
    return b


# ── 1. float comes from Finviz through the data broker ───────────────────────


def test_float_comes_from_finviz_through_the_broker():
    calls = []
    d = sfl.lookup_floats_detail(["skya", "CWST"], U, broker=_broker(calls), now=NOW.timestamp())
    assert calls == [(["SKYA", "CWST"], 168.0)]
    assert d["provider_calls"] == 0 and d["unavailable"] == {}
    assert d["found"]["SKYA"]["float_mm"] == 25.26 and d["found"]["CWST"]["float_mm"] == 62.23
    for row in d["found"].values():
        assert row["source"] == "finviz" and row["via"] == "data_broker.finviz_enrichment_snapshot"
        assert row["as_of"] and row["age_hours"] is not None
    assert d["envelope"]["source"]["projection"] == "finviz_enrichment_snapshot"


def test_default_broker_is_the_finviz_enrichment_projection(monkeypatch):
    seen = []
    real = fes.get_enrichment_batch

    def fake(symbols, **kw):
        seen.append((list(symbols), kw["max_age_hours"]))
        return real(symbols, cache=CACHE, max_age_hours=kw["max_age_hours"], now=NOW)
    monkeypatch.setattr(fes, "get_enrichment_batch", fake)
    out = sfl.lookup_floats(["SKYA"], U, now=NOW.timestamp())
    assert seen == [(["SKYA"], 168.0)] and out["SKYA"]["float_mm"] == 25.26


def test_consumer_output_shape_is_unchanged_and_the_universe_keeps_the_finviz_float():
    rows = [("SKYA", None, None, None, False), ("CWST", None, None, None, False), ("TLX", None, None, None, False)]

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            pass

        def fetchall(self):
            return list(rows)

    class Conn:
        def cursor(self):
            return Cur()
    lookup = lambda syms, u: sfl.lookup_floats(syms, u, broker=_broker(), now=NOW.timestamp())  # noqa: E731
    kept, excluded = ssl.resolve_universe_detail(Conn(), CFG, float_lookup=lookup)
    assert kept == ["SKYA"]
    assert excluded == {"CWST": "float_above_max", "TLX": "float_unknown"}


def test_the_lookup_makes_no_provider_call_of_any_kind():
    src = inspect.getsource(sfl)
    for banned in ("_av_overview", "alpha_vantage_owner", "AlphaVantageOwner", "_fetch_view",
                   "import finviz_enrichment", "requests", "urllib", "alphavantage.co"):
        assert banned not in src, banned
    assert not hasattr(sfl, "alpha_vantage_float") and not hasattr(sfl, "finviz_fetch")
    assert U["float_lookup"]["sources"] == ["finviz_broker"]


# ── 2. missing / stale / zero float -> explicit unavailable, never a number ──


def test_missing_float_is_explicitly_unavailable(capsys):
    out = sfl.lookup_floats(["TLX", "COLA", "EARN", "NOPE", "SKYA"], U, broker=_broker(), now=NOW.timestamp())
    assert set(out) == {"SKYA"}
    d = sfl.lookup_floats_detail(["TLX", "COLA", "EARN", "NOPE"], U, broker=_broker(), now=NOW.timestamp())
    assert d["found"] == {}
    assert d["unavailable"] == {
        "TLX": "Finviz Shs Float absent",
        "COLA": "Finviz record 216h old > 168h",
        "EARN": "Finviz record has no cached_at",
        "NOPE": "not in Finviz enrichment cache",
    }
    printed = capsys.readouterr().out
    assert "TLX float: unavailable (Finviz Shs Float absent)" in printed
    assert "NOPE float: unavailable (not in Finviz enrichment cache)" in printed


def test_broker_failure_makes_every_float_unavailable_with_the_reason():
    def boom(*a, **k):
        raise OSError("cache unreadable")
    d = sfl.lookup_floats_detail(["SKYA"], U, broker=boom, now=NOW.timestamp())
    assert d["found"] == {} and d["unavailable"] == {"SKYA": "finviz broker read failed: OSError"}


# ── 3. the owner refuses OVERVIEW with no HTTP call ───────────────────────────


class _NoHttp:
    calls = 0

    def __call__(self, params, timeout):
        _NoHttp.calls += 1
        raise AssertionError("an Alpha Vantage request was sent")


def _owner(tmp_path, *, dry_run=False):
    reports = []
    o = avo.AlphaVantageOwner(config=copy.deepcopy(AV_CFG), state=tmp_path / "av", http=_NoHttp(),
                              key_loader=lambda: "K", clock=lambda: NOW, sleeper=lambda s: None,
                              registry_path=ROOT / "config" / "data_source_authority.json", dry_run=dry_run,
                              report=lambda *a, **k: reports.append((a, k)))
    return o, reports


@pytest.mark.parametrize("job", ["scalp_float", "fundamentals_overview"])
def test_overview_is_refused_premium_with_no_http_call(tmp_path, job):
    o, reports = _owner(tmp_path)
    r = o.request(job, {"symbol": "SKYA"})
    assert r.outcome == "premium_endpoint_unavailable" and not r.ok and not r.counted
    assert o.requests_sent == 0 and _NoHttp.calls == 0 and reports == []
    assert not o.ledger_path.exists()                          # nothing counted
    rec = json.loads(o.receipts_path(NOW).read_text().splitlines()[-1])
    assert rec["outcome"] == "premium_endpoint_unavailable" and rec["counted"] is False and rec["http_status"] is None


def test_overview_refused_in_a_dry_run_too_and_nothing_written(tmp_path):
    o, _ = _owner(tmp_path, dry_run=True)
    assert o.request("scalp_float", {"symbol": "SKYA"}).outcome == "premium_endpoint_unavailable"
    assert o.requests_sent == 0 and not (tmp_path / "av").exists()


def test_config_disables_scalp_float_and_lists_overview_as_premium():
    sf = AV_CFG["jobs"]["scalp_float"]
    assert sf["daily_allotment"] == 0 and sf["class"] == "disabled" and "option A" in sf["why"]
    assert "OVERVIEW" in avo.premium_functions(AV_CFG)
    assert avo.job_callable(AV_CFG, "scalp_float")[0] is False
    assert avo.job_callable(AV_CFG, "fundamentals_overview") == (
        False, "fundamentals_overview: OVERVIEW is a premium endpoint (premium_endpoint_unavailable)")
    assert AV_CFG["jobs"]["fundamentals_overview"]["daily_allotment"] == 0
    assert avo.job_callable(AV_CFG, "earnings_calendar") == (True, "")
    assert "scalp_float" not in avo.active_jobs(AV_CFG)


def test_external_ingest_overview_path_gets_the_refusal_without_a_request(monkeypatch, tmp_path):
    import external_market_data_ingest as emdi
    monkeypatch.setenv("TRADEAI_AV_OWNER_DIR", str(tmp_path / "av"))
    monkeypatch.setattr(avo, "_default_http", _NoHttp())
    monkeypatch.setattr(avo, "_default_key", lambda: "K")
    data = emdi._av_overview("AAA", job="scalp_float")
    assert "Symbol" not in data and "premium_endpoint_unavailable" in data["Information"]


# ── 4. the premium text is classified ─────────────────────────────────────────


def test_premium_text_is_classified_not_a_generic_notice():
    outcome, payload = avo.classify(200, json.dumps({"Information": PREMIUM_TEXT}))
    assert outcome == "premium_endpoint_unavailable" and payload["Information"] == PREMIUM_TEXT
    assert avo.classify(200, json.dumps({"Information": "Some other notice"}))[0] == "information_notice"
    assert avo.classify(200, json.dumps({"Information": "standard API rate limit is 25 requests per day"}))[0] == "quota_notice"


# ── 5. health: idle / premium, not failing; a real failure stays a failure ────


# The live row on 2026-10-16: last success ~164 h ago, failure newer, last_error the premium notice.
AV_ROW = {"source_key": "alpha_vantage", "status": "error", "last_success_at": NOW - timedelta(hours=164),
          "last_failure_at": NOW - timedelta(hours=2), "last_error": f"information_notice: {PREMIUM_TEXT}"}


def test_alpha_vantage_with_no_active_caller_is_idle_not_failing():
    v = dsv.view_row(AV_ROW, NOW, REGISTRY)
    assert v["status"] == dsv.IDLE and v["scheduled_caller"] is False
    assert v["idle_reason"].startswith("no active callers (")
    assert "premium-endpoint notice" in v["idle_reason"]
    assert not dsv.SCHEDULED_CALLERS.get("alpha_vantage")      # --fundamentals reads Finviz since 10-16
    assert dsv.not_healthy_with_scheduled_caller([v]) == []
    assert cdh.idle_rows([v]) == [v]
    assert cdh._describe(v).startswith("idle: no active callers")


def test_aged_out_success_with_no_active_caller_is_idle():
    row = {"source_key": "alpha_vantage", "status": "healthy", "last_success_at": NOW - timedelta(hours=300)}
    v = dsv.view_row(row, NOW, REGISTRY)
    assert v["status"] == dsv.IDLE and dsv.not_healthy_with_scheduled_caller([v]) == []


def test_premium_error_with_an_active_caller_is_premium_unavailable_not_alerted(monkeypatch):
    monkeypatch.setitem(dsv.SCHEDULED_CALLERS, "alpha_vantage",
                        [{"script": "scripts/alpha_vantage_owner.py --job earnings_calendar", "cron": "5 6 * * *",
                          "owner_job": "earnings_calendar"}])
    v = dsv.view_row(AV_ROW, NOW, REGISTRY)
    assert v["status"] == dsv.PREMIUM_UNAVAILABLE and v["scheduled_caller"] is True
    assert "premium-endpoint notice" in v["idle_reason"]
    assert dsv.not_healthy_with_scheduled_caller([v]) == [] and cdh.idle_rows([v]) == [v]


@pytest.mark.parametrize("active", [True, False])
def test_a_real_failure_stays_a_failure(monkeypatch, active):
    if active:
        monkeypatch.setitem(dsv.SCHEDULED_CALLERS, "alpha_vantage",
                            [{"script": "x", "cron": "5 6 * * *", "owner_job": "earnings_calendar"}])
    row = dict(AV_ROW, last_error="error_message: Invalid API call for EARNINGS_CALENDAR")
    v = dsv.view_row(row, NOW, REGISTRY)
    assert v["status"] == dsv.ERROR and v["idle_reason"] is None
    if active:
        assert dsv.not_healthy_with_scheduled_caller([v]) == [v]


def test_other_sources_are_untouched():
    row = {"source_key": "fred", "status": "error", "last_success_at": NOW - timedelta(hours=50),
           "last_failure_at": NOW - timedelta(hours=1), "last_error": "HTTP 500"}
    v = dsv.view_row(row, NOW, REGISTRY)
    assert v["status"] == dsv.ERROR and v["scheduled_caller"] is True
    assert dsv.not_healthy_with_scheduled_caller([v]) == [v]


# ── 6. Monday --fundamentals reads stored Finviz (operator 2026-10-16 "Switch to Finviz") ──


import external_market_data_ingest as emdi  # noqa: E402

FUND_CACHE = {
    "V": {"cached_at": _iso(4), "market_cap_usd": 748499270000.0, "pe": 34.41, "forward_pe": 26.65, "peg": 1.88,
          "div_yield_pct": 0.67, "profit_margin_pct": 50.35, "roe_pct": 60.67, "total_debt_equity": 0.68, "beta": 0.83},
    "CLF": {"cached_at": _iso(4), "market_cap_usd": 6925780000.0, "pe": None, "forward_pe": 15.4, "peg": None,
            "div_yield_pct": None, "profit_margin_pct": -4.56, "roe_pct": -15.16, "total_debt_equity": 1.37, "beta": 2.05},
    "OLD": {"cached_at": _iso(24 * 10), "pe": 9.0},
}


def _fund_broker(calls=None):
    def b(symbols, *, max_age_hours):
        if calls is not None:
            calls.append((list(symbols), max_age_hours))
        return fes.get_enrichment_batch(symbols, max_age_hours=max_age_hours, now=NOW, cache=FUND_CACHE)
    return b


class _FCur:
    def __init__(self):
        self.rows = []

    def execute(self, sql, params=None):
        assert "INSERT INTO fundamental_data" in sql
        self.rows.append(params)


class _FConn:
    def __init__(self):
        self.c, self.committed, self.closed = _FCur(), False, False

    def cursor(self):
        return self.c

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _boom(*a, **k):
    raise AssertionError("must not be called")


def test_finviz_metrics_keep_the_av_names_and_units_and_name_every_gap():
    m, un = emdi.finviz_fundamental_metrics(FUND_CACHE["V"])
    assert m == {"MarketCap": 748499270000.0, "PE": 34.41, "ForwardPE": 26.65, "PEG": 1.88, "DividendYield": 0.0067,
                 "ProfitMargin": 0.5035, "ROE": 0.6067, "DebtToEquity": 0.68, "Beta": 0.83}
    assert set(un) == {"EPS", "RevenuePerShare", "52WeekHigh", "52WeekLow", "50DayMA", "200DayMA", "AnalystTargetPrice"}
    m2, un2 = emdi.finviz_fundamental_metrics(FUND_CACHE["CLF"])
    assert "PE" not in m2 and un2["PE"] == "Finviz pe empty" and un2["DividendYield"] == "Finviz div_yield_pct empty"
    assert all(v is not None for v in m2.values())                 # nothing defaulted


def test_fundamentals_dry_run_reads_finviz_through_the_broker_and_writes_nothing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(emdi, "_get_conn", _boom)
    monkeypatch.setattr(emdi, "_av_overview", _boom)
    monkeypatch.setattr(emdi, "PROJECT_ROOT", tmp_path)
    out = emdi.ingest_finviz_fundamentals(["V", "CLF", "OLD", "NOPE"], dry_run=True, broker=_fund_broker(calls))
    assert calls == [(["V", "CLF", "OLD", "NOPE"], emdi.FINVIZ_FUNDAMENTALS_MAX_AGE_HOURS)]
    assert out["provider_calls"] == 0 and out["source"] == "finviz" and out["dry_run"] is True
    assert out["fetched"] == 2 and out["rows"] == 9 + 6
    assert out["symbols"]["OLD"]["metrics"] == {}
    assert out["symbols"]["OLD"]["unavailable"]["PE"] == "Finviz record 240h old > 168h"
    assert out["symbols"]["NOPE"]["unavailable"]["MarketCap"] == "not in Finviz enrichment cache"
    assert not (tmp_path / "data").exists()                      # no receipt in a dry run


def test_fundamentals_live_run_writes_finviz_rows_only_for_known_metrics(monkeypatch, tmp_path):
    conn = _FConn()
    monkeypatch.setattr(emdi, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(emdi, "_av_overview", _boom)
    out = emdi.ingest_finviz_fundamentals(["V", "CLF"], broker=_fund_broker(), conn_factory=lambda: conn)
    assert conn.committed and conn.closed
    assert {r[1] for r in conn.c.rows} == {"finviz"}
    written = {(r[0], r[2]): r[3] for r in conn.c.rows}
    assert written[("V", "ROE")] == 0.6067 and ("CLF", "PE") not in written and ("V", "EPS") not in written
    rec = json.loads((tmp_path / "data" / "runtime" / "fundamentals_finviz_last_run.json").read_text())
    assert rec["schema"] == "FundamentalsFinvizRun@v1" and rec["symbols"]["CLF"]["unavailable"]["PE"] == "Finviz pe empty"
    assert out["rows"] == len(conn.c.rows) == 15


def test_the_cron_entrypoint_routes_fundamentals_to_finviz():
    src = (ROOT / "scripts" / "external_market_data_ingest.py").read_text()
    main = src[src.index('if __name__ == "__main__":'):]
    assert "ingest_alpha_vantage()" not in main
    assert 'elif "--fundamentals" in sys.argv:' in main and "ingest_finviz_fundamentals(" in main
    body = inspect.getsource(emdi.ingest_finviz_fundamentals)
    assert "_av_overview" not in body and "finviz_get" not in body


def test_registry_av_row_is_narrowed_and_fundamentals_point_at_finviz():
    av = REGISTRY["providers"]["alpha_vantage"]
    assert "fundamentals" not in av["supplies"]
    assert {"earnings_calendar", "news_sentiment"} <= set(av["supplies"])
    assert av["budget"]["allotments"]["scalp_float"] == 0 and av["budget"]["allotments"]["fundamentals_overview"] == 0
    assert "operator 2026-10-16: yes, narrow the AV row" in av["_narrowed_20261016"]
    assert "fundamentals" not in av["approval"]["scope"].split(";")[0]
    dom = next(d for d in REGISTRY["domains"] if d["domain"] == "fundamentals")
    assert dom["primary_provider"] == "finviz" and dom["writer"] == "scripts/external_market_data_ingest.py"
    assert "fundamentals" not in avo.granted_domains()
