"""The drain/requeue policy actually runs: the 20% trigger, retries on the one queue, one incident per job.

The queue enqueue and the incident writer are injected, so this file uses no DB, no network and no credentials.
Proofs: a 20% window requeues every failed job and reports state; a 19% window changes nothing; an exhausted
job yields exactly one incident and drain_state never says "drained" while it is held.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import llm_queue_drain_policy as dp  # noqa: E402
import run_deep_overnight_llm_queue as runner  # noqa: E402

POLICY = dp.load_policy()
DELAYS = POLICY["drain_requeue"]["retry_delay_seconds"]


class _Recorder:
    def __init__(self):
        self.enqueued = []
        self.incidents = []

    def enqueue(self, plan):
        self.enqueued.append(plan)
        return True

    def record_incident(self, item):
        self.incidents.append(item)


def _job(job_id, attempt, *, status="pending", cause="HTTP 500", requeue_key=None):
    return {
        "job_id": job_id,
        "attempt": attempt,
        "status": status,
        "root_cause": cause,
        "requeue_key": requeue_key,
    }


def _apply(rec, *, total, failed, jobs):
    return runner.apply_drain_requeue(
        total=total,
        failed=failed,
        failed_jobs=jobs,
        enqueue=rec.enqueue,
        record_incident=rec.record_incident,
        policy=POLICY,
    )


# --- 1. the threshold ------------------------------------------------------------------------------------------


def test_a_twenty_percent_window_requeues_every_failed_job_and_reports_state():
    rec = _Recorder()
    jobs = [_job(1, 1), _job(2, 2), _job(3, POLICY["drain_requeue"]["max_attempts"], status="failed")]
    report = _apply(rec, total=15, failed=3, jobs=jobs)  # 3/15 = 20%, inclusive

    assert report["triggered"] is True
    assert [plan["job_id"] for plan in rec.enqueued] == [1, 2], "every retryable failed job is requeued"
    assert [plan["key"] for plan in rec.enqueued] == ["1:1", "2:2"]
    assert [plan["delay_s"] for plan in rec.enqueued] == [DELAYS[0], DELAYS[1]], "delay comes from config"
    assert [item["job_id"] for item in rec.incidents] == [3], "only the exhausted job opens an incident"
    assert report["state"]["status"] != "drained"
    assert report["state"]["queued"] == 2 and report["state"]["failed"] == 1


def test_a_nineteen_percent_window_changes_nothing():
    rec = _Recorder()
    report = _apply(rec, total=100, failed=19, jobs=[_job(i, 1) for i in range(1, 20)])

    assert report["triggered"] is False
    assert report["state"] is None and report["plans"] == []
    assert rec.enqueued == [] and rec.incidents == []


# --- 2. the one queue: idempotent requeue with the configured delay ------------------------------------------


def test_a_job_already_carrying_its_requeue_key_is_not_enqueued_again():
    rec = _Recorder()
    report = _apply(rec, total=1, failed=1, jobs=[_job(7, 1, requeue_key="7:1")])

    assert report["triggered"] is True
    assert rec.enqueued == [], "an already-enqueued job+attempt must be a no-op"
    assert report["requeued"] == 0


class _QueueCursor:
    """Minimal in-memory stand-in for one deep_overnight_llm_queue row (the one queue, no second store)."""

    def __init__(self):
        self.row = {"status": "failed", "attempt_count": 1, "meta": {}}
        self.last_params = None
        self._result = []

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        assert flat.startswith("UPDATE deep_overnight_llm_queue")
        attempt, delay, key, job_id, guard = params
        self.last_params = params
        self._result = []
        if self.row["meta"].get(runner.REQUEUE_KEY_META) == key:
            return  # the WHERE's no-op branch
        self.row.update(status="pending", attempt_count=attempt)
        self.row["meta"][runner.REQUEUE_KEY_META] = key
        self._result = [(job_id,)]

    def fetchone(self):
        return self._result[0] if self._result else None


def test_the_enqueue_helper_uses_the_configured_delay_and_a_second_call_is_a_no_op():
    plan = dp.requeue_plan({"job_id": 7, "attempt": 1}, POLICY, is_deepseek_peak=lambda now: False)
    cur = _QueueCursor()

    assert runner._enqueue_requeue(cur, plan) is True
    assert cur.row["status"] == "pending"
    assert cur.row["attempt_count"] == 1, "the runner increments to attempt 2 when it starts the row"
    assert cur.row["meta"][runner.REQUEUE_KEY_META] == "7:1"
    assert cur.last_params[1] == DELAYS[0]
    assert runner._enqueue_requeue(cur, plan) is False, "a second enqueue of the same key is a no-op"


def test_the_selection_waits_for_a_requeued_rows_delay():
    assert runner.REQUEUE_DUE_SQL.startswith("AND (")
    assert runner.REQUEUE_KEY_META in runner.REQUEUE_DUE_SQL and "queued_at <= NOW()" in runner.REQUEUE_DUE_SQL


# --- 3. max attempts: exactly one incident, never reported drained -------------------------------------------


def test_an_exhausted_job_yields_exactly_one_incident_and_never_reports_drained():
    rec = _Recorder()
    exhausted = _job(42, POLICY["drain_requeue"]["max_attempts"], status="failed", cause="HTTP 500")
    report = _apply(rec, total=5, failed=5, jobs=[exhausted, dict(exhausted)])

    assert report["triggered"] is True
    assert rec.enqueued == [], "an exhausted job is held, not requeued"
    assert len(rec.incidents) == 1 and rec.incidents[0]["incident_key"] == "job:42"
    assert report["incidents"] == 1 and report["held"] == 1
    assert report["state"]["status"] != "drained"
    assert report["state"]["drained"] is False
    assert report["state"]["failed"] == 1, "the held job stays accounted for"


# --- 4. main() actually calls the wiring with the window's counters -----------------------------------------

_COLS = ("id", "job_type", "symbol", "trade_id", "journal_id", "account", "priority_tier", "priority_score",
         "reason_codes", "last_qwen_summary", "last_qwen_confidence", "metadata_json", "attempt_count",
         "input_hash", "source_table", "source_id")


class _Cur:
    def __init__(self, rows):
        self.rows = rows
        self.description = [(c,) for c in _COLS]
        self._rows = []

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self._rows = []
        if flat.startswith("SELECT") and "FROM deep_overnight_llm_queue" in flat:
            self._rows = [(len(self.rows),)] if "COUNT" in flat else list(self.rows)
        elif "INSERT INTO deep_overnight_llm_results" in flat:
            self._rows = [(1,)]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else (0,)

    def close(self):
        pass


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cur(self.rows)

    def commit(self):
        pass

    def close(self):
        pass


class _Res:
    text, lane = "ok", "grok"

    def provenance_line(self):
        return "served by grok"


def _row(job_id, attempts=0):
    return (job_id, "strategy_classification", "AAPL", None, None, None, "P1", 50, ["x"], None, None, {},
            attempts, "h", None, None)


def _run_main(monkeypatch, tmp_path, n, failing, captured):
    from lib.llm_fallback import AllLanesFailed

    bad = set(failing)

    def generate(prompt, **kwargs):
        if int(prompt[3:]) in bad:
            raise AllLanesFailed([{"lane": "grok", "ok": False, "error": "empty response", "skipped_reason": ""}])
        return _Res()

    def fake_apply(**kwargs):
        captured.update(kwargs)
        triggered = dp.drain_triggered(kwargs["total"], kwargs["failed"], kwargs["policy"])
        state = (dp.drain_state([{"job_id": job["job_id"], "status": job["status"]}
                                 for job in kwargs["failed_jobs"]]) if triggered else None)
        return {"triggered": triggered, "requeued": 0, "held": 0, "incidents": 0, "state": state, "plans": []}

    import lib.llm_fallback as lf

    monkeypatch.setattr(lf, "generate_with_fallback", generate)
    monkeypatch.setattr(runner, "apply_drain_requeue", fake_apply)
    monkeypatch.setattr(runner, "get_db_connection", lambda: _Conn([_row(i) for i in range(1, n + 1)]))
    monkeypatch.setattr(runner, "build_prompt", lambda job, *a, **k: f"JOB{job['id']}")
    monkeypatch.setattr(runner, "_extract_and_register_gaps", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(runner, "past_hard_stop", lambda *_a, **_k: False)
    monkeypatch.setattr(runner, "log", lambda _m: None)
    monkeypatch.setenv("TRADEAI_DRAIN_BREAKER_STATE", str(tmp_path / "breaker.json"))
    monkeypatch.setattr(sys, "argv", ["x", "--route", "cloud", "--limit", str(n)])
    runner.main()


def test_main_calls_the_trigger_at_twenty_percent(monkeypatch, tmp_path):
    captured = {}
    # 2/10 = 20%: fail ids 3 and 8 so no run of 3 consecutive failures trips the circuit breaker.
    _run_main(monkeypatch, tmp_path, 10, {3, 8}, captured)

    assert captured["total"] == 10 and captured["failed"] == 2
    assert {job["job_id"] for job in captured["failed_jobs"]} == {3, 8}
    assert dp.drain_triggered(captured["total"], captured["failed"], captured["policy"]) is True


def test_main_does_below_threshold_nothing(monkeypatch, tmp_path):
    captured = {}
    failing = set(range(3, 98, 5))  # exactly 19 of 100, never 3 in a row (gaps of 4 successes)
    assert len(failing) == 19
    _run_main(monkeypatch, tmp_path, 100, failing, captured)

    assert captured["total"] == 100 and captured["failed"] == 19
    assert dp.drain_triggered(captured["total"], captured["failed"], captured["policy"]) is False
