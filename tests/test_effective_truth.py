#!/usr/bin/env python3
"""effective_truth — a configured intention is not a running fact.

Behavioural pins for FeatureFlagTruth@v1, SchedulerTruth@v1 and
FinvizStoreHealth@v1.

The store tests run entirely on temporary files. Scheduler tests parse strict
synthetic command snapshots. Nothing here calls host scheduling tools or enables,
disables, starts, stops or edits a unit, a cron entry, a flag or a cache.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import effective_truth as et  # noqa: E402

NOW = datetime(2026, 9, 3, 20, 0, 0, tzinfo=timezone.utc)


# ── feature flags ────────────────────────────────────────────────────────────


def test_flags_report_declared_and_effective_side_by_side():
    rep = et.feature_flag_truth(ROOT)
    if rep.get("status") == "UNAVAILABLE":
        pytest.skip(f"active_trader.feature_flags unavailable: {rep['reason']}")
    assert rep["schema"] == "FeatureFlagTruth@v1"
    assert rep["flag_count"] >= 5
    for f in rep["flags"]:
        assert "declared" in f and "effective" in f
        assert f["agrees"] == (bool(f["declared"]) == bool(f["effective"]))


def test_the_live_session_flag_is_reported_as_hard_locked():
    """The one flag whose wrong direction is dangerous."""
    rep = et.feature_flag_truth(ROOT)
    if rep.get("status") == "UNAVAILABLE":
        pytest.skip("feature flags unavailable")
    live = next(f for f in rep["flags"] if f["flag"] == "active_trader_live_session_enabled")
    assert live["hard_locked_off"] is True
    assert live["effective"] is False, "a live session must never read as effective from config"


def test_a_config_that_tries_to_enable_the_locked_flag_shows_a_delta(tmp_path, monkeypatch):
    cfg = tmp_path / "flags.json"
    cfg.write_text(json.dumps({"flags": {"active_trader_live_session_enabled": True}}))
    monkeypatch.setenv("ACTIVE_TRADER_FLAGS", str(cfg))
    rep = et.feature_flag_truth(ROOT)
    if rep.get("status") == "UNAVAILABLE":
        pytest.skip("feature flags unavailable")
    live = next(f for f in rep["flags"] if f["flag"] == "active_trader_live_session_enabled")
    assert live["declared"] is True
    assert live["effective"] is False
    assert live["agrees"] is False
    assert "coerced" in live["delta_reason"]
    assert rep["delta_count"] >= 1


# ── schedulers ───────────────────────────────────────────────────────────────


@pytest.fixture
def scheduler_snapshot(monkeypatch):
    """Run the real collectors/parsers against a closed synthetic command set."""
    prefix = ("systemctl", "--user", "--no-pager")
    responses = {
        (*prefix, "list-unit-files", "--type=timer", "--plain"): "live.timer enabled\noff.timer disabled\n",
        (
            *prefix,
            "show",
            "--property=Id,ActiveState,UnitFileState,NextElapseUSecRealtime,NextElapseUSecMonotonic,LastTriggerUSec,Unit",
            "live.timer",
            "off.timer",
        ): (
            "Id=live.timer\nUnit=live.service\nActiveState=active\nUnitFileState=enabled\n"
            "NextElapseUSecRealtime=\nNextElapseUSecMonotonic=42\nLastTriggerUSec=n/a\n\n"
            "Id=off.timer\nUnit=off.service\nActiveState=inactive\nUnitFileState=disabled\n"
            "NextElapseUSecRealtime=\nNextElapseUSecMonotonic=0\nLastTriggerUSec=n/a\n"
        ),
        (
            *prefix,
            "show",
            "--property=Id,ActiveState,Result,ExecMainStatus,ExecMainExitTimestamp",
            "live.service",
            "off.service",
        ): (
            "Id=live.service\nActiveState=failed\nResult=exit-code\nExecMainStatus=1\nExecMainExitTimestamp=\n\n"
            "Id=off.service\nActiveState=inactive\nResult=success\nExecMainStatus=0\nExecMainExitTimestamp=\n"
        ),
        ("crontab", "-l"): "# synthetic fixture\n*/5 * * * * /bin/true\n# 10 2 * * * /bin/false\n",
    }
    calls, unexpected = [], []

    def run(command, **kwargs):
        argv = tuple(command)
        expected_kwargs = {"capture_output": True, "text": True, "timeout": 60 if argv == ("crontab", "-l") else 120}
        if not isinstance(command, list) or argv not in responses or kwargs != expected_kwargs:
            unexpected.append((argv, kwargs))
            raise AssertionError("unexpected scheduler fixture command")
        calls.append(argv)
        return subprocess.CompletedProcess(command, 0, stdout=responses[argv], stderr="")

    monkeypatch.setattr(et.subprocess, "run", run)
    yield calls
    # Collectors catch command errors in production. A swallowed fixture refusal
    # must still fail its test rather than produce a vacuous empty snapshot.
    assert not unexpected, unexpected
    assert calls == list(responses), calls


def test_scheduler_truth_distinguishes_the_failure_modes(scheduler_snapshot):
    rep = et.scheduler_truth()
    assert rep["schema"] == "SchedulerTruth@v1"
    assert rep["timer_unit_files"] == 2
    assert rep["timers_inspected"] == rep["timer_unit_files"]
    assert rep["disabled_timers"] == ["off.timer"]
    assert rep["timers_with_failed_last_run"] == ["live.timer"]
    assert "live.timer" not in rep["enabled_timers_with_no_next_elapse"]
    assert rep["cron_active_entries"] == 1 and rep["cron_commented_out_jobs"] == 1
    for key in (
        "disabled_timers",
        "enabled_timers_with_no_next_elapse",
        "enabled_timers_never_triggered",
        "timers_with_failed_last_run",
    ):
        assert isinstance(rep[key], list)


def test_a_disabled_timer_is_not_counted_as_running(scheduler_snapshot):
    rep = et.scheduler_truth()
    disabled = set(rep["disabled_timers"])
    assert disabled == {"off.timer"}
    for row in rep["timers"]:
        if row["timer"] in disabled:
            assert row["enabled"] is False


def test_a_monotonic_timer_is_not_reported_as_having_no_next_elapse(scheduler_snapshot):
    """The trap: reading only NextElapseUSecRealtime flags every OnUnitActiveSec timer."""
    rep = et.scheduler_truth()
    assert any(row["next_elapse_monotonic"] == "42" for row in rep["timers"])
    for row in rep["timers"]:
        if row["next_elapse_monotonic"] not in (None, "", "0"):
            assert row["next_is_absent"] is False


# ── Finviz store ─────────────────────────────────────────────────────────────


def test_a_missing_store_is_uncached_not_broken(tmp_path):
    rep = et.finviz_store_health(tmp_path / "nope.json", now=NOW)
    assert rep["state"] == et.UNCACHED
    assert "not a provider failure" in rep["reason"]


def test_unparseable_json_is_broken_not_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{ not json")
    rep = et.finviz_store_health(p, now=NOW)
    assert rep["state"] == et.BROKEN_STORE
    assert "does not parse" in rep["reason"]


def test_a_store_with_no_meta_is_broken_because_its_age_is_unknowable(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"AAPL": {"price": 1}}))
    rep = et.finviz_store_health(p, now=NOW)
    assert rep["state"] == et.BROKEN_STORE
    assert rep["symbol_count"] == 1
    assert rep["age_hours"] is None


def test_fresh_and_stale_are_separated_by_the_window(tmp_path):
    for delta_h, expected in ((1.0, et.CACHED_FRESH), (6.0, et.CACHED_STALE), (99.0, et.CACHED_STALE)):
        p = tmp_path / f"c{delta_h}.json"
        stamp = (NOW - timedelta(hours=delta_h)).isoformat()
        p.write_text(json.dumps({"_meta": {"last_updated": stamp}, "AAPL": {}, "MSFT": {}}))
        rep = et.finviz_store_health(p, now=NOW, stale_after_hours=6.0)
        assert rep["state"] == expected, f"{delta_h}h -> {rep['state']}"
        assert rep["symbol_count"] == 2


def test_the_repo_et_timestamp_format_is_not_called_broken(tmp_path):
    """`2026-09-03 15:30:02 ET` is what the producer writes; an ISO-only parser
    would report a four-minute-old store as BROKEN — a manufactured defect."""
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"_meta": {"last_updated": "2026-09-03 15:30:02 ET"}, "AAPL": {}}))
    rep = et.finviz_store_health(p, now=datetime(2026, 9, 3, 19, 34, 0, tzinfo=timezone.utc))
    assert rep["state"] == et.CACHED_FRESH
    assert rep["age_hours"] is not None and rep["age_hours"] < 1


def test_a_genuinely_unparseable_stamp_is_still_broken(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"_meta": {"last_updated": "whenever"}, "AAPL": {}}))
    rep = et.finviz_store_health(p, now=NOW)
    assert rep["state"] == et.BROKEN_STORE
    assert "not a parseable timestamp" in rep["reason"]


def test_a_json_array_is_broken_not_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1,2,3]")
    rep = et.finviz_store_health(p, now=NOW)
    assert rep["state"] == et.BROKEN_STORE
    assert "not an object" in rep["reason"]


# ── the contracts are wired into the served route table ─────────────────────


@pytest.mark.parametrize(
    "route",
    [
        "/api/v2/system/feature-flag-truth",
        "/api/v2/system/scheduler-truth",
        "/api/v2/data-sources/finviz/store-health",
    ],
)
def test_contract_is_registered_in_the_route_table(route):
    """A contract that is defined but unrouted is a filing cabinet (AGENTS.md 13.5)."""
    assert f'"{route}"' in (ROOT / "scripts" / "api_v2.py").read_text(errors="replace")


def test_the_effective_truth_wrapper_fails_closed():
    import ast

    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_bytes())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_effective_truth_block")
    src = ast.dump(fn)
    assert "UNAVAILABLE" in src and "reason" in src
    assert any(isinstance(h, ast.ExceptHandler) for h in ast.walk(fn))


# ── read-only ────────────────────────────────────────────────────────────────


def test_the_module_never_changes_a_unit_or_a_flag():
    src = (ROOT / "scripts" / "lib" / "effective_truth.py").read_text()
    # The module shells out to systemctl and crontab; the pin is that it only ever
    # asks them what they already are. Verbs are checked as argv tokens, because
    # that is how they are actually passed.
    for verb in ("enable", "disable", "start", "stop", "restart", "reload", "kill", "edit"):
        assert f'"{verb}"' not in src, f"read-only module passes systemctl {verb}"
    assert '"crontab", "-l"' in src, "crontab is only ever listed"
    for banned in ("write_text", "unlink", "rmtree", "os.system", "mkdir"):
        assert banned not in src, f"read-only module contains {banned!r}"
    assert et.AUTHORITY == "READ_ONLY_ADVISORY"
