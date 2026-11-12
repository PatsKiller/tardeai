"""LQ-20261107-2246: a drain request naming a release that is not CURRENT is inert.

Reproduces the 2026-11-12 09:46 ET crash loop in a temp tree with the real layout
(<base>/<release dirs>, <base>/CURRENT symlink, <state>/data/runtime/n8n_executor_drain_request.json):
the previous promote left a request with target=old release; the next release's executor (code_root=new,
CURRENT=new) drained and exited at once, then systemd restarted it, forever. Synthetic paths only.

AUTHORITY: READ_ONLY_ADVISORY. Hermetic: tmp_path ledgers, fake clock and runner; no systemd, no network.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import n8n_executor_drain as D  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402
from scripts.lib.n8n_retry_policy import load_policies  # noqa: E402
from tests.test_n8n_executor_drain_20261107 import Clock, Gates, _entry, _wait  # noqa: E402

T0 = 1_791_500_000.0


@pytest.fixture
def tree(tmp_path):
    base = tmp_path / "portfolio-server"
    old, new = base / "rel-old", base / "rel-new"
    old.mkdir(parents=True)
    new.mkdir()
    (base / "CURRENT").symlink_to(new)
    state = tmp_path / "state"
    state.mkdir()
    return SimpleNamespace(base=base, old=old, new=new, state=state, tmp=tmp_path)


def _stale_request(tree):
    """The file the 09:46 promote found: target = previous release, written ~65 min earlier, never acted on."""
    D.write_request(tree.state, tree.old, now=T0 - 3900)


def test_stale_target_is_inert_for_the_executor_of_the_current_release(tree):
    _stale_request(tree)
    assert D.drain_state(tree.state, tree.new, T0) is None


def test_request_for_the_current_release_still_drains_the_old_executor(tree):
    D.write_request(tree.state, tree.new, now=T0 - 5)
    d = D.drain_state(tree.state, tree.old, T0)
    assert d is not None and d["target"] == str(tree.new.resolve())


def test_request_is_still_inert_on_the_target_itself(tree):
    D.write_request(tree.state, tree.new, now=T0 - 5)
    assert D.drain_state(tree.state, tree.new, T0) is None


def test_unknown_current_keeps_the_old_behaviour(tmp_path):
    old, new, state = tmp_path / "a", tmp_path / "b", tmp_path / "s"
    for p in (old, new, state):
        p.mkdir()
    D.write_request(state, new, now=T0 - 5)
    assert D.current_release(old) is None
    assert D.drain_state(state, old, T0) is not None


def test_executor_of_the_current_release_keeps_claiming_with_a_stale_request(tree):
    _stale_request(tree)
    ledger = CoordinationLedger(tree.tmp / "ledger.sqlite")
    store = LedgerRunStore(ledger)
    clock, gates = Clock(T0), Gates()
    allow = {"sweep": _entry(tree.tmp, "sweep")}
    ex = X.ExecutorV2(
        store, allow, env={"TRADEAI_VENV_PYTHON": sys.executable}, state_root=tree.state, code_root=tree.new,
        workers=3, policies=load_policies(), clock=clock, runner_factory=gates.factory, worker_prefix="test",
        quiet=True, registry_rows=[{"lane_id": "sweep", "dispatch": {"retry_policy": "transient-2"}}],
        sleeper=lambda s: None,
    )
    store.request(run_id="run-sweep-00000000001", lane_id="sweep", mode="live", requested_by="t",
                  caller_id="n8n-relay", now=clock.t)
    gates.gate("sweep").set()
    done, result = threading.Event(), {}

    def serve():
        result["r"] = ex.serve(poll_s=0.01)
        done.set()

    threading.Thread(target=serve, daemon=True).start()
    try:
        _wait(lambda: store.get("run-sweep-00000000001")["state"] == "RUN_DONE")
        time.sleep(0.2)
        assert not done.is_set(), f"executor drained and exited on a stale target: {result}"
    finally:
        gates.gate("sweep").set()
        ledger.close()


def test_retarget_rewrites_a_leftover_request_and_reads_it_back(tree):
    _stale_request(tree)
    out = D.retarget(tree.state, tree.new, now=T0)
    assert out["result"] == "ok" and out["was"] == str(tree.old.resolve())
    assert D.read_request(tree.state)["target"] == str(tree.new.resolve())
    assert D.drain_state(tree.state, tree.new, T0) is None


def test_retarget_never_creates_a_request(tree):
    assert D.retarget(tree.state, tree.new)["result"] == "absent"
    assert not D.request_path(tree.state).exists()


def test_retarget_reports_mismatch_when_the_write_does_not_stick(tree, monkeypatch):
    _stale_request(tree)
    monkeypatch.setattr(D, "write_request", lambda *a, **k: None)
    assert D.retarget(tree.state, tree.new)["result"] == "mismatch"


def test_cli_retarget_exit_codes_and_token(tree):
    _stale_request(tree)
    cmd = [sys.executable, str(ROOT / "scripts" / "n8n_executor_drain.py"), "retarget",
           "--target", str(tree.new), "--state-root", str(tree.state)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "RETARGET_RESULT=ok" in r.stdout, r.stdout + r.stderr
    assert json.loads(D.request_path(tree.state).read_text())["target"] == str(tree.new.resolve())
