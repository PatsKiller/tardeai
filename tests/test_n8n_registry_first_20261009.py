"""AGENTS.md 3.0.0 §23.10 P17 — registry-first for n8n (audit C G10).

An ACTIVE n8n workflow is a scheduler. It is declared by a kind-n8n registry row naming its id or by the
generated INDEX (live and shadow ids); anything else is UNDECLARED_N8N_WORKFLOW and fails
`check_lane_registry --fail-on-new`. CI reads the committed snapshot; the host reads live through one
SELECT. Every test here uses fixtures under tmp_path and a fake runner — no docker, no n8n DB.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib import n8n_live_inventory as INV  # noqa: E402

CHECK = ROOT / "scripts" / "check_lane_registry.py"


def _row(lane_id: str, sched: dict) -> dict:
    return {
        "lane_id": lane_id,
        "owner": "platform",
        "scheduler": sched,
        "state": "ACTIVE",
        "expected_cadence_hours": 24,
        "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{lane_id}.json"},
    }


REG = {
    "schema": "LaneRegistry@v1",
    "lanes": [
        _row(
            "lane-a", {"kind": "n8n", "expression": "aaaa000000000001", "match": "scripts/a.py", "cadence": "0 1 * * *"}
        ),
        _row("lane-b", {"kind": "cron", "expression": "scripts/b.py"}),
    ],
    "undeclared_baseline": ["bbbb000000000002"],
}
INDEX = {
    "schema": "N8nWorkflowSet@v1",
    "relay_url_placeholder": "http://RELAY_HOST:18092",
    "lanes": [{"lane_id": "lane-c", "live_workflow_id": "cccc000000000003", "shadow_workflow_id": "cccc00000000003s"}],
}


def _n8n(*ids: str) -> list[dict]:
    return [{"kind": "n8n", "expression": i, "name": f"wf-{i}"} for i in ids]


def test_registry_row_and_generated_index_declare_an_active_workflow():
    found = {"cron": [], "systemd": [], "n8n": _n8n("aaaa000000000001", "cccc000000000003", "cccc00000000003s")}
    known = INV.known_workflow_ids(INDEX)
    assert LR.find_undeclared(REG, found, n8n_known_ids=known) == []


def test_unknown_active_workflow_is_undeclared_and_the_baseline_never_covers_n8n():
    found = {"cron": [], "systemd": [], "n8n": _n8n("bbbb000000000002", "dddd000000000004")}
    out = LR.find_undeclared(REG, found, n8n_known_ids=INV.known_workflow_ids(INDEX))
    assert [(u["kind"], u["expression"], u["code"]) for u in out] == [
        ("n8n", "bbbb000000000002", LR.UNDECLARED_N8N_WORKFLOW),
        ("n8n", "dddd000000000004", LR.UNDECLARED_N8N_WORKFLOW),
    ]
    assert out[0]["name"] == "wf-bbbb000000000002"


def test_a_cron_row_with_the_same_text_does_not_declare_a_workflow():
    reg = {"lanes": [_row("lane-x", {"kind": "cron", "expression": "eeee000000000005 scripts/x.py"})]}
    out = LR.find_undeclared(reg, {"n8n": _n8n("eeee000000000005")}, n8n_known_ids=set())
    assert [u["code"] for u in out] == [LR.UNDECLARED_N8N_WORKFLOW]


def test_known_ids_cover_live_and_shadow_ids_of_the_committed_index():
    idx = INV.load_generated_index()
    known = INV.known_workflow_ids(idx)
    assert len(known) == 2 * len(idx["lanes"])
    git = INV.git_workflows()
    assert set(known) == set(git), "every INDEX id has a generated file and every generated file is in INDEX"


def test_the_committed_snapshot_is_clean_against_the_committed_registry_and_index():
    snap = INV.load_active_snapshot()
    assert snap, "snapshot lists the active workflows"
    found = {"cron": [], "systemd": [], "n8n": INV.discover_n8n(snap)}
    assert LR.find_undeclared(LR.load_registry(), found) == []


def _proc(stdout: str = "", returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def test_run_select_refuses_anything_but_one_select():
    for sql in (
        "update workflow_entity set active = true",
        "select 1; drop table x",
        "delete from workflow_entity",
        "with x as (select 1) select * from x",
    ):
        with pytest.raises(ValueError):
            INV.run_select(sql, runner=lambda *a, **k: _proc("[]"))


def test_live_read_is_one_docker_exec_psql_select_and_filters_active():
    seen = []

    def runner(cmd, **kw):
        seen.append(cmd)
        return _proc(json.dumps([{"id": "a", "name": "A", "active": True}, {"id": "b", "name": "B", "active": False}]))

    rows = INV.read_active_workflows(runner=runner)
    assert [r["id"] for r in rows] == ["a"]
    cmd = seen[0]
    assert cmd[:3] == ["docker", "exec", "m8m-n8n-db"] and cmd[3:9] == ["psql", "-U", "n8n", "-d", "n8n", "-tAc"]
    assert cmd[9].lower().startswith("select")
    assert [r["expression"] for r in INV.discover_n8n(rows)] == ["a"]


def test_a_failed_live_read_is_unavailable_never_empty():
    with pytest.raises(INV.InventoryUnavailable):
        INV.read_active_workflows(runner=lambda *a, **k: _proc("", 1, "no such container"))
    with pytest.raises(INV.InventoryUnavailable):
        INV.read_active_workflows(runner=lambda *a, **k: _proc("not json"))

    def boom(*a, **k):
        raise FileNotFoundError("docker")

    with pytest.raises(INV.InventoryUnavailable):
        INV.read_active_workflows(runner=boom)


def test_monitor_discovery_is_opt_in_and_records_why_it_could_not_look(monkeypatch):
    monkeypatch.delenv(LR.N8N_DISCOVERY_ENV, raising=False)
    assert "n8n" not in LR.discover_all(cron_text="", include_systemd=False)

    def boom(**kw):
        raise INV.InventoryUnavailable("container down")

    monkeypatch.setattr(LR, "discover_n8n_live", boom)
    monkeypatch.setenv(LR.N8N_DISCOVERY_ENV, "1")
    found = LR.discover_all(cron_text="", include_systemd=False)
    assert "n8n" not in found and "container down" in found["n8n_unavailable"]
    monkeypatch.setattr(LR, "discover_n8n_live", lambda **kw: _n8n("zzzz000000000009"))
    found = LR.discover_all(cron_text="", include_systemd=False)
    assert found["n8n"][0]["expression"] == "zzzz000000000009"


def _write(path: Path, doc) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _run(tmp_path: Path, snapshot_ids: list[str], *extra: str) -> subprocess.CompletedProcess:
    reg = _write(tmp_path / "registry.json", REG)
    idx = _write(tmp_path / "INDEX.json", INDEX)
    disc = _write(tmp_path / "discovery.json", {"cron": [], "cron_commented": [], "systemd": []})
    snap = _write(
        tmp_path / "snap.json",
        INV.snapshot_doc(
            [{"id": i, "name": i} for i in snapshot_ids], captured_at="2026-10-09T00:00:00+00:00", source="fixture"
        ),
    )
    return subprocess.run(
        [
            sys.executable,
            str(CHECK),
            "--fail-on-new",
            "--registry",
            str(reg),
            "--discovery-json",
            str(disc),
            "--n8n-snapshot",
            str(snap),
            "--n8n-index",
            str(idx),
            *extra,
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_gate_fails_on_an_undeclared_workflow_and_passes_when_declared(tmp_path):
    bad = _run(tmp_path, ["aaaa000000000001", "ffff000000000006"])
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "UNDECLARED_N8N_WORKFLOW ffff000000000006" in bad.stdout
    good = _run(tmp_path, ["aaaa000000000001", "cccc00000000003s"])
    assert good.returncode == 0, good.stdout + good.stderr
    assert "n8n active workflows    : 2  (source snapshot)" in good.stdout
    skipped = _run(tmp_path, ["ffff000000000006"], "--no-n8n")
    assert skipped.returncode == 0, skipped.stdout + skipped.stderr


def test_gate_cannot_run_when_the_snapshot_is_unreadable(tmp_path):
    reg = _write(tmp_path / "registry.json", REG)
    disc = _write(tmp_path / "discovery.json", {"cron": [], "systemd": []})
    (tmp_path / "snap.json").write_text("{not json", encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            str(CHECK),
            "--fail-on-new",
            "--registry",
            str(reg),
            "--discovery-json",
            str(disc),
            "--n8n-snapshot",
            str(tmp_path / "snap.json"),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 2 and "CANNOT RUN" in r.stderr


def test_discovery_json_may_carry_its_own_n8n_rows(tmp_path):
    reg = _write(tmp_path / "registry.json", REG)
    idx = _write(tmp_path / "INDEX.json", INDEX)
    disc = _write(tmp_path / "discovery.json", {"cron": [], "systemd": [], "n8n": _n8n("1234123412341234")})
    r = subprocess.run(
        [
            sys.executable,
            str(CHECK),
            "--fail-on-new",
            "--json",
            "--registry",
            str(reg),
            "--discovery-json",
            str(disc),
            "--n8n-index",
            str(idx),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 1
    doc = json.loads(r.stdout)
    assert doc["n8n_source"] == "discovery-json" and doc["undeclared"][0]["code"] == "UNDECLARED_N8N_WORKFLOW"
