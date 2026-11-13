"""LQ-2961: a moving stage-wide count in the size-cap curation reason is not a new prospect version.

Synthetic records only. In production 1,575 of 1,701 consecutive versions differed only in
``watchlist.curation.reason`` ("... holds 3314 > cap 120 ..." -> "... holds 3347 ..."), so the
writer re-appended every capped WATCH record every 30 minutes (~600 MB/day).
"""
from __future__ import annotations

import pytest

from scripts.lib import cio_instrument_record as ir
from scripts.lib import cio_prospect_writer as W


def _rec(reason: str, *, decision: str = "propose_out", member: bool = True, conviction: float = 10.6,
         since: str = "2026-11-12T21:07:39+00:00") -> dict:
    return {
        "prospect_schema": ir.PROSPECT_SCHEMA, "stage": "watching", "stance": "WATCH", "subject_key": "WATCH:X",
        "conviction": conviction, "evidence_at": "t1", "expires_at": "t2",
        "conviction_components": {"hermes_score": {"value": 11.0, "evidence_at": "t1"}},
        "watchlist": {"member": member, "origin": "hermes", "protected": False, "reason": "hermes lifecycle watch",
                      "refused": [], "since": since, "support": [],
                      "curation": {"decision": decision, "reason": reason}},
    }


CAP = "size cap: stage watching holds {n} > cap 120; lowest conviction {c}"


def test_only_the_stage_count_and_conviction_text_moved_is_immaterial():
    a = _rec(CAP.format(n=3314, c="10.6"))
    b = _rec(CAP.format(n=3347, c="11.2"), conviction=11.2, since="2026-11-13T13:37:08+00:00")
    assert W.material_changes(a, b) == []


@pytest.mark.parametrize("change", [
    {"decision": "keep"},                                                     # the decision flips
    {"reason": "size cap: stage watching holds 3347 > cap 200; lowest conviction 11.2"},   # the cap moved
    {"reason": "size cap: stage exiting holds 3347 > cap 120; lowest conviction 11.2"},    # another stage
    {"reason": "stale: no evidence for 30 days"},                              # a different rule fired
])
def test_a_real_curation_change_is_still_material(change):
    a = _rec(CAP.format(n=3314, c="10.6"))
    b = _rec(**{"reason": CAP.format(n=3347, c="11.2"), **change})
    assert W.material_changes(a, b) == ["watchlist"]


def test_membership_change_is_still_material():
    a = _rec(CAP.format(n=3314, c="10.6"))
    b = _rec(CAP.format(n=3314, c="10.6"), member=False)
    assert W.material_changes(a, b) == ["watchlist"]


def test_non_cap_reasons_compare_verbatim():
    a = _rec("stale: no evidence for 30 days", decision="propose_out")
    b = _rec("stale: no evidence for 31 days", decision="propose_out")
    assert W.material_changes(a, b) == ["watchlist"]


def test_conviction_beyond_tolerance_is_still_its_own_change():
    a = _rec(CAP.format(n=3314, c="10.6"), conviction=10.6)
    b = _rec(CAP.format(n=3350, c="14.0"), conviction=14.0)
    assert W.material_changes(a, b) == ["conviction"]


def test_a_day_of_count_churn_writes_no_version_between_refreshes():
    # 16 half-hourly runs where only the stage count moves: one mint, no further versions.
    prior = _rec(CAP.format(n=3300, c="10.6"))
    versions = 0
    for i in range(1, 17):
        nxt = _rec(CAP.format(n=3300 + 7 * i, c="10.6"))
        if W.material_changes(prior, nxt):
            versions += 1
            prior = nxt
    assert versions == 0


def test_the_stored_reason_is_not_rewritten():
    reason = CAP.format(n=3347, c="11.2")
    rec = _rec(reason)
    W.material_changes(_rec(CAP.format(n=1, c="1.0")), rec)
    assert rec["watchlist"]["curation"]["reason"] == reason
