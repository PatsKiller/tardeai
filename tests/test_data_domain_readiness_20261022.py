"""Data-domain approval readiness (scripts/lib/data_domain_readiness.py) — hermetic: a fixture registry, fixture
source files and a fixture broker catalog under tmp_path. No database, no network, nothing written outside tmp.

Operator 2026-10-22 on Ops → Controls → Data approvals: "This is not a dashboard." These tests pin what the verdict
means: READY_TO_APPROVE only when the row, promoted in memory with today's ceilings, passes the real gates."""

from __future__ import annotations

import json
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import check_data_source_authority as C  # noqa: E402
from scripts.lib import data_dictionary as DD  # noqa: E402
from scripts.lib import data_domain_readiness as R  # noqa: E402

NOW = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)


def prow(name, *, table=None, file=None, writer=None, unconsolidated=None, projection=None, copies=None, **extra):
    row = {
        "domain": name,
        "status": "proposed",
        "entity": name.title(),
        "title": f"{name} title",
        "class": "native",
        "store": {"table": table} if table else {"file": file},
        "cadence": "event",
        "stale_after_hours": 1,
        "freshness_sla": "1 h",
        "refresh_lane": {"runner": "host", "lane": f"{name}-lane", "note": "fixture"},
        "readers": ["Home"],
        "derived_copies": copies or [],
        "no_coverage": "say_so",
        "proposal": {
            "proposed_by": "agent",
            "proposed_on": "2026-10-22",
            "reference": "fixture",
            "decision": f"Grant {name}.",
        },
        "facts": ["f"],
        "approval": None,
        "projection": projection,
    }
    if writer:
        row["writer"] = writer
    else:
        row["writer"] = None
        row["writer_status"] = "UNCONSOLIDATED"
        row["writer_target"] = unconsolidated or "scripts/target.py"
    row.update(extra)
    return row


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "scripts" / "lib").mkdir(parents=True)
    served = tmp_path / "served"
    (served / "cio").mkdir(parents=True)

    def w(rel, text):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    w("scripts/good_writer.py", "cur.execute('INSERT INTO good_table (a) VALUES (1)')\n")
    w("scripts/good_reader.py", "cur.execute('SELECT a FROM good_table')\n")
    w("scripts/settings_writer.py", "cur.execute('update settings_tbl set v = 1')\n")  # lower-case SQL still counts
    w("scripts/claimed_writer.py", "cur.execute('INSERT INTO claim_tbl VALUES (1)')\n")
    w("scripts/sneaky_writer.py", "cur.execute('Insert Into claim_tbl VALUES (2)')\n")
    w("scripts/multi_a.py", "INSERT INTO multi_tbl VALUES (1)\n")
    w("scripts/multi_b.py", "UPDATE multi_tbl SET x = 1\n")
    w("scripts/pos_writer.py", "INSERT INTO pos_tbl VALUES (1)\n")
    w("scripts/pos_ok_reader.py", "SELECT * FROM pos_tbl\n")
    w("scripts/pos_rogue_reader.py", "SELECT * FROM pos_tbl JOIN x ON true\n")
    w("scripts/lib/thesis_store.py", "THESES = 'cio/theses.jsonl'\nPath(THESES).write_text(x)\n")
    w("scripts/approved_writer.py", "INSERT INTO approved_tbl VALUES (1)\n")
    w("scripts/target.py", "# consolidation target\n")
    (served / "cio" / "theses.jsonl").write_text("{}\n")

    auth = {
        "schema": "DataSourceAuthority@v2",
        "served_from": {"root": str(served)},
        "providers": {},
        "domains": [
            {
                "domain": "pos",
                "store": {"table": "pos_tbl"},
                "writer": "scripts/pos_writer.py",
                "approval": {"approved_by": "operator", "approved_on": "2026-10-06", "reference": "r", "scope": "s"},
                "reader_gate": {"tables": ["pos_tbl"], "measured_unbatched_readers": {}},
                "approved_readers": [
                    {
                        "batch": 1,
                        "reader": "scripts/pos_ok_reader.py",
                        "files": ["scripts/pos_ok_reader.py"],
                        "tables": ["pos_tbl"],
                        "surfaces": ["watch"],
                        "facts": "held flag",
                        "approval": {
                            "approved_by": "operator",
                            "approved_on": "2026-10-22",
                            "reference": "r",
                            "scope": "batch 1",
                        },
                    }
                ],
            },
            {
                "domain": "already",
                "store": {"table": "approved_tbl"},
                "writer": "scripts/approved_writer.py",
                "approval": {"approved_by": "operator", "approved_on": "2026-10-22", "reference": "r", "scope": "s"},
                "title": "Already granted",
                "dictionary": {"schema": DD.SCHEMA, "writer_ceiling": 1, "surface_read_ceilings": {}},
            },
        ],
        "proposed_domains": [
            prow("good", table="good_table", writer="scripts/good_writer.py", projection="good_proj"),
            prow("noproj", table="good_table2", writer="scripts/good_writer.py", projection="missing_proj"),
            prow("settings", table="settings_tbl", unconsolidated="scripts/applier_to_build.py"),
            prow("claim", table="claim_tbl", writer="scripts/claimed_writer.py"),
            prow("multi", table="multi_tbl"),
            prow("pos", table="pos_tbl", writer="scripts/pos_writer.py", extends_approved=True),
            prow("theses", file="cio/theses.jsonl", writer="scripts/lib/thesis_store.py"),
            prow("ghost", table="ghost_tbl", writer="scripts/does_not_exist.py"),
        ],
        "data_dictionary": {
            "schema": DD.SCHEMA,
            "surface_files": [],
            "facts": [
                {
                    "fact": "x",
                    "entity": "e",
                    "domain": "good",
                    "store": "good_table",
                    "field": "value, observed_at",
                    "meaning": "m",
                }
            ],
        },
    }
    (root / "config" / "data_source_authority.json").write_text(json.dumps(auth))
    (root / "config" / "data_domain_approval_notes.json").write_text(
        json.dumps(
            {
                "schema": "DataDomainApprovalNotes@v1",
                "domains": {"good": {"approval_given": True, "decision": "operator approval E"}},
            }
        )
    )
    monkeypatch.setattr(C, "PROJECT_ROOT", root)
    cat = types.ModuleType("lib.data_broker.catalog")
    cat.PROJECTIONS = [{"id": "good_proj"}]
    lib_pkg = types.ModuleType("lib")
    lib_pkg.__path__ = []
    db_pkg = types.ModuleType("lib.data_broker")
    db_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "lib", lib_pkg)
    monkeypatch.setitem(sys.modules, "lib.data_broker", db_pkg)
    monkeypatch.setitem(sys.modules, "lib.data_broker.catalog", cat)
    return root, auth


def _rows(view):
    return {r["domain"]: r for r in view["rows"]}


def _scan(root, probe=None):
    c = R.ReadinessCache(
        root, background=False, table_probe_factory=(lambda: probe) if probe else None, clock=lambda: NOW
    )
    return c.view()


def test_ready_only_when_every_criterion_holds(repo):
    root, _ = repo
    r = _rows(_scan(root))["good"]
    assert r["verdict"] == R.READY and r["missing"] == []
    assert [c["id"] for c in r["criteria"]] == [c["id"] for c in R.CRITERIA]
    assert all(c["ok"] for c in r["criteria"])
    assert r["writer"] == "scripts/good_writer.py" and r["store"] == "table:good_table"
    assert r["live"]["writer_files"]["files"] == ["scripts/good_writer.py"]
    assert "scripts/good_reader.py" in r["live"]["store_readers"]["files"]


def test_missing_projection_is_not_ready(repo):
    root, _ = repo
    r = _rows(_scan(root))["noproj"]
    assert r["verdict"] == R.NOT_READY
    crit = {c["id"]: c for c in r["criteria"]}
    assert not crit["projection_registered"]["ok"]
    assert "missing_proj" in crit["projection_registered"]["gaps"][0]


def test_unconsolidated_row_with_an_unnamed_writer_fails_at_grant(repo):
    """The operator_settings shape: UNCONSOLIDATED, target to build, one real writer the row does not name.
    Promotion records a ceiling of 1 and the writer is not allowed -> DICTIONARY_SECOND_WRITER would fail CI."""
    root, _ = repo
    r = _rows(_scan(root))["settings"]
    assert r["verdict"] == R.NOT_READY
    crit = {c["id"]: c for c in r["criteria"]}
    assert not crit["ceilings_hold"]["ok"]
    assert "scripts/settings_writer.py" in crit["ceilings_hold"]["gaps"][0]


def test_named_single_writer_with_another_writer_is_a_false_claim(repo):
    root, _ = repo
    r = _rows(_scan(root))["claim"]
    assert r["verdict"] == R.NOT_READY
    crit = {c["id"]: c for c in r["criteria"]}
    assert not crit["writer_claim_true"]["ok"]
    assert "scripts/sneaky_writer.py" in crit["writer_claim_true"]["gaps"][0]
    # the gate's own simulated check also fails (ceiling 2 holds the count, but not a single named writer)
    assert r["live"]["writer_files"]["count"] == 2


def test_declared_multi_writer_ceiling_is_grantable(repo):
    """AGENTS.md §26.2: a declared UNCONSOLIDATED ceiling that only falls is grantable; today's count is a warning."""
    root, _ = repo
    r = _rows(_scan(root))["multi"]
    assert r["verdict"] == R.READY
    assert [f["check"] for f in r["live"]["findings"]] == ["DICTIONARY_SECOND_WRITER"]
    assert r["live"]["warn_count"] == 1


def test_unapproved_reader_of_a_gated_store_blocks(repo):
    root, _ = repo
    v = _scan(root)
    r = _rows(v)["pos"]
    assert r["verdict"] == R.NOT_READY
    crit = {c["id"]: c for c in r["criteria"]}
    assert not crit["readers_granted"]["ok"]
    assert "scripts/pos_rogue_reader.py" in crit["readers_granted"]["gaps"][0]
    assert any(f["check"] == "UNAPPROVED_READER" for f in r["live"]["findings"])
    assert (
        r["approved_reader_batches"][0]["batch"] == 1 and r["approved_reader_batches"][0]["approved_on"] == "2026-10-22"
    )
    assert r["extends_approved"] and r["base_domain_approval"]["approved_on"] == "2026-10-06"


def test_missing_writer_file_is_a_malformed_row(repo):
    root, _ = repo
    r = _rows(_scan(root))["ghost"]
    assert r["verdict"] == R.NOT_READY
    crit = {c["id"]: c for c in r["criteria"]}
    assert not crit["row_valid"]["ok"] and "does_not_exist" in crit["row_valid"]["gaps"][0]


def test_approved_row_is_approved_with_its_record(repo):
    root, _ = repo
    r = _rows(_scan(root))["already"]
    assert r["verdict"] == R.APPROVED and r["status"] == "approved"
    assert r["approval"]["approved_by"] == "operator"


def test_summary_counts_and_operator_note(repo):
    root, _ = repo
    v = _scan(root)
    s = v["summary"]
    rows = _rows(v)
    assert s["approved"] == sum(1 for r in rows.values() if r["verdict"] == R.APPROVED) == 1
    assert s["ready"] == sum(1 for r in rows.values() if r["verdict"] == R.READY)
    assert s["not_ready"] == sum(1 for r in rows.values() if r["verdict"] == R.NOT_READY)
    assert s["operator_approved_pending_pr"] == ["good"]
    assert rows["good"]["operator_note"]["decision"] == "operator approval E"


def test_freshness_file_mtime_and_declared_column(repo, tmp_path):
    root, auth = repo
    seen = {}

    def probe(table, columns):
        seen[table] = columns
        if table == "good_table":
            return {"state": "MEASURED", "signal": "max(observed_at)", "newest_at_raw": NOW - timedelta(hours=3)}
        return {"state": "NO_SIGNAL", "detail": "no timestamp column declared in data_dictionary.facts"}

    rows = _rows(_scan(root, probe))
    assert seen["good_table"] == ["observed_at"] and seen["claim_tbl"] == []
    g = rows["good"]["freshness"]
    assert g["age_h"] == 3.0 and g["stale"] is True and g["stale_after_hours"] == 1
    t = rows["theses"]["freshness"]
    assert t["state"] == "MEASURED" and t["signal"] == "file mtime" and isinstance(t["age_h"], float)
    assert rows["claim"]["freshness"]["state"] == "NO_SIGNAL" and rows["claim"]["freshness"]["stale"] is None


def test_no_probe_is_unavailable_never_fresh(repo):
    root, _ = repo
    f = _rows(_scan(root))["good"]["freshness"]
    assert f["state"] == "UNAVAILABLE" and f["stale"] is None


def test_scan_writes_nothing(repo):
    root, _ = repo
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    _scan(root)
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_cache_never_blocks_and_refreshes_once_per_ttl(repo, monkeypatch):
    root, _ = repo
    gate = threading.Event()
    calls = []
    real = R.run_gates

    def slow(auth, r, files=None):
        calls.append(1)
        gate.wait(10)
        return real(auth, r, files)

    monkeypatch.setattr(R, "run_gates", slow)
    c = R.ReadinessCache(root, ttl_s=60, clock=lambda: NOW)
    v1 = c.view()
    assert v1["scan"]["state"] == "RUNNING" and all(r["verdict"] is None for r in v1["rows"])
    assert v1["rows"][0]["store"]  # registry facts render before the scan finishes
    c.view()  # a second request while running starts nothing
    gate.set()
    for t in threading.enumerate():
        if t.name == "data-domain-readiness":
            t.join(20)
    v2 = c.view()
    assert v2["scan"]["state"] == "DONE" and _rows(v2)["good"]["verdict"] == R.READY
    assert len(calls) == 1


def test_failed_scan_is_failed_not_ready(repo, monkeypatch):
    root, _ = repo
    monkeypatch.setattr(R, "run_gates", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    v = R.ReadinessCache(root, background=False, clock=lambda: NOW).view()
    assert v["scan"]["state"] == "FAILED" and "boom" in v["scan"]["error"]
    assert v["summary"]["ready"] == 0 and all(r["verdict"] is None for r in v["rows"])


def test_prefilter_is_identical_to_the_bare_regex(repo):
    """data_dictionary.writer_files / reader_files pre-filter by the lower-cased table name (tables) or the marker
    (files); the result must equal running writes_store / reads_store on every file."""
    root, auth = repo
    files = DD.source_files(root)
    for row in auth["proposed_domains"]:
        st = row["store"]
        brute_w = sorted(p.relative_to(root).as_posix() for p in files if DD.writes_store(p.read_text(), st))
        brute_r = sorted(p.relative_to(root).as_posix() for p in files if DD.reads_store(p.read_text(), st))
        assert DD.writer_files(st, files, root, {}) == brute_w
        assert DD.reader_files(st, files, root, {}) == brute_r
    assert DD.writer_files({"table": "settings_tbl"}, files, root, {}) == ["scripts/settings_writer.py"]


def test_simulation_never_returns_a_grant(repo):
    root, auth = repo
    v = _scan(root)
    blob = json.dumps(v, default=str)
    assert "SIMULATION (not a grant)" not in blob
    assert all(r["approval"] is None for r in v["rows"] if r["verdict"] != R.APPROVED)


def test_the_live_registry_has_seventeen_proposed_rows_and_a_verdict_shape():
    """Against the real registry (no scan): every proposed row renders with its store and writer."""
    auth = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    v = R.assess(auth, None, None, R.load_notes(ROOT))
    names = [r["domain"] for r in v["rows"] if r["status"] == "proposed"]
    assert len(names) == len(auth["proposed_domains"])
    assert all(r["store"] for r in v["rows"])
    assert "cio_prospect" in v["summary"]["operator_approved_pending_pr"]


def test_approval_effects_say_what_changes_and_what_does_not(repo):
    root, _ = repo
    rows = _rows(_scan(root))
    eff = " ".join(rows["multi"]["approval_effects"])
    assert "writer ceiling of 2" in eff and "FAILING instead of warning" in eff
    assert "creates no table, moves no reader" in eff
    assert "already a granted §7A domain" in " ".join(rows["pos"]["approval_effects"])
    assert rows["already"]["approval_effects"] == []
    real = R.approval_effects({"domain": "cio_prospect", "store": {"table": "cio_prospect"}}, None)
    assert any("prospect_store_status" in e for e in real)
