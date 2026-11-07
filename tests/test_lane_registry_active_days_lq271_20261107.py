"""ANCHOR: LANE_REGISTRY_ACTIVE_DAYS_LQ271_20261107. LQ-20261107-271 — the weekend half of "SILENT 30"
was a registry gap, not a dead pipeline.

``scripts/lib/lane_registry.py`` reads ``active_days`` as a DECLARATION: a row with no declaration is
graded in-window on all seven days (``_within_declared_days`` -> ``if not days: return True``). Nineteen
rows whose cron expression already states ``1-5`` (or ``0`` for Sunday) had no declaration, so every
Saturday and Sunday they were graded SILENT — a page for a lane that is correctly resting.

This pins the fix, and pins its blast radius:

1. each of the nineteen rows declares exactly the days its own cron day field states (the declaration is
   derived, not invented — the test re-derives it from the expression);
2. on a Saturday, exactly those nineteen rows move SILENT -> EXPECTED_SILENT and **no other row changes
   verdict** (the SILENT count drops by exactly nineteen);
3. on a weekday the declaration changes nothing: a weekday row is in-window with or without it, and no
   weekday row loses a day it runs on.

Hermetic: the real ``config/lane_registry.json`` is read (the thing under test is the declaration), but
evaluation uses a synthetic scheduler inventory and an empty ``tmp_path`` state root, so no live artifact,
database, network or clock is read.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import lane_registry as LR

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "lane_registry.json"

#: The nineteen rows named by the 2026-11-07T20:55Z finding.
LANES = (
    "active-trader-premarket-watch",
    "active-trader-session-review",
    "advice-digest",
    "alert-missing-conditions",
    "cio-opportunity-curator",
    "db-retention-timer",
    "event-detector",
    "finviz-momentum-scalp-early-lane",
    "generate-weekly-docx",
    "incubator-llm-screener",
    "investment-costs",
    "options-intent-matcher",
    "reconcile-exit-advisory-outcomes",
    "reconcile-pullback-outcomes",
    "rotation-rebalance-digest",
    "run-profit-capture-refresh",
    "send-telegram-proposal-alert",
    "social-ingest-scalp-hot",
    "social-scalp-scanner",
)

#: The one systemd row in the set: no cron field, so its days are stated by the timer's
#: ``OnCalendar=Sun *-*-* 03:00:00`` and pinned here rather than derived.
SYSTEMD_DAYS = {"db-retention-timer": [6]}

SATURDAY = datetime(2026, 11, 7, 21, 20, tzinfo=timezone.utc)
MONDAY = datetime(2026, 11, 9, 15, 37, tzinfo=timezone.utc)


def load() -> dict:
    return json.loads(REGISTRY.read_text())


def row_of(reg: dict, lane_id: str) -> dict:
    return next(r for r in reg["lanes"] if r["lane_id"] == lane_id)


def days_from_cron(expression: str) -> list[int]:
    """Cron day-of-week (0=Sun..6=Sat) -> python weekday (0=Mon..6=Sun).

    Validated against rows that already declare: ``*/20 9-16 * * 1-5`` -> [0,1,2,3,4] matches
    portfolio-live-monitor, portfolio-ai-analyst, morning-brief-0730 and screener-go-alerts, and
    ``0 21 * * 0`` -> [6].
    """
    fields = expression.split()
    assert len(fields) == 5, f"not a 5-field cron expression: {expression!r}"
    days: list[int] = []
    for part in fields[4].split(","):
        if part == "*":
            return [0, 1, 2, 3, 4, 5, 6]
        m = re.fullmatch(r"(\d)(?:-(\d))?", part)
        assert m, f"day field {part!r} is not derivable in {expression!r}"
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        days.extend(range(lo, hi + 1))
    return sorted({(d + 6) % 7 for d in days})


def declared_days(reg: dict, lane_id: str) -> list[int]:
    return row_of(reg, lane_id)["active_days"]


def inventory(reg: dict) -> dict:
    """Say every scheduler is installed, so no row is ORPHANED for the wrong reason."""
    cron, systemd = [], []
    for row in reg["lanes"]:
        sched = row.get("scheduler") or {}
        expr = sched.get("expression")
        if not expr:
            continue
        if sched.get("kind") == "cron":
            cron.append({"expression": sched.get("match") or expr})
        elif sched.get("kind") == "systemd":
            systemd.append({"expression": expr})
    return {"cron": cron, "systemd": systemd}


@pytest.fixture
def never_produced(monkeypatch):
    """Every signal is readable and has never produced — SILENT while in window, EXPECTED_SILENT outside.

    ``observe_signal`` is stubbed on purpose: this change is about the WINDOW rule, and a real
    observation would make the verdicts depend on live artifacts (and on any absolute path a row
    happens to declare). With the stub, the only input left is the declaration under test.
    """
    monkeypatch.setattr(LR, "observe_signal",
                        lambda *a, **k: {"last_output_at": None, "readable": True, "detail": "stub"})


def verdicts(reg: dict, now: datetime) -> dict[str, str]:
    found = inventory(reg)
    return {row["lane_id"]: LR.evaluate_lane(row, now=now, found=found)["verdict"]
            for row in reg["lanes"]}


def without_declarations(reg: dict) -> dict:
    """The registry as it stood before this change: the nineteen rows declare nothing."""
    reg = copy.deepcopy(reg)
    for lane_id in LANES:
        row_of(reg, lane_id).pop("active_days", None)
    return reg


# ── 1. the declaration is the one the expression states ─────────────────────────────────────────────────────

def test_each_of_the_nineteen_rows_declares_the_days_its_cron_expression_states():
    reg = load()
    for lane_id in LANES:
        row = row_of(reg, lane_id)
        if lane_id in SYSTEMD_DAYS:
            assert row["scheduler"]["expression"] == "db-retention.timer"
            expected = SYSTEMD_DAYS[lane_id]
        else:
            expected = days_from_cron(row["scheduler"]["expression"])
        assert declared_days(reg, lane_id) == expected, (
            f"{lane_id}: declares {declared_days(reg, lane_id)}, its expression "
            f"{row['scheduler']['expression']!r} states {expected}")


def test_every_declaration_is_a_list_of_weekday_ints():
    reg = load()
    for lane_id in LANES:
        days = declared_days(reg, lane_id)
        assert isinstance(days, list), f"{lane_id}: {days!r}"
        assert all(isinstance(d, int) and 0 <= d <= 6 for d in days), f"{lane_id}: {days!r}"


def test_a_weekday_lane_did_not_gain_a_day_it_does_not_run_on():
    """The narrow risk of this change: a declaration wider than the schedule hides a real silence."""
    reg = load()
    for lane_id in LANES:
        if lane_id in SYSTEMD_DAYS:
            continue
        derived = set(days_from_cron(row_of(reg, lane_id)["scheduler"]["expression"]))
        assert set(declared_days(reg, lane_id)) <= derived, lane_id


# ── 2. Saturday: exactly these nineteen stop being SILENT, nothing else moves ──────────────────────────────

def test_on_a_saturday_the_nineteen_are_expected_silent_and_the_silent_count_drops_by_nineteen(never_produced):
    after = load()
    before = without_declarations(after)

    before_v = verdicts(before, SATURDAY)
    after_v = verdicts(after, SATURDAY)

    moved = {k: (before_v[k], after_v[k]) for k in before_v if before_v[k] != after_v[k]}
    assert set(moved) == set(LANES), f"verdicts moved outside the nineteen: {sorted(set(moved) - set(LANES))}"
    assert all(pair == (LR.SILENT, LR.EXPECTED_SILENT) for pair in moved.values()), moved

    silent_before = sum(1 for v in before_v.values() if v == LR.SILENT)
    silent_after = sum(1 for v in after_v.values() if v == LR.SILENT)
    assert silent_before - silent_after == len(LANES), (silent_before, silent_after)


def test_on_a_sunday_the_sunday_lanes_are_in_window_and_the_weekday_lanes_are_not(never_produced):
    reg = load()
    sunday = datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc)
    got = verdicts(reg, sunday)
    for lane_id in LANES:
        row = row_of(reg, lane_id)
        if row.get("state") in LR.SILENCE_EXPECTED:
            continue
        expected = LR.SILENT if 6 in declared_days(reg, lane_id) else LR.EXPECTED_SILENT
        assert got[lane_id] == expected, f"{lane_id}: {got[lane_id]} on Sunday, expected {expected}"


# ── 3. a weekday: the weekday rows are untouched, and the Sunday rows rest as they should ─────────────────

def test_on_a_monday_the_weekday_rows_are_unchanged_and_the_sunday_rows_stop_reading_silent(never_produced):
    """The declaration excludes the days a lane rests. On a Monday that must mean nothing for a
    weekday lane, and must mean EXPECTED_SILENT — not SILENT — for a lane that runs only on Sunday."""
    after = load()
    before = without_declarations(after)
    before_v = verdicts(before, MONDAY)
    after_v = verdicts(after, MONDAY)

    sunday_rows = {lane_id for lane_id in LANES if set(declared_days(after, lane_id)) == {6}}
    weekday_rows = set(LANES) - sunday_rows
    assert sunday_rows and weekday_rows == set(LANES) - sunday_rows

    moved = {k: (before_v[k], after_v[k]) for k in before_v if before_v[k] != after_v[k]}
    assert moved == {k: (LR.SILENT, LR.EXPECTED_SILENT) for k in sunday_rows}, moved
    assert all(before_v[k] == after_v[k] for k in weekday_rows)
