"""CIOSourceClocks@v1 — source clocks are the source's own data time.

Deterministic: every source is frozen on disk (tmp root) or behind a stubbed
DB executor.  No live store, DB, or broker is touched.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_source_clocks as csc  # noqa: E402

T1 = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(minutes=37)

FILE_CLOCKS = {
    "portfolio_cash": "2026-10-02 10:30:00 ET",
    "decision": "2026-10-02T14:10:00+00:00",
    "research": "2026-10-02T14:20:00Z",
    "memory": "2026-10-02T14:30:00+00:00",
    "hermes_research": "2026-10-02T14:40:00+00:00",
    "outcome_belief": "2026-10-02T14:50:00+00:00",
}
DB_CLOCKS = {
    "analyst_data": datetime(2026, 10, 2).date(),
    "technicals": datetime(2026, 10, 2, 9, 45, tzinfo=timezone.utc),
}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _freeze_sources(root: Path, *, with_clocks: bool = True) -> None:
    c = FILE_CLOCKS if with_clocks else {k: None for k in FILE_CLOCKS}
    holdings = {
        # Rewritten by every reprice — must never stand in for the position clock.
        "generated_at": "2026-10-02 11:45:01 ET",
        "last_repriced": "2026-10-02 11:45:01 ET",
        "updated_at": "2026-10-02T15:45:48+00:00",
        "holdings": [],
    }
    if c["portfolio_cash"]:
        holdings["positions_built_at"] = c["portfolio_cash"]
    p = root / "data/portfolios/state/holdings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(holdings), encoding="utf-8")
    brief = {"schema": "CIOInvestmentProduct@v1", "summary": "x"}
    if c["decision"]:
        brief["as_of"] = c["decision"]
    (root / "data/cio").mkdir(parents=True, exist_ok=True)
    (root / "data/cio/cio_investment_brief.json").write_text(json.dumps(brief), encoding="utf-8")
    _write_jsonl(root / "data/cio/security_research_spine.jsonl", [
        {"schema": "SecurityResearchSpine@v1", **({"as_of": "2026-10-01T10:00:00Z"} if with_clocks else {})},
        {"schema": "SecurityResearchSpine@v1", **({"as_of": c["research"]} if with_clocks else {})},
    ])
    _write_jsonl(root / "data/cio/memory_contexts.jsonl", [
        {"event": "COMMITTED", **({"committed_at": c["memory"]} if with_clocks else {})},
    ])
    _write_jsonl(root / "data/cio/hermes_research_results.jsonl", [
        {"event": "HERMES_RESEARCH_COMPLETED", **({"completed_ts": c["hermes_research"]} if with_clocks else {})},
    ])
    _write_jsonl(root / "data/cio/outcome_observations.jsonl", [
        {"schema": "OutcomeObservation@v1", **({"source_as_of": c["outcome_belief"]} if with_clocks else {})},
    ])


def _db(values: dict[str, object]):
    calls: list[str] = []

    def execute(sql: str):
        calls.append(sql)
        for source, value in values.items():
            spec = csc.SPECS_BY_SOURCE[source]
            table, column = spec.ref.split(".", 1)
            if f"FROM {table}" in sql and f"max({column})" in sql:
                return {"m": value}
        raise AssertionError(f"unexpected sql {sql}")

    execute.calls = calls  # type: ignore[attr-defined]
    return execute


def _by_source(payload: dict) -> dict[str, dict]:
    return {row["source"]: row for row in payload["sources"]}


def test_eight_sources_declared():
    assert [s.source for s in csc.SOURCE_SPECS] == [
        "portfolio_cash", "decision", "research", "memory",
        "analyst_data", "technicals", "hermes_research", "outcome_belief",
    ]
    for spec in csc.SOURCE_SPECS:
        assert spec.stale_after_seconds > 0


@pytest.mark.parametrize("source", [s.source for s in csc.SOURCE_SPECS])
def test_composition_advances_source_clock_does_not(tmp_path, source):
    _freeze_sources(tmp_path)
    db = _db(DB_CLOCKS)
    first = csc.compose_cio_source_clocks(root=tmp_path, now=T1, db_execute=db)
    second = csc.compose_cio_source_clocks(root=tmp_path, now=T2, db_execute=db)
    a, b = _by_source(first)[source], _by_source(second)[source]
    assert first["composition_as_of"] == T1.isoformat()
    assert second["composition_as_of"] == T2.isoformat()
    assert a["composition_as_of"] != b["composition_as_of"]
    assert a["source_as_of"] is not None
    assert a["source_as_of"] == b["source_as_of"]
    assert a["source_version"] == b["source_version"]
    assert b["age_seconds"] - a["age_seconds"] == int((T2 - T1).total_seconds())
    assert a["source_as_of"] != a["composition_as_of"]
    for key in ("source", "producer", "source_ref", "source_version", "source_as_of",
                "composition_as_of", "age_seconds", "stale_after_seconds", "freshness", "evidence_class"):
        assert key in a


@pytest.mark.parametrize("source", [s.source for s in csc.SOURCE_SPECS])
def test_missing_timestamp_is_null_and_unknown(tmp_path, source):
    _freeze_sources(tmp_path, with_clocks=False)
    db = _db({k: None for k in DB_CLOCKS})
    row = _by_source(csc.compose_cio_source_clocks(root=tmp_path, now=T1, db_execute=db))[source]
    assert row["source_as_of"] is None
    assert row["freshness"] == "UNKNOWN"
    assert row["age_seconds"] is None
    assert row["reason"] == "no_trustworthy_source_timestamp"


def test_reprice_clock_never_stands_in_for_portfolio_cash(tmp_path):
    _freeze_sources(tmp_path, with_clocks=False)
    row = _by_source(csc.compose_cio_source_clocks(root=tmp_path, now=T1, db_execute=_db(DB_CLOCKS)))["portfolio_cash"]
    # generated_at / last_repriced / updated_at exist and are recent, still UNKNOWN.
    assert row["source_as_of"] is None and row["freshness"] == "UNKNOWN"


def test_et_position_clock_parsed_in_new_york_time(tmp_path):
    _freeze_sources(tmp_path)
    row = _by_source(csc.compose_cio_source_clocks(root=tmp_path, now=T1, db_execute=_db(DB_CLOCKS)))["portfolio_cash"]
    # 10:30 EDT == 14:30 UTC → 30 minutes before T1.
    assert row["age_seconds"] == 30 * 60
    assert row["clock_field"] == "positions_built_at"


def test_stale_beyond_explicit_budget(tmp_path):
    _freeze_sources(tmp_path)
    db = _db(DB_CLOCKS)
    late = T1 + timedelta(days=30)
    rows = _by_source(csc.compose_cio_source_clocks(root=tmp_path, now=late, db_execute=db))
    fresh = _by_source(csc.compose_cio_source_clocks(root=tmp_path, now=T1, db_execute=db))
    for source, row in rows.items():
        assert row["freshness"] == "STALE", source
        assert row["age_seconds"] > row["stale_after_seconds"]
        assert fresh[source]["freshness"] == "FRESH", source


def test_missing_store_and_db_failure_are_unavailable(tmp_path):
    def broken(sql: str):
        raise RuntimeError("db down")

    rows = _by_source(csc.compose_cio_source_clocks(root=tmp_path, now=T1, db_execute=broken))
    for source, row in rows.items():
        assert row["freshness"] == "UNAVAILABLE", source
        assert row["source_as_of"] is None
        assert row["evidence_class"] == "UNAVAILABLE"


def test_future_clock_is_not_trusted(tmp_path):
    _freeze_sources(tmp_path)
    _write_jsonl(tmp_path / "data/cio/memory_contexts.jsonl", [
        {"committed_at": "2026-10-02T14:30:00+00:00"},
        {"committed_at": "2027-01-01T00:00:00+00:00"},
    ])
    row = _by_source(csc.compose_cio_source_clocks(root=tmp_path, now=T1, db_execute=_db(DB_CLOCKS)))["memory"]
    assert row["source_as_of"] == "2026-10-02T14:30:00+00:00"


def test_jsonl_probe_is_bounded(tmp_path, monkeypatch):
    _freeze_sources(tmp_path)
    big = tmp_path / "data/cio/security_research_spine.jsonl"
    with big.open("a", encoding="utf-8") as fh:
        for _ in range(5000):
            fh.write(json.dumps({"as_of": "2026-09-01T00:00:00Z", "pad": "x" * 200}) + "\n")
        fh.write(json.dumps({"as_of": "2026-10-02T14:55:00Z"}) + "\n")
    monkeypatch.setattr(csc, "TAIL_BYTES", 16 * 1024)
    row = _by_source(csc.compose_cio_source_clocks(root=tmp_path, now=T1, db_execute=_db(DB_CLOCKS)))["research"]
    assert row["source_as_of"] == "2026-10-02T14:55:00Z"
    assert row["rows_scanned"] < 100


def test_next_cron_fire_weekday_and_hours():
    now = datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)  # Fri 17:00 EDT
    nxt = csc.next_cron_fire("45 5 * * 1-5 indicator_cache_refresh.py", now)
    assert nxt == datetime(2026, 10, 5, 9, 45, tzinfo=timezone.utc)  # Mon 05:45 EDT
    nxt = csc.next_cron_fire("*/15 9-16 * * 1-5", datetime(2026, 10, 2, 15, 50, tzinfo=timezone.utc))
    assert nxt == datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)
    assert csc.next_cron_fire("not a cron", now) is None


def test_next_scheduled_run_from_lane_registry(tmp_path):
    reg = {"lanes": [
        {"lane_id": "a", "state": "ACTIVE", "scheduler": {"kind": "cron", "expression": "0 10 * * *"}},
        {"lane_id": "b", "state": "PAUSED", "scheduler": {"kind": "cron", "expression": "* * * * *"}},
        {"lane_id": "c", "state": "ACTIVE", "scheduler": {"kind": "systemd", "expression": "x.timer"}},
    ]}
    (tmp_path / "config").mkdir()
    (tmp_path / "config/lane_registry.json").write_text(json.dumps(reg), encoding="utf-8")
    out = csc.next_scheduled_run(["a", "b"], now=T1, root=tmp_path, systemd_lookup=None)
    assert out["lane_id"] == "a" and out["next_run_at"] == "2026-10-03T14:00:00+00:00"
    out = csc.next_scheduled_run(["b"], now=T1, root=tmp_path, systemd_lookup=None)
    assert out["next_run_at"] is None and "PAUSED" in out["reason"]
    out = csc.next_scheduled_run(["c"], now=T1, root=tmp_path, systemd_lookup=lambda unit: "2026-10-02 19:45:00 EDT")
    assert out["next_run_at"] == "2026-10-02T23:45:00+00:00"
    out = csc.next_scheduled_run([], now=T1, root=tmp_path)
    assert out["next_run_at"] is None and out["reason"]


def test_route_wraps_composer(monkeypatch):
    import scripts.api_v3_cio as cio

    monkeypatch.setattr(csc, "compose_cio_source_clocks", lambda **kw: {"ok": True, "schema": csc.SCHEMA, "root": str(kw.get("root"))})
    out = cio.get_cio_source_clocks_v1()
    assert out["ok"] is True and out["schema"] == "CIOSourceClocks@v1"

    def boom(**kw):
        raise RuntimeError("x")

    monkeypatch.setattr(csc, "compose_cio_source_clocks", boom)
    out = cio.get_cio_source_clocks_v1()
    assert out["ok"] is False and out["schema"] == "CIOSourceClocks@v1" and out["financial_action"] is False
