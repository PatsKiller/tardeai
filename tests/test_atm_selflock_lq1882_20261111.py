"""ANCHOR: ATM_SELFLOCK_LQ1882_20261111 — the ATM cycle must evaluate under the cron wrapper, and its grade must
come from evaluation activity, not from the log file's timestamp.

Two defects, both measured on the live host 2026-11-11 (P0 SEV-1, LQ-20261107-1882):

1. Self-lock. crontab line 239 runs ``safe_flock.sh /tmp/tradeai_atm.lock ... atm_auto_approver.py``. The wrapper
   takes the flock and passes its LOCKED descriptor to the child; the script then opened the SAME path on a FRESH
   descriptor and took ``LOCK_EX | LOCK_NB`` — which can never win against the lock the ancestor already holds.
   ``logs/atm.log`` holds 770 ``ATM cycle skipped`` lines (first 2026-10-26 04:00, last 2026-11-11 09:30) while
   ``atm_state.last_evaluated_at`` sat at ``2026-10-23 12:01``. Every cycle exited 0.
2. False green. The jobs page graded the lane GOOD because ``logs/atm.log``'s mtime moved: ``run_quality`` saw a
   "succeeded" wrapper-journal run, a file written during it, no item count, and returned GOOD. A job whose only
   output is "I skipped" is not good — at best it is not live, and a state table that never advances is FAILED.

The lock is proven with real processes: ``safe_flock.sh`` from this repo, a real flock, and the real script. The
grader is proven with synthetic lanes, synthetic logs and receipts — the repo is PUBLIC and no production state
directory, journal or database is read here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import run_quality as Q

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 11, 14, 32, 0, tzinfo=timezone.utc)
START = NOW - timedelta(seconds=40)
FINISH = NOW - timedelta(seconds=5)
OLD_STATE = NOW - timedelta(days=19)

LANE = {
    "lane_id": "atm-auto-approver",
    "state": "ACTIVE",
    "scheduler": {"kind": "cron", "expression": "*/15 4-19 * * 1-5", "match": "scripts/atm_auto_approver.py"},
    "output_signal": {"kind": "file_mtime", "path": "logs/atm.log", "evidence": "CRON_LOG_REDIRECT",
                      "skip_line_vocabulary": ["ATM cycle skipped", "another instance holds"]},
    "progress_signal": {"kind": "db_heartbeat", "table": "atm_state", "column": "last_evaluated_at",
                        "decision_table": "atm_decision_log", "decision_column": "decided_at",
                        "receipt_fields": ["evaluated", "proposals_seen", "decisions_written"]},
}
RUN = {"mode": "live", "result": "succeeded", "started_at": START.isoformat(), "finished_at": FINISH.isoformat(),
       "duration_s": 35.0, "run_id": None, "exit_code": 0, "reason": None, "source": "cron wrapper journal"}
ROW = {"lane_id": "atm-auto-approver", "state": "ACTIVE", "status": "ok", "runs": [RUN],
       "last_run": RUN, "history_gap": None}


def _z(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _log_ts(dt):
    """A logging ``%(asctime)s`` stamp (LOCAL time) for ``dt`` — the format logs/atm.log carries."""
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]


def receipt(**extra):
    doc = {"schema": "LaneRunReceipt@v2", "lane_id": "atm-auto-approver", "mode": "live", "status": "ok",
           "ok": True, "exit": 0, "started_at": _z(START), "finished_at": _z(FINISH),
           "summary": {"evaluated": True, "proposals_seen": 2, "decisions_written": 2,
                       "state_before": _z(OLD_STATE), "state_after": _z(FINISH), "state_advanced": True}}
    doc.update(extra)
    return doc


def _evidence(tmp_path, *, doc=None, output_at=FINISH, progress=None, log_lines=()):
    log = tmp_path / "logs" / "atm.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(log_lines) + ("\n" if log_lines else ""))
    if output_at is not None:
        stamp = output_at.timestamp()
        os.utime(log, (stamp, stamp))
    return {"receipt": doc, "receipt_path": "data/runtime/atm-auto-approver_last.json", "output_at": output_at,
            "ledger": [], "history": [], "contract": None, "freshness": [], "freshness_known": True,
            "plausibility": [], "plausibility_known": True, "root": str(tmp_path), "progress": progress}


def _progress(*, state_at, decisions, known=True, detail=None):
    return {"known": known, "state_at": _z(state_at) if state_at else None, "decisions": decisions,
            "label": "atm_state.last_evaluated_at",
            "detail": detail or f"atm_state.last_evaluated_at = {_z(state_at) if state_at else 'NULL'}"}


# ── the contract the registry must carry ────────────────────────────────────────────────────────────────────────

def test_lane_registry_declares_skip_vocabulary_and_progress_signal():
    reg = json.loads((REPO / "config/lane_registry.json").read_text())
    lane = next(l for l in reg["lanes"] if l.get("lane_id") == "atm-auto-approver")
    assert "ATM cycle skipped" in lane["output_signal"]["skip_line_vocabulary"]
    ps = lane["progress_signal"]
    assert (ps["kind"], ps["table"], ps["column"]) == ("db_heartbeat", "atm_state", "last_evaluated_at")
    assert (ps["decision_table"], ps["decision_column"]) == ("atm_decision_log", "decided_at")
    assert {"evaluated", "proposals_seen", "decisions_written"} <= set(ps["receipt_fields"])


# ── grader: a skip-only log is FAILED, never GOOD (defect 2) ────────────────────────────────────────────────────

def test_skip_only_log_grades_failed_not_good(tmp_path):
    """The exact production shape: a succeeded wrapper run, a log written during it, no receipt, no item count.

    Before LQ-1882 this returned GOOD ("Ran live 0 min ago, wrote its output, no item count reported").
    """
    ev = _evidence(tmp_path, doc=None, log_lines=[
        f"{_log_ts(START + timedelta(seconds=2))} [atm] ATM cycle skipped — another instance holds /tmp/tradeai_atm.lock"])
    ev["progress"] = lambda since: _progress(state_at=OLD_STATE, decisions=0)
    g = Q.grade(ROW, LANE, ev, now=NOW)
    assert g["grade"] == "FAILED", g
    assert g["sub"] == "skip_only"
    assert "only a skip" in g["headline"]
    assert g["checks"]["ran_live"]["result"] == "fail"


def test_old_undated_lines_in_the_tail_are_not_read_as_this_runs_output(tmp_path):
    """Only lines from the first in-window stamp onward belong to the run.

    Measured on the live log: a 512 KB tail of an older traceback (continuation lines carry no timestamp) sat
    before the window and made "every appended line is a skip" false — the run graded on the log alone again.
    """
    log = tmp_path / "logs" / "atm.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    old = _log_ts(START - timedelta(hours=3))
    lines = [f"{old} [atm] Traceback (most recent call last):",
             '  File "/opt/x/scripts/atm_auto_approver.py", line 1, in <module>',
             "RuntimeError: boom",
             f"{_log_ts(START + timedelta(seconds=2))} [atm] ATM cycle skipped — another instance holds /tmp/tradeai_atm.lock"]
    log.write_text("\n".join(lines) + "\n")
    assert Q.appended_lines(log, START) == [lines[-1]]
    ev = _evidence(tmp_path, doc=None, log_lines=lines)
    ev["progress"] = lambda since: _progress(state_at=OLD_STATE, decisions=0)
    g = Q.grade(ROW, LANE, ev, now=NOW)
    assert (g["grade"], g["sub"]) == ("FAILED", "skip_only"), g


def test_a_log_with_a_real_evaluation_is_not_treated_as_a_skip(tmp_path):
    ev = _evidence(tmp_path, doc=receipt(), log_lines=[
        f"{_log_ts(START + timedelta(seconds=2))} [atm] ATM cycle skipped — another instance holds /tmp/x.lock",
        f"{_log_ts(START + timedelta(seconds=9))} [atm] ATM cycle: 2 pending proposals (mode=dry_run)"])
    ev["progress"] = lambda since: _progress(state_at=FINISH, decisions=2)
    g = Q.grade(ROW, LANE, ev, now=NOW)
    assert g["grade"] == "GOOD", g


# ── grader: GOOD requires the state table to advance AND a same-run receipt that evaluated ──────────────────────

def test_good_only_when_state_advanced_and_decisions_written(tmp_path):
    ev = _evidence(tmp_path, doc=receipt(produced_count=2, attempted_count=2),
                   log_lines=[f"{_log_ts(START + timedelta(seconds=9))} [atm] ATM cycle: 2 pending proposals"])
    ev["progress"] = lambda since: _progress(state_at=FINISH, decisions=2)
    g = Q.grade(ROW, LANE, ev, now=NOW)
    assert g["grade"] == "GOOD", g
    assert g["count"]["value"] == 2
    assert g["checks"]["progress"]["result"] == "pass"


def test_state_table_not_advanced_grades_failed(tmp_path):
    """The live shape of defect 1: the log grows every 15 min, atm_state has not moved since 2026-10-23."""
    ev = _evidence(tmp_path, doc=None, log_lines=[
        f"{_log_ts(START + timedelta(seconds=2))} [atm] ATM cycle: 2 pending proposals (mode=dry_run)"])
    ev["progress"] = lambda since: _progress(state_at=OLD_STATE, decisions=0)
    g = Q.grade(ROW, LANE, ev, now=NOW)
    assert g["grade"] == "FAILED", g
    assert g["sub"] == "progress_stale"
    assert "has not advanced" in g["headline"]


def test_unreadable_progress_is_unproven_never_good(tmp_path):
    ev = _evidence(tmp_path, doc=receipt(produced_count=2), log_lines=[
        f"{_log_ts(START + timedelta(seconds=2))} [atm] ATM cycle: 2 pending proposals"])
    ev["progress"] = lambda since: {"known": False, "detail": "OperationalError: connection refused"}
    g = Q.grade(ROW, LANE, ev, now=NOW)
    assert g["grade"] == "UNPROVEN", g
    assert g["sub"] == "progress_unverifiable"


def test_state_advanced_without_a_same_run_receipt_is_unproven(tmp_path):
    ev = _evidence(tmp_path, doc=None, log_lines=[
        f"{_log_ts(START + timedelta(seconds=2))} [atm] ATM cycle: 2 pending proposals"])
    ev["progress"] = lambda since: _progress(state_at=FINISH, decisions=2)
    g = Q.grade(ROW, LANE, ev, now=NOW)
    assert g["grade"] == "UNPROVEN", g
    assert g["sub"] == "no_run_receipt"


def test_receipt_that_did_not_evaluate_is_degraded(tmp_path):
    # What build_receipt writes for a stopped cycle: status degraded, outcome degraded, reason in plain words.
    doc = receipt(produced_count=0, attempted_count=0, status="degraded", outcome="degraded",
                  outcome_reason="atm_mode_paused",
                  summary={"evaluated": False, "proposals_seen": 0, "decisions_written": 0,
                           "outcome": "paused"})
    ev = _evidence(tmp_path, doc=doc, log_lines=[
        f"{_log_ts(START + timedelta(seconds=2))} [atm] ATM mode=paused until None"])
    ev["progress"] = lambda since: _progress(state_at=FINISH, decisions=0)
    g = Q.grade(ROW, LANE, ev, now=NOW)
    assert g["grade"] == "DEGRADED", g


def test_evaluated_queue_with_nothing_due_is_idle_not_good(tmp_path):
    doc = receipt(produced_count=0, attempted_count=0, empty_reason="nothing_due",
                  summary={"evaluated": True, "proposals_seen": 0, "decisions_written": 0})
    ev = _evidence(tmp_path, doc=doc, log_lines=[
        f"{_log_ts(START + timedelta(seconds=2))} [atm] ATM cycle: 0 pending entry proposals (mode=dry_run)"])
    ev["progress"] = lambda since: _progress(state_at=FINISH, decisions=0)
    g = Q.grade(ROW, LANE, ev, now=NOW)
    assert g["grade"] == "IDLE", g


def test_progress_signal_absent_leaves_other_lanes_unchanged(tmp_path):
    lane = dict(LANE, lane_id="synthetic-no-progress", progress_signal=None)
    row = dict(ROW, lane_id="synthetic-no-progress")
    ev = _evidence(tmp_path, doc=receipt(produced_count=2), log_lines=[
        f"{_log_ts(START + timedelta(seconds=2))} [atm] unrelated"])
    g = Q.grade(row, lane, ev, now=NOW)
    assert g["grade"] == "GOOD", g
    assert "progress" not in g["checks"]


# ── lock contract: real processes, real flock, the real script ──────────────────────────────────────────────────

PROBE = r'''
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atm_auto_approver as A
A.ATM_CYCLE_LOCK = os.environ["PROBE_OUTER"]
A.ATM_INNER_LOCK = os.environ["PROBE_INNER"]


def fake_body(started=None, markers=None):
    # The DB half is not the subject here: this stands in for "the cycle body was entered and finished".
    markers.update(evaluated=True, proposals_seen=0, decisions_written=0,
                   state_before="2026-11-11T09:00:00-05:00", state_after="2026-11-11T09:32:00-05:00",
                   state_advanced=True, outcome="evaluated_no_proposals")
    return markers


A._run_cycle_locked = fake_body
res = A.run_cycle()
print("PROBE_RESULT " + json.dumps({"outcome": res.get("outcome"), "holder": res.get("lock_holder"),
                                    "blocker": res.get("blocker")}))
'''


def _project(tmp_path):
    root = tmp_path / "proj"
    (root / "scripts/lib").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "data/runtime").mkdir(parents=True)
    shutil.copy(REPO / "scripts/atm_auto_approver.py", root / "scripts/atm_auto_approver.py")
    shutil.copy(REPO / "scripts/lib/__init__.py", root / "scripts/lib/__init__.py")
    # Module-level imports the lock probe never reaches: the cycle body is stubbed. Synthetic, no connection.
    (root / "scripts/db_adapter.py").write_text(
        "def get_connection():\n    return None\n\n\ndef ensure_conn():\n    return None\n")
    (root / "scripts/lib/paper_account_policy.py").write_text(FAKE_POLICY)
    (root / "scripts/atm_probe.py").write_text(PROBE)
    return root


def _run(project, argv, extra_env=None):
    env = dict(os.environ, PROBE_OUTER=str(project / "outer.lock"), PROBE_INNER=str(project / "inner.lock"),
               TRADEAI_STATE_ROOT=str(project), TMPDIR=os.environ.get("TMPDIR", "/tmp"))
    env.update(extra_env or {})
    return subprocess.run(argv, cwd=str(project), env=env, capture_output=True, text=True, timeout=120)


def _probe_result(out):
    line = next((l for l in out.splitlines() if l.startswith("PROBE_RESULT ")), None)
    assert line, f"probe printed no result:\n{out}"
    return json.loads(line[len("PROBE_RESULT "):])


def test_cron_style_wrapper_run_adopts_the_wrapper_lock_and_evaluates(tmp_path):
    """THE regression: safe_flock holds the lock; the script must run, not skip. Before the fix this logged
    "ATM cycle skipped — another instance holds tradeai_atm.lock" and exited 0."""
    project = _project(tmp_path)
    log = project / "logs/atm.log"
    with log.open("w") as stream:
        proc = subprocess.run(
            ["bash", str(REPO / "scripts/safe_flock.sh"), str(project / "outer.lock"),
             sys.executable, "-I", str(project / "scripts/atm_probe.py")],
            cwd=str(project),
            env=dict(os.environ, TRADEAI_STATE_ROOT=str(project),
                     PROBE_OUTER=str(project / "outer.lock"), PROBE_INNER=str(project / "inner.lock")),
            stdout=stream, stderr=subprocess.STDOUT, timeout=120)
    assert proc.returncode == 0, log.read_text()
    text = log.read_text()
    assert "ATM cycle skipped" not in text
    result = _probe_result(text)
    assert result == {"outcome": "evaluated_no_proposals", "holder": "wrapper", "blocker": None}


def test_the_collision_probe_never_truncates_the_wrappers_lock_file(tmp_path):
    """A direct run asks "is the cron lock held?" by opening that path. Opening it "w" would empty the wrapper's
    lock file; the probe opens it for append and leaves whatever is there alone."""
    project = _project(tmp_path)
    lock = project / "outer.lock"
    lock.write_text("sentinel held by nothing\n")
    proc = _run(project, [sys.executable, "-I", "-c",
                          "import sys; sys.path.insert(0, 'scripts'); import atm_auto_approver as A; "
                          f"print('HELD', A._another_process_holds({str(lock)!r}))"])
    assert proc.returncode == 0, proc.stderr
    assert "HELD False" in proc.stdout, proc.stdout
    assert lock.read_text() == "sentinel held by nothing\n"


def test_without_the_wrapper_the_script_takes_its_own_distinct_lock(tmp_path):
    project = _project(tmp_path)
    proc = _run(project, [sys.executable, "-I", str(project / "scripts/atm_probe.py")])
    assert proc.returncode == 0, proc.stderr
    assert _probe_result(proc.stderr + proc.stdout)["holder"] == "inner"
    # The two locks are different files, and the inner path never collides with the wrapper's.
    assert (project / "inner.lock").exists()


def test_a_direct_run_skips_while_a_wrapper_run_holds_the_outer_lock(tmp_path):
    import fcntl

    project = _project(tmp_path)
    with (project / "outer.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = _run(project, [sys.executable, "-I", str(project / "scripts/atm_probe.py")])
    assert proc.returncode == 0, proc.stderr
    result = _probe_result(proc.stderr + proc.stdout)
    assert result["outcome"] == "skipped" and result["blocker"] == str(project / "outer.lock")


def test_second_direct_run_skips_on_the_inner_lock(tmp_path):
    import fcntl

    project = _project(tmp_path)
    with (project / "inner.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = _run(project, [sys.executable, "-I", str(project / "scripts/atm_probe.py")])
    assert proc.returncode == 0, proc.stderr
    result = _probe_result(proc.stderr + proc.stdout)
    assert result["outcome"] == "skipped" and result["blocker"] == str(project / "inner.lock")


def test_the_old_lock_contract_self_locks_under_the_wrapper(tmp_path):
    """Fail-before, kept as a test: the pre-fix body (fresh descriptor on the wrapper's own path) must lose its
    flock. Proven here without git history by replaying exactly that call under safe_flock."""
    project = _project(tmp_path)
    old_call = (
        "import fcntl, os, sys\n"
        "path = sys.argv[1]\n"
        "fd = open(path, 'w')\n"
        "try:\n"
        "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "    print('OLD_ACQUIRED')\n"
        "except OSError as e:\n"
        "    print('OLD_SKIPPED', type(e).__name__)\n"
    )
    probe = project / "scripts/old_lock_probe.py"
    probe.write_text(old_call)
    proc = _run(project, ["bash", str(REPO / "scripts/safe_flock.sh"), str(project / "outer.lock"),
                          sys.executable, "-I", str(probe), str(project / "outer.lock")])
    assert proc.returncode == 0
    assert "OLD_SKIPPED" in proc.stdout, proc.stdout + proc.stderr


# ── staging: the REAL cycle body in an isolated temp PROJECT_ROOT with a synthetic DB ──────────────────────────

FAKE_DB = r'''
"""Synthetic database for the LQ-1882 staging test. No production connection is ever opened."""
import datetime as _dt

STATE = {"mode": "dry_run", "before": _dt.datetime(2026, 11, 11, 14, 0, 0, tzinfo=_dt.timezone.utc),
         "after": None, "decisions": 0}


class _Cursor:
    def __init__(self):
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        low = s.lower()
        self.description = None
        self._rows = []
        if low.startswith("select * from atm_state"):
            self.description = [("id",), ("mode",), ("last_evaluated_at",), ("paused_until",), ("config_hash",),
                                ("last_state_change_at",), ("last_state_change_by",), ("pause_reason",)]
            self._rows = [(1, STATE["mode"], STATE["after"] or STATE["before"], None, "synthetic", None, None, None)]
        elif low.startswith("update atm_state set last_evaluated_at"):
            STATE["after"] = _dt.datetime.now(_dt.timezone.utc)
        elif low.startswith("select last_evaluated_at from atm_state"):
            self._rows = [(STATE["after"],)]
        elif "sum(pnl)" in low:
            self._rows = [(0,)]
        elif "equity_source" in low:
            self._rows = [(None,)]
        elif "from paper_trade_proposals" in low:
            self.description = [("id",), ("symbol",)]
            self._rows = []
        elif "count(*) from atm_decision_log" in low:
            self._rows = [(STATE["decisions"],)]
        elif "count(*)" in low:
            self._rows = [(0,)]
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _Conn:
    closed = 0
    autocommit = False

    def cursor(self, *a, **k):
        return _Cursor()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def get_connection():
    return _Conn()


def ensure_conn():
    return _Conn()
'''

FAKE_ATM_CONFIG = r'''
def load_config():
    return ({"b1_tracking": {"enabled": False}}, "synthetichash")


def get_enabled_accounts():
    return ["synthetic-account"]


def get_effective_limits():
    return {}


def is_bucket2_excluded(*a, **k):
    return False


def is_same_day_skip(*a, **k):
    return False


def get_strategy_filter():
    return None


def get_operating_hours():
    return {"start_et": "00:00", "extended_hours_exit_et": "23:59"}


def get_kill_switch_thresholds():
    return {"per_account": 3.0, "aggregate": 5.0}
'''

FAKE_POLICY = r'''
def all_paper_only(accounts):
    return True


def suppress_paper_alert(key, context=None, symbol=None):
    return True
'''


def _staging_project(tmp_path):
    root = tmp_path / "staging"
    (root / "scripts/lib").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "data/runtime").mkdir(parents=True)
    shutil.copy(REPO / "scripts/atm_auto_approver.py", root / "scripts/atm_auto_approver.py")
    shutil.copy(REPO / "scripts/lib/__init__.py", root / "scripts/lib/__init__.py")
    # The real receipt writer and the helpers it imports: the same code as the checkout, all stdlib inside.
    for name in ("lane_last_receipt.py", "status_consistency.py", "persistent_state_root.py",
                 "atomic_json_store.py"):
        shutil.copy(REPO / "scripts/lib" / name, root / "scripts/lib" / name)
    (root / "scripts/db_adapter.py").write_text(FAKE_DB)
    (root / "scripts/atm_config_manager.py").write_text(FAKE_ATM_CONFIG)
    (root / "scripts/lib/paper_account_policy.py").write_text(FAKE_POLICY)
    return root


def _staging_env(project):
    # Every store the cycle touches resolves under the temp root (TRADEAI_STATE_ROOT); the production state
    # directory is never opened, and the temp root is the only PYTHONPATH the run needs (it needs none).
    return dict(os.environ, TRADEAI_STATE_ROOT=str(project),
                TRADEAI_ATM_CYCLE_LOCK=str(project / "outer.lock"),
                TRADEAI_ATM_INNER_LOCK=str(project / "inner.lock"))


def test_real_cycle_body_evaluates_in_an_isolated_root_and_writes_a_receipt(tmp_path):
    project = _staging_project(tmp_path)
    outer, inner = project / "outer.lock", project / "inner.lock"
    log = project / "logs/atm.log"
    with log.open("w") as stream:
        proc = subprocess.run(
            ["bash", str(REPO / "scripts/safe_flock.sh"), str(outer),
             sys.executable, "-I", str(project / "scripts/atm_auto_approver.py")],
            cwd=str(project), env=_staging_env(project), stdout=stream, stderr=subprocess.STDOUT, timeout=180)
    text = log.read_text()
    assert proc.returncode == 0, text
    assert "ATM cycle skipped" not in text, text
    assert "0 pending entry proposals" in text, text

    receipt_path = project / "data/runtime/atm-auto-approver_last.json"
    assert receipt_path.exists(), f"no receipt written; log:\n{text}"
    doc = json.loads(receipt_path.read_text())
    summary = doc["summary"]
    assert doc["lane_id"] == "atm-auto-approver" and doc["status"] == "ok"
    assert summary["evaluated"] is True
    assert summary["state_advanced"] is True
    assert summary["proposals_seen"] == 0 and summary["decisions_written"] == 0
    assert summary["lock_holder"] == "wrapper"
    assert summary["atm_mode"] == "dry_run"
    assert doc["outcome"] == "empty" and doc["outcome_reason"] == "nothing_due"

    # And that receipt, read by the real grader, is IDLE — never GOOD, never FAILED.
    lane = dict(LANE)
    evidence = {"receipt": doc, "receipt_path": "data/runtime/atm-auto-approver_last.json",
                "output_at": datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc), "ledger": [],
                "history": [], "contract": None, "freshness": [], "freshness_known": True, "plausibility": [],
                "plausibility_known": True, "root": str(project), "progress": None}
    row = {"lane_id": "atm-auto-approver", "state": "ACTIVE", "status": "ok",
           "runs": [{"mode": "live", "result": "succeeded", "started_at": summary["started_at"],
                     "finished_at": summary["finished_at"], "duration_s": 0.2, "exit_code": 0,
                     "source": "cron wrapper journal"}],
           "last_run": None, "history_gap": None}
    row["last_run"] = row["runs"][0]
    grade = Q.grade(row, lane, evidence, now=datetime.now(timezone.utc))
    assert grade["grade"] == "IDLE", grade


def test_receipt_never_lands_in_the_production_state_root(tmp_path, monkeypatch):
    """The staging run must be inert: it resolves data/runtime under the temp root only."""
    project = _staging_project(tmp_path)
    proc = subprocess.run([sys.executable, "-I", str(project / "scripts/atm_auto_approver.py")],
                          cwd=str(project), env=_staging_env(project), capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(p.name for p in (project / "data/runtime").iterdir()) == ["atm-auto-approver_last.json"]


# ── LQ-1882 follow-up (lead ruling 2026-11-11 10:46 ET): the immediate trigger is its own lane ──────────────
# proposal_enrichment_loop.py runs `safe_flock.sh /tmp/tradeai_atm.lock <PY> atm_auto_approver.py` on every
# ENTRY_ZONE_VALID proposal. Sharing the lock is deliberate (one evaluation at a time); sharing the lane's
# IDENTITY was the defect: those runs landed on component tradeai_atm and overwrote
# data/runtime/atm-auto-approver_last.json, so the scheduled */15 lane was graded on a run it did not schedule
# (10:30 slot: EMPTY / not_written, because the last run wrote logs/atm_immediate.log).

IMMEDIATE = "atm-auto-approver-immediate"


def test_safe_flock_names_component_from_the_caller_when_it_says_so(tmp_path):
    """The wrapper's component is the lock basename by default, and the caller's name when it sets
    TRADEAI_SAFEFLOCK_COMPONENT. Before this, an event-driven caller could not be told apart from the lane whose
    lock it holds."""
    journal = REPO / "logs/safe_flock_events.jsonl"
    start = journal.stat().st_size if journal.exists() else 0
    lock = tmp_path / "atm_shared.lock"

    for extra in ({}, {"TRADEAI_SAFEFLOCK_COMPONENT": IMMEDIATE}):
        proc = subprocess.run(["bash", str(REPO / "scripts/safe_flock.sh"), str(lock), "true"],
                              env=dict(os.environ, **extra), cwd=str(REPO),
                              capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    with journal.open("rb") as f:
        f.seek(start)
        lines = [json.loads(ln) for ln in f.read().decode("utf-8", "replace").splitlines() if ln.strip()]
    started = [e["component"] for e in lines if e.get("event_type") == "started" and e.get("lock_file") == str(lock)]
    assert started == ["atm_shared", IMMEDIATE], started


def test_an_immediate_cycle_writes_its_own_receipt_not_the_scheduled_lanes(tmp_path):
    """The same evaluation, run as the event-driven lane, must leave data/runtime/atm-auto-approver_last.json
    alone. Before this, RECEIPT_LANE was a constant and the trigger overwrote the scheduled lane's receipt."""
    project = _staging_project(tmp_path)
    env = dict(_staging_env(project), TRADEAI_ATM_LANE_ID=IMMEDIATE)
    log = project / "logs/atm.log"
    with log.open("w") as stream:
        proc = subprocess.run(
            ["bash", str(REPO / "scripts/safe_flock.sh"), str(project / "outer.lock"),
             sys.executable, "-I", str(project / "scripts/atm_auto_approver.py")],
            cwd=str(project), env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
    assert proc.returncode == 0, log.read_text()
    receipts = sorted(p.name for p in (project / "data/runtime").iterdir())
    assert receipts == [f"{IMMEDIATE}_last.json"], receipts
    body = json.loads((project / "data/runtime" / f"{IMMEDIATE}_last.json").read_text())
    assert body.get("lane_id") in (IMMEDIATE, None), body


def test_the_registry_keeps_the_two_atm_lanes_apart():
    """Two registry rows, two journal components, two output files — otherwise the split is cosmetic."""
    from scripts.lib import cron_outage_watchdog as W

    reg = json.loads((REPO / "config/lane_registry.json").read_text())
    rows = {r["lane_id"]: r for r in reg["lanes"] if r["lane_id"].startswith("atm-auto-approver")}
    assert set(rows) == {"atm-auto-approver", IMMEDIATE}, sorted(rows)
    assert W.component(rows[IMMEDIATE]) == IMMEDIATE
    assert rows["atm-auto-approver"]["output_signal"]["path"] == "logs/atm.log"
    assert rows[IMMEDIATE]["output_signal"]["path"] == "logs/atm_immediate.log"
    assert rows[IMMEDIATE]["progress_signal"]["table"] == "atm_state"
