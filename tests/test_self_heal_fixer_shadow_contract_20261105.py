"""self-heal-fixer-shadow: a reviewed health contract and a dry_run dispatch block (D11 shadow, 2026-11-04).

Closes the codex-cloud BLOCK at cec50be3b (PR #2577):

* CX1 [P1] - the lane entered shadow with no entry in config/n8n_health_contracts.json, so
  scripts/check_n8n_health_contracts.py reported ``MISSING_CONTRACT self-heal-fixer-shadow (stage:shadow)``.
  AGENTS.md section 23.19 requires a contract before the registry PR; this lane's contract is pinned below.
* CX2 [P2] - ``scheduler.expression: dispatcher`` plus a cadence does not schedule anything:
  scripts/lib/n8n_due.py::_eligible_lanes skips a row whose ``dispatch`` block is absent or unparseable, so
  ``dispatch_mode(row)`` was ``off`` and no slot was ever emitted. The row now declares ``dispatch.mode:
  dry_run``; ``compute_due`` at the declared Thursday 09:30 ET slot emits it in mode dry_run.

The lane stays SHADOW and dry: allowlist ``live_arg`` is null and dispatch mode is dry_run. Nothing here
activates, schedules or runs the fixer; the host lane self-heal-fixer stays PAUSED / KEEP_ON_CRON.

Hermetic: repo config read only, no DB, no network, no n8n.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

LANE = "self-heal-fixer-shadow"
#: Thursday 2026-11-05 09:30 America/New_York (EST, DST ended 2026-11-01) is the lane's declared slot.
SLOT = datetime(2026, 11, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))
#: The lane fires hourly, weekdays 09:30-18:30 Eastern. Its longest quiet gap is Friday 18:30 ->
#: Monday 09:30 Eastern. ``scripts/lib/lane_registry.py::_scheduler_present`` treats
#: ``expected_cadence_hours`` as a wall-clock maximum since the last finished run (not a per-slot
#: interval), so the declaration below the row must cover that gap or a healthy lane reads ORPHANED
#: every evening and all weekend.
WEEKDAY_CRON = "30 9-18 * * 1-5"
MAX_SCHEDULED_GAP_HOURS = 63.0


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _row() -> dict:
    return next(r for r in _json("config/lane_registry.json")["lanes"] if r["lane_id"] == LANE)


def _entry() -> dict:
    return next(e for e in _json("config/n8n_run_allowlist.json")["lanes"] if e["lane_id"] == LANE)


def _contract() -> dict:
    return next(c for c in _json("config/n8n_health_contracts.json")["contracts"] if c["id"] == LANE)


def test_row_is_a_shadow_dispatcher_row_with_a_parseable_dry_run_dispatch_block():
    from scripts.lib import lane_dispatch as LD

    row, sched = _row(), _row()["scheduler"]
    assert (sched["kind"], sched["expression"]) == ("n8n", "dispatcher")
    assert sched["stage"] == "shadow", "the lane must not leave shadow in this repair"
    assert sched.get("wave"), "a dispatcher row needs scheduler.wave (4.1.0 policy test)"
    assert row["dispatch"]["mode"] == "dry_run"
    assert row["dispatch"]["cron"] == [sched["cadence"]] == ["30 9-18 * * 1-5"]
    assert row["dispatch"]["tz"] == sched["timezone"] == "America/New_York"
    assert row["dispatch"]["class"] == "report"
    assert row["dispatch"]["retry_policy"] == "transient-2"
    assert LD.validate_dispatch_block(row) == []
    assert LD.dispatch_mode(row) == "dry_run"
    assert LD.dispatchable(row)


def test_allowlist_supports_only_the_dry_mode():
    entry = _entry()
    assert entry["dry_run_arg"] == ["--cycle"]
    assert entry["live_arg"] is None
    assert entry["lock_kind"] == "flock"
    assert entry.get("output_receipt") is None


def test_a_complete_reviewed_health_contract_exists():
    from scripts.lib import n8n_health_contracts as H

    contract = _contract()
    assert contract["status"] == "REVIEWED", "a new lane's contract is REVIEWED before its registry PR"
    assert contract["kind"] == "lane" and contract["stage"] == "shadow"
    assert contract["target_reason"] == "stage:shadow"
    assert H.validate_contract(contract) == []
    assert H.unknown_fields(contract) == []
    assert contract["review"]["status"] == "REVIEWED"
    assert contract["review"]["reviewed_by"].strip() and contract["review"]["reviewed_on"]
    assert contract["evidence"]["receipt"] == _row()["output_signal"]["path"]
    from scripts.lib.n8n_output_verdict import validate_expected_output

    assert validate_expected_output(contract["expected_output"]) == []


def test_compute_due_emits_the_lane_dry_run_at_its_thursday_slot():
    from scripts.lib import n8n_due as D
    from scripts.lib import n8n_retry_policy as RP

    registry = _json("config/lane_registry.json")["lanes"]
    allowlist = _json("config/n8n_run_allowlist.json")      # the N8nRunAllowlist@v1 document
    policies = RP.load_policies(ROOT / "config/n8n_retry_policies.json")
    due = D.compute_due(
        registry,
        allowlist,
        policies,
        None,                      # an empty ledger: every slot in the window is DUE
        SLOT,
        source="schedule",
        lane_filter=[LANE],
        tz="America/New_York",
    )
    assert due["errors"] == []
    items = [i for i in due["items"] if i["lane_id"] == LANE]
    assert len(items) == 1, due["items"]
    assert items[0]["mode"] == "dry_run"
    assert items[0]["slot_local"] == "20261105T0930"


# ── the weekday schedule gap: a healthy lane must not read ORPHANED off-hours ──────────────


def _evaluate(root: Path, now: datetime, last: datetime, *, cadence: float | None = None) -> dict:
    """`evaluate_lane` for this row against a synthetic n8n run ledger and output receipt.

    `last` is the finish time of the most recent successful (RUN_DONE, dry_run) fire. The same
    time stamps the output receipt, so scheduler presence and output freshness agree.
    """
    from scripts.lib import lane_registry as LR

    runs = root / "data/runtime/n8n_runs"
    runs.mkdir(parents=True)
    receipt = root / "data/runtime/self_heal_fixer_shadow/receipt.json"
    receipt.parent.mkdir(parents=True)
    (runs / "run-1.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "lane_id": LANE,
                "mode": "dry_run",
                "state": "RUN_DONE",
                "finished_at": last.astimezone(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    receipt.write_text("{}", encoding="utf-8")
    os.utime(receipt, (last.timestamp(), last.timestamp()))
    row = dict(_row())
    if cadence is not None:
        row["expected_cadence_hours"] = cadence
    return LR.evaluate_lane(
        row, now=now.astimezone(timezone.utc), found={"cron": [], "systemd": []}, root=root
    )


def test_declared_cadence_covers_the_weekday_schedule_gap():
    """The liveness rule is wall-clock, so a weekday-only n8n lane must declare the weekend gap."""
    from reconcile_lane_registry import cron_cadence_hours

    row = _row()
    assert cron_cadence_hours(WEEKDAY_CRON) == MAX_SCHEDULED_GAP_HOURS
    assert float(row["expected_cadence_hours"]) >= MAX_SCHEDULED_GAP_HOURS, (
        "a cadence below the longest scheduled gap reports ORPHANED every evening and all weekend"
    )
    assert row["active_days"] == [0, 1, 2, 3, 4]


def test_health_is_not_orphaned_off_hours_when_every_scheduled_fire_succeeded(tmp_path):
    """Monday evening, Saturday and Monday pre-first-fire must not read ORPHANED.

    Every scenario has a RUN_DONE and a receipt at the last scheduled fire. `cadence=1.0` is
    the pre-fix declaration and is kept as the negative control: it is exactly what produced the
    nightly and weekend false alarm the review found.
    """
    et = ZoneInfo("America/New_York")
    cases = [
        # name, now, last successful fire, verdict the pre-fix 1 h declaration produced
        ("in-window Monday", datetime(2026, 11, 9, 10, 30, tzinfo=et), datetime(2026, 11, 9, 9, 40, tzinfo=et), "LIVE"),
        ("Monday evening", datetime(2026, 11, 9, 20, 0, tzinfo=et), datetime(2026, 11, 9, 18, 35, tzinfo=et), "ORPHANED"),
        ("Saturday", datetime(2026, 11, 7, 12, 0, tzinfo=et), datetime(2026, 11, 6, 18, 35, tzinfo=et), "ORPHANED"),
        ("Monday before first fire", datetime(2026, 11, 9, 9, 0, tzinfo=et), datetime(2026, 11, 6, 18, 35, tzinfo=et), "ORPHANED"),
    ]
    for i, (name, now, last, before_verdict) in enumerate(cases):
        got = _evaluate(tmp_path / f"fixed-{i}", now, last)
        assert got["verdict"] == "LIVE" and got["ok"] is True, (name, got)
        assert got["scheduler_present"] is True, (name, got)
        assert got["in_declared_window"] is (now.weekday() < 5), (name, got)
        # Negative control: the pre-fix 1 h declaration reproduces the false alarm the review found.
        before = _evaluate(tmp_path / f"before-{i}", now, last, cadence=1.0)
        assert before["verdict"] == before_verdict, (name, before)

