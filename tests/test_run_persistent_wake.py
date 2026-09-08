"""CLI runner for persistent wake — hermetic, no crontab/network/DB."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.persistent_agent_wake import FEATURE_FLAG as WAKE_FLAG  # noqa: E402
from scripts.lib.persistent_wake_schedule import FEATURE_FLAG as SCHED_FLAG  # noqa: E402
from scripts.lib.persistent_wake_store import JsonlStore  # noqa: E402
from scripts.run_persistent_wake import both_flags_on, main, run_once  # noqa: E402

SG = "97172f54-916c-5960-aa73-f16321f1cf3e"
NOW = datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc)
ENV_BOTH = {WAKE_FLAG: "1", SCHED_FLAG: "1", "PROVENANCE_PRODUCER": "test",
            "TRADEAI_SOURCE_SHA": "bd9950df8e9bf23002e6a126e0736e4b3e4b3f02"}


def _mem(tmp_path: Path, content: str = "alpha", *, hours_ago: float = 1.0,
         malformed: bool = False) -> Path:
    p = tmp_path / "mem.jsonl"
    if malformed:
        p.write_text("MALFORMED: broken\n")
        return p
    row = {
        "fact_id": "f1",
        "subject_guid": SG,
        "content": content,
        "as_of": (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z"),
    }
    p.write_text(json.dumps(row) + "\n")
    return p


def test_disabled_by_default_neither_flag(tmp_path):
    state = tmp_path / "s"
    rc = run_once(
        agent_id="cio", subject_guid=SG, env={}, when=NOW, state_root=state,
        memory_backend=_mem(tmp_path),
    )
    assert rc == 0
    assert JsonlStore(state).count("wakes") == 0
    assert JsonlStore(state).count("commitments") == 0


def test_only_wake_flag_still_disabled(tmp_path):
    state = tmp_path / "s"
    env = {WAKE_FLAG: "1", SCHED_FLAG: "0"}
    assert both_flags_on(env) is False
    rc = run_once(
        agent_id="cio", subject_guid=SG, env=env, when=NOW, state_root=state,
        memory_backend=_mem(tmp_path),
    )
    assert rc == 0
    assert JsonlStore(state).count("wakes") == 0


def test_only_schedule_flag_still_disabled(tmp_path):
    state = tmp_path / "s"
    env = {WAKE_FLAG: "0", SCHED_FLAG: "1"}
    assert both_flags_on(env) is False
    rc = run_once(
        agent_id="cio", subject_guid=SG, env=env, when=NOW, state_root=state,
        memory_backend=_mem(tmp_path),
    )
    assert rc == 0
    assert JsonlStore(state).count("wakes") == 0


def test_both_flags_slot_due_exactly_one_wake(tmp_path):
    state = tmp_path / "s"
    mem = _mem(tmp_path)
    rc = run_once(
        agent_id="cio", subject_guid=SG, env=ENV_BOTH, when=NOW, state_root=state,
        memory_backend=mem,
    )
    assert rc == 0
    assert JsonlStore(state).count("wakes") == 1
    assert JsonlStore(state).count("commitments") == 1


def test_same_slot_twice_still_one_wake(tmp_path):
    state = tmp_path / "s"
    mem = _mem(tmp_path)
    assert run_once(agent_id="cio", subject_guid=SG, env=ENV_BOTH, when=NOW,
                    state_root=state, memory_backend=mem) == 0
    assert run_once(agent_id="cio", subject_guid=SG, env=ENV_BOTH,
                    when=NOW + timedelta(minutes=10),
                    state_root=state, memory_backend=mem) == 0
    assert JsonlStore(state).count("wakes") == 1
    assert JsonlStore(state).count("commitments") == 1


def test_missed_slot_skipped_not_caught_up(tmp_path):
    """Invoking at T must not mint wakes for T-1h / T-2h (skip_missed)."""
    state = tmp_path / "s"
    mem = _mem(tmp_path)
    assert run_once(agent_id="cio", subject_guid=SG, env=ENV_BOTH, when=NOW,
                    state_root=state, memory_backend=mem) == 0
    wakes = list(JsonlStore(state).iter("wakes"))
    assert len(wakes) == 1
    # Only the current slot is present — no catch-up rows for prior hours.
    from scripts.lib.persistent_wake_schedule import ScheduleContract
    c = ScheduleContract("cio", "scheduled_persistent_review")
    assert wakes[0]["schedule_slot_utc"] == c.slot_for(NOW)
    for i in (1, 2, 3):
        past = c.slot_for(NOW - timedelta(hours=i))
        assert wakes[0]["schedule_slot_utc"] != past or i == 0


def test_malformed_memory_refuses_exit_0(tmp_path, capsys):
    state = tmp_path / "s"
    mem = _mem(tmp_path, malformed=True)
    rc = run_once(
        agent_id="cio", subject_guid=SG, env=ENV_BOTH, when=NOW, state_root=state,
        memory_backend=mem,
    )
    assert rc == 0
    assert JsonlStore(state).count("commitments") == 0
    out = capsys.readouterr().out
    assert "refused" in out or "MEMORY_MALFORMED" in out


def test_absent_memory_refuses_exit_0(tmp_path, capsys):
    state = tmp_path / "s"
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    rc = run_once(
        agent_id="cio", subject_guid=SG, env=ENV_BOTH, when=NOW, state_root=state,
        memory_backend=empty,
    )
    assert rc == 0
    assert JsonlStore(state).count("commitments") == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["outcome"] in {"refused", "ok"}  # LOADED/no_relevant_memory -> refused
    assert line["outcome"] == "refused"


def test_dry_run_writes_nothing(tmp_path, capsys):
    state = tmp_path / "s"
    mem = _mem(tmp_path)
    rc = run_once(
        agent_id="cio", subject_guid=SG, env=ENV_BOTH, when=NOW, state_root=state,
        memory_backend=mem, dry_run=True,
    )
    assert rc == 0
    assert JsonlStore(state).count("wakes") == 0
    assert JsonlStore(state).count("commitments") == 0
    assert "dry_run" in capsys.readouterr().out


def test_cli_main_argparse_disabled(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(WAKE_FLAG, raising=False)
    monkeypatch.delenv(SCHED_FLAG, raising=False)
    rc = main([
        "--agent-id", "cio",
        "--subject-guid", SG,
        "--state-root", str(tmp_path / "s"),
        "--memory-path", str(_mem(tmp_path)),
        "--when-utc", NOW.isoformat().replace("+00:00", "Z"),
    ])
    assert rc == 0
    assert "disabled" in capsys.readouterr().out


def test_no_crontab_dependency_in_module_source():
    """Portability guard: must not *invoke* crontab (CI has no binary).

    Docstring mentions of the word are fine; subprocess/check_output/call forms are not.
    """
    import ast
    src = (ROOT / "scripts" / "run_persistent_wake.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # ["crontab", ...] literal in a call
            for arg in list(node.args) + [kw.value for kw in (node.keywords or [])]:
                if isinstance(arg, ast.Constant) and arg.value == "crontab":
                    raise AssertionError("crontab invoked as a subprocess argument")
                if isinstance(arg, (ast.List, ast.Tuple)):
                    for elt in arg.elts:
                        if isinstance(elt, ast.Constant) and elt.value == "crontab":
                            raise AssertionError("crontab invoked as a subprocess argument")
