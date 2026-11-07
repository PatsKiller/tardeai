"""ANCHOR: HERMES_CANONICAL_STATUS_TABLES_20261107 — a table count names its tables or says unknown.

LQ-20261107-53. ``/api/v2/hermes/workflow-matrix`` reads three audit JSONs from
``PROJECT_ROOT/data/hermes``. ``data/*`` is gitignored, so a release rsync carries none of them: on the
release running on 2026-11-07 that directory held only ``legacy_agent_inventory_latest.json``. The
route's ``load()`` turned the absence into ``{}``, the endpoint answered

    "db_lineage": [],  "workflow_count": null,  "graph_nodes": [],  "safe_views_count": 0

and ``build_hermes_canonical_status.py`` wrote ``db_tables_count: 0`` into
``data/runtime/hermes_canonical_status_latest.json`` — the file the portal, the matrix Markdown and the
Word doc are regenerated from. A reader could not tell "no tables" from "could not read the file".

The files are runtime state: they live in ``persistent-state/data/hermes`` (6 tables, 19 workflows, 9
graph nodes, 13 safe views, written 2026-06-07). Pinned here:

  1. the route resolves them through the state root, keeps the release as a fallback, and reports,
     per file, whether it was present, where it came from, its mtime and any parse error;
  2. a file that is absent or unreadable yields ``None`` for the values it would have answered — an
     answered empty list is a real 0, a missing file is unknown;
  3. the snapshot **names its tables** and carries the definitions and the source's age;
  4. a lineage written 2026-06-07 cannot answer "writes in the last 24 h": the tables are still named
     and the write counts are reported as unknown, not as a five-month-old number with a 24-hour label.

Hermetic: temporary directories, injected payloads; no host, no database, no network.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402
import build_hermes_canonical_status as b  # noqa: E402

NOW = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)

LINEAGE = {
    "generated_note": "read-only Phase 209 DB lineage",
    "tables": [
        {"table": "hermes_research_intelligence", "exists": True, "rows": 1976, "writes_24h": 436,
         "last_write": "2026-06-07 12:30:45-04:00"},
        {"table": "hermes_memory_events", "exists": True, "rows": 812, "writes_24h": 2,
         "last_write": "2026-06-07 11:02:10-04:00"},
    ],
    "safe_views": ["v1", "v2"],
}
OWNERS = {"workflow_count": 19, "any_cli_profile_in_jobs": True, "rows": [{"name": "w"}]}
NODES = {"nodes": [{"id": "n1", "name": "node one", "owner_hint": "hermes"}]}


def _route(monkeypatch, tmp_path, *, state=None, release=None):
    """Point the route at a temporary state root and release root."""
    state_dir = tmp_path / "state" / "data" / "hermes"
    release_dir = tmp_path / "release"
    if state is not None:
        state_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in state.items():
            # nosemgrep: tq-py-nonatomic-store-write -- pytest tmp_path fixture, not a store
            (state_dir / name).write_text(payload if isinstance(payload, str) else json.dumps(payload))
    if release is not None:
        rel_dir = release_dir / "data" / "hermes"
        rel_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in release.items():
            # nosemgrep: tq-py-nonatomic-store-write -- pytest tmp_path fixture, not a store
            (rel_dir / name).write_text(payload if isinstance(payload, str) else json.dumps(payload))

    import lib.n8n_pilot_observations as obs
    monkeypatch.setattr(obs, "state_root", lambda *a, **k: str(tmp_path / "state"))
    monkeypatch.setattr(api_v2, "PROJECT_ROOT", release_dir)
    return api_v2._hermes_workflow_matrix()


# ── 1. the route: state root first, and a missing file is not an empty matrix ───────────────────────

def test_the_route_reads_the_state_root(monkeypatch, tmp_path):
    wfm = _route(monkeypatch, tmp_path, state={
        "hermes_db_lineage_latest.json": LINEAGE,
        "hermes_workflow_owner_matrix_latest.json": OWNERS,
        "hermes_graph_node_inventory_latest.json": NODES,
    })
    assert [t["table"] for t in wfm["db_lineage"]] == ["hermes_research_intelligence", "hermes_memory_events"]
    assert wfm["workflow_count"] == 19 and len(wfm["graph_nodes"]) == 1 and wfm["safe_views_count"] == 2
    src = wfm["audit_sources"]["files"]["db_lineage"]
    assert src["present"] is True and src["path"].startswith(str(tmp_path / "state" / "data" / "hermes"))
    assert src["modified_at"] and src["error"] is None


def test_a_missing_lineage_file_is_null_not_zero_tables(monkeypatch, tmp_path):
    """The release that served "0 DB tables" had no lineage file at all — that is unknown."""
    wfm = _route(monkeypatch, tmp_path)
    assert wfm["db_lineage"] is None
    assert wfm["workflow_count"] is None and wfm["graph_nodes"] is None and wfm["safe_views_count"] is None
    assert wfm["audit_sources"]["files"]["db_lineage"]["present"] is False


def test_an_answered_empty_lineage_is_a_real_zero(monkeypatch, tmp_path):
    wfm = _route(monkeypatch, tmp_path, state={
        "hermes_db_lineage_latest.json": {"tables": [], "safe_views": []}})
    assert wfm["db_lineage"] == [] and wfm["safe_views_count"] == 0


def test_a_corrupt_file_is_reported_not_read_as_empty(monkeypatch, tmp_path):
    wfm = _route(monkeypatch, tmp_path, state={"hermes_db_lineage_latest.json": "{not json"})
    assert wfm["db_lineage"] is None
    assert wfm["audit_sources"]["files"]["db_lineage"]["error"] == "JSONDecodeError"


def test_the_release_is_still_a_fallback(monkeypatch, tmp_path):
    """A bare checkout has no state root; the release copy must still be read."""
    wfm = _route(monkeypatch, tmp_path, release={"hermes_db_lineage_latest.json": LINEAGE})
    assert len(wfm["db_lineage"]) == 2
    assert "release" in wfm["audit_sources"]["files"]["db_lineage"]["path"]


# ── 2. the snapshot names its tables, or says the count is unknown ──────────────────────────────────

def _matrix(state_present=True, *, days_old=0, tables=None, graph=("n1",)):
    lin = {"present": state_present, "path": "/state/data/hermes/hermes_db_lineage_latest.json",
           "modified_at": (NOW - timedelta(days=days_old)).isoformat() if state_present else None,
           "error": None}
    nodes = {"present": bool(graph), "path": "/state/data/hermes/hermes_graph_node_inventory_latest.json",
             "modified_at": (NOW - timedelta(days=days_old)).isoformat() if graph else None, "error": None}
    wf = {"audit_sources": {"files": {"db_lineage": lin, "graph_nodes": nodes}},
          "db_lineage": tables if tables is not None else (LINEAGE["tables"] if state_present else None),
          "workflow_count": 19 if state_present else None,
          "graph_nodes": ([{"id": n} for n in graph] if graph else []) if state_present else None,
          "safe_views_count": 2 if state_present else None}
    return b.derive_matrix(wf)


def test_the_snapshot_names_every_table():
    fields, prov = _matrix()
    assert fields["db_tables_count"] == 2
    assert [t["table"] for t in fields["db_tables"]] == ["hermes_research_intelligence", "hermes_memory_events"]
    assert prov["db_tables_count"]["definition"].startswith("entries in the `tables` list")


def test_a_missing_lineage_is_an_unknown_count_not_zero():
    fields, prov = _matrix(state_present=False)
    assert fields["db_tables"] is None and fields["db_tables_count"] is None
    assert fields["graph_nodes"] is None and fields["graph_nodes_count"] is None
    assert prov["db_tables_count"]["error"] == "lineage source not found"


def test_an_answered_empty_table_list_is_zero():
    fields, _prov = _matrix(tables=[])
    assert fields["db_tables"] == [] and fields["db_tables_count"] == 0


def test_a_stale_lineage_names_the_tables_but_reports_no_24h_numbers():
    """The host's lineage was written 2026-06-07; 436 writes is that day's number, not today's."""
    fields, prov = _matrix(days_old=153)
    assert fields["db_tables_count"] == 2
    assert [t["table"] for t in fields["db_tables"]] == ["hermes_research_intelligence", "hermes_memory_events"]
    assert all(t["writes_24h"] is None for t in fields["db_tables"])
    assert fields["db_writes_24h"] == {"research_intelligence": None, "memory_events": None}
    assert prov["db_writes_24h"]["fresh"] is False
    assert prov["db_tables_count"]["stale"] is True


def test_a_fresh_lineage_carries_the_write_counts():
    fields, prov = _matrix(days_old=0.5)
    assert fields["db_writes_24h"] == {"research_intelligence": 436, "memory_events": 2}
    assert prov["db_writes_24h"]["fresh"] is True and prov["db_tables_count"]["stale"] is False


def test_graph_nodes_unknown_is_not_the_same_as_none_owned():
    fields, _ = _matrix(graph=())
    assert fields["graph_nodes_count"] == 0 and fields["graph_nodes"] == []


def test_the_snapshot_end_to_end_carries_the_named_tables(monkeypatch):
    wf = {"audit_sources": {"files": {"db_lineage": {
              "present": True, "path": "/state/data/hermes/hermes_db_lineage_latest.json",
              "modified_at": NOW.isoformat(), "error": None}}},
          "db_lineage": LINEAGE["tables"], "workflow_count": 19, "graph_nodes": [], "safe_views_count": 2}
    monkeypatch.setattr(b, "api", lambda ep: wf if ep == "workflow-matrix" else {})
    monkeypatch.setattr(b, "sysd", lambda cmd: "")
    monkeypatch.setattr(b, "measure_host_counts", lambda: {
        "crons_count": 327, "timers_count": 83, "timers_system_count": 20,
        "counts_provenance": {}})

    snap, _ = b.build_snapshot()

    assert snap["db_tables_count"] == 2 and len(snap["db_tables"]) == 2
    assert snap["db_tables"][0]["table"] == "hermes_research_intelligence"
    assert snap["db_writes_24h"]["research_intelligence"] == 436
    assert snap["counts_provenance"]["db_tables_count"]["source"].endswith("hermes_db_lineage_latest.json")
    assert snap["crons_count"] == 327 and snap["timers_count"] == 83


def test_age_days_never_invents_an_age():
    assert b._age_days(None) is None
    assert b._age_days("") is None
    assert b._age_days("not a date") is None
    assert b._age_days(NOW.isoformat(), now=NOW) == 0
    assert b._age_days((NOW - timedelta(days=3)).isoformat(), now=NOW) == 3.0
