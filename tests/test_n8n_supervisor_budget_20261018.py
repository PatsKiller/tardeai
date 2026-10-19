"""Bounded deterministic actions and budget-independent P1 enrollment; no real service/model/send."""
from __future__ import annotations

import json
import multiprocessing
import queue
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts import n8n_failure_diagnosis as FD
from scripts import supervisor_breach_detector as S
from tests.test_n8n_llm_remediation_20261010 import _siem_row

NOW = datetime(2026, 10, 18, 14, tzinfo=timezone.utc)
LANE = "fixture-supervisor"
LANES = [{"lane_id": LANE, "state": "ACTIVE", "scheduler": {"kind": "systemd", "expression": "fixture.timer"}}]
BREACHES = [{"lane_id": LANE, "kind": kind, "breach_id": "fixture-" + kind} for kind in ("SILENT", "NO_OUTPUT", "HUNG")]


def history(tmp_path, rows=()):
    path = tmp_path / "supervisor_recoveries.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def legacy_attempt():
    return {"schema": "Recovery@v1", "lane_id": LANE, "ts": (NOW - timedelta(seconds=30)).isoformat(),
            "mode": "live", "executed": True, "level": 1, "rc": 0}


def test_prior_restart_and_multiple_same_cycle_actions_never_exceed_cap(tmp_path, monkeypatch):
    history(tmp_path, [legacy_attempt()])
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0, stderr=""))
    S._self_heal_l1_l2(BREACHES, LANES, {}, NOW, tmp_path, live=True)
    assert len(calls) == 1, "one prior restart leaves one of the two allowed attempts"


def test_concurrent_evaluators_reserve_before_invoking_an_action(tmp_path, monkeypatch):
    history(tmp_path)
    first_two = threading.Barrier(2)
    calls, lock = [], threading.Lock()

    def action(*a, **k):
        with lock:
            calls.append(a)
            n = len(calls)
        if n <= 2:
            first_two.wait(timeout=3)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", action)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(S._self_heal_l1_l2, BREACHES[:2], LANES, {}, NOW, tmp_path, live=True) for _ in range(2)]
        for future in futures:
            future.result(timeout=5)
    assert len(calls) == 2, "the per-lane budget is shared across evaluators"


def test_independent_processes_share_the_atomic_attempt_budget(tmp_path, monkeypatch):
    history(tmp_path)
    ctx = multiprocessing.get_context("fork")
    barrier, calls = ctx.Barrier(2), ctx.Queue()

    def action(*a, **k):
        calls.put(a)
        barrier.wait(timeout=5)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", action)
    workers = [ctx.Process(target=S._self_heal_l1_l2, args=(BREACHES, LANES, {}, NOW, tmp_path),
                           kwargs={"live": True}) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=7)
        assert worker.exitcode == 0
    assert calls.get(timeout=1) and calls.get(timeout=1)
    with pytest.raises(queue.Empty):
        calls.get(timeout=0.05)


def test_crash_after_reservation_consumes_budget_and_l2_cannot_bypass_it(tmp_path, monkeypatch):
    history(tmp_path)

    def crash(*a, **k):
        raise KeyboardInterrupt("fixture crash after durable admission")

    monkeypatch.setattr(subprocess, "run", crash)
    with pytest.raises(KeyboardInterrupt):
        S._self_heal_l1_l2(BREACHES, LANES, {}, NOW, tmp_path, live=True)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0, stderr=""))
    no_systemd_lane = [{"lane_id": LANE, "state": "ACTIVE", "scheduler": {"kind": "cron"}}]
    S._self_heal_l1_l2(BREACHES, no_systemd_lane, {LANE: {"alternate": "fixture-alt.service"}}, NOW, tmp_path, live=True)
    assert len(calls) == 1 and calls[0][0] == ["systemctl", "--user", "start", "fixture-alt.service"]


def test_legacy_failed_attempts_remain_budgeted_without_new_optional_fields(tmp_path, monkeypatch):
    history(tmp_path, [{**legacy_attempt(), "executed": False, "error": "TimeoutExpired:fixture"}, legacy_attempt()])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("legacy attempted actions lost from budget"))
    assert S._self_heal_l1_l2(BREACHES, LANES, {}, NOW, tmp_path, live=True)["l1_executed"] == 0


@pytest.mark.parametrize("failure", ["nonzero", "timeout"])
def test_failed_restart_still_consumes_an_attempt_and_never_claims_recovery(tmp_path, monkeypatch, failure):
    history(tmp_path)
    calls = []

    def action(*a, **k):
        calls.append(a)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(a[0], 60)
        return SimpleNamespace(returncode=1, stderr="fixture restart failed")

    monkeypatch.setattr(subprocess, "run", action)
    S._self_heal_l1_l2(BREACHES, LANES, {}, NOW, tmp_path, live=True)
    assert len(calls) == 2
    records = [json.loads(line) for line in (tmp_path / "supervisor_recoveries.jsonl").read_text().splitlines()]
    attempted = [row for row in records if row.get("attempted")]
    assert len(attempted) == 2 and all(row.get("business_recovered") is False for row in attempted)


@pytest.mark.parametrize("raw", [None, "{incomplete-json\n", '{"executed":true,"ts":"invalid-time"}\n'])
def test_missing_or_unreadable_budget_history_fails_closed(tmp_path, monkeypatch, raw):
    if raw is not None:
        (tmp_path / "supervisor_recoveries.jsonl").write_text(raw)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0, stderr=""))
    result = S._self_heal_l1_l2(BREACHES, LANES, {}, NOW, tmp_path, live=True)
    assert calls == [], "an unavailable attempt budget cannot authorize a restart"
    assert result["budget_status"] == "unavailable" and result["l1_executed"] == 0


@pytest.mark.parametrize("setting,value", [("L1_MAX_PER_WINDOW", None), ("L1_MAX_PER_WINDOW", float("nan")),
                                         ("L1_MAX_PER_WINDOW", True), ("L1_WINDOW_S", float("inf")),
                                         ("L1_WINDOW_S", -1)])
def test_unknown_or_nonfinite_budget_configuration_fails_closed(tmp_path, monkeypatch, setting, value):
    history(tmp_path)
    monkeypatch.setattr(S, setting, value)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("unknown cap authorized an action"))
    assert S._self_heal_l1_l2(BREACHES, LANES, {}, NOW, tmp_path, live=True)["budget_status"] == "unavailable"


@pytest.mark.parametrize("mutation", [{"attempted": "false"}, {"attempt_reserved": 1},
                                     {"attempt_id": float("nan")}, {"ts": "2099-01-01T00:00:00+00:00"}])
def test_malformed_and_future_attempt_history_fails_closed(tmp_path, monkeypatch, mutation):
    history(tmp_path, [{**legacy_attempt(), **mutation}])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("untrusted history authorized an action"))
    assert S._self_heal_l1_l2(BREACHES, LANES, {}, NOW, tmp_path, live=True)["budget_status"] == "unavailable"


def diagnose(tmp_path, state, *, cap=0):
    rows = [_siem_row(rid=30 - i, lane="fixture-lane-" + str(i), severity=severity, error="fixture dependency offline")
            for i, severity in enumerate(("CRITICAL", "URGENT", "CRITICAL"))]
    diag = FD.diagnose(rows, catalogue={FD.D.lane_of(row): {} for row in rows}, registry={}, state=state, now=NOW,
                       ledger=tmp_path / "missing-test-ledger.sqlite", governed_call=lambda *a, **k: pytest.fail("AI cap bypassed"),
                       artifact_root=tmp_path, min_severity="WARN", max_incidents=cap,
                       deferral=lambda *a: SimpleNamespace(defer=False), output_observer=lambda *a: None,
                       effect_keys={}, live_lanes=frozenset())
    FD.apply_results(diag, [], state, {row["id"]: row for row in rows}, now=NOW,
                     store_factory=lambda: pytest.fail("critical enrollment executed an action"),
                     allowlist={}, root=tmp_path)
    return diag


def test_distinct_critical_episodes_enroll_after_cycle_cap_and_repeats_deduplicate(tmp_path):
    state = FD.empty_state()
    diag = diagnose(tmp_path, state)
    assert all(row["outcome"] == "not_this_cycle" for row in diag["results"])
    assert len(state["escalations"]) == 3 and all(row["priority"] == "P1" for row in state["escalations"].values())
    stats = FD.counts(diag, [])
    assert stats["p1_enrolled_new"] == stats["p1_open"] == 3
    before = {key: row["at"] for key, row in state["escalations"].items()}
    diag = diagnose(tmp_path, state)
    assert {key: row["at"] for key, row in state["escalations"].items()} == before
    assert FD.counts(diag, [])["p1_enrolled_new"] == 0 and FD.counts(diag, [])["p1_open"] == 3


def test_daily_ai_caps_never_limit_distinct_critical_enrollment(tmp_path):
    state = FD.empty_state()
    day = FD.day_bucket(state, NOW)
    day.update(spend_usd=FD.D.DAILY_CAP_USD, calls=FD.D.MAX_CALLS_PER_DAY)
    diag = diagnose(tmp_path, state, cap=10)
    assert sum(row.get("outcome") == "not_this_cycle" for row in diag["results"]) == 2
    assert len(state["escalations"]) == 3
    assert FD.counts(diag, [])["p1_enrolled_new"] == FD.counts(diag, [])["p1_open"] == 3
