"""LQ-20261107-1907: the CIO pages read the conflict ledger from the durable root, not the release dir.

Live defect (LQ-1905): /api/v2/cio/pages resolved the ledger under the RELEASE directory, which has no
data/conflicts/, so /v3/risk said "conflict ledger not yet produced" while the ledger existed in
persistent-state. Synthetic fixtures only; nothing here reads live state.
"""
from datetime import timedelta
from pathlib import Path

from scripts.lib import cio_truth, w7_pages
from scripts.lib.conflicts import api as conflicts_api
from tests.test_conflict_ledger import NOW, SUBJECT, conflict, ledger


def _durable_with_one_record(tmp_path):
    durable = tmp_path / "persistent"
    ledger(durable).reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    return durable


def test_ledger_root_overrides_the_release_root(tmp_path):
    durable = _durable_with_one_record(tmp_path)
    release = tmp_path / "release"
    (release / "data").mkdir(parents=True)
    section = cio_truth._ledger_conflicts(release, NOW + timedelta(hours=1), ledger_root=durable)
    assert len(section["findings"]) == 1 and not section.get("gap")


def test_without_ledger_root_the_explicit_root_is_still_used(tmp_path):
    # An explicitly supplied root never falls back to another root (resolve docstring).
    durable = _durable_with_one_record(tmp_path)
    section = cio_truth._ledger_conflicts(durable, NOW + timedelta(hours=1))
    assert len(section["findings"]) == 1


def test_resolve_threads_ledger_root(tmp_path):
    durable = _durable_with_one_record(tmp_path)
    release = tmp_path / "release"
    (release / "data").mkdir(parents=True)
    doc = cio_truth.resolve(release, NOW + timedelta(hours=1), inputs={}, ledger_root=durable)
    assert len(doc["conflicts"]["findings"]) == 1


def test_page_payload_passes_ledger_root_to_the_resolver(tmp_path):
    seen = {}
    def resolver(**kw):
        seen.update(kw)
        return {"conflicts": {"findings": [], "gap": None}}
    try:
        w7_pages.page_payload(tmp_path, now=NOW, resolver=resolver, ledger_root=tmp_path / "durable")
    except Exception:
        pass  # projection of a stub truth may fail; only the resolver call matters here
    assert seen.get("ledger_root") == tmp_path / "durable"


def test_page_payload_without_ledger_root_leaves_resolver_signature_alone(tmp_path):
    seen = {}
    def resolver(**kw):
        seen.update(kw)
        return {"conflicts": {"findings": [], "gap": None}}
    try:
        w7_pages.page_payload(tmp_path, now=NOW, resolver=resolver)
    except Exception:
        pass
    assert "ledger_root" not in seen


def test_missing_ledger_gap_names_the_path_not_not_yet_produced(tmp_path):
    section = conflicts_api.records_section(tmp_path)
    reason = section["gap"]["reason"]
    assert "not yet produced" not in reason
    assert str(tmp_path / "data/conflicts/conflict_events.jsonl") in reason
    assert conflicts_api.approval_rows(tmp_path)["gap"]["reason"] == reason
    assert conflicts_api.sections_for_guids(tmp_path, ["g1"])["g1"]["gap"]["reason"] == reason


def test_over_cap_gap_reports_shown_and_total(tmp_path):
    from tests.test_conflict_ledger import KEY
    st = ledger(tmp_path)
    for i in range(203):
        st.reconcile(SUBJECT.__class__("security", f"g{i}", f"S{i}", {"held": False}),
                     [conflict(key=f"security:g{i}:U7:desk")], at=NOW, apply=True)
    section = conflicts_api.records_section(tmp_path)
    assert section["gap"]["reason"] == "more conflict records available"
    assert section["gap"]["total"] == 203 and section["gap"]["shown"] == 200 == len(section["findings"])
