#!/usr/bin/env python3
"""setup_run_contract.py — one canonical GO/WAIT/NOGO summary (cc-header-truth-v2).

Pins the reconciliation invariants the header and Trading page must share:

* AVOID / NO_GO / NOGO / disqualified / unclassified / error are NOT synonyms;
* GO + WAIT + NOGO == classified_count;
* classified + excluded + unclassified must reconcile to the scanned population;
* a second disagreeing "scanned" claim degrades the summary to PARTIAL, never
  to an authoritative-looking RECONCILED.

No network, broker, scheduler, Drive, database or production path is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.setup_run_contract import (  # noqa: E402
    INTEGRITY_COUNT_MISMATCH,
    INTEGRITY_DATA_UNAVAILABLE,
    INTEGRITY_PARTIAL,
    INTEGRITY_RECONCILED,
    build_setup_run_summary,
    classify_decision,
    derive_run_id,
    tally_decisions,
)


# ── classification: a closed taxonomy, never "everything else is NOGO" ───────


@pytest.mark.parametrize(
    "decision,expected",
    [
        ("GO", "go"),
        ("BUY", "go"),
        ("LONG", "go"),
        ("wait", "wait"),
        ("HOLD", "wait"),
        ("AVOID", "nogo"),
        ("NO_GO", "nogo"),
        ("NOGO", "nogo"),
        ("SELL", "nogo"),
        ("", "unclassified"),
        (None, "unclassified"),
        ("totally-unexpected", "unclassified"),
    ],
)
def test_classify_decision_never_lumps_unknown_into_nogo(decision, expected):
    assert classify_decision(decision) == expected


def test_disqualified_row_is_excluded_even_when_decision_is_go():
    assert classify_decision("GO", disqualified=True) == "excluded"


# ── tally partition ──────────────────────────────────────────────────────────


def test_tally_partitions_every_row_into_exactly_one_class():
    rows = [
        {"decision": "GO"},
        {"decision": "WAIT"},
        {"decision": "AVOID"},
        {"decision": None},
        {"decision": "GO", "disqualified": True},
        {"decision": "NOGO"},
    ]
    t = tally_decisions(rows)
    assert sum(t.values()) == len(rows)
    assert t == {"go": 1, "wait": 1, "nogo": 2, "excluded": 1, "unclassified": 1}


# ── run id is deterministic ──────────────────────────────────────────────────


def test_derive_run_id_is_stable_for_the_same_run():
    a = derive_run_id("evening", "2026-09-03", "2026-09-03T02:00:00Z")
    b = derive_run_id("evening", "2026-09-03", "2026-09-03T02:00:00Z")
    assert a == b == "2026-09-03::evening"


def test_derive_run_id_falls_back_without_label_or_date():
    rid = derive_run_id("", "", "2026-09-03T02:00:00Z")
    assert rid.startswith("ts-")


# ── invariants ───────────────────────────────────────────────────────────────


def _reconciled_tally():
    return {"go": 2, "wait": 1, "nogo": 2, "excluded": 1, "unclassified": 1}


def test_go_plus_wait_plus_nogo_equals_classified_count():
    s = build_setup_run_summary(run_id="r", tally=_reconciled_tally(), scanned_count=7)
    assert s["go_count"] + s["wait_count"] + s["nogo_count"] == s["classified_count"] == 5
    assert s["count_integrity"] == INTEGRITY_RECONCILED


def test_missing_scanned_count_is_data_unavailable_not_reconciled():
    s = build_setup_run_summary(run_id="r", tally=_reconciled_tally())
    assert s["count_integrity"] == INTEGRITY_DATA_UNAVAILABLE
    assert s["count_integrity_reason"]


def test_count_mismatch_is_visible_not_authoritative():
    s = build_setup_run_summary(run_id="r", tally=_reconciled_tally(), scanned_count=80)
    assert s["count_integrity"] == INTEGRITY_COUNT_MISMATCH
    assert "80" in s["count_integrity_reason"]
    # the raw counts survive so a consumer can show what it knows
    assert s["scanned_count"] == 80 and s["classified_count"] == 5


def test_two_scanned_contracts_that_disagree_are_partial():
    s = build_setup_run_summary(run_id="r", tally=_reconciled_tally(), scanned_count=7, scanned_count_alt=80)
    assert s["count_integrity"] == INTEGRITY_PARTIAL
    assert s["count_integrity_reason"]


def test_zero_result_is_reconciled_not_an_error():
    s = build_setup_run_summary(
        run_id="r",
        tally={"go": 0, "wait": 0, "nogo": 0, "excluded": 0, "unclassified": 0},
        scanned_count=0,
        scanned_count_alt=0,
    )
    assert s["count_integrity"] == INTEGRITY_RECONCILED
    assert s["classified_count"] == 0


def test_summary_carries_the_full_contract_fields():
    s = build_setup_run_summary(
        run_id="r",
        tally=_reconciled_tally(),
        scanned_count=7,
        run_label="evening",
        run_date="2026-09-03",
        run_timestamp="2026-09-03T02:00:00Z",
        source="trade_ai_scans",
        freshness_status="RUN_HEALTHY",
        quality="OK",
    )
    for field in (
        "contract_version",
        "run_id",
        "run_label",
        "run_date",
        "run_timestamp",
        "source",
        "calculation_version",
        "scanned_count",
        "classified_count",
        "go_count",
        "wait_count",
        "nogo_count",
        "excluded_count",
        "unclassified_count",
        "reconciled_scanned",
        "freshness_status",
        "quality",
        "count_integrity",
    ):
        assert field in s, f"missing contract field {field}"
