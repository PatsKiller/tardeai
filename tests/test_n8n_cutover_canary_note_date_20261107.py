"""The canary note is dated by the run, not by a literal (LQ-20261107-35, lead 2026-11-07).

`canary_entry` wrote `" | <wave> 2026-10-15 (n8n_cutover_wave.py): canary — …"` into the allowlist
`source` note, and `canary_contract` defaulted its `state_note` date to the same literal — the day the
wave framework was written. Every wave after 2026-10-15 therefore stamped its canary with that old
date, so a reader could not tell a fresh canary from the framework's first day.

The date now comes from `run_date()` (UTC, the moment the tool runs). An explicit `date=` still wins:
`contract_canary` passes one, and its output must not change.

Every fixture here is synthetic: the repository is public.

ANCHOR: N8N_CUTOVER_CANARY_NOTE_DATE_20261107
"""

from __future__ import annotations

import sys
from datetime import date as dt_date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import n8n_cutover_wave as W  # noqa: E402

FRAMEWORK_DATE = "2026-10-15"


@pytest.fixture()
def run_day(monkeypatch):
    """Freeze the run date somewhere no literal could plausibly be, so a returning literal fails."""
    monkeypatch.setattr(W, "run_date", lambda: "2031-02-03")
    return "2031-02-03"


def _entry():
    return {"lane_id": "demo-lane", "command": ["$PY", "scripts/demo_lane.py"], "source": "test-source"}


def _parsed():
    return {"live_arg": ["--apply"]}


def _contract():
    return {
        "id": "demo-lane",
        "kind": "lane",
        "stage": "shadow",
        "healthy": [{"check": "shadow_dry_run_done", "text": "dry run ok"}],
        "state_note": "",
    }


# ── the allowlist source note ──────────────────────────────────────────────────────────────────


def test_the_canary_note_carries_the_run_date(run_day):
    note = W.canary_entry(_entry(), _parsed(), "/tmp/demo.lock", "OVN-9x")["source"]

    assert f"OVN-9x {run_day}" in note
    assert FRAMEWORK_DATE not in note


def test_an_explicit_date_still_wins_on_the_entry_note(run_day):
    note = W.canary_entry(_entry(), _parsed(), "/tmp/demo.lock", "OVN-9x", date="2026-10-16")["source"]

    assert "OVN-9x 2026-10-16" in note
    assert run_day not in note


def test_a_wave_already_named_in_the_source_is_not_appended_twice(run_day):
    entry = dict(_entry(), source="test-source | OVN-9x already recorded")

    assert W.canary_entry(entry, _parsed(), "/tmp/demo.lock", "OVN-9x")["source"] == entry["source"]


# ── the health-contract state note ─────────────────────────────────────────────────────────────


def test_the_contract_state_note_defaults_to_the_run_date(run_day):
    out = W.canary_contract(_contract(), "OVN-9x")

    assert out["stage"] == "canary"
    assert f"OVN-9x {run_day}: stage canary" in out["state_note"]
    assert FRAMEWORK_DATE not in out["state_note"]


def test_an_explicit_date_still_wins_on_the_contract_note(run_day):
    out = W.canary_contract(_contract(), "CH1", date="2026-10-16")

    assert "CH1 2026-10-16: stage canary" in out["state_note"]
    assert run_day not in out["state_note"]


# ── the source of the date ─────────────────────────────────────────────────────────────────────


def test_run_date_is_the_utc_day():
    parsed = dt_date.fromisoformat(W.run_date())

    # one day of slack: the clock may cross UTC midnight between the call and this assertion
    assert abs((parsed - datetime.now(timezone.utc).date()).days) <= 1
