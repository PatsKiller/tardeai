"""Release train arming finding 6 (ANCHOR RELEASE_TRAIN_ORPHAN_WATCHDOG_20261021): orphaned-claim recovery.

A claim in ``train_requests/claimed/`` whose receipt is not terminal, older than the configured age (default 2x the
claimer's 3 h maximum run = 360 min) and with no live owner (pid AND /proc start time) is moved to ``orphaned/`` and
one P2 needs-action intent is raised. It is never deleted, never re-run, and never given a receipt by the watchdog:
``train-orphan-resolve`` closes it only after ``train-reconcile`` (refused while any train is non-terminal).

Hermetic: the controller test world under tmp_path; the notifier is a list. No network, DB, systemd or broker.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.test_release_train_controller_20261021 import World, put, receipt, request  # noqa: E402
from scripts.lib import needs_action as NA  # noqa: E402
from scripts.lib import release_train_controller as T  # noqa: E402
from scripts.lib import release_train_window_view as WV  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
LEAD = datetime(2026, 10, 21, 16, 35, tzinfo=ET)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("TRADEAI_RELEASE_TRAIN_ORPHAN_AFTER_MIN", raising=False)


def _orphan_setup(w, *, owner=None, ack_min_ago=400):
    """A request claimed and ACKNOWLEDGED ``ack_min_ago`` minutes ago whose claimer died (no terminal receipt)."""
    req = request()
    spool = T.RequestSpool(w.state_dir)
    spool.claimed.mkdir(parents=True)
    (spool.claimed / f"{req['request_id']}.json").write_text(json.dumps(req))
    ack = T.utc_iso(w.clock.t - ack_min_ago * 60)
    spool.write_receipt(req["request_id"], T._receipt(req, state="ACKNOWLEDGED", mode="simulate", now=w.clock.t,
                                                      acknowledged_at=ack))
    T.RC._atomic_write_json(spool.owners / f"{req['request_id']}.json",
                            {**(owner or {"pid": 999999, "start_ticks": 1, "host": os.uname().nodename}),
                             "claimed_at": ack})
    return req, spool


def _claim(w, **kw):
    sent = []
    code, out = T.process_requests(w.state, lambda live: w.controller(live=live), apply=kw.pop("apply", True),
                                   now=lambda: w.clock.t, notify=lambda m, p: sent.append((p, m)) or {"accepted": True},
                                   **kw)
    return out, sent


def test_default_age_is_twice_the_max_run():
    assert T.ORPHAN_AFTER_MIN_DEFAULT == 2 * T.CLAIM_MAX_RUN_MIN == 360
    unit = (ROOT / "docs/ops/packets/release-train-20261021/tradeai-release-train-claim.service.proposed").read_text()
    assert "TimeoutStartSec=3h" in unit
    assert T.orphan_after_min(None) == 360 and T.orphan_after_min(15) == 15


def test_env_overrides_the_age(monkeypatch):
    monkeypatch.setenv("TRADEAI_RELEASE_TRAIN_ORPHAN_AFTER_MIN", "45")
    assert T.orphan_after_min(None) == 45
    monkeypatch.setenv("TRADEAI_RELEASE_TRAIN_ORPHAN_AFTER_MIN", "junk")
    assert T.orphan_after_min(None) == 360


def test_an_old_dead_claim_is_orphaned_with_one_p2_and_never_rerun(tmp_path):
    w = World(tmp_path, now=LEAD)
    req, spool = _orphan_setup(w)
    out, sent = _claim(w)
    assert [o["result"] for o in out["orphans"]] == ["ORPHANED"]
    assert (spool.orphaned / f"{req['request_id']}.json").exists()
    assert not (spool.claimed / f"{req['request_id']}.json").exists()
    assert not (spool.pending / f"{req['request_id']}.json").exists()           # never re-queued
    assert receipt(w, req["request_id"])["state"] == "ACKNOWLEDGED"             # the watchdog writes no receipt
    assert len(sent) == 1 and sent[0][0] == "P2" and "reconcile" in sent[0][1]
    rows = [json.loads(x) for x in (spool.root / "orphaned.jsonl").read_text().splitlines()]
    assert rows[0]["kind"] == "orphaned" and rows[0]["request_id"] == req["request_id"]
    assert out["requests"] == [] and w.writer.calls == [] and w.host.calls == []
    # a second pass does nothing more
    out2, sent2 = _claim(w)
    assert out2["orphans"] == [] and sent2 == []


def test_a_young_claim_is_left_alone(tmp_path):
    w = World(tmp_path, now=LEAD)
    req, spool = _orphan_setup(w, ack_min_ago=30)
    out, sent = _claim(w)
    assert out["orphans"] == [] and (spool.claimed / f"{req['request_id']}.json").exists() and sent == []


def test_a_claim_with_a_live_owner_is_left_alone(tmp_path):
    w = World(tmp_path, now=LEAD)
    req, spool = _orphan_setup(w, owner=T.claim_owner())          # this very process: pid + start time match
    out, sent = _claim(w)
    assert out["orphans"][0]["result"].startswith("LIVE_OWNER") and sent == []
    assert (spool.claimed / f"{req['request_id']}.json").exists()


def test_a_recycled_pid_is_not_a_live_owner(tmp_path):
    me = T.claim_owner()
    assert T.owner_alive(me)
    assert not T.owner_alive({**me, "start_ticks": me["start_ticks"] + 1})
    assert not T.owner_alive({**me, "host": "another-host"}) and not T.owner_alive(None)


def test_a_terminal_claim_is_never_orphaned(tmp_path):
    w = World(tmp_path, now=LEAD)
    req, spool = _orphan_setup(w)
    spool.write_receipt(req["request_id"], T._receipt(req, state="COMPLETED", mode="simulate", now=w.clock.t,
                                                      acknowledged_at=T.utc_iso(w.clock.t - 60), outcome="NO_OP"))
    out, _ = _claim(w)
    assert out["orphans"] == []


def test_dry_run_only_reports(tmp_path):
    w = World(tmp_path, now=LEAD)
    req, spool = _orphan_setup(w)
    out, sent = _claim(w, apply=False)
    assert out["orphans"][0]["result"].startswith("WOULD_ORPHAN") and sent == []
    assert (spool.claimed / f"{req['request_id']}.json").exists() and not spool.orphaned.exists()


def test_the_claimer_records_its_owner(tmp_path):
    w = World(tmp_path, now=LEAD)
    req = request()
    put(w, req)
    _claim(w)
    owner = T.RequestSpool(w.state_dir).owner(req["request_id"])
    assert owner["pid"] == os.getpid() and owner["start_ticks"] == T.proc_start_ticks(os.getpid())


def test_needs_action_shows_the_orphan_until_resolved(tmp_path):
    w = World(tmp_path, now=LEAD)
    req, spool = _orphan_setup(w)
    _claim(w)
    st = NA.read_release_window_state(w.state_dir)
    items = NA.rule_release_window(st, datetime.now(ET))
    assert [i["severity"] for i in items] == ["P2"] and req["request_id"] in items[0]["title"]
    # resolve: dry run first, then apply
    code, body = T.resolve_orphan(w.state, req["request_id"], "claimer killed in drill; nothing to reconcile",
                                  apply=False, now=lambda: w.clock.t)
    assert body["outcome"] == "WOULD_RESOLVE" and receipt(w, req["request_id"])["state"] == "ACKNOWLEDGED"
    code, body = T.resolve_orphan(w.state, req["request_id"], "claimer killed in drill; nothing to reconcile",
                                  apply=True, now=lambda: w.clock.t)
    assert body["outcome"] == "RESOLVED"
    r = receipt(w, req["request_id"])
    assert r["state"] == "FAILED" and r["refusal"]["code"] == "CONTROLLER_FAILED" and WV.validate_receipt(r) == []
    assert NA.rule_release_window(NA.read_release_window_state(w.state_dir), datetime.now(ET)) == []
    assert (spool.orphaned / f"{req['request_id']}.json").exists()                # kept, never deleted


def test_resolve_is_refused_until_trains_are_reconciled(tmp_path):
    w = World(tmp_path, now=LEAD)
    req, spool = _orphan_setup(w)
    _claim(w)
    d = w.state_dir / "trains" / "rt-20261021-1800-abcdef"
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({"outcome": None}))
    code, body = T.resolve_orphan(w.state, req["request_id"], "a reason that is long", apply=True)
    assert code == T.EXIT_REFUSED and body["outcome"] == "REFUSED_RECONCILE_FIRST"
    assert receipt(w, req["request_id"])["state"] == "ACKNOWLEDGED"


def test_resolve_refuses_an_unknown_request(tmp_path):
    w = World(tmp_path, now=LEAD)
    code, body = T.resolve_orphan(w.state, "rtw-20261021-1800-win", "a reason that is long", apply=True)
    assert code == T.EXIT_REFUSED


def test_packet_finding_6_is_marked_fixed():
    text = (ROOT / "docs/ops/packets/release-train-arming-20261021/README.md").read_text(encoding="utf-8")
    seg = text[text.index("6. **No watchdog for an orphaned claim.**"):]
    assert "**Status: FIXED**" in seg[:1400]


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_train_orphan_watchdog_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_ORPHAN_WATCHDOG_20261021"
    assert "tests/test_release_train_orphan_watchdog_20261021.py" in doc["files"]
