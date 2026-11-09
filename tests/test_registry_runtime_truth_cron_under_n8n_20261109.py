"""Registry / runtime truth: a cron row the n8n dispatcher runs is named, never reported absent (LQ-20261107-1575).

`scripts/check_registry_runtime_truth.py` reads the crontab, the n8n workflow table, systemd and the coordination
ledger. When a `kind: cron` row's crontab line was retired by the n8n cutover (the line stays in `crontab -l` as
`# RETIRED 2026-11-08 n8n-cutover …`), the row still declares `kind: cron` with `scheduler.match` pointing at the
script and `dispatch.mode: live`, and the checker reported ACTIVE_CRON_LINE_ABSENT — "the registry says the job runs
and it does not" — for a lane the dispatcher in fact fires on schedule. 2026-11-09 dry run: 28 such rows, every one of
them with live runs whose `requested_by` is an n8n workflow and whose `slot_key` is set (event-detector at 12:00Z and
14:00Z, trade-ai-scalp-live 42 scheduled runs in the window, …).

The registry's declared MECHANISM is wrong; the lane runs. That is the same class as CRON_ROW_RUNS_UNDER_TIMER and it
must be reported, not suppressed into a fabricated absence.

This file pins:

* the reader: `read_ledger` carries `scheduled_runs` — live runs in the window that the ledger records as SCHEDULED
  (`slot_key IS NOT NULL`) and requested by an n8n workflow. A manual `--apply` run (null slot_key) is not scheduling
  evidence and never stands in for the dispatcher. A ledger built before the `slot_key` column existed still reads as
  `ok` with no scheduling evidence, never as a crash;
* the rule: CRON_ROW_RUNS_UNDER_N8N for an ACTIVE kind-cron row at canary/cutover with `dispatch.mode: live`, no
  active crontab line and scheduled n8n runs in the ledger. Without that evidence the row is still reported
  ACTIVE_CRON_LINE_ABSENT; a live timer under the same row is named first (CRON_ROW_RUNS_UNDER_TIMER).

Hermetic: tmp ledgers and repo roots, canned crontab; no live ledger, no docker, no crontab, no systemctl.

ANCHOR: REGISTRY_RUNTIME_TRUTH_CRON_UNDER_N8N_20261109

COVERS = ["scripts/check_registry_runtime_truth.py"]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_registry_runtime_truth as RT  # noqa: E402

ANCHOR = "REGISTRY_RUNTIME_TRUTH_CRON_UNDER_N8N_20261109"
DISPATCHER = "n8n:workflow:tradeai-dispatcher"
NOW = RT.datetime(2026, 11, 9, 12, tzinfo=RT.timezone.utc)
SLOT = "d:sweep:live:20261109T0700"


# ── fixtures ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _row(lane, *, state="ACTIVE", kind="cron", match="scripts/sweep.py", stage="canary", dispatch="live"):
    sched = {"kind": kind, "expression": "0 7 * * *", "match": match}
    if stage is not None:
        sched["stage"] = stage
    row = {"lane_id": lane, "owner": "t", "state": state, "scheduler": sched, "output_signal": {"kind": "none"}}
    if dispatch is not None:
        row["dispatch"] = {"mode": dispatch}
    return row


def _decl(rows):
    return {"rows": {r["lane_id"]: r for r in rows}, "contracts": {}, "allow": {}, "processes": {},
            "grandfathered_draft": []}


def _codes(found):
    return [(c["code"], c["lane_id"]) for c in found]


def _ledger(path: Path, *, runs=(), slot_key_column=True):
    """runs: (lane, mode, state, requested_at, requested_by, slot_key)."""
    conn = sqlite3.connect(path)
    slot = ", slot_key TEXT" if slot_key_column else ""
    conn.executescript(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT,"
        f" requested_by TEXT{slot});"
        "CREATE TABLE effect_owners (process TEXT PRIMARY KEY, owner TEXT, epoch INTEGER, switched_at TEXT);"
    )
    for i, run in enumerate(runs):
        lane, mode, state, at, by = run[:5]
        key = run[5] if len(run) > 5 else None
        if slot_key_column:
            conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)", (f"r{i}", lane, mode, state, at, by, key))
        else:
            conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)", (f"r{i}", lane, mode, state, at, by))
    conn.commit()
    conn.close()
    return path


def _fixture_root(tmp_path, rows, *, runs=(), slot_key_column=True):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    # nosemgrep: tq-py-nonatomic-store-write -- synthetic fixture inside pytest's tmp_path, not a live store
    (root / "config" / "lane_registry.json").write_text(json.dumps({"lanes": rows}), encoding="utf-8")
    (root / "config" / "n8n_health_contracts.json").write_text(json.dumps({"contracts": []}), encoding="utf-8")
    (root / "config" / "n8n_run_allowlist.json").write_text(json.dumps({"lanes": []}), encoding="utf-8")
    live = tmp_path / "live.env"
    live.write_text("TRADEAI_N8N_RELAY_LIVE_LANES=\n", encoding="utf-8")
    return root, _ledger(tmp_path / "ledger.sqlite", runs=runs, slot_key_column=slot_key_column), live


def _report(tmp_path, rows, *, runs=(), slot_key_column=True):
    root, ledger, live = _fixture_root(tmp_path, rows, runs=runs, slot_key_column=slot_key_column)
    return RT.build_report(root=root, ledger_path=ledger, live_lanes_env=live, now=NOW, window_days=7,
                           cron_runner=lambda: (0, "0 1 * * * /venv/bin/python /r/scripts/other.py\n"),
                           skip_n8n=True, skip_systemd=True)


SCHEDULED = {"live_runs": {}, "owners": {},
             "scheduled_runs": {"sweep": {"count": 3, "last": "2026-11-09T07:00:01+00:00",
                                          "scheduler": DISPATCHER, "last_state": "RUN_DONE"}}}


# ── 1. the reader ───────────────────────────────────────────────────────────────────────────────────────────────


def test_read_ledger_carries_the_runs_the_ledger_records_as_scheduled(tmp_path):
    path = _ledger(tmp_path / "ledger.sqlite", runs=[
        ("sweep", "live", "RUN_DONE", "2026-11-09T07:00:01+00:00", DISPATCHER, SLOT),
        ("sweep", "live", "RUN_DONE", "2026-11-09T08:00:02+00:00", "agent:claude", None),  # manual --apply: not a slot
        ("sweep", "live", "RUN_SKIPPED_LOCK", "2026-11-09T09:00:03+00:00", DISPATCHER, SLOT),
        ("manual-only", "live", "RUN_DONE", "2026-11-09T07:30:00+00:00", DISPATCHER, None),  # n8n, no slot
        ("other", "live", "RUN_DONE", "2026-11-09T07:15:00+00:00", "n8n:workflow:tradeai-heartbeat-watcher",
         "d:other:live:20261109T0715"),
    ])
    st, got, _ = RT.read_ledger(path, RT.datetime(2026, 11, 9, 0, tzinfo=RT.timezone.utc))
    assert st == "ok"
    assert set(got["scheduled_runs"]) == {"sweep", "other"}
    sweep = got["scheduled_runs"]["sweep"]
    assert sweep["count"] == 2, "a scheduled run that skipped lock is still scheduled"
    assert sweep["last"] == "2026-11-09T09:00:03+00:00" and sweep["last_state"] == "RUN_SKIPPED_LOCK"
    assert sweep["scheduler"] == DISPATCHER
    assert got["scheduled_runs"]["other"]["scheduler"] == "n8n:workflow:tradeai-heartbeat-watcher"
    # live_runs keeps its own semantics: every live RUN_DONE, scheduled or not
    assert got["live_runs"]["sweep"]["count"] == 2 and got["live_runs"]["manual-only"]["count"] == 1


def test_a_ledger_without_the_slot_key_column_reads_ok_and_carries_no_scheduling_evidence(tmp_path):
    path = _ledger(tmp_path / "legacy.sqlite", slot_key_column=False, runs=[
        ("sweep", "live", "RUN_DONE", "2026-11-09T07:00:01+00:00", DISPATCHER),
    ])
    st, got, _ = RT.read_ledger(path, RT.datetime(2026, 11, 9, 0, tzinfo=RT.timezone.utc))
    assert st == "ok", "an older ledger must not make the whole report unreadable"
    assert got["live_runs"]["sweep"]["count"] == 1
    assert got["scheduled_runs"] == {}, "no slot column means the reader cannot tell scheduled from manual"


def test_runs_outside_the_window_and_non_live_modes_are_not_scheduling_evidence(tmp_path):
    path = _ledger(tmp_path / "ledger.sqlite", runs=[
        ("sweep", "live", "RUN_DONE", "2026-10-01T07:00:00+00:00", DISPATCHER, SLOT),  # before the window
        ("sweep", "emulated", "RUN_DONE", "2026-11-09T07:00:00+00:00", DISPATCHER, SLOT),  # not a live run
        ("sweep", "live", "RUN_DONE", "2026-11-09T07:00:00+00:00", "operator", SLOT),  # slot, but not an n8n workflow
    ])
    st, got, _ = RT.read_ledger(path, RT.datetime(2026, 11, 2, 12, tzinfo=RT.timezone.utc))
    assert st == "ok"
    assert got["scheduled_runs"] == {}


# ── 2. the rule ────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_cron_row_the_n8n_dispatcher_schedules_is_named_not_absent():
    found, _, _ = RT.evaluate(_decl([_row("sweep")]), ledger=SCHEDULED, live_lanes=[], cron_lines=[],
                              n8n_active=[], systemd={})
    assert _codes(found) == [("CRON_ROW_RUNS_UNDER_N8N", "sweep")]
    ev = found[0]["evidence"]
    assert ev["match"] == "scripts/sweep.py" and ev["registry_state"] == "ACTIVE"
    assert ev["scheduler"] == DISPATCHER and ev["scheduled_runs"] == 3
    assert ev["last_requested_at"] == "2026-11-09T07:00:01+00:00"
    assert "ACTIVE" in found[0]["detail"] and "n8n" in found[0]["detail"]
    assert "no active crontab line" in found[0]["detail"]


def test_without_scheduled_evidence_the_row_is_still_reported_absent():
    no_sched = {"live_runs": {"sweep": {"count": 1, "last": "2026-11-09T07:00:01+00:00"}}, "owners": {},
                "scheduled_runs": {}}
    found, _, _ = RT.evaluate(_decl([_row("sweep")]), ledger=no_sched, live_lanes=[], cron_lines=[],
                              n8n_active=[], systemd={})
    assert _codes(found) == [("ACTIVE_CRON_LINE_ABSENT", "sweep")]


def test_a_cron_line_still_present_is_not_a_mechanism_finding():
    cron = ["0 7 * * * /venv/bin/python /r/scripts/sweep.py --apply"]
    found, _, _ = RT.evaluate(_decl([_row("sweep")]), ledger=SCHEDULED, live_lanes=[], cron_lines=cron,
                              n8n_active=[], systemd={})
    assert _codes(found) == []


def test_a_live_timer_under_the_same_row_is_named_first():
    systemd = {"sweep.timer": {"present": True, "enabled": True, "live": True, "scopes": ["user"],
                               "live_scopes": ["user"], "unit_file_state": "enabled", "active_state": "active",
                               "triggers": "sweep.service",
                               "commands": ["/venv/bin/python /r/scripts/sweep.py --apply"]}}
    found, _, _ = RT.evaluate(_decl([_row("sweep")]), ledger=SCHEDULED, live_lanes=[], cron_lines=[],
                              n8n_active=[], systemd=systemd)
    assert _codes(found) == [("CRON_ROW_RUNS_UNDER_TIMER", "sweep")]


def test_a_row_with_no_live_n8n_path_is_not_excused_by_an_n8n_run():
    found, _, _ = RT.evaluate(_decl([_row("sweep", dispatch="shadow")]), ledger=SCHEDULED, live_lanes=[],
                              cron_lines=[], n8n_active=[], systemd={})
    assert _codes(found) == [("ACTIVE_CRON_LINE_ABSENT", "sweep")]


def test_a_declared_off_cron_row_is_not_excused_by_an_n8n_run():
    found, _, _ = RT.evaluate(_decl([_row("sweep", state="PAUSED")]), ledger=SCHEDULED, live_lanes=[],
                              cron_lines=[], n8n_active=[], systemd={})
    assert _codes(found) == [], "a paused row that n8n runs is DECLARED_OFF_BUT_RUNS_LIVE's finding, not this one"


# ── 3. the real report path ───────────────────────────────────────────────────────────────────────────────────


def test_the_reader_and_the_rule_are_wired_into_the_report(tmp_path):
    report = _report(tmp_path, [_row("sweep")], runs=[
        ("sweep", "live", "RUN_DONE", "2026-11-09T07:00:01+00:00", DISPATCHER, SLOT),
    ])
    assert report["sources"]["coordination_ledger"]["status"] == "ok"
    assert _codes(report["contradictions"]) == [("CRON_ROW_RUNS_UNDER_N8N", "sweep")]


def test_a_report_over_a_legacy_ledger_does_not_crash_and_keeps_the_old_verdict(tmp_path):
    report = _report(tmp_path, [_row("sweep")], slot_key_column=False, runs=[
        ("sweep", "live", "RUN_DONE", "2026-11-09T07:00:01+00:00", DISPATCHER),
    ])
    assert report["sources"]["coordination_ledger"]["status"] == "ok"
    assert _codes(report["contradictions"]) == [("ACTIVE_CRON_LINE_ABSENT", "sweep")]
