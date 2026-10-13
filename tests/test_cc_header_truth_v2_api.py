#!/usr/bin/env python3
"""cc-header-truth-v2 — API wiring pins.

These are structural assertions (AST) that the canonical contracts are actually
wired into the served endpoints, not merely defined and left unused — the
filing-cabinet defect AGENTS.md §13.5 names.

No network, broker, scheduler, Drive, database or production path is touched.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API_V2 = ROOT / "scripts" / "api_v2.py"


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(API_V2.read_bytes())


def _fn(tree, name):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    pytest.fail(f"{name}() not found in api_v2.py")


def _dict_keys(node: ast.AST) -> set:
    keys = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict):
            for k in sub.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


# ── VIX names its source and observation time (Phase 2 D) ────────────────────


def test_vix_observation_returns_source_and_observation_time(tree):
    fn = _fn(tree, "_vix_observation")
    # A bare float hides which source answered; the contract is a 3-tuple.
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    assert any(isinstance(r.value, ast.Tuple) and len(r.value.elts) == 3 for r in returns), (
        "_vix_observation must return (value, source, observation_time)"
    )
    # the fallback path reads market_regime_indicators.vix_close by name
    src = ast.dump(fn)
    assert "market_regime_indicators.vix_close" in src


def test_compute_trade_ai_publishes_vix_source_and_observation_time(tree):
    fn = _fn(tree, "_compute_trade_ai")
    keys = _dict_keys(fn)
    assert "vix_source" in keys
    assert "vix_observation_time" in keys


# ── run-scoped GO/WAIT/NOGO contract is wired (Phase 2 C) ────────────────────


def test_compute_trade_ai_publishes_run_id_and_setup_run_summary(tree):
    fn = _fn(tree, "_compute_trade_ai")
    keys = _dict_keys(fn)
    assert "run_id" in keys
    assert "setup_run_summary" in keys


def test_summary_endpoint_serves_the_canonical_contract(tree):
    fn = _fn(tree, "trade_ai_summary")
    # the keys tuple must carry the canonical fields so the header reads them
    keys = {
        elt.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Tuple)
        for elt in node.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    }
    assert {"run_id", "setup_run_summary", "vix_source", "vix_observation_time"} <= keys


# ── overview reads trade_ai from the same cached payload, not a raw file ─────


def test_overview_sources_trade_ai_from_the_cached_payload(tree):
    fn = _fn(tree, "overview")
    calls = [
        n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "trade_ai"
    ]
    assert calls, "overview must read trade_ai() (same payload as summary), not a divergent file"


def test_overview_trade_ai_block_carries_run_id_and_setup_summary(tree):
    fn = _fn(tree, "overview")
    keys = _dict_keys(fn)
    assert "setup_run_summary" in keys
    assert "run_id" in keys
    assert "vix_source" in keys
    assert "vix_observation_time" in keys


# ── portfolio aggregate names scope (Phase 2 A) ──────────────────────────────


def test_overview_publishes_an_all_accounts_aggregate(tree):
    fn = _fn(tree, "overview")
    keys = _dict_keys(fn)
    assert "portfolio_aggregate" in keys
    src = ast.dump(fn)
    # Wired through the contract builder — not an inline dict that can drift
    # from accounts[] clocks (live acceptance rollback 2026-09-03).
    assert "build_portfolio_aggregate" in src, (
        "overview must call build_portfolio_aggregate so oldest/newest share accounts[] clocks"
    )


def test_overview_publishes_a_quote_selection_envelope(tree):
    fn = _fn(tree, "overview")
    keys = _dict_keys(fn)
    assert "quote_selection" in keys, "the header must expose selected quote provider vs fallback"


# ── journal metrics state basis, window, scope (Phase 2 E) ───────────────────


def test_journal_block_states_basis_window_and_scope(tree):
    fn = _fn(tree, "overview")
    keys = _dict_keys(fn)
    assert "account_scope" in keys, "journal must name the account scope"
    assert "time_window" in keys, "journal must name the time window"
    assert "calculation_version" in keys, "journal must name its calculation version"


# Shared scanner/advisory view exercises real pure source with scratch files only.
@pytest.fixture
def candidate_projection():
    from lib import scanner_candidate_projection

    return scanner_candidate_projection


def _shared_fixture():
    return {
        "run_id": "2026-10-12::0900",
        "latest_run_timestamp": "2026-10-12T13:13:15+00:00",
        "setup_run_summary": {"run_id": "2026-10-12::0900", "run_date": "2026-10-12", "scanned_count": 44},
        "tickers": [
            {
                "symbol": "ABCD",
                "decision": "WAIT",
                "run_id": "2026-10-12::0900",
                "security_guid": "tradeai:security:fixture-abcd",
                "event_id": "fixture-event",
                "event_at": "2026-10-12T13:10:00Z",
            },
            {"symbol": "TRADE", "decision": "GO", "run_id": "2026-10-12::0900"},
        ],
    }, [
        {
            "contract": "active-trader-momentum-alert-v1",
            "ts_epoch": 1791813060,
            "candidate": {
                "symbol": " abcd ",
                "session_date": "2026-10-12",
                "security_guid": "tradeai:security:fixture-abcd",
                "event_id": "fixture-event",
                "event_at": "2026-10-12T13:10:00Z",
            },
            "kind": "TRIGGERED",
            "verdict": "ALERT",
            "sent": True,
        },
        {
            "contract": "active-trader-momentum-alert-v1",
            "ts_epoch": 1791813120,
            "candidate": {"symbol": "ONLYAT", "session_date": "2026-10-12"},
            "kind": "ARMED",
            "verdict": "ALERT",
            "sent": False,
        },
    ]


def _shared_build(mod, cache=None, journal=None, **kwargs):
    cache0, journal0 = _shared_fixture()
    from datetime import datetime

    return mod.build_candidate_projection(
        cache0 if cache is None else cache,
        journal0 if journal is None else journal,
        now=datetime.fromisoformat("2026-10-12T14:00:00+00:00"),
        **kwargs,
    )


def test_shared_candidates_union_is_bidirectional_and_source_verdicts_remain(candidate_projection):
    out = _shared_build(candidate_projection)
    rows = {r["symbol"]: r for r in out["candidates"]}
    assert set(rows) == {"ABCD", "TRADE", "ONLYAT"}
    assert rows["ABCD"]["sources"] == ["ACTIVE_TRADER", "TRADE_AI"]
    assert rows["ABCD"]["trade_ai"]["verdicts"] == ["WAIT"]
    assert rows["ABCD"]["active_trader"]["verdicts"] == ["ALERT"]
    assert rows["ONLYAT"]["classification"] == "PENDING"
    assert rows["ONLYAT"]["trade_ai"]["status"] == "MISSING"
    assert rows["TRADE"]["active_trader"]["status"] == "MISSING"
    assert out["authority"] == "READ_ONLY_ADVISORY"
    assert out["memory_behavior_influence"] == 0


def test_shared_projection_preserves_sources_and_all_approval_fields(candidate_projection):
    import copy

    cache, journal = _shared_fixture()
    cache["tickers"][0].update(approval="REJECTED", account="fixture", qty=13, live=False)
    journal[0].update(approval="AUTHORIZED", order_id="fixture-order", stop=12.3)
    before = copy.deepcopy((cache, journal))
    out = _shared_build(candidate_projection, cache, journal)
    assert (cache, journal) == before

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(v) for v in value))
        return set()

    assert not {"approval", "order_id", "qty", "stop", "account", "live"} & keys(out)
    assert all(r["execution_authority"] == "NONE" for r in out["candidates"])


def test_shared_projection_duplicate_signal_has_stable_identity_and_snapshot(candidate_projection):
    import copy

    cache, journal = _shared_fixture()
    journal += [copy.deepcopy(journal[0])]
    a = _shared_build(candidate_projection, cache, journal)
    b = _shared_build(candidate_projection, cache, list(reversed(journal)))
    assert a["candidates"] == b["candidates"]
    assert a["snapshot_id"] == b["snapshot_id"]
    joined = next(r for r in a["candidates"] if r["symbol"] == "ABCD")
    assert len(joined["active_trader"]["observations"]) == 1


def test_shared_projection_keeps_conflicting_events_and_marks_disagreement(candidate_projection):
    cache, journal = _shared_fixture()
    cache["tickers"][0]["decision"] = "AVOID"
    other = dict(journal[0], ts_epoch=1791813200, verdict="VETO", sent=False)
    journal.append(other)
    out = _shared_build(candidate_projection, cache, journal)
    row = next(r for r in out["candidates"] if r["symbol"] == "ABCD")
    assert row["classification"] == "CONFLICT"
    assert set(row["active_trader"]["verdicts"]) == {"ALERT", "VETO"}
    assert len(row["active_trader"]["observations"]) == 2
    assert "CROSS_SOURCE_DISAGREEMENT" in row["conflicts"]
    assert "ACTIVE_TRADER_VERDICT_CONFLICT" in row["conflicts"]


def test_shared_projection_friday_run_cannot_become_monday_by_session_anchor(candidate_projection):
    cache, journal = _shared_fixture()
    cache.update(
        run_id="2026-10-09::1730", date="2026-10-12", stale=False, latest_run_timestamp="2026-10-09T21:38:48+00:00"
    )
    cache["setup_run_summary"].update(run_id="2026-10-09::1730", run_date="2026-10-09")
    cache["tickers"][0]["run_id"] = "2026-10-09::1730"
    cache["tickers"][1]["run_id"] = "2026-10-09::1730"
    out = _shared_build(candidate_projection, cache, journal)
    row = next(r for r in out["candidates"] if r["symbol"] == "ABCD")
    assert row["trade_ai"]["session_state"] == "STALE_SESSION"
    assert row["trade_ai"]["observations"][0]["run_id"] == "2026-10-09::1730"
    assert out["source_metadata"]["TRADE_AI"]["business_date_mismatch"] is True
    assert out["source_metadata"]["TRADE_AI"]["summary"]["scanned_count"] == 44


def test_shared_projection_unknown_metadata_never_promotes_to_go(candidate_projection):
    out = _shared_build(candidate_projection, {"tickers": [{"symbol": "XX", "decision": "NEW_VALUE"}]}, [])
    row = out["candidates"][0]
    assert row["classification"] == "UNKNOWN"
    assert row["trade_ai"]["verdicts"] == ["UNKNOWN"]
    assert row["trade_ai"]["session_state"] == "UNKNOWN"
    assert row["trade_ai"]["observations"][0]["observed_at"] is None
    assert row["execution_authority"] == "NONE"


@pytest.mark.parametrize("cache,journal", [(None, None), ([], {}), ({"tickers": "bad"}, [None, 4])])
def test_shared_projection_unavailable_sources_are_not_measured_zero(candidate_projection, cache, journal):
    out = _shared_build(
        candidate_projection,
        cache={} if cache is None else cache,
        journal=[] if journal is None else journal,
        source_status={"TRADE_AI": "MALFORMED", "ACTIVE_TRADER": "MISSING"},
    )
    assert out["status"] == "UNAVAILABLE"
    assert out["candidate_count"] is None
    assert out["candidates"] == []


def test_shared_projection_reader_is_read_only_and_retains_partial_file_failure(candidate_projection, tmp_path):
    import json

    cache, journal = _shared_fixture()
    cp, jp = tmp_path / "trade_ai_cache.json", tmp_path / "momentum_alerts.jsonl"
    cp.write_text(json.dumps(cache))
    jp.write_text("\n".join(json.dumps(r) for r in journal) + "\n")
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (cp, jp)]
    out = candidate_projection.read_candidate_snapshot(cp, jp)
    assert out["candidate_count"] == 3
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in (cp, jp)] == before
    cp.write_text("{malformed")
    bad = cp.read_bytes()
    out = candidate_projection.read_candidate_snapshot(cp, jp)
    assert out["status"] == "PARTIAL"
    assert out["source_metadata"]["TRADE_AI"]["status"] == "MALFORMED"
    assert {r["symbol"] for r in out["candidates"]} == {"ABCD", "ONLYAT"}
    assert cp.read_bytes() == bad


def test_shared_reader_refuses_oversized_cache_and_reports_truncated_journal(candidate_projection, tmp_path):
    import json

    cp, jp = tmp_path / "trade_ai_cache.json", tmp_path / "momentum_alerts.jsonl"
    cp.write_text(" " * 100)
    jp.write_text("bad\n" + json.dumps(_shared_fixture()[1][0]) + "\n")
    out = candidate_projection.read_candidate_snapshot(cp, jp, max_cache_bytes=10, max_journal_bytes=150)
    assert out["source_metadata"]["TRADE_AI"]["status"] == "OVERSIZED"
    assert out["source_metadata"]["ACTIVE_TRADER"]["tail_truncated"] is True


def test_shared_candidates_endpoint_has_no_producer_or_engine_calls(tree, monkeypatch, tmp_path):
    import types

    fn = _fn(tree, "trade_ai_candidates")
    called = []
    fixture = types.ModuleType("lib.scanner_candidate_projection")
    fixture.read_candidate_snapshot = lambda cp, jp: called.append((cp, jp)) or {"snapshot_id": "fixture"}
    fixture.build_candidate_projection = lambda *args, **kwargs: pytest.fail("missing-root fallback unexpectedly used")
    monkeypatch.setitem(sys.modules, "lib.scanner_candidate_projection", fixture)
    state = tmp_path / "state"
    state.mkdir()
    (state / "PERSISTENT_STATE_ROOT.json").write_text("{}")

    class FixturePath:
        @staticmethod
        def home():
            return tmp_path

    target = tmp_path / "trade-ai-releases" / "persistent-state"
    target.mkdir(parents=True)
    (target / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    ns = {"Path": FixturePath}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(API_V2), "exec"), ns)
    assert ns["trade_ai_candidates"]() == {"snapshot_id": "fixture"}
    assert called == [
        (target / "data/runtime/trade_ai_cache.json", target / "data/active_trader/momentum_alerts.jsonl")
    ]
    src = ast.dump(fn)
    assert "trade_ai" not in {
        n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "active_trader" not in {n.module for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)}
    routes = next(
        n.value
        for n in tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ROUTES" for t in n.targets)
    )
    assert any(
        isinstance(k, ast.Constant)
        and k.value == "/api/v2/trade-ai/candidates"
        and isinstance(v, ast.Name)
        and v.id == "trade_ai_candidates"
        for k, v in zip(routes.keys, routes.values)
    )


def test_both_views_consume_the_identical_shared_candidate_component():
    for page in ("TradingHub.tsx", "ActiveTraderHub.tsx"):
        src = (ROOT / "apps/command-center-v3/src/pages" / page).read_text()
        assert "<SharedMomentumCandidates" in src
    comp = (ROOT / "apps/command-center-v3/src/components/tradeai/SharedMomentumCandidates.tsx").read_text()
    assert "/api/v2/trade-ai/candidates" in comp
    assert "snapshot_id" in comp
    assert "source_metadata" in comp


def test_shared_endpoint_missing_canonical_marker_refuses_alternate_roots(tree, monkeypatch, tmp_path):
    import types

    calls = []
    fixture = types.ModuleType("lib.scanner_candidate_projection")
    fixture.read_candidate_snapshot = lambda *args: pytest.fail("unmarked source root was read")
    fixture.build_candidate_projection = lambda *args, **kwargs: (
        calls.append((args, kwargs)) or {"status": "UNAVAILABLE"}
    )
    monkeypatch.setitem(sys.modules, "lib.scanner_candidate_projection", fixture)

    class FixturePath:
        @staticmethod
        def home():
            return tmp_path

    ns = {"Path": FixturePath}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[_fn(tree, "trade_ai_candidates")], type_ignores=[])),
            str(API_V2),
            "exec",
        ),
        ns,
    )
    assert ns["trade_ai_candidates"]() == {"status": "UNAVAILABLE"}
    assert calls == [((None, None), {"source_status": {"TRADE_AI": "UNAVAILABLE", "ACTIVE_TRADER": "UNAVAILABLE"}})]


def test_shared_projection_unproven_go_is_unknown_and_source_verdict_is_retained(candidate_projection):
    out = _shared_build(candidate_projection, {"tickers": [{"symbol": "XX", "decision": "GO"}]}, [])
    row = out["candidates"][0]
    assert row["classification"] == "UNKNOWN"
    assert row["trade_ai"]["verdicts"] == ["GO"]
    assert out["source_sha"] == "UNKNOWN"
    assert out["run_id"] is None and out["finished_at"] is None


def test_shared_projection_population_contract_does_not_invent_consumer_confirmation(candidate_projection):
    out = _shared_build(candidate_projection)
    assert out["population_contract"] == "shared_signal_union"
    assert out["projection_hash"] == out["snapshot_id"]
    assert out["source_verdicts_preserved"] is True
    assert "consumer_views" not in out
    assert out["source_metadata"]["TRADE_AI"]["freshness_bound_seconds"] == "NOT_MEASURED"


def test_shared_snapshot_hash_binds_canonical_summary_without_retally(candidate_projection):
    import copy

    cache, journal = _shared_fixture()
    original = _shared_build(candidate_projection, cache, journal)
    corrected_cache = copy.deepcopy(cache)
    corrected_cache["setup_run_summary"]["scanned_count"] = 42
    corrected = _shared_build(candidate_projection, corrected_cache, journal)
    assert original["candidates"] == corrected["candidates"]
    assert original["snapshot_id"] != corrected["snapshot_id"]
    assert original["source_metadata"]["TRADE_AI"]["summary"]["scanned_count"] == 44
    assert corrected["source_metadata"]["TRADE_AI"]["summary"]["scanned_count"] == 42
