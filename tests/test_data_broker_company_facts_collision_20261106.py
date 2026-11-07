"""Company facts survive a judged-prospect collision when one fact-only sibling exists (2026-11-06).

HELD + WATCH prospects for one GUID is a judgment conflict. It must stay visible on the review
lifecycle, but it must not blank the company facts that live on the fact-only SECURITY record:
that dropped direct stocks out of Look-through and Allocation. Synthetic fixtures only.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import cio_instrument_record as ir  # noqa: E402
from scripts.lib.data_broker import cio_company_facts as broker  # noqa: E402
from test_cio_company_facts_20261024 import AT, GUID, IDENT, NOW, facts  # noqa: E402


def _judged(store):
    for kind, stage, stance in (("HELD", "held", "HOLD"), ("WATCH", "watching", "WATCH")):
        rec = ir.new_record(kind, "ACME", symbols=["ACME"], **IDENT)
        rec, _ = ir.apply_prospect(rec, prospect={
            "stage": stage, "stance": stance, "conviction": 61,
            "evidence_at": AT, "expires_at": (NOW + timedelta(days=1)).isoformat(),
        })
        store.upsert(rec)


def _fact_only(store):
    rec = ir.new_record("SECURITY", "ACME", symbols=["ACME"], **IDENT)
    rec, _ = ir.apply_prospect(rec, prospect={"research": {"company_facts": facts()}}, fact_only=True)
    store.upsert(rec)


def test_collision_with_fact_only_sibling_keeps_facts_and_flags_lifecycle(tmp_path):
    store = ir.InstrumentRecordStore(tmp_path / ir.DEFAULT_PATH)
    _fact_only(store)
    _judged(store)
    row = broker.for_security(broker.load_snapshot(tmp_path), "ACME", GUID, now=NOW)
    assert row["company_facts"]["company"]["value"] == "Acme Instruments Inc."
    assert row["company_facts"].get("missing_reason") != "multiple_cio_records_for_guid"
    assert row["review_lifecycle"]["status"] == "MISSING"
    assert row["review_lifecycle"]["missing_reason"] == "multiple_cio_records_for_guid"


def test_collision_without_fact_only_sibling_stays_missing(tmp_path):
    store = ir.InstrumentRecordStore(tmp_path / ir.DEFAULT_PATH)
    _judged(store)
    row = broker.for_security(broker.load_snapshot(tmp_path), "ACME", GUID, now=NOW)
    assert row["company_facts"]["missing_reason"] == "multiple_cio_records_for_guid"
    assert row["review_lifecycle"]["missing_reason"] == "multiple_cio_records_for_guid"
