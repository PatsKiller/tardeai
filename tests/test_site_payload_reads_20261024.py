"""W2 population, byte-budget and cache-only GET contracts; all state is synthetic."""
import copy
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib import site_payload_reads as reads

NOW = datetime(2026, 10, 24, 20, tzinfo=timezone.utc)


def candidate(i, *, history=4):
    source = {"status": "AVAILABLE", "session_state": "CURRENT_SESSION", "verdicts": ["WAIT"],
              "observations": [{"verdict": "WAIT", "observed_at": NOW.isoformat(),
                                "setup_evidence": {"passed_count": 2, "catalyst": {"text": "界" * 900}}}
                               for _ in range(history)]}
    return {"candidate_id": str(i), "symbol": f"TEST{i}", "trade_ai": copy.deepcopy(source),
            "active_trader": copy.deepcopy(source), "conflicts": ["source_disagreement"] if i % 3 == 0 else [],
            "classification": "PENDING" if i % 2 == 0 else "WAIT"}


def test_every_candidate_reachable_once_under_200kb_without_mutating_owner():
    source = {"schema": "SharedMomentumCandidates@v1", "candidate_count": 220,
              "candidates": [candidate(i) for i in range(220)]}
    original = copy.deepcopy(source)
    seen, offset = [], 0
    while True:
        page = reads.candidates_page(source, {"filter": "ALL", "limit": 100, "offset": offset})
        assert reads.encoded_size({"ok": True, "data": page}) < 200_000
        assert page["candidate_count"] == 220
        assert page["pagination"]["total"] == 220
        assert all(len(r["trade_ai"]["observations"]) == 1 for r in page["candidates"])
        seen.extend(r["candidate_id"] for r in page["candidates"])
        if not page["pagination"]["has_more"]:
            break
        assert page["pagination"]["next_offset"] > offset
        offset = page["pagination"]["next_offset"]
    assert seen == [str(i) for i in range(220)]
    assert source == original
    detail = reads.candidates_page(source, {"candidate_id": "9", "filter": "ALL"})
    assert len(detail["candidates"][0]["trade_ai"]["observations"]) == 4


def test_candidate_filters_apply_before_offset_and_counts_cover_source():
    source = {"candidate_count": 12, "candidates": [candidate(i, history=1) for i in range(12)]}
    page = reads.candidates_page(source, {"filter": "CONFLICT", "offset": 1, "limit": 2})
    assert [r["candidate_id"] for r in page["candidates"]] == ["3", "6"]
    assert page["filter_counts"] == {"ALL": 12, "ACTIONABLE": 12, "CONFLICT": 4, "CURRENT": 12}
    assert page["pagination"]["total"] == 4
    assert page["candidate_count"] == 12
    assert reads.candidates_page({"candidate_count": None, "candidates": []})["candidate_count"] is None


@pytest.mark.parametrize("query", [{"limit": "bad", "offset": "no"}, {"limit": ["1000000"], "offset": [-20]}, {"limit": "-1"}])
def test_windows_are_bounded_even_for_malformed_queries(query):
    offset, limit = reads.window(query)
    assert offset >= 0 and 1 <= limit <= 100


def test_single_oversized_row_and_metadata_are_explicit_gaps():
    page = reads.page_rows({"rows": [{"symbol": "HUGE", "facts": "x" * 600_000}]}, "rows")
    assert page["rows"] == [] and page["payload_gap"]["reason"] == "row_exceeds_payload_budget"
    assert page["pagination"]["total"] == 1
    assert page["pagination"]["next_offset"] is None
    page = reads.page_rows({"rows": [], "huge": "x" * 600_000}, "rows")
    assert reads.encoded_size(page) < 500_000
    assert page["payload_gap"]["reason"] == "metadata_exceeds_payload_budget"


def test_scanner_filters_before_page_and_drops_global_etag():
    source = {"__etag__": 'W/"owner"', "tickers": [{"symbol": f"T{i}", "decision": "GO" if i % 2 else "WAIT"} for i in range(15)],
              "summary": {"go": 7}}
    page = reads.scanner_page(source, {"decision": "GO", "limit": 2, "offset": 2})
    assert [r["symbol"] for r in page["tickers"]] == ["T5", "T7"]
    assert page["pagination"]["total"] == 7
    assert page["summary"] == source["summary"]
    assert "__etag__" not in page and "__etag__" in source


def test_scheduler_paging_preserves_global_health_summary():
    source = {"rows": [{"id": i} for i in range(800)], "summary": {"FAILED": 200, "OK": 600}}
    page = reads.scheduler_page(source, {"offset": 700, "limit": 50})
    assert page["pagination"]["total"] == 800 and len(page["rows"]) == 50
    assert page["rows"][0]["id"] == 700 and page["summary"] == source["summary"]


def test_prospects_returns_only_selected_lane_rows_and_all_lane_counts():
    source = {"counts": {"total": 180}, "lanes": [{"id": lane, "count": 90, "items": [{"symbol": f"{lane}{i}"} for i in range(90)]} for lane in ("actionable", "forming")]}
    page = reads.prospects_page(source, {"lane": "forming", "offset": 25, "limit": 25})
    assert page["lanes"][0]["items"] == [] and page["lanes"][0]["count"] == 90
    assert page["lanes"][1]["items"][0]["symbol"] == "forming25"
    assert page["pagination"]["total"] == 90 and page["counts"]["total"] == 180


def test_watchpool_counts_are_from_full_deduplicated_population_and_sql_pages():
    calls = []
    def query(sql, params=None):
        calls.append((sql, params))
        assert "DISTINCT ON (sp.symbol, sp.strategy_id, sp.origin_system)" in sql
        if "GROUP BY 1,2" in sql:
            return [{"current_status": "ACTIVE", "origin_system": "cio", "n": 800}, {"current_status": "EXPIRED", "origin_system": "screener", "n": 300}]
        return [{"symbol": f"T{i}", "current_status": "ACTIVE"} for i in range(100, 150)]
    page = reads.read_watchpool({"status": "ACTIVE", "offset": 100, "limit": 50}, db_query=query)
    assert page["count"] == 1100 and page["by_status"] == {"ACTIVE": 800, "EXPIRED": 300}
    assert page["pagination"]["total"] == 800 and page["pagination"]["next_offset"] == 150
    assert calls[1][1] == ("ACTIVE", 50, 100)
    assert "LIMIT %s OFFSET %s" in calls[1][0]
    assert reads.read_watchpool({}, db_query=lambda *a, **k: None)["count"] is None


def test_expired_invalidated_and_bad_expiry_removed_before_top_n(monkeypatch):
    from lib.data_broker import watch_prospects, watch_curation
    rows = {}
    for i, stage in enumerate(["expired", "invalidated", "forming", "forming", "forming"]):
        row = watch_prospects.no_record_row(f"TEST{i}")
        row.update(stage=stage, lane="expired" if stage == "expired" else "forming",
                   expires_at="2026-10-25T20:00:00Z", conviction=80-i)
        rows[row["symbol"]] = row
    rows["TEST4"]["expires_at"] = "bad"
    g = {"now": NOW, "payload": {}, "row_for": rows.__getitem__, "opps": {s: {"rank": i+1, "conviction": 80-i} for i, s in enumerate(rows)}, "operator": {}, "held": set(), "proj_meta": {}}
    monkeypatch.setattr(watch_prospects, "gather", lambda q: g)
    monkeypatch.setattr(watch_curation, "read_dismissed", lambda **k: ({}, "ok"))
    out = reads.read_curation({"n": 2, "view": "suggests"})
    assert [r["symbol"] for r in out["suggests"]["rows"]] == ["TEST2", "TEST3"]
    assert out["suggests"]["pagination"]["total"] == 2
    assert "capped stage view" in out["suggests"]["universe_note"]
    assert set(g["opps"]) == set(rows)


def test_broker_list_refresh_is_cache_only_even_if_stale(tmp_path):
    path = tmp_path / "data/runtime/broker_list_cache.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"v2|symbol=TEST": {"ts": NOW.timestamp()-1000, "data": {"proposals": [{"symbol": "TEST", "current_price": 9}], "pagination": {"total": 1}}}}))
    before = path.read_bytes()
    out = reads.read_broker_list(tmp_path, {"symbol": ["TEST"], "refresh": "1"}, now=NOW)
    assert out["quotes_live"] is False and out["stale"] is True
    assert out["proposals"][0]["current_price"] == 9
    assert out["provider_calls"] == 0 and path.read_bytes() == before
    assert reads.read_broker_list(tmp_path, {"symbol": "MISSING"}, now=NOW)["pagination"]["total"] is None


def test_stored_stop_rows_never_claim_complete_broker_read():
    calls = []
    def query(sql):
        calls.append(sql)
        return [{"account": "schwab_roth_ira", "symbol": "TEST", "stop_price": 8,
                 "status": "pending_activation", "captured_at": NOW.isoformat()}]
    def resolver(account, symbol, *, broker_rows, now):
        assert broker_rows[0]["status"] == "pending_activation"
        return {"stop_price": 8, "stop_state": "pending_activation", "stop_status_raw": "pending_activation", "stop_captured_at": NOW.isoformat()}
    out = reads.read_stored_stops({"refresh": "true"}, db_query=query, stop_resolver=resolver, now=NOW)
    assert len(calls) == 1 and calls[0].lstrip().startswith("SELECT")
    assert out["by_key"]["TEST:schwab_roth_ira"]["status"] == "pending_activation"
    assert out["attempted"] is False and out["provider_calls"] == 0
    assert out["complete"] is False and out["broker_stop_read_ok_accounts"] == []


def test_directive_and_staged_totals_do_not_equal_list_caps(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "research_critique_pipeline", types.SimpleNamespace(load_critique_snapshot=lambda: {}, extract_critique_fields=lambda _: {}))
    monkeypatch.setitem(sys.modules, "lib.data_broker.watch_discovery", types.SimpleNamespace(directive_score_meta=lambda _: {}))
    calls = []
    def query(sql, params=None, fetch="all"):
        calls.append((sql, params))
        if fetch == "one":
            if "AS total" in sql:
                return {"total": 1200, "proposed": 110}
            return {"n": 900}
        return []
    out = reads.read_watch_directives({"offset": 50, "limit": 25}, db_query=query, root=tmp_path)
    assert out["directive_count"] == 1200 and out["proposed_count"] == 110
    assert out["desk_suggestions_count"] == 900 and out["recent_hits_count"] == 900
    assert any("LIMIT %s OFFSET %s" in sql and params == (25, 50) for sql, params in calls)
    assert out["pagination"]["total"] == 1200


def test_adapter_source_has_no_execution_or_network_imports():
    import ast
    tree = ast.parse(Path(reads.__file__).read_text())
    forbidden = {"subprocess", "requests", "httpx", "socket", "open_trades_intelligence", "broker_desk_automation", "schwab"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not forbidden.intersection(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in forbidden


def test_canonical_guid_values_win_and_lower_signals_remain_conflicts():
    projection, calls = {"prospects": []}, []
    rows = [{"symbol": "SAME", "security_guid": guid, "stance": "BUY", "conviction": 99,
             "conviction_source": "lower_signal", "conflicts": []} for guid in ("guid-a", "guid-b")]
    original = copy.deepcopy(rows)
    def resolver(guid, **kwargs):
        calls.append((guid, kwargs))
        return {"stance": "TRIM" if guid == "guid-a" else "HOLD", "conviction": 42,
                "as_of": NOW.isoformat(), "stale": False, "gap": None, "conflicts": []}
    out = reads.canonical_rows(rows, resolver=resolver, projection=projection)
    assert [r["stance"] for r in out] == ["TRIM", "HOLD"]
    assert all(r["conviction"] == 42 and len(r["conflicts"]) == 2 for r in out)
    assert out[0]["conflicts"][0]["b"]["value"] == "BUY"
    assert all(r["next_action"]["kind"] == "resolve_conflict" for r in out)
    assert [c[0] for c in calls] == ["guid-a", "guid-b"]
    assert all(c[1]["projection"] is projection for c in calls)
    assert rows == original


def test_hermes_findings_counts_and_audit_are_not_page_lengths():
    calls = []
    def query(sql, params=None, fetch="all"):
        calls.append((sql, params))
        if fetch == "one":
            return {"n": 900} if "hermes_promotion_audit" in sql else {"total": 1200, "promoted": 900, "staged": 100, "embedded": 800}
        if "FROM hermes_research_intelligence" in sql:
            assert "EXISTS" in sql and "LEFT JOIN" not in sql
            return [{"id": 20, "symbol": "TEST", "created_at": NOW.isoformat()}]
        return [{"source_id": 7, "target_table": "facts", "promoted_at": NOW.isoformat()}]
    out = reads.read_hermes_findings({"status": "staged", "offset": 17, "limit": 25}, db_query=query)
    assert out["total"] == 1200 and out["pagination"]["total"] == 1200
    assert out["promoted"] == 900 and out["audit_pagination"]["total"] == 900
    assert any(params == ("staged", 25, 17) for _, params in calls)
    assert reads.encoded_size(out) < 500_000


def test_hermes_backlog_status_count_and_sql_window():
    calls = []
    def query(sql, params=None, fetch="all"):
        calls.append((sql, params))
        if fetch == "one":
            return {"n": 3000}
        return [{"id": 7, "symbol": "TEST", "created_at": NOW.isoformat(), "evidence_json": []}]
    out = reads.read_hermes_backlog({"status": "archived", "offset": 100, "limit": 50}, db_query=query, evidence_packet=lambda _: {})
    assert out["total"] == 3000 and out["pagination"]["total"] == 3000
    assert "status = %s" in calls[0][0] and calls[0][1] == ("archived",)
    assert calls[1][1] == ("archived", 50, 100)


def test_retention_aggregates_every_retained_row_and_unknown_stays_unknown(monkeypatch):
    from lib.comms import classify
    monkeypatch.setattr(classify, "categories", lambda: [{"id": "fixture", "ttl_hours": 48}])
    out = reads.read_comms_retention(db_query=lambda sql: [
        {"retention_class": "operational", "knowledge_status": "accepted", "n": 800},
        {"retention_class": "operational", "knowledge_status": "none", "n": 500},
        {"retention_class": "research", "knowledge_status": "accepted", "n": 700}])
    assert out["total"] == 2000 and out["byClass"] == {"operational": 1300, "research": 700}
    assert out["byKnowledge"] == {"accepted": 1500, "none": 500}
    missing = reads.read_comms_retention(db_query=lambda _: None)
    assert missing["total"] is None and missing["status"] == "unavailable"


def test_route_factory_is_lazy_and_refresh_cannot_call_old_engine(monkeypatch, tmp_path):
    calls = []
    def forbidden(*args, **kwargs):
        raise AssertionError("Owner reader invoked during registration")
    handlers = reads.bounded_routes(root=lambda: tmp_path, db_query=forbidden, clean=lambda x: x,
                                    scanner=forbidden, evidence_packet=forbidden)
    assert len(handlers) == 11
    monkeypatch.setattr(reads, "read_stored_stops", lambda q, **kw: calls.append(q) or {"attempted": False})
    assert handlers["/api/v2/holdings/live-stops"]({"refresh": "1"}) == {"attempted": False}
    assert calls == [{"refresh": "1"}]
    with pytest.raises(RuntimeError, match="Stored proposal list unavailable"):
        handlers["/api/v2/broker-proposals"]({"refresh": "1"})
    assert handlers["/api/v2/broker-proposals/summary"]({"refresh": "1"})["total"] is None


def test_candidate_generation_reused_across_clients_and_pages(monkeypatch, tmp_path):
    from lib import scanner_candidate_projection
    (tmp_path / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    calls = []
    def load(*args, **kwargs):
        calls.append(args)
        return {"candidate_count": 120, "candidates": [candidate(i, history=1) for i in range(120)]}
    monkeypatch.setattr(scanner_candidate_projection, "read_candidate_snapshot", load)
    first = reads.read_candidates(tmp_path, {"filter": "ALL", "limit": 10}, now=NOW)
    second = reads.read_candidates(tmp_path, {"filter": "ALL", "offset": 10, "limit": 10}, now=NOW)
    assert len(calls) == 1
    assert first["candidates"][0]["candidate_id"] == "0"
    assert second["candidates"][0]["candidate_id"] == "10"


def test_large_observation_history_is_paged_without_losing_rows():
    row = candidate(7, history=250)
    for index, observation in enumerate(row["trade_ai"]["observations"]):
        observation["run_id"] = f"run-{index}"
    payload = {"candidate_count": 1, "candidates": [row]}
    seen, offset = [], 0
    while True:
        page = reads.candidates_page(payload, {"candidate_id": "7", "history_source": "TRADE_AI", "offset": offset, "limit": 100})
        assert reads.encoded_size({"ok": True, "data": page}) < 200_000
        assert page["pagination"]["total"] == 250
        assert page["candidates"][0]["active_trader"]["observations"] == []
        seen.extend(o["run_id"] for o in page["candidates"][0]["trade_ai"]["observations"])
        if not page["pagination"]["has_more"]:
            break
        offset = page["pagination"]["next_offset"]
        assert offset is not None
    assert seen == [f"run-{i}" for i in range(250)]


def test_summary_counts_cover_all_candidates_and_unknown_is_not_zero():
    page = reads.candidates_page({"candidate_count": 20, "candidates": [candidate(i, history=1) for i in range(20)]}, {"view": "summary"})
    assert page["candidates"] == [] and page["candidate_count"] == 20
    assert page["filter_counts"]["CONFLICT"] == 7
    unknown = reads.candidates_page({"candidate_count": None, "candidates": []}, {"view": "summary"})
    assert unknown["filter_counts"] == dict.fromkeys(["ALL", "ACTIONABLE", "CONFLICT", "CURRENT"])


def test_broker_summary_is_stored_and_malformed_cache_is_explicit(tmp_path):
    path = tmp_path / "data/runtime/broker_list_cache.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"v2|default": {"ts": NOW.timestamp()-1000, "data": {"queue_summary": {"total": 321}}}}))
    before = path.read_bytes()
    summary = reads.read_broker_summary(tmp_path, now=NOW)
    assert summary["total"] == 321 and summary["stale"] is True and summary["provider_calls"] == 0
    assert path.read_bytes() == before
    path.write_text('["not a cache mapping"]')
    assert reads.read_broker_summary(tmp_path, now=NOW)["total"] is None
    assert reads.read_broker_list(tmp_path, now=NOW)["cache_status"] == "unavailable"
