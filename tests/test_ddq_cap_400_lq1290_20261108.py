"""LQ-20261107-1290: due_diligence_questions request cap 200 -> 400 in every write site.

The lane's n8n path asks 5 questions per slot at a 20-minute cadence: 72 slots in a weekend day is
360 requests, so a 200/day soft cap refuses the Saturday and Sunday afternoon slots outright. The
operator approved 400 on 2026-11-08 19:07 ET ("raise it to whatever you need for the weekdays and the
weekend") and the live DB was raised through llm_cap_admin at 19:10:39 ET (DDQ-REQUEST-CAP-400.txt).

Nothing in the runtime reads this value from one place:

  * ``scripts/lib/llm_consumption.sync_process_policies_from_registry`` seeds the DB from
    ``config/llm_process_registry.json`` with ``daily_soft_cap = COALESCE(EXCLUDED, existing)``, so the
    registry value WINS over the DB on every deploy;
  * ``scripts/sync_cio_process_caps.py`` overwrites the same column from its CAPS dict.

A raise applied to only one of them (or only to the DB) reverts on the next sync or deploy. These tests
pin 400 in both writers, prove they agree, and prove the dollar cap the operator said to leave alone
is untouched.

COVERS = ["config/llm_process_registry.json", "scripts/sync_cio_process_caps.py"]
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import sync_cio_process_caps as sync

ROOT = Path(__file__).resolve().parents[1]
PID = "due_diligence_questions"
NEW_SOFT_CAP = 400
#: 5 questions x 72 slots = 360 on a weekend day; 400 = 360 + ~10%.
WEEKEND_NEED = 5 * 72
#: 2026-11-07 21:08 ET operator directive (LQ-20261107-538): "Leave the cap at 1.50".
UNCHANGED_DOLLAR_CAP = 1.50


def _registry_row() -> dict:
    doc = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    for row in doc["processes"]:
        if row.get("id") == PID:
            return row
    raise AssertionError(f"{PID} is not registered")


def test_registry_carries_the_400_request_cap() -> None:
    row = _registry_row()
    assert row["daily_soft_cap"] == NEW_SOFT_CAP
    # 400 must actually cover the weekend slot count the lane asks for.
    assert row["daily_soft_cap"] >= WEEKEND_NEED


def test_sync_caps_matches_the_registry() -> None:
    """The second writer must not revert the registry on its next run."""
    assert sync.CAPS[PID] == (UNCHANGED_DOLLAR_CAP, NEW_SOFT_CAP)
    cost, soft = sync.CAPS[PID]
    row = _registry_row()
    assert (cost, soft) == (row["daily_cost_cap_usd"], row["daily_soft_cap"])


def test_dollar_cap_is_unchanged() -> None:
    assert sync.CAPS[PID][0] == UNCHANGED_DOLLAR_CAP
    assert _registry_row()["daily_cost_cap_usd"] == UNCHANGED_DOLLAR_CAP


def test_the_raise_is_dated_in_the_registry_notes() -> None:
    """The row records why 400, not only that it is 400."""
    notes = _registry_row().get("notes") or ""
    assert "LQ-20261107-1290" in notes
    assert "360" in notes
