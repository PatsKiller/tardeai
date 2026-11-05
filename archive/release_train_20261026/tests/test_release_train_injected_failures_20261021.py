"""Release train arming finding 5 (ANCHOR RELEASE_TRAIN_INJECTED_FAILURES_20261021): injected failures are
exercisable in shadow and recorded in the receipt's ``injected_failures``, and a shadow train HALTS (simulated) on a
STOP or a corrupt latch exactly where a live train would, recording ``would_halt``.

The five drills (``--inject red-check|conflict|stop-midrun|corrupt-latch|crash``) are shadow / dry-run only: the
request writer refuses one for a live request, the claimer refuses a live request that carries a marker, a live
controller refuses ``set_injection`` and ``train-run --live --inject`` is refused. Each drill is simulated: no latch,
control, capability, GitHub or host write.

Hermetic: the controller test world under tmp_path (tmp git repo, fake GitHub, fake deploy host). No network, DB,
systemd or broker. psycopg2 is stubbed by the imported controller test module.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tests.test_release_train_controller_20261021 import HOST_ACTOR, World, put, receipt, request  # noqa: E402
from tests.test_release_train_n8n_20261021 import _run, cfg, policy, shadow_cfg  # noqa: E402,F401
from scripts.lib import release_control as RC  # noqa: E402
from scripts.lib import release_train_controller as T  # noqa: E402
from scripts.lib import release_train_window as W  # noqa: E402
from scripts.lib import release_train_window_view as WV  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
LEAD = datetime(2026, 10, 21, 16, 35, tzinfo=ET)  # the W-90 request tick for the 18:00 window


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state-root"))
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(tmp_path / "rw"))
    (tmp_path / "rw").mkdir(exist_ok=True)


def _marker(w, rid, name):
    d = w.state_dir / "train_requests" / "injections"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{rid}.json").write_text(
        json.dumps(
            {
                "schema": "TrainInjection@v1",
                "request_id": rid,
                "inject": name,
                "created_at": "2026-10-21T20:30:00Z",
                "created_by": "operator_cli",
            }
        )
    )


def _drill(tmp_path, name):
    w = World(tmp_path, now=LEAD)
    req = request()
    put(w, req)
    _marker(w, req["request_id"], name)
    code, out = T.process_requests(w.state, lambda live: w.controller(live=live), apply=True, now=lambda: w.clock.t)
    r = receipt(w, req["request_id"])
    assert WV.validate_receipt(r) == [], WV.validate_receipt(r)
    assert r["mode"] == "simulate" and r["shadow"] is True
    # simulated: nothing written beyond the spool
    assert not w.state.latch.exists() and w.writer.calls == [] and w.host.calls == []
    assert not (w.state_dir / "capabilities.json").exists() and not (w.state_dir / "claims").exists()
    return w, r, out


def _codes(r):
    return [n["code"] for n in r["needs_action"]]


def test_corrupt_latch_halts_shadow_like_live(tmp_path):
    w, r, _ = _drill(tmp_path, "corrupt-latch")
    assert r["state"] == "REFUSED" and r["refusal"]["code"] == "STOP_UNREADABLE"
    assert r["injected_failures"] == [{"name": "corrupt-latch", "phase": "preconditions", "behaved": "AS_SPECIFIED"}]
    assert _codes(r)[0] == "WOULD_HALT" and "REFUSED_STOP_UNREADABLE" in r["needs_action"][0]["text"]


def test_stop_midrun_halts_shadow_at_the_next_boundary(tmp_path):
    w, r, _ = _drill(tmp_path, "stop-midrun")
    assert r["state"] == "COMPLETED" and r["outcome"] == "STOPPED"
    assert r["injected_failures"] == [{"name": "stop-midrun", "phase": "select", "behaved": "AS_SPECIFIED"}]
    assert "WOULD_HALT" in _codes(r) and "simulate" not in str(json.loads(w.ctl.path.read_text()).get("mode"))
    assert RC.ReleaseControl(w.state_dir).view().mode == RC.RUNNING  # control file untouched


def test_red_check_fails_pre_merge(tmp_path):
    w, r, _ = _drill(tmp_path, "red-check")
    assert r["state"] == "COMPLETED" and r["outcome"] == "FAILED_PRE_MERGE"
    assert r["injected_failures"] == [{"name": "red-check", "phase": "qualify", "behaved": "AS_SPECIFIED"}]


def test_conflict_ejects_the_pr(tmp_path):
    w, r, _ = _drill(tmp_path, "conflict")
    assert r["injected_failures"] == [{"name": "conflict", "phase": "integrate", "behaved": "AS_SPECIFIED"}]
    assert r["state"] == "COMPLETED" and r["outcome"] == "NO_OP"  # #12 rides on; shadow never releases


def test_crash_is_a_failed_controller_with_reconcile_noted(tmp_path):
    w, r, out = _drill(tmp_path, "crash")
    assert r["state"] == "FAILED" and r["refusal"]["code"] == "CONTROLLER_FAILED"
    assert "INJECTED_CRASH" in r["refusal"]["detail"] and r["outcome"] is None
    assert r["injected_failures"] == [{"name": "crash", "phase": "select", "behaved": "AS_SPECIFIED"}]
    assert "reconcile" in r["needs_action"][0]["text"]


def test_an_injection_that_is_not_reached_says_so(tmp_path):
    w = World(tmp_path, now=LEAD)
    c = w.controller(
        live=False,
        queue=__import__("tests.test_release_train_controller_20261021", fromlist=["StaticQueue"]).StaticQueue([]),
    )
    c.set_injection("red-check")
    code, rec = c.run(LEAD)
    assert rec["reason"] == "NOTHING_ELIGIBLE"
    assert rec["injected_failures"] == [{"name": "red-check", "phase": "not_reached", "behaved": "NOT_REACHED"}]


def test_a_real_set_latch_halts_shadow(tmp_path):
    w = World(tmp_path, now=LEAD)
    w.state.write(w.state.latch, {"latched_at": "x"})
    req = request()
    put(w, req)
    T.process_requests(w.state, lambda live: w.controller(live=live), apply=True, now=lambda: w.clock.t)
    r = receipt(w, req["request_id"])
    assert r["state"] == "REFUSED" and r["refusal"]["code"] == "STOP_SET" and _codes(r)[0] == "WOULD_HALT"
    assert r["members"] == [] and "push_train_ref" not in r["simulated_effects"]  # it never reached qualify


def test_a_real_corrupt_latch_halts_shadow(tmp_path):
    w = World(tmp_path, now=LEAD)
    w.state.latch.write_text("{corrupt")
    code, rec = w.controller(live=False).run(LEAD)
    assert rec["reason"] == "REFUSED_STOP_UNREADABLE" and rec["would_halt"]["at"] == "preconditions"
    assert w.state.latch.read_text() == "{corrupt"  # never repaired, never removed


def test_stop_mode_without_a_latch_halts_shadow_like_live(tmp_path):
    w = World(tmp_path, now=LEAD)
    w.ctl.request_stop(HOST_ACTOR, "drill")
    os.rename(w.state.latch, w.state_dir / "STOP.json.archived-test")  # leave only the control STOP mode
    code, rec = w.controller(live=False).run(LEAD)
    # live refuses REFUSED_STOPPED at the preconditions; shadow now does the same (simulated)
    assert rec["reason"] == "REFUSED_STOPPED" and rec["refused"] and rec["would_halt"]["at"] == "preconditions"
    assert T.refusal_code(rec["reason"]) == "STOP_SET"


def test_unarmed_shadow_still_runs_on_and_records_would_refuse(tmp_path):
    w = World(tmp_path, now=LEAD, arm=False)
    code, rec = w.controller(live=False).run(LEAD)
    assert rec["would_halt"] is None and any("CONTROL_UNARMED" in x for x in rec["would_refuse"])
    assert rec["outcome"] == "DRY_RUN_COMPLETE"


def test_live_refuses_every_injection(tmp_path):
    w = World(tmp_path)
    c = w.controller(live=True)
    with pytest.raises(ValueError, match="shadow"):
        c.set_injection("crash")
    with pytest.raises(ValueError):
        w.controller(live=False).set_injection("nope")
    args = SimpleNamespace(live=True, inject="crash", cmd="train-run")
    assert T.cli(args) == T.EXIT_REFUSED


def test_claimer_refuses_a_live_request_with_a_marker(tmp_path):
    w = World(tmp_path)
    req = request(shadow=False, shadow_reason=None)
    put(w, req)
    _marker(w, req["request_id"], "crash")
    T.process_requests(
        w.state, lambda live: w.controller(live=live), apply=True, now=lambda: w.clock.t, live_status="ACTIVE"
    )
    r = receipt(w, req["request_id"])
    assert (
        r["state"] == "REFUSED"
        and r["refusal"]["code"] == "INVALID_REQUEST"
        and "shadow-only" in r["refusal"]["detail"]
    )
    assert w.writer.calls == [] and w.host.calls == []


def test_claimer_refuses_a_bad_marker(tmp_path):
    w = World(tmp_path, now=LEAD)
    req = request()
    put(w, req)
    d = w.state_dir / "train_requests" / "injections"
    d.mkdir(parents=True)
    (d / f"{req['request_id']}.json").write_text("{bad")
    T.process_requests(w.state, lambda live: w.controller(live=live), apply=True, now=lambda: w.clock.t)
    assert receipt(w, req["request_id"])["refusal"]["code"] == "INVALID_REQUEST"


def test_request_writer_inject_writes_the_marker_first_for_shadow(tmp_path, monkeypatch, cfg):
    rc = _run(tmp_path, monkeypatch, ["--append", "--shadow-only", "--inject", "crash"], cfg_override=shadow_cfg(cfg))
    assert rc == 0
    m = json.loads((tmp_path / "rw/train_requests/injections/rtw-20261021-1800-win.json").read_text())
    assert m["schema"] == "TrainInjection@v1" and m["inject"] == "crash"
    assert (tmp_path / "rw/train_requests/pending/rtw-20261021-1800-win.json").exists()
    assert oct(os.stat(tmp_path / "rw/train_requests/injections/rtw-20261021-1800-win.json").st_mode & 0o777) == "0o600"


def test_request_writer_refuses_inject_for_a_live_request(tmp_path, monkeypatch, cfg):
    from tests.test_release_train_n8n_20261021 import deleg  # noqa: F401

    rc = _run(
        tmp_path,
        monkeypatch,
        ["--append", "--inject", "crash"],
        cfg_override=cfg,
        pol=policy(armed=True, enabled=("1800",)),
        code="AUTHORIZED",
    )
    assert rc == 2
    assert not (tmp_path / "rw/train_requests").exists() or not any((tmp_path / "rw/train_requests").rglob("*.json"))


def test_write_injection_refuses_live_and_unknown():
    with pytest.raises(W.ContractError):
        W.write_injection({"request_id": "rtw-20261021-1800-win", "shadow": False}, "crash")
    with pytest.raises(W.ContractError):
        W.write_injection({"request_id": "rtw-20261021-1800-win", "shadow": True}, "nope")
    assert W.INJECTIONS == T.INJECTIONS


def test_packet_finding_5_is_marked_fixed():
    text = (ROOT / "docs/ops/packets/release-train-arming-20261021/README.md").read_text(encoding="utf-8")
    seg = text[text.index("5. **The `injected_failures` receipt field is always `[]`.**") :]
    assert "**Status: FIXED**" in seg[:1600]


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_train_injected_failures_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_INJECTED_FAILURES_20261021"
    assert "tests/test_release_train_injected_failures_20261021.py" in doc["files"]
