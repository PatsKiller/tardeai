"""Data-integrity fix PR (operator-approved 2026-10-18): one hermetic test per item.

1. analyst_consensus_history: Finviz recom values that carry "%" or sit off 1..5 (JNUG "-95.44%" -> "Strong Buy")
   are refused by the writer, the cache loader and every consumer; the remediation script is dry-run by default and
   quarantines (archive + NULL, never DELETE) only with --apply AND TRADEAI_REMEDIATION_GRANT.
2. analyst_data_history: no empty payload is inserted; readers render the vote distribution "unavailable".
3. indicator ATR stop: never <= 0 (None + "atr_exceeds_price").
4. catalyst_confidence: clamped to [0, 1].
5. NaN ytd -> None; int32-max sentinel bid/ask -> spread unknown; normalizer confidence clamped.
6. monitors: plausibility fingerprint = (contract, column, rule, severity band) + windowed rules + retired_store;
   gap resolution: symbol touches count as attempts, per-class fingerprints, no midnight "Cleared", digest routing.
7. llm_curation outside the DeepSeek window is "deferred" and calls no model.
8. both monitors as n8n dispatcher lanes with REVIEWED contracts, LaneRunReceipt@v2 output, and the operator packet.

Hermetic: tmp paths and fakes only; no database, broker, network, Telegram, systemd or n8n.

COVERS = ["scripts/lib/analyst_recom_guard.py", "scripts/db_adapter.py", "scripts/finviz_enrichment.py",
          "scripts/lib/data_broker/advisory_desk.py", "scripts/analyst_report_builder.py",
          "scripts/remediate_analyst_consensus_20261018.py", "scripts/asset_intelligence_pipeline.py",
          "scripts/lib/analyst_vote_distribution.py", "scripts/broker_proposal_intel.py", "scripts/indicator_engine.py",
          "scripts/scoring.py", "scripts/etf_performance_enrich.py", "scripts/proposal_execution_readiness.py",
          "scripts/agent_recommendation_normalizer.py", "scripts/data_plausibility_monitor.py",
          "scripts/check_gap_resolution.py", "scripts/lib/gap_resolver.py", "config/data_plausibility_contracts.json",
          "config/host_comms_intent_routes.json", "config/lane_registry.json", "config/n8n_run_allowlist.json",
          "config/n8n_health_contracts.json", "docs/ops/packets/data-integrity-monitors-n8n-20261018/cutover.sh"]
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_gap_resolution as cgr  # noqa: E402
import data_plausibility_monitor as dpm  # noqa: E402
from scripts.lib import analyst_recom_guard as G  # noqa: E402
from scripts.lib import analyst_vote_distribution as V  # noqa: E402

CONFIG = ROOT / "config"
PACKET = ROOT / "docs" / "ops" / "packets" / "data-integrity-monitors-n8n-20261018"
SCRIPT = PACKET / "cutover.sh"
DPM_LANE = "n8n-data-plausibility-audit"
GAP_LANE = "n8n-gap-resolution-audit"
JNUG = {"recom": "-95.44%", "recom_score": -95.44, "analyst_rating": "Strong Buy",
        "cached_at": "2026-09-05T10:09:33.427619"}


def _load(name: str) -> dict:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_send(monkeypatch):
    """Every Telegram chokepoint is a stub that fails: no test here may reach one unless it installs its own."""
    calls: list = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("a Telegram chokepoint was called")

    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = boom
    for name in ("telegram_alert", "scripts.telegram_alert"):
        monkeypatch.setitem(sys.modules, name, fake)
    yield calls


# ── 1. analyst consensus: the guard, the writer, the loader, the consumers ───────────────────────────────────────


def test_jnug_percent_recom_is_refused_by_the_guard():
    assert G.recom_reject_reason("-95.44%", -95.44) == G.REASON_PERCENT
    assert G.recom_reject_reason("938.86%", 938.86) == G.REASON_PERCENT
    # a percent that happens to land inside 1..5 is still not a rating (the old consumer guard passed it)
    assert G.recom_reject_reason("3.81%", 3.81) == G.REASON_PERCENT
    assert G.recom_reject_reason("17.11", None) == G.REASON_OUT_OF_RANGE
    assert G.recom_reject_reason(None, 160.15) == G.REASON_SCORE_MISMATCH
    # NaN is refused. The reviewed guard on main (#1870, classify_recom) reports it as off-scale, not unparseable.
    assert G.recom_reject_reason(None, float("nan")) == G.REASON_SCORE_MISMATCH
    assert G.recom_reject_reason("2.10", 2.1) is None
    assert G.recom_reject_reason("buy", 2.0) is None  # hermes stores a label as recom_raw
    assert G.recom_reject_reason(None, None) is None and not G.is_valid_recom(None, None)
    assert G.is_valid_recom("1.8", 1.8) and not G.is_valid_recom("-95.44%", -95.44)


def test_the_writer_refuses_jnug_and_counts_it_in_the_receipt():
    import db_adapter

    cache = {"JNUG": dict(JNUG), "WMT": {"recom": "1.8", "recom_score": 1.8, "analyst_rating": "Buy"},
             "BELFB": {"recom": "938.86%", "recom_score": 938.86, "analyst_rating": "Strong Sell"},
             "_meta": {"x": 1}}
    rows, receipt = db_adapter.build_analyst_consensus_rows("2026-10-18", cache, {"BELFB": {"target": "120"}})
    by_sym = {r[1]: r for r in rows}
    assert "JNUG" not in by_sym  # nothing analyst-related left: no row at all
    assert by_sym["WMT"][2:5] == ("1.8", 1.8, "Buy")
    # BELFB keeps its target-price row, with the fabricated rating stripped and the reason recorded
    assert by_sym["BELFB"][2:6] == (None, None, None, 120.0)
    assert json.loads(by_sym["BELFB"][7])["recom_reject_reason"] == G.REASON_PERCENT
    assert receipt["recom_refused"] == 2 and receipt["refused_by_reason"] == {G.REASON_PERCENT: 2}
    assert sorted(receipt["refused_symbols"]) == ["BELFB", "JNUG"] and receipt["considered"] == 3


def test_the_cache_loader_nulls_stale_off_scale_entries_and_keeps_the_raw_text(tmp_path):
    import finviz_enrichment as fe

    state = tmp_path / "data" / "state"
    state.mkdir(parents=True)
    (state / "ticker_enrichment_cache.json").write_text(json.dumps(
        {"JNUG": dict(JNUG), "AAPL": {"recom": "1.9", "recom_score": 1.9, "analyst_rating": "Buy"}}))
    cache = fe.load_cache(tmp_path)
    assert cache["JNUG"]["recom"] == "-95.44%"  # evidence kept
    assert cache["JNUG"]["recom_score"] is None and cache["JNUG"]["analyst_rating"] is None
    assert cache["JNUG"]["recom_reject_reason"] == G.REASON_PERCENT
    assert cache["AAPL"]["recom_score"] == 1.9 and "recom_reject_reason" not in cache["AAPL"]


def test_the_root_parse_is_header_keyed_and_refuses_a_percent_recom():
    import finviz_enrichment as fe

    assert "Recom" not in str(fe.VIEWS[141])  # the view that shifted carries no Recom column
    assert fe._classify_recom("-95.44%") == (None, None, "percent_sign_not_a_1_5_rating")
    assert fe._classify_recom("2.0")[1] == "Buy"


def test_advisory_desk_consensus_fallback_refuses_a_percent_that_lands_in_1_5(monkeypatch):
    from lib.data_broker import advisory_desk as ad

    def _execute(sql, params=None, fetch="all"):
        if "yahoo_analyst_targets_history" in sql:
            return [{"sym": "JNUG", "target_mean_price": None, "target_high_price": None, "target_low_price": None,
                     "number_of_analyst_opinions": 0, "recommendation_mean": None, "current_price": 10.0,
                     "snapshot_date": "2026-10-17"},
                    {"sym": "WMT", "target_mean_price": 120.0, "target_high_price": None, "target_low_price": None,
                     "number_of_analyst_opinions": 40, "recommendation_mean": None, "current_price": 100.0,
                     "snapshot_date": "2026-10-17"}]
        return [{"sym": "JNUG", "recom_raw": "-95.44%", "recom_score": -95.44, "analyst_rating": "Strong Buy",
                 "target_price": None, "snapshot_date": "2026-10-17"},
                {"sym": "WMT", "recom_raw": "3.81%", "recom_score": 3.81, "analyst_rating": "Hold",
                 "target_price": None, "snapshot_date": "2026-10-17"}]

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=_execute))
    out = ad._load_analyst_context({"JNUG", "WMT"})
    for sym in ("JNUG", "WMT"):
        assert out[sym]["consensus_rating"] == "" and "consensus_score" not in out[sym], sym


def test_analyst_report_builder_drops_fabricated_rating_rows(monkeypatch):
    import analyst_report_builder as arb

    assert arb._recom_row_ok({"recom_raw": "2.0", "recom_score": 2.0})
    assert not arb._recom_row_ok({"recom_raw": "-95.44%", "recom_score": -95.44})
    assert not arb._recom_row_ok({"recom_raw": "3.81%", "recom_score": 3.81})

    def _db_query(sql, params=None, fetch="all"):
        if "analyst_consensus_history" in sql:
            return [{"snapshot_date": "2026-10-17", "analyst_rating": "Strong Buy", "recom_raw": "-95.44%",
                     "recom_score": -95.44, "target_price": None},
                    {"snapshot_date": "2026-10-10", "analyst_rating": "Hold", "recom_raw": "3.0",
                     "recom_score": 3.0, "target_price": None}]
        return []

    monkeypatch.setattr(arb, "_db_query", _db_query)
    sec = arb._analyst_commentary_section("JNUG", {}, {})
    assert "Strong Buy" not in sec["content"]  # the inverted rating never becomes a "rating change"


class _RemediationCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql: list[str] = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.rowcount = len(self.rows) if ("INSERT" in sql or "UPDATE" in sql) else 0

    def fetchall(self):
        return list(self.rows)


class _RemediationConn:
    def __init__(self, rows):
        self.cur = _RemediationCursor(rows)
        self.committed = self.rolled_back = self.closed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


BAD_ROWS = [(1, "2026-10-17", "JNUG", "-95.44%", -95.44, "Strong Buy", "finviz"),
            (2, "2026-10-17", "BELFB", "938.86%", 938.86, "Strong Sell", "finviz")]


def _remediation_cache(tmp_path) -> Path:
    p = tmp_path / "state" / "ticker_enrichment_cache.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"JNUG": dict(JNUG), "WMT": {"recom": "1.8", "recom_score": 1.8}}))
    return p


def test_remediation_is_a_dry_run_by_default_and_writes_nothing(tmp_path, capsys):
    from scripts import remediate_analyst_consensus_20261018 as RM

    cache = _remediation_cache(tmp_path)
    before = cache.read_bytes()
    conn = _RemediationConn(BAD_ROWS)
    assert RM.run(["--cache", str(cache), "--json"], connect=lambda: conn, environ={}) == 0
    rep = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rep["mode"] == "dry_run" and rep["bad_rows"] == 2
    assert [b["symbol"] for b in rep["bad_cache_entries"]] == ["JNUG"]
    assert all(s.lstrip().startswith("SELECT") for s in conn.cur.sql) and not conn.committed
    assert "position('%%' in coalesce(recom_raw, '')) > 0" in conn.cur.sql[0]
    assert "snapshot_date >= %(since)s" in conn.cur.sql[0]
    assert cache.read_bytes() == before


def test_remediation_apply_needs_the_grant(tmp_path, capsys):
    from scripts import remediate_analyst_consensus_20261018 as RM

    cache = _remediation_cache(tmp_path)
    conn = _RemediationConn(BAD_ROWS)
    assert RM.run(["--apply", "--apply-cache", "--cache", str(cache)], connect=lambda: conn, environ={}) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert all(s.lstrip().startswith("SELECT") for s in conn.cur.sql) and not conn.committed
    assert json.loads(cache.read_text())["JNUG"]["recom_score"] == -95.44


def test_remediation_apply_archives_then_nulls_and_never_deletes(tmp_path, capsys):
    from scripts import remediate_analyst_consensus_20261018 as RM

    cache = _remediation_cache(tmp_path)
    conn = _RemediationConn(BAD_ROWS)
    rc = RM.run(["--apply", "--apply-cache", "--cache", str(cache), "--json"], connect=lambda: conn,
                environ={RM.GRANT_ENV: "grant-20261018-test"})
    assert rc == 0 and conn.committed
    sql = "\n".join(conn.cur.sql)
    assert f"CREATE TABLE IF NOT EXISTS {RM.QUARANTINE_TABLE}" in sql
    assert f"INSERT INTO {RM.QUARANTINE_TABLE} SELECT * FROM analyst_consensus_history" in sql
    assert "SET recom_score = NULL, analyst_rating = NULL" in sql
    assert "DELETE" not in sql.upper() and "DROP" not in sql.upper()
    assert sql.index("INSERT INTO") < sql.index("UPDATE analyst_consensus_history")  # archive first
    doc = json.loads(cache.read_text())
    assert doc["JNUG"]["recom"] == "-95.44%" and doc["JNUG"]["recom_score"] is None
    assert doc["JNUG"]["recom_reject_reason"] == G.REASON_PERCENT and doc["WMT"]["recom_score"] == 1.8
    archived = list((cache.parent / "archive").glob("ticker_enrichment_cache.*.json"))
    assert len(archived) == 1 and json.loads(archived[0].read_text())["JNUG"]["recom_score"] == -95.44


# ── 2. analyst_data_history: no empty payloads; readers say "unavailable" ─────────────────────────────────────────


def test_no_empty_analyst_payload_is_inserted(monkeypatch, capsys):
    import asset_intelligence_pipeline as aip

    executed: list[tuple] = []

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Cur()

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=lambda **k: _Conn()))
    env = {k: "x" for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")}
    rows = [{"symbol": "AAA", "asset_type": "stock", "analyst": {}},
            {"symbol": "BBB", "asset_type": "stock", "analyst": {"buy": 3, "hold": 1}}]
    aip.mirror_to_db(rows, env)
    targets = [s.split("(")[0].split("INTO")[1].strip() for s, _ in executed]
    assert targets.count("asset_intelligence_history") == 2
    assert [p[0] for s, p in executed if "analyst_data_history" in s] == ["BBB"]
    assert "1 empty analyst payload(s) not inserted" in capsys.readouterr().out
    assert not aip.analyst_payload_is_observation({}) and not aip.analyst_payload_is_observation({"buy": 0})


def test_vote_distribution_is_unavailable_for_empty_or_zero_payloads():
    assert V.vote_distribution({}) == {"distribution": None, "status": "unavailable",
                                       "reason": V.REASON_PROVIDER_RETIRED, "provider": None}
    assert V.vote_distribution("{}")["status"] == "unavailable"
    assert V.vote_distribution(None)["reason"] == V.REASON_NO_ROW
    assert V.vote_distribution({"buy": 0, "hold": 0})["reason"] == V.REASON_NO_VOTES
    ok = V.vote_distribution({"buy": 3, "strong_buy": 1, "provider": "x"})
    assert ok["status"] == "available" and ok["distribution"]["buy"] == 3 and ok["distribution"]["sell"] == 0


def test_broker_proposal_intel_reports_unavailable_not_zero_votes(monkeypatch):
    import broker_proposal_intel as bpi

    def _q(sql, params=None, one=False):
        if "yahoo_analyst_targets_history" in sql:
            return {"recommendation_key": "buy", "recommendation_mean": 2.0, "number_of_analyst_opinions": 12,
                    "target_mean_price": 120.0, "target_high_price": 150.0, "target_low_price": 90.0,
                    "current_price": 100.0, "snapshot_date": "2026-10-17"}
        return {"payload": {}, "as_of": "2026-10-17"}

    monkeypatch.setattr(bpi, "_q", _q)
    monkeypatch.setattr(bpi, "_load_enrichment_cache", lambda s: {"recom": "3.81%", "recom_score": 3.81,
                                                                  "analyst_rating": "Hold"})
    monkeypatch.setattr(bpi, "_load_pro_analyst_pill", lambda s: {})
    out = bpi._analyst_intel("WMT")
    assert out["distribution"] is None and out["distribution_status"] == "unavailable"
    assert out["distribution_unavailable_reason"] == V.REASON_PROVIDER_RETIRED
    assert [s["source"] for s in out["sources"]] == ["yahoo"]  # the percent Finviz recom is refused too


def test_api_v2_readers_use_the_unavailable_status():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    assert src.count("from lib.analyst_vote_distribution import vote_distribution as _vote_distribution") == 2
    assert '"dist_status": d["status"]' in src and '"distribution_status":' in src


def test_the_plausibility_contract_for_the_retired_store_only_fails_on_new_empty_rows():
    c = next(x for x in _load("data_plausibility_contracts.json")["contracts"] if x["table"] == "analyst_data_history")
    assert c["rule"] == "retired_store" and c["retired_at"] == "2026-10-18"
    sql = dpm._retired_store_sql(c)
    assert "\"as_of\" >= '2026-10-18'::date" in sql and "'{}'::jsonb" in sql

    class _Cur:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            return (0, 0)

    r = dpm._check_retired_store(_Cur(), c)
    assert r["violations"] == 0


# ── 3-5. stop floor, confidence clamps, NaN, sentinels ─────────────────────────────────────────────────────────────


def _atr_stop_module():
    """atr_stop_target is pure; indicator_engine imports numpy/pandas/yfinance at module level and CI installs
    only pytest + pyyaml, so load just the function and its reason constant from the source."""
    import ast
    import math
    import types

    tree = ast.parse((ROOT / "scripts" / "indicator_engine.py").read_text(encoding="utf-8"))
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == "atr_stop_target")
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "STOP_REASON_ATR_EXCEEDS_PRICE"
                                                  for t in n.targets))]
    assert len(keep) == 2, "atr_stop_target and STOP_REASON_ATR_EXCEEDS_PRICE must stay top-level"
    mod = types.ModuleType("indicator_engine_atr")
    mod.math = math
    exec(compile(ast.Module(body=keep, type_ignores=[]), "indicator_engine.py", "exec"), mod.__dict__)
    return mod


def test_atr_stop_is_never_at_or_below_zero():
    ie = _atr_stop_module()

    assert ie.atr_stop_target(1.0, 1.5, 1.0, 2.0) == (None, 4.0, ie.STOP_REASON_ATR_EXCEEDS_PRICE)
    assert ie.atr_stop_target(2.0, 1.0, 2.0, 2.0) == (None, 4.0, ie.STOP_REASON_ATR_EXCEEDS_PRICE)  # stop == 0
    assert ie.atr_stop_target(100.0, 2.0, 1.0, 2.0) == (98.0, 104.0, None)
    assert ie.atr_stop_target(100.0, float("nan"), 1.0, 2.0)[0] is None


def test_catalyst_confidence_is_clamped_to_one():
    import scoring

    ok, conf, _ = scoring.validate_catalyst_relevance("RLYB", "Rallybio Corporation Holdings Group",
                                                      "RLYB: Rallybio Corporation Holdings beats estimates")
    assert ok and conf == 1.0  # 0.6 ticker + 0.5 company first word would be 1.1 unclamped


def test_nan_ytd_is_unknown():
    import etf_performance_enrich as epe

    assert epe.finite_or_none(float("nan")) is None and epe.finite_or_none(float("inf")) is None
    assert epe.finite_or_none(12.5) == 12.5 and epe.finite_or_none(None) is None


def test_int32_max_sentinel_bid_ask_is_not_a_price():
    import proposal_execution_readiness as per

    assert per.is_int32_sentinel(2147483647) and per.is_int32_sentinel(2147.48)
    assert per.is_int32_sentinel(214748.3647) and per.is_int32_sentinel(2147479900.0)
    assert not per.is_int32_sentinel(101.5) and not per.is_int32_sentinel(None) and not per.is_int32_sentinel(0)
    src = (ROOT / "scripts" / "proposal_execution_readiness.py").read_text()
    assert "bid = ask = spread = spread_pct = None" in src


def test_normalizer_confidence_is_clamped_to_unit_scale():
    import agent_recommendation_normalizer as arn

    assert arn._conf01(1.2) == 1.0 and arn._conf01(-0.1) == 0.0 and arn._conf01(0.55) == 0.55
    assert arn._conf01(float("nan")) is None and arn._conf01("x") is None and arn._conf01(None) is None


# ── 6a. data plausibility monitor ──────────────────────────────────────────────────────────────────────────────────


def _v(table, column, violations, total, rule="range"):
    return {"table": table, "column": column, "rule": rule, "severity": "BLOCK", "status": "VIOLATION",
            "violations": violations, "total": total, "detail": f"rule={rule}", "samples": []}


def test_plausibility_fingerprint_is_the_band_not_the_count():
    bands = _load("data_plausibility_contracts.json")["alert_policy"]["pct_bands_pct"]
    a = dpm.alert_fingerprint([_v("trade_ai_scans", "catalyst_confidence", 900, 5311, "single_scale")], bands)
    b = dpm.alert_fingerprint([_v("trade_ai_scans", "catalyst_confidence", 915, 5311, "single_scale")], bands)
    c = dpm.alert_fingerprint([_v("trade_ai_scans", "catalyst_confidence", 2700, 5311, "single_scale")], bands)
    assert a == b == {"trade_ai_scans.catalyst_confidence:single_scale": "BLOCK:10-50%"}
    assert c == {"trade_ai_scans.catalyst_confidence:single_scale": "BLOCK:>=50%"}
    assert dpm.severity_band(1, 1000, bands) == "0-1%" and dpm.severity_band(5, 5, []) == "any"


def test_plausibility_windowed_rules_and_policy():
    doc = _load("data_plausibility_contracts.json")
    pol = dpm.window_policy(doc)
    assert pol["default_window_days"] == 30 and set(pol["rules"]) == set(dpm.WINDOWED_RULES)
    assert dpm.alert_policy(doc)["min_realert_minutes"] == 10080
    sqls: list[str] = []

    class _Cur:
        def execute(self, sql, params=None):
            sqls.append(sql)
            self.last = (sql, params)

        def fetchone(self):
            sql, params = self.last
            if "information_schema" in sql:
                return (1,) if params[1] in ("column", "created_at") else None
            return (0,)

        def fetchall(self):
            return []

    c = {"table": "t", "column": "column", "rule": "min", "min": 0.0, "severity": "BLOCK"}
    r = dpm._check(_Cur(), c, pol)
    assert r["status"] == "OK" and r["window"] == "last 30d by created_at"
    counted = [s for s in sqls if s.startswith("SELECT count(*)")]
    assert all("\"created_at\" > now() - interval '30 days'" in s for s in counted) and len(counted) == 2
    sqls.clear()
    r = dpm._check(_Cur(), dict(c, window_days=0), pol)  # explicit opt-out: whole table
    assert r["window"] is None and not any("interval" in s for s in sqls)


class _PlausCursor:
    """Answers every query the monitor sends with a clean measurement."""

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        if "information_schema" in self.sql:
            return (1,)
        if "count(*) FILTER (WHERE" in self.sql and "<= 1)" in self.sql:
            return (10, 0, 10)
        if "count(*) FILTER" in self.sql:
            return (0, 5)
        return (0,)

    def fetchall(self):
        return []

    def close(self):
        pass


class _PlausConn:
    def cursor(self):
        return _PlausCursor()

    def close(self):
        pass


@pytest.fixture
def lane_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "data" / "governance").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(state / "data" / "governance" / "ledger.sqlite"))
    monkeypatch.setattr(dpm, "STATE_PATH", tmp_path / "dpm_alert.json")
    monkeypatch.setattr(cgr, "STATE_PATH", tmp_path / "cgr_alert.json")
    receipts: list = []
    monkeypatch.setattr(dpm, "_write_run_receipt", lambda *a, **k: receipts.append(("dpm", a)))
    monkeypatch.setattr(cgr, "_write_run_receipt", lambda *a, **k: receipts.append(("cgr", a)))
    return types.SimpleNamespace(state=state, tmp=tmp_path, receipts=receipts)


def _contract(lane: str) -> dict:
    return {c["id"]: c for c in _load("n8n_health_contracts.json")["contracts"]}[lane]


def test_plausibility_lane_receipt_is_v2_and_produced(lane_env, monkeypatch):
    from scripts.lib import lane_last_receipt as R
    from scripts.lib import n8n_output_verdict as OV

    rid = f"d:{DPM_LANE}:live:20261018T0620"
    monkeypatch.setenv("TRADEAI_RUN_ID", rid)
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")  # the n8n executor sets it; main's receipt binds run_mode
    assert dpm.lane_main([], connect=_PlausConn) == 0  # the n8n entry with the canary live_arg []
    doc = json.loads(R.attempt_receipt_path(DPM_LANE, rid, lane_env.state).read_text())
    n = len(_load("data_plausibility_contracts.json")["contracts"])
    assert doc["schema"] == "LaneRunReceipt@v2" and doc["produced_count"] == n and doc["attempted_count"] == n
    verdict = OV.evaluate(_contract(DPM_LANE)["expected_output"], doc, run_id=rid, lane_id=DPM_LANE, mode="live")
    assert verdict["verdict"] == "produced"
    assert not dpm.STATE_PATH.exists()  # no --alert: the dry live_arg notifies nobody and keeps no alert state


def test_plausibility_unreachable_database_is_the_fatal_skip(lane_env, monkeypatch):
    from scripts.lib import lane_last_receipt as R
    from scripts.lib import n8n_output_verdict as OV

    rid = f"d:{DPM_LANE}:live:20261018T0620"
    monkeypatch.setenv("TRADEAI_RUN_ID", rid)

    def _down():
        raise OSError("connection refused")

    assert dpm.lane_main([], connect=_down) == 1
    doc = json.loads(R.attempt_receipt_path(DPM_LANE, rid, lane_env.state).read_text())
    assert doc["skipped_reasons"] == {dpm.SKIP_DEPENDENCY: 1} and doc["status"] == "failed"
    verdict = OV.evaluate(_contract(DPM_LANE)["expected_output"], doc, run_id=rid, lane_id=DPM_LANE, mode="live")
    assert verdict["verdict"] != "produced"


def test_plausibility_dry_run_writes_nothing(lane_env, capsys):
    assert dpm.main(["--dry-run"], connect=_PlausConn) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert lane_env.receipts == [] and not (lane_env.state / "data" / "runtime").exists()
    assert dpm.main(["--dry-run", "--alert"], connect=_PlausConn) == 2


def _ledger(lane_env) -> Path:
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger

    path = Path(os.environ["TRADEAI_N8N_COORDINATION_LEDGER"])
    CoordinationLedger(path).close()
    return path


def _intents(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT domain, kind, workflow_id, state FROM comms_intents ORDER BY domain, kind").fetchall()
    finally:
        conn.close()


def test_plausibility_queue_mode_queues_a_host_intent_and_never_sends(lane_env, no_send):
    ledger = _ledger(lane_env)
    bad = _v("indicator_confluence_cache", "stop_price", 17, 1817, "min")
    out = dpm._alert([bad], [bad], notify="queue", bands_pct=[1.0, 10.0, 50.0])
    assert out["notified"] and out["channel"] == "queue"
    assert _intents(ledger) == [("data", "data_plausibility_violation", "host.data_plausibility_monitor", "QUEUED")]
    # the consumer maps it to a P2 incident (DIGEST tier), never PAGE
    from scripts.lib import n8n_comms_intent_consumption as C

    routes = C.load_routes()
    m = C.map_intent({"domain": "data", "kind": "data_plausibility_violation", "workflow_id": "host.x"}, routes)
    assert m["severity"] == "P2"
    assert no_send == []


# ── 6b. gap resolution monitor ─────────────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_a_research_gap_touched_after_it_opened_is_attempted():
    created = NOW - timedelta(hours=10)
    research = [{"gap_id": "rg-1", "symbol": "TSLA", "status": "OPEN", "created_at": _iso(created)},
                {"gap_id": "rg-2", "symbol": "RKLB", "status": "OPEN", "created_at": _iso(created)},
                {"gap_id": "rg-3", "symbol": "NVDA", "status": "OPEN", "created_at": _iso(created)},
                {"gap_id": "rg-4", "symbol": "AMD", "status": "OPEN", "created_at": _iso(created)}]
    touches = cgr.symbol_touches(
        [{"gap_id": "resolver-id-never-equal", "subject": "NVDA", "started": _iso(NOW - timedelta(hours=1))}],
        [{"symbol": "TSLA", "updated_at": _iso(NOW - timedelta(hours=2))},
         {"symbol": "AMD", "updated_at": _iso(created - timedelta(hours=5))}],  # touched BEFORE the gap: no attempt
        [{"symbol": "RKLB", "status": "completed", "completed_ts": _iso(NOW - timedelta(hours=3))}],
    )
    out = cgr.open_gaps([], research, [], now=NOW, touches=touches)
    assert [g["gap_id"] for g in out] == ["rg-4"]
    # without touches (the old behaviour) every research gap is OPEN_NO_ATTEMPT: the ids never match
    assert len(cgr.open_gaps([], research, [{"gap_id": "resolver-id-never-equal"}], now=NOW)) == 4


def test_collect_reads_the_injected_touch_files(tmp_path):
    rg = tmp_path / "gaps.jsonl"
    rg.write_text(json.dumps({"gap_id": "rg-1", "symbol": "TSLA", "status": "OPEN",
                              "created_at": _iso(NOW - timedelta(hours=5))}) + "\n")
    st = tmp_path / "state.jsonl"
    st.write_text(json.dumps({"symbol": "TSLA", "updated_at": _iso(NOW - timedelta(hours=1))}) + "\n")
    rep = cgr.collect(now=NOW, receipts_path=tmp_path / "r", queue_path=tmp_path / "q", research_path=rg,
                      retired=frozenset(), denials=[], state_path=st, hermes_path=tmp_path / "h")
    assert rep["findings"]["OPEN_NO_ATTEMPT"] == [] and rep["touch_rows"]["symbols_touched"] == 1


def _report(**findings):
    f = {"OPEN_NO_ATTEMPT": [], "VECTOR_FAILING": [], "RETIRED_RAN": [], "REFUSED_NOWHERE": []}
    f.update(findings)
    return {"schema": cgr.SCHEMA, "findings": f, "finding_count": sum(len(v) for v in f.values())}


@pytest.fixture
def captured(monkeypatch, tmp_path):
    sent: list = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda body, **k: sent.append((body, k)) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(cgr, "STATE_PATH", tmp_path / "cgr_state.json")
    return sent


def test_vector_failing_growth_and_midnight_clear_are_not_news(captured):
    cgr._alert(_report(VECTOR_FAILING=[{"vector": "llm_curation", "errors_today": 3}]))
    assert len(captured) == 1 and captured[0][1]["priority"] == "P2" and captured[0][0].startswith(cgr.SENTINEL)
    cgr._alert(_report(VECTOR_FAILING=[{"vector": "llm_curation", "errors_today": 9}]))  # count grew: same set
    cgr._alert(_report())  # UTC midnight: the per-day set empties
    assert len(captured) == 1, [b for b, _ in captured]
    cgr._alert(_report(VECTOR_FAILING=[{"vector": "llm_curation", "errors_today": 3}]))  # new day, same set again
    assert len(captured) == 2


def test_open_no_attempt_goes_to_the_digest_without_the_sentinel(captured):
    gaps = [{"gap_id": f"g{i}", "domain": "research_thesis", "subject": f"S{i}", "age_hours": 3.0,
             "origin": "research_gaps"} for i in range(3)]
    cgr._alert(_report(OPEN_NO_ATTEMPT=gaps))
    assert len(captured) == 1
    body, kw = captured[0]
    assert kw["priority"] == "P3" and cgr.SENTINEL not in body and "3 gap(s) open" in body
    from operator_alert_policy_v2 import classify_legacy_message

    assert classify_legacy_message(body).alert_type != "data_integrity"
    cgr._alert(_report(OPEN_NO_ATTEMPT=gaps))  # unchanged count:hash -> silent
    assert len(captured) == 1
    fp = cgr.fingerprint(_report(OPEN_NO_ATTEMPT=gaps))
    assert fp["immediate"] == {} and fp["digest"]["OPEN_NO_ATTEMPT"].startswith("3:")


def test_gap_queue_mode_queues_both_routes_and_never_sends(lane_env, no_send):
    ledger = _ledger(lane_env)
    out = cgr._alert(_report(RETIRED_RAN=[{"gap_id": "g", "vector": "backup_provider", "provider": "fmp",
                                           "outcome": "answered", "started": "2026-10-18T13:00:00+00:00"}],
                             OPEN_NO_ATTEMPT=[{"gap_id": "g1", "domain": "d", "subject": "S", "age_hours": 3.0,
                                               "origin": "gap_queue"}]), notify="queue")
    assert out["sent"] == ["immediate", "digest"] and "error" not in out
    assert _intents(ledger) == [("data", "gap_resolution_digest", "host.check_gap_resolution", "QUEUED"),
                                ("data", "gap_resolution_finding", "host.check_gap_resolution", "QUEUED")]
    from scripts.lib import n8n_comms_intent_consumption as C

    routes = C.load_routes()
    assert C.map_intent({"domain": "data", "kind": "gap_resolution_finding", "workflow_id": "w"}, routes)["severity"] == "P2"
    assert C.map_intent({"domain": "data", "kind": "gap_resolution_digest", "workflow_id": "w"}, routes)["severity"] == "P3"
    assert no_send == []


def test_gap_queue_failure_does_not_advance_state(lane_env):
    # no ledger: queue_intent refuses ledger_absent -> the run is a failed delivery, the state stays put
    rc = cgr.lane_main(["--alert"], collect_fn=lambda: _report(VECTOR_FAILING=[{"vector": "v", "errors_today": 3}]))
    assert rc == 1 and not cgr.STATE_PATH.exists()
    # the systemd spelling of the same queue path behaves the same
    rc = cgr.main(["--lane-receipt", "--alert", "--notify", "queue"],
                  collect_fn=lambda: _report(VECTOR_FAILING=[{"vector": "v", "errors_today": 3}]))
    assert rc == 1 and not cgr.STATE_PATH.exists()


def test_plausibility_owner_switch_argv_queues_through_lane_main(lane_env, no_send, monkeypatch):
    ledger = _ledger(lane_env)

    class _ViolCursor(_PlausCursor):
        def fetchone(self):
            if "information_schema" in self.sql:
                return (1,)
            if "count(*) FILTER" in self.sql:
                return (0, 5) if "<= 1)" not in self.sql else (10, 0, 10)
            return (3,) if "WHERE" in self.sql and "< 0.0" in self.sql else (100,)

    class _ViolConn(_PlausConn):
        def cursor(self):
            return _ViolCursor()

    monkeypatch.setenv("TRADEAI_RUN_ID", f"d:{DPM_LANE}:live:20261018T0620")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")  # the n8n executor sets it; main's receipt binds run_mode
    assert dpm.lane_main(["--alert"], connect=_ViolConn) == 0
    assert _intents(ledger) == [("data", "data_plausibility_violation", "host.data_plausibility_monitor", "QUEUED")]
    assert no_send == []


def test_the_n8n_entry_scripts_are_not_senders_for_the_dispatcher_gate():
    from scripts.lib import advisory_lane_guard as AG

    for lane in (DPM_LANE, GAP_LANE):
        script = AG.entry_script(_allow()[lane]["command"])
        rep = AG.scan_entry(script)
        assert not rep.is_sender and rep.market_data_only(), (lane, rep.sends, rep.problems())
    # the systemd entries still send through the chokepoint (their --notify send default)
    assert AG.scan_entry("scripts/data_plausibility_monitor.py").is_sender
    assert AG.scan_entry("scripts/check_gap_resolution.py").is_sender


def test_gap_lane_receipt_is_v2(lane_env, monkeypatch):
    from scripts.lib import lane_last_receipt as R
    from scripts.lib import n8n_output_verdict as OV

    rid = f"d:{GAP_LANE}:live:20261018T1007"
    monkeypatch.setenv("TRADEAI_RUN_ID", rid)
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")  # the n8n executor sets it; main's receipt binds run_mode
    rep = _report(OPEN_NO_ATTEMPT=[{"gap_id": "g", "domain": "d", "subject": "S", "age_hours": 3, "origin": "x"}])
    rep.update({"receipts": 4, "queued_gaps": 1, "research_gaps": 0, "search_denials": 0})
    assert cgr.lane_main([], collect_fn=lambda: rep) == 0  # a finding is output, not a failure
    doc = json.loads(R.attempt_receipt_path(GAP_LANE, rid, lane_env.state).read_text())
    assert doc["produced_count"] == 2 and doc["attempted_count"] == 4
    eo = _contract(GAP_LANE)["expected_output"]
    assert OV.evaluate(eo, doc, run_id=rid, lane_id=GAP_LANE, mode="live")["verdict"] == "produced"
    empty = {**_report(), "receipts": 0, "queued_gaps": 0, "research_gaps": 0, "search_denials": 0}
    assert cgr.lane_output(empty)["empty_reason"] == "no_new_input"
    assert cgr.lane_output(None, error="OSError")["skipped_reasons"] == {cgr.SKIP_DEPENDENCY: 1}


def test_gap_dry_run_writes_nothing(lane_env, capsys):
    assert cgr.main(["--dry-run"], collect_fn=_report) == 0
    assert "DRY RUN" in capsys.readouterr().out and lane_env.receipts == []
    assert not cgr.STATE_PATH.exists() and not (lane_env.state / "data" / "runtime").exists()


# ── 7. llm_curation: deferred outside the window, never Ollama ────────────────────────────────────────────────────


def test_llm_curation_is_deferred_outside_the_bulk_window(monkeypatch):
    import scripts.lib.deepseek_offpeak as offpeak
    from scripts.lib import gap_resolver as gr

    monkeypatch.setattr(offpeak, "is_bulk_deepseek_window", lambda dt=None: False)
    monkeypatch.setattr(gr, "_curate_ollama", lambda p: pytest.fail("embedding model called for chat"))
    monkeypatch.setattr(gr, "_curate_deepseek", lambda p: pytest.fail("window closed"))
    ctx = gr.Context(live=True)
    out = gr._v_llm_curation(gr.DataGap(domain="analyst_view", subject="WMT", question="q", evidence={"k": 1}), {}, ctx)
    assert out.outcome == "deferred" and "deferred" in gr.OUTCOMES
    assert "deferred" in out.detail


def test_a_deferred_attempt_does_not_spend_the_vector_budget(tmp_path):
    from scripts.lib import gap_resolver as gr

    rows = [{"vector": "llm_curation", "outcome": "deferred", "started": NOW.isoformat(), "requester": "cron"}]
    path = tmp_path / "receipts.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert gr.attempts_today("llm_curation", now=NOW, path=path) == 0


# ── 8. n8n lanes with proper contracts ─────────────────────────────────────────────────────────────────────────────


def _rows() -> dict:
    return {r["lane_id"]: r for r in _load("lane_registry.json")["lanes"]}


def _allow() -> dict:
    return {e["lane_id"]: e for e in _load("n8n_run_allowlist.json")["lanes"]}


@pytest.mark.parametrize("lane,script,cadence,hours,lock,timeout", [
    (DPM_LANE, "scripts/n8n_data_plausibility_audit.py", "20 6 * * *", 24.0, "/tmp/tradeai_data_plausibility.lock", 600),
    (GAP_LANE, "scripts/n8n_gap_resolution_audit.py", "7,37 * * * *", 0.5, "/tmp/tradeai_gap_resolution.lock", 300),
])
def test_registry_allowlist_and_contract_pins(lane, script, cadence, hours, lock, timeout):
    from scripts.lib import lane_dispatch as LD
    from scripts.lib import n8n_health_contracts as H
    from scripts.lib import n8n_output_verdict as OV
    from tests.support import data_integrity_monitors_n8n as DIM

    row, hb = _rows()[lane], _rows()["n8n-comms-intent-consumer"]
    assert row["scheduler"] == {"kind": "n8n", "expression": "dispatcher", "match": script, "cadence": cadence,
                                "stage": "canary", "wave": "W4"}
    assert set(row["scheduler"]) == set(hb["scheduler"])
    assert row["dispatch"] == {"mode": "live", "cron": [cadence], "tz": "America/New_York", "wave": "W4",
                               "class": "monitor", "priority": 5, "retry_policy": "none"}
    assert row["state"] == "ACTIVE" and row["expected_cadence_hours"] == hours
    assert row["output_signal"] == {"kind": "json_key", "path": f"data/runtime/{lane}_last.json", "key": "ok_at"}
    assert LD.dispatch_eligible(row) == (True, "eligible") and LD.forbidden_hits(row) == []
    e = _allow()[lane]
    assert e["command"] == ["$PY", script] and e["dry_run_arg"] == ["--dry-run"]
    assert e["live_arg"] == []  # DRY live_arg first: lane_main measures + writes the receipt, notifies nobody
    assert e["lock"] == lock and e["lock_kind"] == "flock" and e["timeout_s"] == timeout
    assert e["output_receipt"] == "v2" and e["output_signal"] == row["output_signal"]["path"]
    assert e["market_gate"] is False and not any("send" in a or "telegram" in a for a in e["live_arg"])
    c = _contract(lane)
    assert c["status"] == "REVIEWED" and c["stage"] == "canary" and c["workflow_id"] == "dispatcher"
    assert H.validate_contract(c) == [] and H.unknown_fields(c) == []
    assert OV.validate_expected_output(c["expected_output"]) == []
    assert "dependency_unavailable" in c["expected_output"]["fatal_skip_reasons"]
    assert c["alerting"]["failed"]["notifier_priority"] == "P2"  # never PAGE (§24.1)
    assert c["baseline"]["timeout_s"] == timeout
    assert lane in DIM.LIVE and DIM.LANES[lane][:3] == (script, cadence, lock)
    assert lane not in _load("n8n_effect_keys.json")["lanes"]
    # the legacy systemd rows are untouched: the timers stay the alerting owners until c3
    legacy = {DPM_LANE: "data-plausibility-audit", GAP_LANE: "gap-resolution-audit"}[lane]
    assert _rows()[legacy]["scheduler"]["kind"] == "systemd" and _rows()[legacy]["state"] == "ACTIVE"


def test_the_health_contract_gate_has_no_errors_for_the_lanes():
    from scripts.lib import n8n_health_contracts as H

    res = H.check(_load("n8n_health_contracts.json"), _load("lane_registry.json"), H.load_json(H.GENERIC_INDEX_PATH))
    assert not [e for e in res["errors"] if DPM_LANE in e or GAP_LANE in e]


def test_the_cli_flags_in_the_allowlist_are_real():
    for mod in (dpm, cgr):
        src = Path(mod.__file__).read_text()
        for flag in ("--lane-receipt", "--dry-run", "--notify", "--alert"):
            assert f'"{flag}"' in src, (mod.__name__, flag)


@pytest.mark.parametrize("lane,now,slot", [
    (DPM_LANE, datetime(2026, 10, 18, 10, 20, tzinfo=timezone.utc), "20261018T0620"),
    (GAP_LANE, datetime(2026, 10, 18, 14, 37, tzinfo=timezone.utc), "20261018T1037"),
])
def test_the_gateway_emits_a_live_d_key_and_demotes_off_the_live_list(lane, now, slot, tmp_path, monkeypatch):
    from scripts.lib import n8n_due as D
    from scripts.lib import n8n_retry_policy as RP
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

    rows, allow = [_rows()[lane]], {lane: _allow()[lane]}
    policies = RP.load_policies(CONFIG / "n8n_retry_policies.json")
    led = CoordinationLedger(tmp_path / "ledger.sqlite")
    try:
        store = LedgerRunStore(led)
        monkeypatch.setenv("TRADEAI_N8N_RELAY_LIVE_LANES", f"heartbeat-watch {lane}")
        due = D.compute_due(rows, allow, policies, store, now, source="schedule")
        assert [(i["lane_id"], i["mode"], i["idempotency_key"]) for i in due["items"]] == [
            (lane, "live", f"d:{lane}:live:{slot}")]
        monkeypatch.setenv("TRADEAI_N8N_RELAY_LIVE_LANES", "heartbeat-watch")
        due = D.compute_due(rows, allow, policies, store, now, source="schedule")
        assert [(i["mode"], i["reason"]) for i in due["items"]] == [("dry_run", "relay_live_not_enabled")]
    finally:
        led.close()


def test_host_routes_load_and_name_one_producer_each():
    from scripts.lib import n8n_fabric_store as F

    routes = F.load_host_intent_routes()["routes"]
    assert routes[("data", "data_plausibility_violation")] == {
        "tier": "DIGEST", "runbook_id": "data-plausibility-audit", "producer": "data_plausibility_monitor"}
    assert routes[("data", "gap_resolution_finding")]["tier"] == "DIGEST"
    assert routes[("data", "gap_resolution_digest")]["tier"] == "DASHBOARD"
    assert dpm.INTENT_PRODUCER == "data_plausibility_monitor" and cgr.INTENT_PRODUCER == "check_gap_resolution"


# ── 8b. the operator packet against fakes ──────────────────────────────────────────────────────────────────────────


def test_packet_is_dry_by_default_set_f_and_never_changes_a_unit():
    src = SCRIPT.read_text()
    assert src.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in src and "\nset -f\n" in src
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    for bad in ("rm ", "crontab", "n8n import", "import:workflow", "update:workflow", "DELETE ", "DROP ", "--force",
                "UPDATE ", "INSERT "):
        assert bad not in code, bad
    # every state-changing systemctl verb is only ever ECHOED for the operator; the script runs read-only queries
    for line in code.splitlines():
        if "SYSTEMCTL_BIN\"" in line:
            assert "is-enabled" in line or "is-active" in line, line
        for verb in ("restart", "disable", "enable --now", "stop "):
            if f"systemctl --user {verb}" in line:
                assert f'echo "    systemctl --user {verb}' in line or "operator_commands" in line, line
    assert os.access(SCRIPT, os.X_OK)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_packet_passes_shellcheck():
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


@pytest.fixture
def pk(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "systemctl.calls"
    (bin_dir / "systemctl").write_text("#!/usr/bin/env bash\n"
                                       f'echo "$*" >> {calls}\n'
                                       'case "$*" in *is-enabled*) echo enabled ;; *is-active*) echo active ;; esac\n')
    (bin_dir / "systemctl").chmod(0o755)
    live = tmp_path / "n8n-live-lanes.env"
    live.write_text("# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-incident-fanin\n")
    live.chmod(0o600)
    state = tmp_path / "state"
    (state / "data" / "governance").mkdir(parents=True)
    served = tmp_path / "served"
    shutil.copytree(CONFIG, served / "config")
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PY": sys.executable, "SERVED": str(served),
           "STATE": str(state), "LEDGER": str(state / "data" / "governance" / "n8n_coordination_ledger.sqlite"),
           "LIVE_LANES_ENV": str(live), "SYSTEMCTL_BIN": str(bin_dir / "systemctl")}

    def run(*args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True,
                              timeout=120, cwd=str(tmp_path))

    return types.SimpleNamespace(run=run, live=live, calls=calls, state=state, served=served, tmp=tmp_path, env=env)


def test_relay_dry_run_changes_nothing_and_apply_needs_a_grant(pk):
    before = pk.live.read_bytes()
    p = pk.run("relay")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "DRY RUN" in p.stdout and f"adds: {DPM_LANE} {GAP_LANE}" in p.stdout
    assert "systemctl --user restart tradeai-n8n-run-relay.service" in p.stdout  # printed, not run
    assert pk.live.read_bytes() == before and not pk.calls.exists()
    p = pk.run("relay", "--apply")
    assert p.returncode == 1 and "TRADEAI_FABRIC_GRANT not set" in p.stdout


def test_relay_apply_appends_backs_up_reads_back_and_restarts_nothing(pk):
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert pk.live.read_text() == (
        f"# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-incident-fanin {DPM_LANE} {GAP_LANE}\n")
    assert oct(pk.live.stat().st_mode & 0o777) == "0o600"
    assert len(list(pk.tmp.glob("n8n-live-lanes.env.bak-*-data-integrity-monitors-relay"))) == 1
    assert not pk.calls.exists()  # no systemctl at all: the restart is the operator's
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0 and "already has both lanes" in p.stdout


def test_c3_refuses_until_the_owner_switch_argv_is_served(pk):
    pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    p = pk.run("c3", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 1 and "owner-switch argv" in p.stdout
    assert not (pk.state / "data" / "runtime" / "data_integrity_monitors_owner_switch.json").exists()


def _served_owner_argv(pk) -> None:
    path = pk.served / "config" / "n8n_run_allowlist.json"
    doc = json.loads(path.read_text())
    for e in doc["lanes"]:
        if e["lane_id"] in (DPM_LANE, GAP_LANE):
            e["live_arg"] = ["--alert"]
    path.write_text(json.dumps(doc))


def _proof_runs(pk, ok: bool = True) -> None:
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger

    ledger = Path(pk.env["LEDGER"])
    CoordinationLedger(ledger).close()
    conn = sqlite3.connect(ledger)
    runtime = pk.state / "data" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    for lane in (DPM_LANE, GAP_LANE):
        rid = f"d:{lane}:live:20261018T1037"
        rec = {"run_id": rid, "state": "RUN_DONE", "output_verdict": {"verdict": "produced", "produced_count": 2}}
        conn.execute("INSERT INTO runs (run_id, lane_id, mode, state, requested_at, receipt_json) VALUES (?,?,?,?,?,?)",
                     (rid, lane, "live", "RUN_DONE" if ok else "RUN_FAILED", datetime.now(timezone.utc).isoformat(),
                      json.dumps(rec)))
        (runtime / f"{lane}_last.json").write_text(json.dumps({"status": "ok" if ok else "failed",
                                                              "ok_at": "2026-10-18T14:37:00+00:00"}))
    conn.commit()
    conn.close()


def test_proof_needs_a_good_live_run_per_lane(pk):
    _proof_runs(pk, ok=False)
    p = pk.run("proof")
    assert p.returncode == 1 and "FAIL" in p.stdout


def test_c3_records_the_switch_and_only_prints_the_timer_commands(pk):
    pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    _served_owner_argv(pk)
    _proof_runs(pk, ok=True)
    p = pk.run("proof")
    assert p.returncode == 0, p.stdout + p.stderr
    p = pk.run("c3")
    assert p.returncode == 0 and "DRY RUN" in p.stdout, p.stdout + p.stderr
    p = pk.run("c3", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "systemctl --user disable --now tradeai-data-plausibility.timer" in p.stdout
    assert "systemctl --user disable --now tradeai-gap-resolution.timer" in p.stdout
    doc = json.loads((pk.state / "data" / "runtime" / "data_integrity_monitors_owner_switch.json").read_text())
    assert doc["owner"] == "n8n" and doc["grant"] == "g1" and doc["lanes"] == [DPM_LANE, GAP_LANE]
    assert not pk.calls.exists()  # never ran systemctl
    p = pk.run("rollback", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert pk.live.read_text() == "# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-incident-fanin\n"
    assert "systemctl --user enable --now tradeai-data-plausibility.timer" in p.stdout
    assert not pk.calls.exists()
