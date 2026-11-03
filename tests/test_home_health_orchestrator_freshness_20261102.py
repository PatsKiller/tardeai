"""Home health: the Trade AI Orchestrator is judged by the lane that actually runs.

CC5's Home audit (D2, 2026-11-02): the component monitored `logs/screener_pm.log` with a 180-minute
wall-clock threshold, while the only ACTIVE lane that writes that log runs 17:30 ET Monday to Friday
(`orchestrator-slot`; `orchestrator-slot-midday` is RETIRED). The monitor therefore called the
component STALE every evening, all night and all weekend.

These are PRODUCTION-LOOP tests, not helper tests: every case drives the real
``system_health_agent.run_health_check(dry_run=True, now=<fixed instant>)`` loop with a fake DB
connection and a temporary project tree, so the assertion fails if the wiring (the schedule resolver,
the fixed clock, the fallback marker or the row built for the operator) is broken - not merely if a
projection helper changes. Nothing here reads the live DB, the network, :7777 or a provider, and
``dry_run=True`` means the loop sends and writes nothing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

_spec = importlib.util.spec_from_file_location("health_agent_under_test", ROOT / "scripts" / "system_health_agent.py")
health = importlib.util.module_from_spec(_spec)
sys.modules["health_agent_under_test"] = health
_spec.loader.exec_module(health)  # type: ignore[union-attr]

ET = ZoneInfo("America/New_York")
ORCHESTRATOR = dict(next(c for c in health.MONITORED_COMPONENTS if c["component"] == "trade_ai_orchestrator"))

# The ACTIVE lane's slot, and the fixture instants, in UTC. The US DST change was 2026-11-01, so these
# November dates are EST (UTC-5): Friday 17:31 ET = 22:31Z, Saturday 10:00 ET = 15:00Z.
FRIDAY_RUN = datetime(2026, 11, 6, 17, 31, tzinfo=ET)
SATURDAY = datetime(2026, 11, 7, 10, 0, tzinfo=ET)
MONDAY_AFTER_MISSED_FIRE = datetime(2026, 11, 9, 18, 30, tzinfo=ET)


def _utc(stamp: datetime) -> datetime:
    return stamp.astimezone(timezone.utc)


class StubCursor:
    """The few cursor operations the loop performs; no live database is reachable."""

    rowcount = 0
    description: list = []

    def __init__(self):
        self.statements: list = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class StubConn:
    """A DB connection that records SQL and returns empty results."""

    closed = 0

    def __init__(self):
        self.statements: list = []
        self.cursors: list = []
        self.commits = 0

    def cursor(self, *args, **kwargs):
        cur = StubCursor()
        self.cursors.append(cur)
        self.statements = cur.statements  # the last cursor's SQL is enough for these tests
        return cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = 1


def _no_live_side_effects(monkeypatch):
    """Fail the test if anything reaches an alert transport or spawns a process."""
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda *a, **k: pytest.fail("a dry-run health check must not send an alert")
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)

    def forbid_subprocess(*a, **k):
        pytest.fail("the isolated health loop must not spawn a process")

    monkeypatch.setattr(health.subprocess, "run", forbid_subprocess)

    # The stop-monitoring collector shells out to broker sync scripts on a real host; in the isolated
    # loop it is stubbed, so a dry run never touches a provider. A module-level stub wins over the
    # function-local `from lib.stop_monitoring_health import ...`.
    stop = types.ModuleType("lib.stop_monitoring_health")
    stop.run_stop_monitoring_health = lambda conn=None, apply=True: {"alerts": [], "diagnosis": {}}
    monkeypatch.setitem(sys.modules, "lib.stop_monitoring_health", stop)


def _project(tmp_path: Path, monkeypatch, *, log_mtime: datetime, registry: dict | None = None) -> Path:
    """A temporary served tree: its own logs, state root and (optionally) lane registry."""
    monkeypatch.setattr(health, "PROJECT_ROOT", tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    state = tmp_path / "state"
    (state / "logs").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    # Bound at import to the real project root; point it at the fixture tree so nothing real is read.
    monkeypatch.setattr(health, "SAFE_FLOCK_LOG", logs / "safe_flock_events.jsonl")
    if registry is not None:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "lane_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    log = logs / "screener_pm.log"
    log.write_text("run complete\n", encoding="utf-8")
    stamp = log_mtime.timestamp()
    os.utime(log, (stamp, stamp))
    return log


def _drive(monkeypatch, now: datetime, comp: dict | None = None):
    """Run the real loop at a fixed clock with only the orchestrator monitored."""
    monkeypatch.setattr(health, "MONITORED_COMPONENTS", [dict(comp or ORCHESTRATOR)])
    conn = StubConn()
    monkeypatch.setattr(health, "_get_conn", lambda: conn)
    _no_live_side_effects(monkeypatch)
    report = health.run_health_check(dry_run=True, verbose=False, now=_utc(now))
    row = next(c for c in report["checks"] if c["component"] == "trade_ai_orchestrator")
    return report, row, conn


# ---------------------------------------------------------------- 1. a weekend is not stale
def test_weekend_check_is_ok_because_nothing_was_due(tmp_path, monkeypatch):
    """Last success Friday 17:31 ET, now Saturday 10:00 ET: the wall-clock rule said STALE."""
    _project(tmp_path, monkeypatch, log_mtime=FRIDAY_RUN)
    report, row, _ = _drive(monkeypatch, SATURDAY)

    assert row["status"] == "OK", row["freshness_evidence"]
    # The schedule judged was the ACTIVE lane's weekday slot, not a 180-minute wall clock, and the
    # decision was taken at the supplied instant (the loop must pass `now` into freshness, not fall
    # back to the host wall clock).
    assert row["freshness_evidence"]["reason"] == "schedule_fresh"
    assert row["freshness_evidence"]["observed_at"] == _utc(SATURDAY).isoformat()
    assert report["summary"]["stale"] == 0


# ---------------------------------------------------------------- 2. a missed fire is stale
def test_a_missed_monday_fire_is_stale(tmp_path, monkeypatch):
    """Friday's run, checked Monday 18:30 ET after Monday's 17:30 fire never happened."""
    _project(tmp_path, monkeypatch, log_mtime=FRIDAY_RUN)
    report, row, _ = _drive(monkeypatch, MONDAY_AFTER_MISSED_FIRE)

    assert row["status"] == "STALE", row["freshness_evidence"]
    assert row["freshness_evidence"]["reason"] == "scheduled_success_missing"
    assert report["summary"]["stale"] == 1


# ---------------------------------------------------------------- 3. a fallback is visible
@pytest.mark.parametrize(
    "registry_text,reason_token,human_reason",
    [
        (
            "{not json",
            "source_registry_unavailable",
            "the lane registry could not be read",
        ),
        (
            json.dumps(
                {
                    "schema": "LaneRegistry@v1",
                    "lanes": [
                        {
                            "lane_id": "orchestrator-slot",
                            "state": "ACTIVE",
                            "scheduler": {"kind": "cron", "schedules": ["30 17 * * 1-5"]},
                        }
                    ],
                }
            ),
            "source_mapping_missing_or_ambiguous",
            "the mapped lane is missing or ambiguous",
        ),
    ],
)
def test_a_fallback_is_visible_on_the_row(tmp_path, monkeypatch, registry_text, reason_token, human_reason):
    """The resolver falls back to the literal, and the row says why instead of pretending to resolve."""
    _project(tmp_path, monkeypatch, log_mtime=FRIDAY_RUN)
    config = tmp_path / "config"
    config.mkdir()
    (config / "lane_registry.json").write_text(registry_text, encoding="utf-8")

    report, row, _ = _drive(monkeypatch, SATURDAY)

    assert row["status"] == "OK", row["freshness_evidence"]
    # The real reason travels on the field the operator surface renders - not a hardcoded claim.
    error = row["last_error"] or ""
    assert "fallback" in error.lower()
    assert human_reason in error or reason_token in error
    # The schedule cell must not read as a healthy resolved schedule.
    assert "NOT MEASURED" in row["schedule"]
    assert human_reason in row["schedule"]
    assert "corrected" not in row["schedule"]
    assert row["schedule"] != ORCHESTRATOR["schedule"]


# ---------------------------------------------------------------- 4. the alert names the real reason
@pytest.mark.parametrize(
    "resolved_from,reason",
    [
        ("literal_fallback:source_registry_unavailable", "the lane registry could not be read"),
        ("literal_fallback:source_mapping_missing_or_ambiguous", "the mapped lane is missing or ambiguous"),
    ],
)
def test_the_escalation_names_the_fallback_with_its_real_reason(resolved_from, reason, monkeypatch):
    comp = {
        "component": "trade_ai_orchestrator",
        "display": "Trade AI Orchestrator",
        "schedule": "30 17 * * 1-5",
        "schedule_resolved_from": resolved_from,
        "critical": True,
    }
    sent = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda message, **kwargs: sent.append(message) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)

    class Conn(StubConn):
        def cursor(self, *a, **k):
            cur = super().cursor(*a, **k)
            cur.fetchone = lambda: [0]  # no prior escalation to dedupe against
            return cur

    health._escalate(
        comp,
        {"status": "STALE", "freshness_evidence": {"success_at": "2026-11-06T22:31:00+00:00"}},
        Conn(),
    )

    assert len(sent) == 1
    expected = f"Expected: 30 17 * * 1-5 (fallback — {reason})"
    assert expected in sent[0], sent[0]
    # The old text always blamed an unreadable registry; a different real reason must not say that.
    if "registry" not in reason:
        assert "the lane registry could not be read" not in sent[0]


# ---------------------------------------------------------------- 5. a list schedule renders as a list
def test_a_list_schedule_is_json_free_on_the_row(tmp_path, monkeypatch):
    """Two ACTIVE lanes produce a schedule list; it must render `A | B`, never a Python repr."""
    registry = {
        "schema": "LaneRegistry@v1",
        "lanes": [
            {"lane_id": "list-am", "state": "ACTIVE", "scheduler": {"kind": "cron", "schedules": ["30 17 * * 1-5"]}},
            {"lane_id": "list-pm", "state": "ACTIVE", "scheduler": {"kind": "cron", "schedules": ["0 12 * * 1-5"]}},
        ],
    }
    comp = dict(ORCHESTRATOR)
    comp.pop("declared_schedule", None)
    comp["monitor_lane_ids"] = ["list-am", "list-pm"]
    _project(tmp_path, monkeypatch, log_mtime=FRIDAY_RUN, registry=registry)

    _report, row, _ = _drive(monkeypatch, SATURDAY, comp=comp)

    rendered = "30 17 * * 1-5 | 0 12 * * 1-5"
    assert row["schedule"] == rendered
    assert "[" not in row["schedule"] and "', '" not in row["schedule"]
    resolved = health._resolve_component_schedule(comp)
    assert resolved["schedule"] == ["30 17 * * 1-5", "0 12 * * 1-5"]
    assert health.schedule_expected_line(resolved) == rendered
