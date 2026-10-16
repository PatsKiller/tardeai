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
    assert "premium endpoint" in v["idle_reason"]
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
