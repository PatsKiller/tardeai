"""Bounded home plan projection matches the writer store without constructing it.

Only isolated synthetic projections/ledgers are used. Forked memory comparisons
run on files generated here; no server, database, providers or credentials.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import sys
import time
import tracemalloc
import types
from pathlib import Path

import pytest

from scripts.lib import cio_home_plan_view as view
from scripts.lib.cio_plans import CIOPlanStore


def _plan(pid, created="2026-10-23T12:00:00+00:00", status="draft", **kw):
    return {
        "plan_id": pid,
        "created_ts": created,
        "status": status,
        "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
        "symbols": [pid.upper()],
        "version": 2,
        "summary": "fixture summary",
        "extra": {"material": True, "hermes_result_id": "r1"},
        **kw,
    }


def _world(root, plans, *, events=(), offset=0):
    directory = root / "data/cio"
    directory.mkdir(parents=True, exist_ok=True)
    ledger = directory / "cio_plans.jsonl"
    ledger.write_text("".join(json.dumps(event) + "\n" for event in events))
    projection = directory / "cio_plans_projection.json"
    projection.write_text(json.dumps({"plans": plans, "event_offset": offset, "updated_ts": "2026-10-23T12:00:00Z"}))
    return projection, ledger


def _store(projection, ledger):
    return CIOPlanStore(event_path=ledger, projection_path=projection)


def _api():
    import scripts.api_v3_cio as api

    return api


def test_public_and_coverage_match_the_full_store_with_event_catchup(tmp_path, monkeypatch):
    events = [
        {"event_type": "PLAN_UPDATED", "plan_id": "missing", "payload": {"summary": "ignored"}},
        {
            "event_type": "PLAN_STATUS_CHANGED",
            "plan_id": "a",
            "payload": {"status": "done"},
            "occurred_at": "2026-10-23T13:00:00Z",
        },
        {
            "event_type": "PLAN_UPDATED",
            "plan_id": "b",
            "payload": {"summary": "changed", "created_ts": "ignored"},
            "occurred_at": "2026-10-23T13:01:00Z",
        },
        {"event_type": "PLAN_CREATED", "plan_id": "c", "payload": _plan("c")},
        {"event_type": "PLAN_CREATED", "plan_id": "missing", "payload": _plan("missing")},
        {"event_type": "PLAN_SUPERSEDED", "plan_id": "old", "payload": {}, "occurred_at": "2026-10-23T13:02:00Z"},
    ]
    projection, ledger = _world(tmp_path, {pid: _plan(pid) for pid in ["a", "b", "old"]}, events=events)
    reference = _store(projection, ledger)
    monkeypatch.setattr(_api(), "_now_iso", lambda: "2026-10-23T20:30:00Z")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in [projection, ledger]}
    monkeypatch.setattr(CIOPlanStore, "__init__", lambda *a, **k: pytest.fail("writable store constructor reached"))
    bounded = view.HomePlanView(tmp_path)
    assert bounded.read_state["ok"], bounded.read_state
    assert _api().get_cio_plans(limit=12, store=bounded) == _api().get_cio_plans(limit=12, store=reference)
    assert _api()._coverage_plan_index(store=bounded) == _api()._coverage_plan_index(store=reference)
    assert bounded.read_state["open_plan_count"] == len(reference.list_open_plans(limit=5000))
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    assert not list((tmp_path / "data/cio").glob("*.lock"))


@pytest.mark.parametrize("chunk", [1, 7, 31, 65536])
def test_chunk_boundaries_unicode_escaped_text_and_metadata_order(tmp_path, monkeypatch, chunk):
    projection, ledger = _world(tmp_path, {"a": _plan("a", summary='é✓ escaped "quote" and \\ slash')})
    monkeypatch.setattr(view, "CHUNK", chunk)
    bounded = view.HomePlanView(tmp_path)
    assert bounded.read_state["ok"], bounded.read_state
    assert bounded.list_open_plans(limit=12) == _store(projection, ledger).list_open_plans(limit=12)


def test_trailing_partial_events_and_bad_json_match_existing_store(tmp_path):
    event = {
        "event_type": "PLAN_UPDATED",
        "plan_id": "a",
        "payload": {"summary": "new"},
        "occurred_at": "2026-10-23T14:00:00Z",
    }
    projection, ledger = _world(tmp_path, {"a": _plan("a")}, events=[event])
    with ledger.open("a") as fh:
        fh.write('broken JSON\n{"event_type":"unfinished')
    bounded = view.HomePlanView(tmp_path)
    assert bounded.read_state["ok"]
    assert bounded.list_open_plans(limit=12) == _store(projection, ledger).list_open_plans(limit=12)


@pytest.mark.parametrize("offset", [None, -1, 99999999])
def test_legacy_or_out_of_range_offset_preserves_projection_read_semantics(tmp_path, offset):
    projection, ledger = _world(
        tmp_path,
        {"a": _plan("a")},
        offset=offset,
        events=[{"event_type": "PLAN_CREATED", "plan_id": "new", "payload": _plan("new")}],
    )
    bounded = view.HomePlanView(tmp_path)
    assert bounded.read_state["ok"]
    assert bounded.list_open_plans(limit=12) == _store(projection, ledger).list_open_plans(limit=12)


def test_windows_keep_exact_newest_rows_and_expose_coverage_truncation(tmp_path):
    projection, ledger = _world(tmp_path, {str(i): _plan(str(i), created=f"2026-10-{i + 1:02d}") for i in range(9)})
    bounded = view.HomePlanView(tmp_path, public_limit=2, coverage_limit=3)
    expected = _store(projection, ledger).list_open_plans(limit=9)
    assert bounded.list_open_plans(limit=2) == expected[:2]
    assert [r["plan_id"] for r in bounded.list_open_plans(limit=5000)] == [r["plan_id"] for r in expected[:3]]
    assert bounded.read_state["coverage_truncated"] is True
    assert bounded.read_state["open_plan_count"] == 9


@pytest.mark.parametrize("replace", ["projection", "ledger"])
def test_source_replacement_during_read_is_unavailable_not_a_mixed_snapshot(tmp_path, monkeypatch, replace):
    projection, ledger = _world(tmp_path, {"a": _plan("a")})
    original = view._projection_rows
    calls = 0

    def replacing_rows(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            target = projection if replace == "projection" else ledger
            replacement = target.with_suffix(".fixture")
            replacement.write_bytes(target.read_bytes())
            replacement.replace(target)
        yield from original(path)

    monkeypatch.setattr(view, "_projection_rows", replacing_rows)
    bounded = view.HomePlanView(tmp_path)
    assert not bounded.read_state["ok"]
    assert "during bounded read" in bounded.read_state["reason"]
    assert bounded.list_open_plans(limit=12) == []


@pytest.mark.parametrize(
    "damage", ["missing", "truncated", "duplicate", "large_value", "many_plans", "tail_limit", "retained_limit"]
)
def test_unavailable_inputs_never_return_partial_success_or_rebuild(tmp_path, monkeypatch, damage):
    root = tmp_path / "fixture"
    if damage != "missing":
        projection, ledger = _world(root, {"a": _plan("a"), "b": _plan("b")})
        if damage == "truncated":
            projection.write_text('{"plans":{"a":')
        elif damage == "duplicate":
            projection.write_text('{"plans":{"a":{},"a":{}}}')
        elif damage == "large_value":
            monkeypatch.setattr(view, "MAX_VALUE_CHARS", 10)
        elif damage == "many_plans":
            monkeypatch.setattr(view, "MAX_PLANS", 1)
        elif damage == "tail_limit":
            ledger.write_text("x" * 128)
            monkeypatch.setattr(view, "MAX_TAIL_BYTES", 32)
        elif damage == "retained_limit":
            monkeypatch.setattr(view, "MAX_RETAINED_BYTES", 1)
    bounded = view.HomePlanView(root)
    assert bounded.read_state["ok"] is False
    assert bounded.list_open_plans(limit=12) == bounded.list_open_plans(limit=5000) == []
    assert not list(root.rglob("*.lock")) and not list(root.rglob("*.tmp"))
    if damage == "missing":
        assert not root.exists()


def test_home_factory_uses_bounded_view_without_writable_store(tmp_path, monkeypatch):
    api = _api()
    _world(tmp_path, {"a": _plan("a")})
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "_plan_store", lambda: pytest.fail("full store reached"))
    result = api._home_plan_store()
    assert result.read_state["ok"]
    assert api.get_cio_plans(limit=12, store=result)["plans"][0]["plan_id"] == "a"
    assert api._coverage_plan_index(store=result)[0]["hermes_result_id"] == "r1"


def test_actual_home_route_uses_the_view_with_all_other_domains_neutralized(tmp_path, monkeypatch):
    api = _api()
    projection, ledger = _world(tmp_path, {"a": _plan("a")})
    before = {p: p.read_bytes() for p in (projection, ledger)}
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "_plan_store", lambda: pytest.fail("writable plan store reached"))
    monkeypatch.setattr(api, "_cio_actions_data", lambda *args: [])
    monkeypatch.setattr(api, "get_cio_thesis", lambda: {})
    monkeypatch.setattr(api, "_delegation_data", lambda: {})
    monkeypatch.setattr(api, "stamp_decision_identity", lambda *args: None)
    v2 = types.ModuleType("api_v2")
    for name in ("_cio_capital_plan", "_cio_sector_opportunities", "_cio_report_v2"):
        setattr(v2, name, lambda: {})
    v2._load_json = lambda *args: {}
    v2._db_query = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "api_v2", v2)
    fixtures = {
        "scripts.lib.cio_command_center": {
            "build_office_home": lambda **kw: {"plans_seen": kw["plans"], "coverage_seen": kw["coverage_plans"]}
        },
        "scripts.lib.cio_opportunity_queue": {"build_queue_from_executor": lambda *args: {}},
        "scripts.lib.cio_graph_impact": {"build_graph_impact_for_s6": lambda **kw: {}},
        "scripts.lib.cio_investment_product": {"collect_holdings": lambda *args: {}},
        "scripts.lib.cio_operator_product": {"build_operator_product": lambda **kw: {}},
        "scripts.lib.cio_scorecard": {"stamp_home_attention": lambda *args, **kw: None},
    }
    for name, attributes in fixtures.items():
        module = types.ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    result = api.get_cio_home()
    assert result["ok"] and result["plan_read"]["ok"], result
    assert result["plans_seen"][0]["plan_id"] == "a"
    assert result["coverage_seen"][0]["hermes_result_id"] == "r1"
    assert before == {p: p.read_bytes() for p in before}
    assert not list((tmp_path / "data/cio").glob("*.lock"))


def _fork_memory(root, bounded):
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            before = int(
                next(s.split()[1] for s in Path("/proc/self/status").read_text().splitlines() if s.startswith("VmRSS:"))
            )
            start = time.monotonic()
            tracemalloc.start()
            if bounded:
                result = view.HomePlanView(root)
                assert result.read_state["ok"], result.read_state
                rows = result.list_open_plans(limit=12)
            else:
                result = _store(root / "data/cio/cio_plans_projection.json", root / "data/cio/cio_plans.jsonl")
                rows = result.list_open_plans(limit=12)
            receipt = {
                "peak_delta_kib": max(0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before),
                "seconds": time.monotonic() - start,
                "plan_ids": [r["plan_id"] for r in rows],
                "python_peak_bytes": tracemalloc.get_traced_memory()[1],
            }
            os.write(write_fd, json.dumps(receipt).encode())
        except BaseException as exc:
            os.write(write_fd, json.dumps({"error": repr(exc)}).encode())
        finally:
            os.close(write_fd)
            os._exit(0)
    os.close(write_fd)
    with os.fdopen(read_fd) as fh:
        result = json.load(fh)
    _, status = os.waitpid(pid, 0)
    assert status == 0 and "error" not in result, result
    return result


@pytest.mark.skipif(not hasattr(os, "fork"), reason="forked Linux memory proof")
def test_large_synthetic_projection_memory_is_bounded_in_forked_children(tmp_path):
    projection, _ = _world(tmp_path, {})
    with projection.open("w") as fh:
        fh.write('{"event_offset":0,"plans":{')
        for i in range(2000):
            if i:
                fh.write(",")
            fh.write(
                json.dumps(str(i)) + ":" + json.dumps(_plan(str(i), created=f"{i:06d}", unused_history="x" * 32768))
            )
        fh.write("}}")
    assert projection.stat().st_size > 60 << 20
    before, after = _fork_memory(tmp_path, False), _fork_memory(tmp_path, True)
    assert before["plan_ids"] == after["plan_ids"]
    assert after["peak_delta_kib"] < 100 * 1024, after
    assert after["python_peak_bytes"] < 32 << 20, after
    assert before["peak_delta_kib"] > after["peak_delta_kib"] + 40 * 1024, (before, after)
    print(
        json.dumps(
            {"fixture_bytes": projection.stat().st_size, "full_store": before, "bounded_home_view": after},
            sort_keys=True,
        )
    )
