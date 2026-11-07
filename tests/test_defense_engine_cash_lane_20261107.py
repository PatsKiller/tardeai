"""LQ-20261107-263: the Defense engine's cash source names its writer lane.

DEFAULTS gave "cash" an empty lane list, so the desk said "no scheduled writer" about a source that has had
an n8n lane (defense-cash-alternatives) since 2026-11-06. Synthetic values only.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import defense_engine as de  # noqa: E402
from lib import desks_a  # noqa: E402

NOW = datetime(2030, 1, 7, 15, 0, tzinfo=timezone.utc)


def test_cash_source_lane_matches_the_desk_map():
    assert de.DEFAULTS["sources"]["cash"][2] == desks_a.DEFENSE_LANES["cash"]


def test_stale_cash_file_reads_stale_not_no_writer():
    row = de.source_row("cash", "2029-12-01T00:00:00+00:00", de.DEFAULTS, {"defense-cash-alternatives": "ACTIVE"}, NOW)
    assert row["state"] == "stale" and row["lane_ids"] == ["defense-cash-alternatives"]


def test_paused_cash_writer_reads_paused():
    row = de.source_row("cash", None, de.DEFAULTS, {"defense-cash-alternatives": "PAUSED"}, NOW)
    assert row["state"] == "paused"
