"""Consumption evidence must not be overstated (defect 15).

Written by the integration owner at INTEGRATION_ORDER.md step 11. The campaign's
own history is the reason: the audited "consumption receipts = 4" baseline was
four orphan rows referencing events that never existed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib.campaign_interfaces import (  # noqa: E402
    USABLE_RECEIPT_SQL,
    is_usable_consumption_receipt,
)


def _row(**kw):
    base = {"policy_decision": None, "effect_kind": "changed_question", "effect_ref": "q1"}
    base.update(kw)
    return base


def test_tombstoned_receipts_never_count():
    for pd in ("TOMBSTONED_ORPHAN_EVENT_NOT_FOUND",
               "TOMBSTONED_NON_ORGANIC_TEST_ARTIFACT"):
        assert not is_usable_consumption_receipt(_row(policy_decision=pd))


def test_effect_none_is_honest_but_not_evidence():
    assert not is_usable_consumption_receipt(_row(effect_kind="none", effect_ref=None))


def test_effect_without_resolvable_ref_does_not_count():
    assert not is_usable_consumption_receipt(_row(effect_ref=None))


def test_a_real_effect_counts():
    assert is_usable_consumption_receipt(_row())


def test_the_five_production_rows_all_score_zero():
    """The exact rows in production on 2026-09-07, post-tombstone."""
    live = [
        {"policy_decision": "TOMBSTONED_ORPHAN_EVENT_NOT_FOUND", "effect_kind": None, "effect_ref": None},
        {"policy_decision": "TOMBSTONED_ORPHAN_EVENT_NOT_FOUND", "effect_kind": None, "effect_ref": None},
        {"policy_decision": "TOMBSTONED_ORPHAN_EVENT_NOT_FOUND", "effect_kind": None, "effect_ref": None},
        {"policy_decision": "TOMBSTONED_ORPHAN_EVENT_NOT_FOUND", "effect_kind": None, "effect_ref": None},
        {"policy_decision": "TOMBSTONED_NON_ORGANIC_TEST_ARTIFACT", "effect_kind": None, "effect_ref": None},
    ]
    assert sum(1 for r in live if is_usable_consumption_receipt(r)) == 0, (
        "post-tombstone the system has ZERO usable consumption receipts; any "
        "surface reporting otherwise is conflating receipt types (defect 15)"
    )


def test_sql_and_python_predicates_agree_on_shape():
    assert "TOMBSTONED%" in USABLE_RECEIPT_SQL
    assert "effect_kind <> 'none'" in USABLE_RECEIPT_SQL
    assert "effect_ref IS NOT NULL" in USABLE_RECEIPT_SQL
