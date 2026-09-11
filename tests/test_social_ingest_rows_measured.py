#!/usr/bin/env python3
"""A pipeline must not report a row count it never measured.

`social_ingest.py` ended its successful run with

    run_complete(_run_id, rows_processed=0)

a hardcoded literal, while every ingest function it calls already returned an
`inserted` count that was thrown away. So the pipeline reported rows_produced=0
on every successful run regardless of what it wrote, and `pipeline_zero_rows`
alerted on it as a dead producer.

Measured 2026-09-11 against the live database:

    social_posts   761 rows inserted in the preceding 36h
    newest row     2026-09-10 10:30:37 ET
    last run       2026-09-10 10:30:02 ET   <- the run that reported ZERO

The 2026-09-06 remediation converted the sixteen scripts that relied on the
DEFAULT rows_processed=0. This one passed 0 EXPLICITLY, so it read as
deliberate and the sweep passed it over.

AGENTS.md: two states cannot express "no input". None means NOT MEASURED; 0
means measured and genuinely empty. Collapsing them leaves an alarm that can
neither fire on a real outage nor stop firing on a healthy pipeline.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SOURCE = (ROOT / "scripts" / "social_ingest.py").read_text(encoding="utf-8")

from scripts.social_ingest import rows_from_results  # noqa: E402


def test_counts_are_summed_not_assumed():
    assert rows_from_results([{"inserted": 5}, {"inserted": 7}]) == 12


def test_a_real_measured_zero_is_zero_not_unknown():
    """The pipeline ran and genuinely inserted nothing. That is 0, not null."""
    assert rows_from_results([{"inserted": 0}]) == 0


def test_nothing_reported_is_unknown_not_zero():
    """No producer reported a count at all -> NOT MEASURED, written as null.

    This is the distinction the hardcoded literal destroyed.
    """
    assert rows_from_results([]) is None
    assert rows_from_results([None, "nonsense", {"no_count": 1}]) is None


def test_partial_reporting_still_counts_what_was_measured():
    assert rows_from_results([{"inserted": 3}, {"no_count": 1}]) == 3


def test_missing_or_null_inserted_is_treated_as_zero_not_dropped():
    assert rows_from_results([{"inserted": None}]) == 0


def test_the_hardcoded_literal_is_gone():
    """Source-level guard against the exact line being reinstated.

    Asserted on the AST so a comment quoting the old call cannot satisfy it.
    """
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name != "run_complete":
            continue
        for kw in node.keywords:
            if kw.arg == "rows_processed":
                assert not (
                    isinstance(kw.value, ast.Constant) and kw.value.value == 0
                ), "run_complete(rows_processed=0) is a fabricated measurement"
