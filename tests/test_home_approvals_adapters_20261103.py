#!/usr/bin/env python3
"""Read-only adapters for the Home v008 action types.

Each test uses an injected runner or a fake /proc tree, so nothing here touches the network, a live process, the
scheduler or a store. The property under test is always the same: a fact that moved refuses the click in plain English,
and an adapter with no reviewed execute wiring cannot act.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import home_approvals as ha  # noqa: E402
from lib import home_approvals_adapters as ad  # noqa: E402

HEAD = "5c15ddb039e944b9c946d769265aea347943b7b8"
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)


def _record(**facts):
    base = {"pr": 2504, "head_sha": HEAD}
    base.update(facts)
    return {"id": "apr-test", "type": "merge_pr", "facts": base}


def _runner(payload, code=0, err=""):
    def run(argv):
        return code, json.dumps(payload) if payload is not None else "", err
    return run


def test_merge_pr_passes_when_the_head_is_the_reviewed_head():
    ok, plain = ad.check_merge_pr(_record(), run=_runner({"state": "OPEN", "headRefOid": HEAD}))
    assert ok and plain == ""


def test_merge_pr_refuses_when_the_head_moved_and_says_so():
    ok, plain = ad.check_merge_pr(_record(), run=_runner({"state": "OPEN", "headRefOid": "f" * 40}))
    assert not ok and "head moved" in plain


def test_merge_pr_refuses_when_the_pr_is_closed():
    ok, plain = ad.check_merge_pr(_record(), run=_runner({"state": "MERGED", "headRefOid": HEAD}))
    assert not ok and "nothing to merge" in plain


def test_a_gh_failure_is_fail_closed_with_a_plain_reason():
    ok, plain = ad.check_merge_pr(_record(), run=_runner(None, code=1, err="HTTP 502"))
    assert not ok and "HTTP 502" in plain


def test_rerun_ci_binds_to_the_run_head():
    record = {"id": "x", "type": "rerun_ci", "facts": {"run_id": 5, "head_sha": HEAD}}
    assert ad.check_rerun_ci(record, run=_runner({"headSha": HEAD, "status": "completed"}))[0]
    ok, plain = ad.check_rerun_ci(record, run=_runner({"headSha": "a" * 40, "status": "completed"}))
    assert not ok and "no longer on the head" in plain


def test_stop_job_requires_the_same_pid_start_time_and_command(tmp_path):
    proc = tmp_path / "proc"
    pid_dir = proc / "4242"
    pid_dir.mkdir(parents=True)
    head = "4242 (some worker) S "
    fields = ["0"] * 18 + ["98765"] + ["0"] * 20          # tail[19] is starttime (field 22 overall)
    (pid_dir / "stat").write_text(head + " ".join(fields) + "\n")
    cmd = b"python3\x00worker.py\x00"
    (pid_dir / "cmdline").write_bytes(cmd)

    record = {"id": "x", "type": "stop_job", "facts": {
        "pid": 4242, "start_time_epoch": 98765, "cmd_sha256": hashlib.sha256(cmd).hexdigest()}}
    assert ad.check_stop_job(record, proc_root=proc) == (True, "")

    restarted = {"facts": dict(record["facts"], start_time_epoch=1)}
    ok, plain = ad.check_stop_job(restarted, proc_root=proc)
    assert not ok and "restarted" in plain

    different = {"facts": dict(record["facts"], cmd_sha256="b" * 64)}
    ok, plain = ad.check_stop_job(different, proc_root=proc)
    assert not ok and "different command" in plain

    gone = {"facts": dict(record["facts"], pid=9999)}
    ok, plain = ad.check_stop_job(gone, proc_root=proc)
    assert not ok and "no longer running" in plain


def test_install_schedule_refuses_when_the_unit_already_exists(tmp_path):
    record = {"facts": {"lane_id": "tradeai-demo", "schedule_expression": "* * * * *",
                        "file_sha256": "c" * 64}}
    assert ad.check_install_schedule(record, unit_root=tmp_path) == (True, "")
    (tmp_path / "tradeai-demo.service").write_text("[Unit]\n")
    ok, plain = ad.check_install_schedule(record, unit_root=tmp_path)
    assert not ok and "already exists" in plain


def test_restore_refuses_unless_the_packet_is_present_exactly_once(tmp_path):
    payload = b"packet-bytes"
    sha = hashlib.sha256(payload).hexdigest()
    record = {"facts": {"packet_sha256": sha}}
    ok, plain = ad.check_restore_store(record, packet_root=tmp_path)
    assert not ok and "not present exactly once" in plain
    (tmp_path / "a.packet").write_bytes(payload)
    assert ad.check_restore_store(record, packet_root=tmp_path) == (True, "")
    (tmp_path / "b.packet").write_bytes(payload)
    ok, plain = ad.check_restore_store(record, packet_root=tmp_path)
    assert not ok and "exactly once" in plain


def test_grant_refuses_when_the_grant_already_exists(tmp_path):
    record = {"facts": {"grant_id": "43756a84", "tier": "A", "uses": 1, "expires_at": "2026-11-04T00:00:00Z",
                        "reason": "r"}}
    assert ad.check_grant(record, grants_root=tmp_path) == (True, "")
    (tmp_path / "43756a84.json").write_text("{}")
    ok, plain = ad.check_grant(record, grants_root=tmp_path)
    assert not ok and "already exists" in plain


def test_an_adapter_without_wiring_can_check_but_never_act(tmp_path):
    store = ha.Store(tmp_path / "state")
    record = ha.create(store, {
        "type": "merge_pr", "title": "t", "why": "w", "rule": "r", "what_happens": "x", "risk": "n",
        "undo": "u", "facts": {"pr": 2504, "head_sha": HEAD},
    }, requester={"session": "cc-deepseek-5"}, now=NOW)
    executor = ad.make_executor("merge_pr", run=_runner({"state": "OPEN", "headRefOid": HEAD}))
    ctx = ha.server_context(principal="operator", session="op", csrf_ok=True, listener="serve_proxy")
    result = ha.decide(store, record["id"], ctx=ctx, actor="operator", decision="approve",
                       now=NOW,
                       executor=executor)
    assert result["state"] == "failed"
    attempted = result["result"]["attempted"]
    assert attempted["step_reached"] == "execute_refused_no_wiring"
    assert "no reviewed wiring" in result["result"]["plain"]
