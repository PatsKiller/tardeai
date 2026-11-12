"""LQ-20261107-2196: a shared cold store load must not be charged to one source's timeout.

Production (2026-11-11): every hourly cio-ask-lifecycle run is a fresh process, so the first tracked thread paid the
cold parse of the CIO record store (12.4 s measured) inside internal.cio_record_research's 15 s budget, and the parse
starved internal.thesis (1.2 s alone, 12.95 s concurrently). Both timed out, the thread deferred six times, then
failed with SOURCE_TIMEOUT_LIMIT and the lane exited 1 (06, 10, 16, 23 ET). Synthetic fixtures only.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from scripts.lib import cio_ask_research as car

NOW = datetime(2026, 11, 12, 4, 0, tzinfo=timezone.utc)


def _entity():
    return car.Entity(label="Example Co", kind="listed", symbol="EXMP", security_guid="guid-exmp",
                      identity_status="RESOLVED")


COLD_S = 0.6     # the shared store's cold load
BUDGET_S = 0.3   # the source's own budget: shorter than the cold load, longer than a warm read


def _slow_shared_load(ctx):
    with ctx.shared_lock:
        if "store" not in ctx.shared:
            time.sleep(COLD_S)
            ctx.shared["store"] = {"loaded": True}
        return ctx.shared["store"]


def _fact_from_store(ent, ctx):
    _slow_shared_load(ctx)
    return [car.make_fact(source="internal.fixture", family="internal", kind="company_evidence",
                          subject_key=ent.subject_key, symbol=ent.symbol, claim="fixture fact", as_of=NOW.isoformat(),
                          citation={"store": "fixture"})]


def _ctx():
    return car.ResearchContext(question="what changed?", now=NOW)


def test_a_source_whose_shared_store_is_cold_answers_when_the_store_is_prepared_outside_its_budget():
    spec = car.SourceSpec("internal.fixture", "internal", _fact_from_store, BUDGET_S, prepare=_slow_shared_load)
    out = car.gather_facts([_entity()], [spec], _ctx())
    assert [r["status"] for r in out["runs"]] == ["ok"], out["runs"]
    assert not [g for g in out["gaps"] if g["reason"] == "TIMEOUT"]
    prep = out["prepared"]
    assert [p["source"] for p in prep] == ["internal.fixture"] and prep[0]["status"] == "ok"
    assert prep[0]["elapsed_s"] >= COLD_S * 0.9  # the cold load is measured and published, not hidden


def test_without_prepare_the_same_cold_load_is_a_timeout_so_the_fixture_reproduces_production():
    spec = car.SourceSpec("internal.fixture", "internal", _fact_from_store, BUDGET_S)
    out = car.gather_facts([_entity()], [spec], _ctx())
    assert [r["status"] for r in out["runs"]] == ["timeout"]
    assert out.get("prepared", []) == []


def test_a_shared_prepare_runs_once_for_every_entity_and_source_that_names_it():
    calls = []

    def prepare(ctx):
        calls.append(threading.get_ident())
        return _slow_shared_load(ctx)

    a = car.SourceSpec("internal.a", "internal", _fact_from_store, BUDGET_S, prepare=prepare)
    b = car.SourceSpec("internal.b", "internal", _fact_from_store, BUDGET_S, prepare=prepare)
    e2 = _entity()
    out = car.gather_facts([_entity(), e2], [a, b], _ctx())
    assert len(calls) == 1
    assert sorted(r["status"] for r in out["runs"]) == ["ok"] * 4


def test_a_failing_prepare_is_recorded_and_the_source_still_reports_its_own_outcome():
    def broken(ctx):
        raise OSError("store unreadable")

    def fn(ent, ctx):
        raise OSError("store unreadable")

    spec = car.SourceSpec("internal.fixture", "internal", fn, BUDGET_S, prepare=broken)
    out = car.gather_facts([_entity()], [spec], _ctx())
    assert out["prepared"][0]["status"] == "error" and out["prepared"][0]["error"] == "OSError"
    assert [r["status"] for r in out["runs"]] == ["error"]  # never ok, never silently dropped


def test_the_production_sources_that_share_a_cold_store_declare_a_prepare_step():
    specs = {s.name: s for s in car.default_sources()}
    assert specs["internal.cio_record_research"].prepare is not None
    assert specs["internal.thesis"].prepare is not None
    # timeouts unchanged: the fix moves the cold load out of the budget, it does not widen the budget
    assert specs["internal.cio_record_research"].timeout_s == 15.0
    assert specs["internal.thesis"].timeout_s == 15.0


def test_prepare_timing_never_enters_the_evidence_fingerprint():
    spec = car.SourceSpec("internal.fixture", "internal", _fact_from_store, BUDGET_S, prepare=_slow_shared_load)
    one = car.gather_facts([_entity()], [spec], _ctx())
    two = car.gather_facts([_entity()], [spec], _ctx())
    assert car.evidence_fingerprint(one["facts"], one["runs"]) == car.evidence_fingerprint(two["facts"], two["runs"])
