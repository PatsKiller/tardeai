"""Actual fixer recovery readers agree with the shared verdict; temp ledgers only."""

from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from scripts import self_heal_fixer as S
from scripts.lib import recovery_validator as RV
from scripts.lib import self_heal_fixer as F

LANE = "fixture-output"
SINCE = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def good_row():
    rec = {
        "schema": "RunReceipt@v2",
        "lane_id": LANE,
        "run_id": "d:fixture-output:live:20261018T1300",
        "attempt": 1,
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "finished_at": "2026-10-18T13:00:00+00:00",
        "output_verdict": {"verdict": "produced", "contract_id": LANE},
    }
    return {
        **{k: rec[k] for k in ("lane_id", "run_id", "attempt", "mode", "state", "exit_code", "finished_at")},
        "receipt": rec,
    }


def variant(case):
    row = good_row()
    rec = row["receipt"]
    if case.startswith("inner_"):
        field = case.removeprefix("inner_")
        rec[field] = {
            "lane_id": "other-lane",
            "run_id": "other-run",
            "attempt": 2,
            "state": "RUN_FAILED",
            "exit_code": False,
            "finished_at": "2026-10-18T13:01:00+00:00",
        }[field]
    elif case == "future":
        row["finished_at"] = rec["finished_at"] = "2099-01-01T00:00:00+00:00"
    elif case == "naive":
        row["finished_at"] = rec["finished_at"] = "2026-10-18T13:00:00"
    elif case == "stale":
        row["finished_at"] = rec["finished_at"] = "2026-10-18T11:00:00+00:00"
    elif case == "wrong_contract":
        rec["output_verdict"]["contract_id"] = "other-lane"
    elif case == "requested_dry":
        row["mode"] = "dry_run"
    elif case == "effective_dry":
        rec["mode"] = "dry_run"
    elif case == "lock_skip":
        rec["lock_skipped"] = True
    elif case == "empty_allowed":
        rec["output_verdict"]["verdict"] = "empty_allowed"
    elif case != "good":
        raise AssertionError(case)
    return row


CASES = [
    "inner_lane_id",
    "inner_run_id",
    "inner_attempt",
    "inner_state",
    "inner_exit_code",
    "inner_finished_at",
    "future",
    "naive",
    "stale",
    "wrong_contract",
    "requested_dry",
    "effective_dry",
    "lock_skip",
    "good",
    "empty_allowed",
]


@pytest.mark.parametrize("case", CASES)
def test_pure_fixer_reader_cannot_disagree_with_shared_recovery(case):
    row = variant(case)
    shared, _ = RV.validate(row, mode="live", since=SINCE, lane=LANE)
    assert (F.receipt_meets_output_contract(row, SINCE) is None) is shared


def ledger(path, row, *, legacy=False):
    row = copy.deepcopy(row)
    row["receipt_json"] = json.dumps(row.pop("receipt"))
    if legacy:
        row.pop("attempt")
    with sqlite3.connect(path) as conn:
        columns = [
            "run_id TEXT PRIMARY KEY",
            "lane_id TEXT",
            "mode TEXT",
            "state TEXT",
            "exit_code INTEGER",
            "finished_at TEXT",
            "receipt_json TEXT",
        ]
        if not legacy:
            columns.append("attempt INTEGER")
        conn.execute("CREATE TABLE runs (" + ",".join(columns) + ")")
        fields = list(row)
        conn.execute(
            "INSERT INTO runs (" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ")",
            [row[x] for x in fields],
        )


@pytest.mark.parametrize("case", CASES)
def test_actual_fixer_ledger_reader_uses_same_authoritative_evidence(tmp_path, case):
    row = variant(case)
    path = tmp_path / "runs.sqlite"
    ledger(path, row)
    expected, _ = RV.validate(row, mode="live", since=SINCE, lane=LANE)
    result = S.output_recovered(LANE, SINCE, {"ledger": str(path), "kind": "live_receipt_output_verdict@v1"})
    assert result["recovered"] is expected


def test_fixer_adapter_obeys_the_shared_verdict_owner(monkeypatch):
    seen = []
    monkeypatch.setattr(RV, "validate", lambda row, **kwargs: seen.append((row, kwargs)) or (False, "review_refusal"))
    assert F.receipt_meets_output_contract(good_row(), SINCE) == "review_refusal"
    assert len(seen) == 1 and seen[0][1]["mode"] == "live"


def test_actual_reader_preserves_durable_attempt_and_lane_for_shared_owner(tmp_path, monkeypatch):
    row = good_row()
    path = tmp_path / "runs.sqlite"
    ledger(path, row)
    seen = []
    monkeypatch.setattr(RV, "validate", lambda row, **kwargs: seen.append((row, kwargs)) or (False, "review_refusal"))
    result = S.output_recovered(LANE, SINCE, {"ledger": str(path)})
    assert result["recovered"] is False
    assert len(seen) == 1
    assert seen[0][0]["attempt"] == 1 and seen[0][0]["lane_id"] == LANE
    assert seen[0][1]["lane"] == LANE


def test_supported_legacy_ledger_without_optional_attempt_remains_readable(tmp_path):
    row = good_row()
    row["receipt"].pop("attempt")
    path = tmp_path / "legacy.sqlite"
    ledger(path, row, legacy=True)
    assert S.output_recovered(LANE, SINCE, {"ledger": str(path)})["recovered"] is True


def test_missing_deployment_time_stays_unproven():
    assert F.receipt_meets_output_contract(good_row(), None) == "no_since"
