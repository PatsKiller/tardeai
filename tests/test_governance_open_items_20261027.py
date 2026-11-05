"""docs/governance/OPEN_ITEMS.md: every known gap has an owner and a review date (AGENTS.md 26.0.0).

Hermetic: reads the committed register and synthetic strings only.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_open_items as coi  # noqa: E402

HEADER = "| " + " | ".join(coi.COLUMNS) + " |\n|" + "---|" * len(coi.COLUMNS) + "\n"
GOOD = "| OI-001 | High | Something is broken | platform | 2026-11-03 | Fix now | open | #1 | AGENTS.md §7 |\n"


def test_committed_register_is_valid():
    text = (ROOT / "docs" / "governance" / "OPEN_ITEMS.md").read_text(encoding="utf-8")
    assert coi.validate(text) == []
    assert len(coi.parse_rows(text)) >= 30, "the register should carry every known gap moved out of AGENTS.md"


def test_good_row_passes():
    assert coi.validate(HEADER + GOOD) == []


def test_missing_owner_fails():
    bad = GOOD.replace("| platform |", "|  |")
    assert any("owner" in e for e in coi.validate(HEADER + bad))


def test_unknown_owner_fails():
    bad = GOOD.replace("| platform |", "| nobody |")
    assert any("owner" in e for e in coi.validate(HEADER + bad))


def test_missing_review_date_fails():
    bad = GOOD.replace("| 2026-11-03 |", "| soon |")
    assert any("review date" in e for e in coi.validate(HEADER + bad))


def test_duplicate_id_fails():
    assert any("duplicate" in e for e in coi.validate(HEADER + GOOD + GOOD))


def test_done_needs_a_fix_reference():
    bad = GOOD.replace("| open | #1 |", "| done | — |")
    assert any("done without" in e for e in coi.validate(HEADER + bad))


def test_no_table_fails():
    assert coi.validate("# OPEN_ITEMS\n\nnothing here\n")


def test_overdue_reports_open_rows_past_review():
    rows = coi.overdue(HEADER + GOOD, dt.date(2026, 11, 4))
    assert [r["ID"] for r in rows] == ["OI-001"]
    assert coi.overdue(HEADER + GOOD, dt.date(2026, 11, 3)) == []
