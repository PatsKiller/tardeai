"""Operator resume settles an idle deploy STOP itself (2026-10-28).

The release-train controller that acknowledged and settled a STOP was retired 2026-10-27, so
``scripts/release_control_cli.py resume`` refused STOP_NOT_SETTLED after every ``stop`` until the operator ran
``acknowledge_stop`` / ``settle`` by hand as a controller actor. ``resume(settle_if_idle=True)`` (the CLI's path)
now settles the STOP as the verified operator, but only while it holds the GlobalReleaseLock that the
deploy_on_main poller holds for a whole deploy; a held lock means a deploy is in flight and the refusal stands.

Hermetic: tmp_path state dir, fixed clock, a fake TTY. No git, network, DB or systemd.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import release_control_cli as CLI  # noqa: E402
from scripts.lib import release_control as RC  # noqa: E402

NOW = 1_793_200_000.0
HOST = RC.Actor("host_cli", "uid:test")
CC = RC.Actor("cc", "operator@tailnet")
CTRL = RC.Actor("controller", "tradeai-release-train.service")
READY = {"checked_at": "2026-10-28T15:00:00Z"}


def _proof(ctl: RC.ReleaseControl, command: str, phrase: str | None = None) -> RC.HostCliProof:
    return RC.HostCliProof(tty="/dev/pts/9", uid=os.getuid(), confirmation=phrase or ctl.expected_phrase(command))


def refused(code: str):
    return pytest.raises(RC.ControlRefused, match=rf"^{re.escape(code)}\b")


class FakeTty:
    def __init__(self, text: str) -> None:
        self.text = text

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        return self.text

    def fileno(self) -> int:
        return 0


@pytest.fixture
def ctl(tmp_path) -> RC.ReleaseControl:
    c = RC.ReleaseControl(tmp_path / "state", clock=lambda: NOW)
    (tmp_path / "state").mkdir()
    c.arm(HOST, _proof(c, "arm"), policy_digest="a" * 64, reason="arm for test")
    return c


@pytest.fixture
def held_lock(ctl):
    """Another holder of <state>/.lock, as the deploy_on_main poller holds it for a whole deploy."""
    fh = open(ctl.root / RC.GLOBAL_LOCK_NAME, "a+")  # noqa: SIM115
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    yield fh
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    fh.close()


def journal(ctl: RC.ReleaseControl) -> list[dict]:
    return [json.loads(x) for x in ctl.journal_path.read_text(encoding="utf-8").splitlines() if x.strip()]


def cli(ctl: RC.ReleaseControl, *args: str, stdin=None) -> tuple[int, dict]:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = CLI.main(["--state-dir", str(ctl.root), *args], stdin=stdin)
    return rc, json.loads(buf.getvalue())


# ── CLI: stop then resume with nothing in flight ────────────────────────────────────────────────────────


def test_cli_stop_then_resume_works_with_nothing_in_flight(ctl, monkeypatch):
    monkeypatch.setattr(CLI.os, "ttyname", lambda fd: "/dev/pts/9")
    rc, out = cli(ctl, "stop", "--reason", "operator stop")
    assert rc == 0 and out["outcome"] == "STOP_REQUESTED"
    phrase = ctl.expected_phrase("resume")
    assert phrase == f"RESUME EPOCH {ctl.view().epoch + 1}"

    rc, out = cli(ctl, "resume", "--reason", "incident reviewed", stdin=FakeTty(phrase + "\n"))
    assert rc == 0, out
    assert out["outcome"] == "RESUMED"
    assert out["settled_by"]["actor"] == {"kind": "host_cli", "identity": f"uid:{os.getuid()}"}
    v = ctl.view()
    assert v.mode == RC.RUNNING and v.latch_state == RC.LATCH_ABSENT
    assert Path(out["latch_archived"]).exists(), "latch archived by rename, never deleted"


def test_cli_resume_still_needs_the_typed_phrase(ctl, monkeypatch):
    monkeypatch.setattr(CLI.os, "ttyname", lambda fd: "/dev/pts/9")
    cli(ctl, "stop", "--reason", "operator stop")
    rc, out = cli(ctl, "resume", "--reason", "wrong phrase", stdin=FakeTty("RESUME\n"))
    assert rc == 2 and out["code"] == "OPERATOR_PROOF_REFUSED"
    assert ctl.view().mode == RC.STOP_REQUESTED, "a refused proof settles nothing"
    assert not any(r["command"] == "operator_settle" for r in journal(ctl))


# ── in flight: the refusal stands ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phase", ["requested", "acknowledged", "settling"])
def test_resume_refuses_while_a_deploy_holds_the_global_lock(ctl, held_lock, phase):
    ctl.request_stop(CC, "stop")
    if phase != "requested":
        ctl.acknowledge_stop(CTRL)
    if phase == "settling":
        ctl.settle(CTRL, in_flight=True)
    before = ctl.view()
    with refused("STOP_NOT_SETTLED"):
        ctl.resume(HOST, _proof(ctl, "resume"), reason="too early", readiness=READY, settle_if_idle=True)
    after = ctl.view()
    assert (after.mode, after.version, after.latch_state) == (before.mode, before.version, RC.LATCH_SET)
    last = journal(ctl)[-1]
    assert last["command"] == "resume" and last["result"]["code"] == "STOP_NOT_SETTLED"
    assert last["result"]["in_flight"] is True


def test_cli_resume_refuses_while_in_flight(ctl, held_lock, monkeypatch):
    monkeypatch.setattr(CLI.os, "ttyname", lambda fd: "/dev/pts/9")
    cli(ctl, "stop", "--reason", "operator stop")
    rc, out = cli(ctl, "resume", "--reason", "too early", stdin=FakeTty(ctl.expected_phrase("resume") + "\n"))
    assert rc == 2 and out["code"] == "STOP_NOT_SETTLED"
    assert "in flight" in out["detail"]
    assert ctl.view().mode == RC.STOP_REQUESTED


def test_library_default_keeps_the_settled_rule(ctl):
    """Callers that do not opt in (Ops -> Controls passkey applier) keep the old refusal."""
    ctl.request_stop(CC, "stop")
    with refused("STOP_NOT_SETTLED"):
        ctl.resume(HOST, _proof(ctl, "resume"), reason="no opt in", readiness=READY)
    assert ctl.view().mode == RC.STOP_REQUESTED


# ── audit: who settled ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phase", ["requested", "acknowledged", "settling"])
def test_audit_records_who_settled(ctl, phase):
    ctl.request_stop(CC, "stop")
    if phase != "requested":
        ctl.acknowledge_stop(CTRL)
    if phase == "settling":
        ctl.settle(CTRL, in_flight=True)
    from_mode = ctl.view().mode
    out = ctl.resume(HOST, _proof(ctl, "resume"), reason="incident reviewed", readiness=READY, settle_if_idle=True)
    assert out["outcome"] == "RESUMED"

    rows = journal(ctl)
    settle = [r for r in rows if r["command"] == "operator_settle"]
    assert len(settle) == 1
    s = settle[0]
    assert s["actor"] == {"kind": "host_cli", "identity": "uid:test"}
    assert s["result"]["outcome"] == RC.STOPPED and s["result"]["in_flight"] is False
    assert s["result"]["from_mode"] == from_mode and s["result"]["via"] == "resume"
    assert rows.index(s) < max(i for i, r in enumerate(rows) if r["command"] == "resume")

    body = ctl.view().raw
    prior = body["resumed"]["prior_stop"]
    assert body["resumed"]["prior_mode"] == RC.STOPPED
    assert prior["settled_by"]["actor"] == {"kind": "host_cli", "identity": "uid:test"}
    assert prior["acknowledged_at"] and prior["settling_at"] and prior["stopped_at"]
    assert (ctl.root / RC.GLOBAL_LOCK_NAME).exists()
    # the lock was released: a following deploy can take it
    with RC.GlobalReleaseLock(ctl.root, timeout_s=0.0):
        pass


def test_already_stopped_resume_records_no_operator_settle(ctl):
    ctl.request_stop(CC, "stop")
    ctl.acknowledge_stop(CTRL)
    ctl.settle(CTRL, in_flight=False)
    out = ctl.resume(HOST, _proof(ctl, "resume"), reason="incident reviewed", readiness=READY, settle_if_idle=True)
    assert out["outcome"] == "RESUMED" and "settled_by" not in out
    assert not any(r["command"] == "operator_settle" for r in journal(ctl))


# ── wording ─────────────────────────────────────────────────────────────────────────────────────────────


def test_user_facing_wording_says_deploy_stop(ctl):
    ctl.request_stop(CC, "stop")
    _, latch = RC.read_latch(ctl.latch_path)
    assert latch["detail"].startswith("deploy STOP;")
    for path in (ROOT / "scripts" / "release_control_cli.py", ROOT / "scripts" / "lib" / "release_control.py"):
        assert "release train STOP" not in path.read_text(encoding="utf-8")
