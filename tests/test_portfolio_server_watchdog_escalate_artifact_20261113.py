"""MEM-CONTAIN review N2: a watchdog ESCALATE leaves durable artifacts, not only a log line: one JSON line in an
escalation log (data/ops/watchdog_escalations.jsonl in production) and one FINDING file per escalation episode in the
lead inbox. No Telegram / email / text send. Every external effect is a stub; artifacts land in tmp dirs."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "portfolio_server_watchdog.sh"
FAKE_PID = "2147483000"


def _stub(d: Path, name: str, body: str) -> None:
    p = d / name
    p.write_text("#!/bin/bash\n" + body + "\n")
    p.chmod(0o755)


@pytest.fixture
def env(tmp_path):
    stub = tmp_path / "bin"
    stub.mkdir()
    rec = tmp_path / "calls.log"
    _stub(stub, "curl", f'echo "curl $*" >> "{rec}"; exit 7')  # never healthy
    _stub(stub, "pgrep", f"echo {FAKE_PID}")
    _stub(stub, "systemctl", f'echo "systemctl $*" >> "{rec}"; case "$*" in *is-active*) echo active; exit 0;; '
                              f'*ControlGroup*) echo ""; exit 0;; esac; exit 0')
    _stub(stub, "sleep", "exit 0")
    _stub(stub, "fake_kill", f'echo "kill $*" >> "{rec}"; exit 1')
    for name in ("send_telegram", "mail", "sendmail", "telegram_send"):  # any send attempt would be recorded
        _stub(stub, name, f'echo "SEND {name} $*" >> "{rec}"; exit 0')
    logs = tmp_path / "logs"
    logs.mkdir()
    e = dict(os.environ)
    e.update({
        "PATH": f"{stub}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "PORTFOLIO_WATCHDOG_URL": "http://127.0.0.1:9/fake-health",
        "PORTFOLIO_WATCHDOG_LOG": str(logs / "wd.log"),
        "PORTFOLIO_WATCHDOG_PROC": "fake_portfolio_server_for_test.py",
        "PORTFOLIO_WATCHDOG_KILL_CMD": str(stub / "fake_kill"),
        "PORTFOLIO_WATCHDOG_ESCALATION_LOG": str(tmp_path / "ops" / "watchdog_escalations.jsonl"),
        "PORTFOLIO_WATCHDOG_FINDING_DIR": str(tmp_path / "inbox"),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
    })
    return {"env": e, "rec": rec, "logs": logs, "state": logs / ".portfolio_server_watchdog_kills",
            "esc": tmp_path / "ops" / "watchdog_escalations.jsonl", "inbox": tmp_path / "inbox", "tmp": tmp_path}


def _escalate(env, runs=1, extra=None):
    now = int(time.time())
    env["state"].write_text("".join(f"{now - s}\n" for s in (100, 600, 1200)))
    e = dict(env["env"], **(extra or {}))
    for _ in range(runs):
        cp = subprocess.run(["/bin/bash", str(SH)], env=e, capture_output=True, text=True, timeout=60)
        assert cp.returncode == 0, cp.stderr


def test_escalate_writes_a_jsonl_record_and_one_finding(env):
    _escalate(env)
    lines = env["esc"].read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "ESCALATE" and rec["pid"] == int(FAKE_PID) and rec["recent_kills"] == 3
    assert rec["kill_cap"] == 3 and rec["window_s"] == 1800 and rec["at_utc"] and rec["at_et"]
    assert rec["episode"] and "evidence" in rec
    findings = list(env["inbox"].glob("FINDING-portfolio-server-watchdog-ESCALATE-*.md"))
    assert len(findings) == 1
    text = findings[0].read_text()
    assert "ESCALATE" in text and FAKE_PID in text and "NOT killed" in text
    assert not list(env["inbox"].glob(".*tmp*")) and not list(env["esc"].parent.glob("*.tmp*"))


def test_repeated_escalate_in_one_episode_appends_records_but_one_finding(env):
    _escalate(env, runs=3)
    assert len(env["esc"].read_text().splitlines()) == 3
    assert len(list(env["inbox"].glob("FINDING-portfolio-server-watchdog-ESCALATE-*.md"))) == 1


def test_escalate_sends_nothing(env):
    _escalate(env)
    calls = env["rec"].read_text().splitlines() if env["rec"].exists() else []
    assert not any(c.startswith("SEND ") for c in calls) and not any(c.startswith("kill ") for c in calls)


def test_overridden_log_keeps_artifacts_beside_it_when_no_artifact_path_is_given(env):
    e = dict(env["env"])
    e.pop("PORTFOLIO_WATCHDOG_ESCALATION_LOG")
    e.pop("PORTFOLIO_WATCHDOG_FINDING_DIR")
    env["env"] = e
    _escalate(env)
    assert (env["logs"] / "watchdog_escalations.jsonl").exists()
    assert list(env["logs"].glob("FINDING-portfolio-server-watchdog-ESCALATE-*.md"))


def test_unwritable_artifact_paths_never_break_the_run(env):
    blocker = env["tmp"] / "blocker"
    blocker.write_text("x")
    _escalate(env, extra={"PORTFOLIO_WATCHDOG_ESCALATION_LOG": str(blocker / "x.jsonl"),
                          "PORTFOLIO_WATCHDOG_FINDING_DIR": str(blocker / "inbox")})
    log = (env["logs"] / "wd.log").read_text()
    assert "ESCALATE:" in log and "escalation artifact write failed" in log
