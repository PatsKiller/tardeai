"""LQ-20261107-1670 — hermes-usefulness-backfill must survive a cio-governed-bridge restart.

Live 2026-11-09: the bridge was restarted by activation under the 14:15 ET slot -- stopped 14:16:52, started
14:16:54. The first rating in flight died with ``RemoteDisconnected``; the next seven raised
``URLError: [Errno 111] Connection refused``; the loop counted eight row failures, exited 1 after 5.8 s, and the
lane's single-attempt policy dead-lettered the slot for two seconds of downtime
(``d:hermes-usefulness-backfill:live:20261109T1415``, reason ``exit_1``, ``scored_now: 0``).

Fail-before (origin/main 9c21372aa): ``ReadinessWait``, ``BridgeNotReady`` and ``READINESS_MARKERS`` do not exist;
the run has no notion of a transport refusal, so one restart is one dead letter.

Pass-after: a transport refusal is waited out inside the run on a bounded schedule, each episode is recorded
once in ``data/runtime/hermes_bridge_readiness.jsonl``, and a bridge that never returns aborts the run once with
``abort_reason: bridge_not_ready`` and exit 75 (EX_TEMPFAIL) instead of burning the queue as provider faults.

Synthetic only: a fake connection, a fake rating call, an injected sleeper, a temp state root. No DB, no network,
no model, no credential, no live symbol or dollar amount.
"""
from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from scripts import hermes_external_feedback_loop as hf

ROWS = [(70115, "deepseek", "TSTX", "q?", "r?", "d?", "2026-11-09T13:00:00+00:00")]


# --------------------------------------------------------------------------- fakes


class Cur:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []
        self._last = ""

    def execute(self, sql, params=None):
        self._last = str(sql)
        self.sql.append((" ".join(str(sql).split()), params))
        return self

    def fetchall(self):
        return [] if "GROUP BY lane" in self._last else list(self.rows)

    def fetchone(self):
        return (0, 0)


class Conn:
    def __init__(self, rows):
        self.cur = Cur(rows)
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def refused():
    """What the live run actually raised: urllib wrapping the socket refusal."""
    return urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))


@pytest.fixture()
def state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture()
def slept(monkeypatch):
    """No real waiting, and the exact schedule the run would have used."""
    calls: list[float] = []
    monkeypatch.setattr(hf.time, "sleep", lambda s: calls.append(s))
    return calls


def run(monkeypatch, *, rate, rows=ROWS, apply=True):
    conn = Conn(rows)
    monkeypatch.setattr(hf, "_db", lambda: conn)
    monkeypatch.setattr(hf, "_outcome", lambda cur, symbol, after: None)
    monkeypatch.setattr(hf, "_rate", rate)
    monkeypatch.setattr(hf, "KILL", Path("/nonexistent/HERMES_DISABLED"))
    result = hf._run_feedback(type("A", (), {"apply": apply, "model": "deepseek-flash", "max_rows": len(rows)})())
    return result, conn


def events(state_root):
    path = state_root / "data" / "runtime" / hf.READINESS_EVENT_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- the wait itself


def test_the_schedule_is_bounded_and_well_inside_the_lanes_cadence():
    """The wait must never outlive the slot: the lane fires hourly, and the whole wait is 5 % of that interval."""
    assert hf.READINESS_BACKOFF_S == (2, 4, 8, 16, 30, 60, 60)
    assert sum(hf.READINESS_BACKOFF_S) <= 180
    reg = json.loads((Path(__file__).resolve().parents[1] / "config" / "lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r.get("lane_id") == "hermes-usefulness-backfill")
    assert row["dispatch"]["cron"] == ["15 * * * *"] and row["dispatch"]["class"] == "ingest"
    assert sum(hf.READINESS_BACKOFF_S) * 10 < 3600


def test_a_refusal_is_distinguished_from_a_governance_refusal_and_a_provider_fault():
    assert hf._is_readiness(str(refused()))
    # the live 14:15 message: urllib's URLError around the refusal, and the bridge client's own class name
    assert hf._is_readiness("<urlopen error [Errno 111] Connection refused>")
    assert hf._is_readiness("HermesLlmError: bridge_flash_error:RemoteDisconnected('Remote end closed connection "
                            "without response')")
    assert not hf._is_readiness("HTTP Error 500")
    # a governance refusal that mentions a connection is terminal, and terminal is checked first
    assert hf._is_terminal("BRIDGE_ROUTE_REFUSED: connection refused by policy")
    assert not hf._is_terminal(str(refused()))


def test_the_waiter_recovers_and_reports_the_episode_once():
    seen = []
    attempts = {"n": 0}

    def call():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise refused()
        return "ok"

    wait = hf.ReadinessWait(call, schedule=(2, 4), sleep=lambda s: seen.append(s), emit=lambda e: seen.append(e))
    assert wait() == "ok"
    assert seen[:2] == [2, 4]
    assert seen[2]["outcome"] == "recovered" and seen[2]["attempts"] == 3 and seen[2]["waited_s"] == 6
    assert "connection refused" in seen[2]["first_error"].lower()
    assert (wait.retries, wait.waited_s) == (2, 6)


def test_a_bridge_that_never_returns_gives_up_after_the_whole_schedule_with_one_event():
    seen = []
    wait = hf.ReadinessWait(lambda: (_ for _ in ()).throw(refused()), schedule=(2, 4),
                            sleep=lambda s: seen.append(("sleep", s)), emit=lambda e: seen.append(e))
    with pytest.raises(hf.BridgeNotReady) as exc:
        wait()
    assert "after 3 attempts over 6s" in str(exc.value)
    assert seen[:2] == [("sleep", 2), ("sleep", 4)]
    assert seen[2]["outcome"] == "gave_up" and seen[2]["attempts"] == 3
    assert len([e for e in seen if isinstance(e, dict)]) == 1


def test_a_provider_fault_is_not_waited_on():
    slept = []
    wait = hf.ReadinessWait(lambda: (_ for _ in ()).throw(RuntimeError("HermesLlmError: upstream 500")),
                            schedule=(2, 4), sleep=lambda s: slept.append(s), emit=lambda e: None)
    with pytest.raises(RuntimeError):
        wait()
    assert slept == []


# --------------------------------------------------------------------------- the run


def test_a_restart_mid_queue_scores_the_row_and_leaves_a_readiness_receipt(state_root, monkeypatch):
    monkeypatch.setattr(hf.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def rate(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise refused()
        return 0.75, "actionable and specific", {"provider": "governed_bridge", "model": hf.N8N_PROCESS_ID}

    result, conn = run(monkeypatch, rate=rate)
    assert {k: result[k] for k in ("selected", "scored", "failed", "aborted", "abort_reason",
                                   "readiness_retries", "readiness_waited_s")} == {
        "selected": 1, "scored": 1, "failed": 0, "aborted": False, "abort_reason": None,
        "readiness_retries": 1, "readiness_waited_s": 2}
    ev = events(state_root)
    assert [e["outcome"] for e in ev] == ["recovered"] and ev[0]["attempts"] == 2
    assert ev[0]["schema"] == hf.READINESS_SCHEMA and ev[0]["lane"] == "hermes-usefulness-backfill"
    # the score was written, and the row's usefulness went in exactly once
    updates = [s for s in conn.cur.sql if s[0].startswith("UPDATE hermes_external_research")]
    assert len(updates) == 1 and "tst_taxable" not in json.dumps(conn.cur.sql)


def test_a_bridge_that_stays_down_aborts_once_instead_of_failing_every_row(state_root, monkeypatch):
    monkeypatch.setattr(hf.time, "sleep", lambda s: None)
    rows = [(70000 + i, "deepseek", "TSTX", "q", "r", "d", "2026-11-09T13:00:00+00:00") for i in range(8)]
    result, conn = run(monkeypatch, rate=lambda *a, **k: (_ for _ in ()).throw(refused()), rows=rows)
    assert result["abort_reason"] == "bridge_not_ready"
    assert result["scored"] == 0 and result["failed"] == 0, "a bridge outage is not eight provider faults"
    assert result["readiness_retries"] == len(hf.READINESS_BACKOFF_S)
    assert not [s for s in conn.cur.sql if s[0].startswith("UPDATE")]
    assert [e["outcome"] for e in events(state_root)] == ["gave_up"]


def test_a_governance_refusal_is_not_waited_on(state_root, monkeypatch):
    slept = []
    monkeypatch.setattr(hf.time, "sleep", lambda s: slept.append(s))
    result, _ = run(monkeypatch, rate=lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("BRIDGE_ROUTE_REFUSED: process not registered")))
    assert result["abort_reason"] == "governance_refused" and result["failed"] == 1
    assert slept == [] and events(state_root) == []


def test_a_provider_fault_still_counts_as_a_failure(state_root, monkeypatch):
    slept = []
    monkeypatch.setattr(hf.time, "sleep", lambda s: slept.append(s))
    calls = {"n": 0}

    def dropped_then_ok(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HermesLlmError: bridge_flash_error:RemoteDisconnected('Remote end closed "
                               "connection without response')")
        return 0.4, "grounded", {"provider": "governed_bridge", "model": hf.N8N_PROCESS_ID}

    result, _ = run(monkeypatch, rate=dropped_then_ok)
    # a dropped connection IS a readiness marker: the bridge went away mid-request
    assert slept == [2] and result["readiness_retries"] == 1 and result["scored"] == 1

    slept.clear()
    result2, _ = run(monkeypatch, rate=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP Error 500")))
    assert slept == [] and result2["failed"] == 1 and result2["abort_reason"] is None


def test_main_returns_exit_tempfail_and_the_receipt_names_the_reason(state_root, monkeypatch):
    monkeypatch.setattr(hf.time, "sleep", lambda s: None)
    monkeypatch.setattr(hf, "_load_env", lambda: {})
    conn = Conn(ROWS)
    monkeypatch.setattr(hf, "_db", lambda: conn)
    monkeypatch.setattr(hf, "_outcome", lambda cur, symbol, after: None)
    monkeypatch.setattr(hf, "_rate", lambda *a, **k: (_ for _ in ()).throw(refused()))
    monkeypatch.setattr(hf, "KILL", Path("/nonexistent/HERMES_DISABLED"))
    assert hf.main(["--apply", "--max-rows", "8"]) == hf.EXIT_TEMPFAIL == 75
    receipt = json.loads((state_root / "data" / "runtime" / "hermes-usefulness-backfill_last.json").read_text())
    assert receipt["exit"] == 75 and receipt["status"] == "failed"
    assert receipt["summary"]["abort_reason"] == "bridge_not_ready"


# --------------------------------------------------------------------------- the contract


def test_the_self_healing_inventory_names_this_mechanism_and_its_artifact():
    """The mechanism is only contract, not prose, if the machine-checked inventory carries it: the code path must
    exist, the evidence source must be the file this lane writes, and the predicate must be the outcome it emits."""
    from scripts.lib.n8n_maturity import dims_healing

    repo = Path(__file__).resolve().parents[1]
    doc = json.loads((repo / dims_healing.INVENTORY_REL).read_text(encoding="utf-8"))
    rows = {m["id"]: m for m in doc["mechanisms"]}
    row = rows["hermes_usefulness_bridge_readiness"]
    assert row["category"] == "retry" and row["code"] == "scripts/hermes_external_feedback_loop.py"
    assert (repo / row["code"]).is_file()
    assert row["evidence_source"]["kind"] == "jsonl"
    assert row["evidence_source"]["path"] == f"data/runtime/{hf.READINESS_EVENT_FILE}"
    assert row["evidence_source"]["ts_key"] == "ts"
    assert row["success_predicate"]["field"] == "outcome"
    assert row["success_predicate"]["equals"] == "recovered"
    # the inventory self-check must accept THIS row (other rows' existing defects are not ours to fix here)
    assert not [p for p in dims_healing.inventory_problems(doc, repo)
                if p.startswith("hermes_usefulness_bridge_readiness")]


def test_the_lane_code_has_no_broker_and_no_model_reach():
    src = Path(hf.__file__).read_text(encoding="utf-8")
    for banned in ("place_order", "requests.post", "broker_order", "MBI_BEHAVIOR = 1"):
        assert banned not in src
