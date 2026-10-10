"""n8n refactor wave 1 (W2), 2026-10-10 — supervisor_breach_detector.py (timer:tradeai-supervisor-breach-detector).

``--dry-run`` is the explicit spelling of the default and wins over --write/--heal/--ladder/
--enqueue-escalations, so the write block is unreachable from it. With --write the lane receipt
``supervisor_breach_detector_latest.json`` is written last, with ``ok_at`` only when every step held; a
failed L3/L1-L2/L4-L5 step (printed and swallowed before) now exits 1. Breaches are findings: exit 0.
Hermetic: a tmp registry, a tmp state root, no DB, no heartbeat write.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import supervisor_breach_detector as sbd  # noqa: E402

COVERS = ["scripts/supervisor_breach_detector.py"]


def _lane(lane_id, path):
    return {
        "lane_id": lane_id,
        "state": "ACTIVE",
        "expected_cadence_hours": 1,
        "scheduler": {"kind": "systemd", "expression": f"{lane_id}.timer"},
        "output_signal": {"kind": "file_mtime", "path": path},
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    code = tmp_path / "code"
    (code / "config").mkdir(parents=True)
    state = tmp_path / "state"
    rt = state / "data" / "runtime"
    rt.mkdir(parents=True)
    (code / "config" / "lane_registry.json").write_text(json.dumps({"lanes": [_lane("lane-a", "data/runtime/a.json")]}))
    (rt / "supervisor_sla_seed.json").write_text(json.dumps({"rows": [{"lane_id": "lane-a", "max_run_s": 60}]}))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_HEARTBEAT_DIR", str(tmp_path / "hb"))
    monkeypatch.setattr(sbd, "_read_only_db_query", lambda: None)
    fake_db = type(sys)("db_adapter")
    fake_db._get_conn = lambda: (_ for _ in ()).throw(RuntimeError("no db in tests"))
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    import supervisor_heartbeat as hbmod

    beats = []
    monkeypatch.setattr(hbmod, "beat", lambda *a, **k: beats.append(a) or {"pg": "skipped"})
    return {"code": code, "state": state, "rt": rt, "beats": beats, "tmp": tmp_path}


def _main(monkeypatch, env, *argv):
    monkeypatch.setattr(
        sys,
        "argv",
        ["supervisor_breach_detector.py", "--root", str(env["code"]), "--state-root", str(env["state"]), *argv],
    )
    return sbd.main()


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_dry_run_wins_over_every_live_flag_and_writes_nothing(env, monkeypatch, capsys):
    before = _snapshot(env["tmp"])
    monkeypatch.setattr(sbd, "_self_heal_l1_l2", lambda *a, **k: pytest.fail("self-heal reached"))
    monkeypatch.setattr(sbd, "_ladder_l4_l5", lambda *a, **k: pytest.fail("ladder reached"))
    assert _main(monkeypatch, env, "--dry-run", "--write", "--heal", "--ladder", "--enqueue-escalations") == 0
    cap = capsys.readouterr()
    assert "dry run: nothing written" in cap.out and "ignoring --write" in cap.err
    assert '"breaches": 1' in cap.out and "NO_OUTPUT" in cap.out
    assert _snapshot(env["tmp"]) == before and env["beats"] == []


def test_dry_run_mutation_tested_breach_count_follows_the_signal(env, monkeypatch, capsys):
    _main(monkeypatch, env, "--dry-run")
    first = capsys.readouterr().out
    (env["state"] / "data/runtime/a.json").write_text("{}")  # the lane produced: the breach goes away
    _main(monkeypatch, env, "--dry-run")
    second = capsys.readouterr().out
    assert '"breaches": 1' in first and '"breaches": 0' in second


def test_source_order_dry_run_disables_write_before_the_write_block():
    src = inspect.getsource(sbd.main)
    i = src.index("if a.dry_run:\n        a.write = a.heal = a.ladder = a.enqueue_escalations = False")
    assert i < src.index("if a.write:") < src.index('led.open("a"')


def test_write_records_and_latest_carries_ok_at_breaches_are_findings(env, monkeypatch):
    assert _main(monkeypatch, env, "--write") == 0
    latest = json.loads((env["rt"] / "supervisor_breach_detector_latest.json").read_text())
    assert latest["breaches"] == 1 and latest["steps_failed"] == [] and latest["ok_at"] == latest["as_of"]
    assert len((env["rt"] / "supervisor_breaches.jsonl").read_text().splitlines()) == 1
    assert len(env["beats"]) == 1


def test_a_failed_step_exits_1_and_carries_the_previous_ok_at(env, monkeypatch):
    assert _main(monkeypatch, env, "--write") == 0
    ok_at = json.loads((env["rt"] / "supervisor_breach_detector_latest.json").read_text())["ok_at"]

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(sbd, "_ladder_l4_l5", boom)
    assert _main(monkeypatch, env, "--write") == 1
    latest = json.loads((env["rt"] / "supervisor_breach_detector_latest.json").read_text())
    assert latest["steps_failed"] == ["ladder:OSError"] and latest["ok_at"] == ok_at


def test_proposed_allowlist_argv_is_dispatcher_eligible():
    from tests.test_agents_policy_4_1_0_amendment import dispatcher_eligible

    entry = {
        "lane_id": "supervisor-breach-detector",
        "command": ["$PY", "scripts/supervisor_breach_detector.py"],
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--write"],
    }
    assert dispatcher_eligible(
        entry, {"scheduler": {"kind": "systemd", "expression": "tradeai-supervisor-breach-detector.timer"}}
    ) == (True, "ok")
