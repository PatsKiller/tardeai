"""Admission invariants for the 06:00-11:55 ET Finviz momentum-scalp lane.

These tests describe the safe candidate shape without adding the lane to the live registry,
allowlist, or n8n. In particular, the extant host command's ``--submit-validation`` flag is
not admissible for dispatcher execution. No network, database, n8n, broker, or scheduler I/O.
"""
from __future__ import annotations

import copy
import json
import shlex
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from scripts import build_n8n_health_contracts as B  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import cron_schedule as CS  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402

LANE = "finviz-momentum-scalp-early-lane"
ET = ZoneInfo("America/New_York")
SCHEDULE = "*/5 6-11 * * 1-5"
LOCK = "/tmp/tradeai_finviz_momentum_scalp.lock"
COMMAND = ["$PY", "scripts/run_finviz_momentum_scalp_scan.py"]
LIVE_ARGS = [
    "--window", "early", "--apply", "--refresh-if-older-min", "15",
    "--sync-signals", "--generate-proposals", "--run-validation-fast-path",
]


def _candidate():
    """The proposed dispatcher entry and source twin; deliberately not persisted to config."""
    source_command = (
        "cd $PROJ && flock -n " + LOCK + " timeout 280 env MOMENTUM_SCALP_OUTER_DEADLINE_S=260 "
        "$PY scripts/run_finviz_momentum_scalp_scan.py " + shlex.join(LIVE_ARGS)
    )
    row = {
        "lane_id": LANE,
        "owner": "scalp",
        "state": "ACTIVE",
        "expected_cadence_hours": 1 / 12,
        "scheduler": {
            "kind": "cron",
            "expression": SCHEDULE,
            "command_text": source_command,
            "match": "scripts/run_finviz_momentum_scalp_scan.py",
            "stage": "shadow",
        },
        "output_signal": {"kind": "file_mtime", "path": "data/runtime/finviz-momentum-scalp-early-lane_last.json"},
        "dispatch": {
            "mode": "dry_run",
            "cron": [SCHEDULE],
            "tz": "America/New_York",
            "wave": "W5",
            "class": "pipeline",
            "priority": 2,
            "retry_policy": "transient-2",
        },
    }
    entry = {
        "lane_id": LANE,
        "command": COMMAND,
        "dry_run_arg": ["--dry-run"],
        "live_arg": LIVE_ARGS,
        "lock": LOCK,
        "lock_kind": "flock",
        "timeout_s": 280,
        "market_gate": False,
        "output_signal": "data/runtime/finviz-momentum-scalp-early-lane_last.json",
    }
    return row, entry, source_command


def test_submit_validation_in_source_command_is_refused():
    row, _entry, _source = _candidate()
    unsafe = copy.deepcopy(row)
    unsafe["scheduler"]["command_text"] += " --submit-validation"
    assert LD.dispatch_eligible(unsafe)[0] is False
    assert "submit" in LD.dispatch_eligible(unsafe)[1]


def test_safe_candidate_argv_matches_source_lock_and_timeout():
    row, entry, source = _candidate()
    assert "--submit-validation" not in source
    assert X.validate_entry(entry) is None
    assert LD.dispatch_eligible(row)[0] is True

    # The host twin and dispatcher entry must call the same script with the same business argv.
    source_tokens = shlex.split(source)
    source_py_script = source_tokens[source_tokens.index("$PY"):]
    assert source_py_script == [*entry["command"], *entry["live_arg"]]

    # Both schedulers serialize against one lock; host and executor timeout are identical.
    assert source_tokens[source_tokens.index("flock") + 2] == entry["lock"]
    assert source_tokens[source_tokens.index("timeout") + 1] == str(entry["timeout_s"])
    argv = X.build_argv(entry, "live", env={"TRADEAI_VENV_PYTHON": "/venv/bin/python"},
                        state_root=Path("/state"), code_root=Path("/code"))
    assert argv is not None
    assert argv[:5] == ["flock", "-n", "-E", str(X.FLOCK_CONFLICT_EXIT), LOCK]
    assert argv[5:9] == ["timeout", "-k", str(X.KILL_AFTER_S), "280"]
    assert argv[9:] == ["/venv/bin/python", *entry["command"][1:], *LIVE_ARGS]


@pytest.mark.parametrize(
    "day",
    [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)],
)
def test_dispatcher_schedule_has_exact_weekday_slots(day):
    start = datetime.combine(day, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
    end = datetime.combine(day.replace(day=day.day + 1), datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
    fires = CS.fires_between(SCHEDULE, start, end, "America/New_York")
    local = [fire.at.astimezone(ET) for fire in fires]
    assert len(local) == 72
    assert [t.strftime("%H:%M") for t in local] == [
        f"{hour:02d}:{minute:02d}" for hour in range(6, 12) for minute in range(0, 60, 5)
    ]
    assert all(t.date() == day and t.weekday() < 5 for t in local)


@pytest.mark.parametrize("day", [date(2026, 10, 10), date(2026, 10, 11)])
def test_dispatcher_schedule_has_no_weekend_slots(day):
    start = datetime.combine(day, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
    end = datetime.combine(day.replace(day=day.day + 1), datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
    assert CS.fires_between(SCHEDULE, start, end, "America/New_York") == []


def test_dispatcher_schedule_has_no_off_window_slots():
    row, _entry, _source = _candidate()
    block = LD.parse_dispatch_block(row)
    assert block is not None and block.tz == "America/New_York" and block.cron == (SCHEDULE,)
    start = datetime(2026, 10, 12, 0, 0, tzinfo=ET).astimezone(timezone.utc)
    end = datetime(2026, 10, 13, 0, 0, tzinfo=ET).astimezone(timezone.utc)
    local = [f.at.astimezone(ET) for f in CS.fires_between(block.cron[0], start, end, block.tz)]
    assert local and all(6 <= t.hour <= 11 and t.minute % 5 == 0 for t in local)
    assert not any(t.hour == 12 for t in local)


def test_new_lane_contract_is_complete_but_remains_draft_without_owner_review():
    row, entry, _source = _candidate()
    contract = B.lane_contract(LANE, "stage:shadow", row, entry, None, None, frozenset(), [], date(2026, 10, 13))
    assert contract["status"] == "DRAFT"
    assert contract["id"] == LANE
    assert contract["purpose"]["text"] == H.UNKNOWN
    assert contract["owner"] == "scalp"
    assert contract["connects_to"]
    assert contract["healthy"] and contract["degraded"] and contract["failed"]
    assert contract["baseline"]["timeout_s"] == 280
    assert contract["alerting"]["degraded"]["notifier_priority"]
    assert contract["alerting"]["failed"]["notifier_priority"]
    assert H.unknown_fields(contract)  # missing owner-supplied semantics stay visible, not fabricated
    assert H.validate_contract(contract) == []

    contracts = {"contracts": [contract], "grandfathered_draft": []}
    registry = {"lanes": [row]}
    result = H.check(contracts, registry, {"workflows": []}, today=date(2026, 10, 13))
    assert any(error.startswith(f"DRAFT_NOT_GRANDFATHERED {LANE}") for error in result["errors"])
