"""Phase 3 lanes: identity is attached, and a tagging failure never loses the row.

Three lanes wired here because the sector was already in hand and simply dropped:
inference_sizing_recommendations (its proposal comes from paper_trade_proposals,
which carries sector+industry) and the two directive staging tables (sector sits
in the spec as gics_sector/finviz_sector).

The rotation case is the one that matters most. rotation_signal_to_feedback()
returns None without a sector and sets `symbol` only when an ETF proxy exists --
rotation is sector-FIRST by design. Tagging it by symbol would reproduce the
sector_move defect one table over, so the sector is the SUBJECT and the symbol,
when present, is a MENTION.
"""
from __future__ import annotations

import scripts.lib.two_way_curation as twc
from scripts.lib.cio_narrative_write import (
    NarrativeBehaviorRefused,
    row_guid_for,
    write_narrative,
)


class _Cur:
    def __init__(self, fail=False):
        self.sql = []
        self.rowcount = 1
        self._fail = fail

    def execute(self, sql, params=None):
        if self._fail:
            raise RuntimeError("db down")
        self.sql.append((sql, params))


# --- the fail-safe direction, which is opposite to the rest of the campaign ---

def test_a_tagging_failure_does_NOT_raise():
    """An untagged row is degraded; a lost row is a blank surface.

    Everywhere else in this campaign the gate fails CLOSED. Here it must not:
    the operator would rather see an untagged watchlist row than an empty hub.
    """
    r = write_narrative(_Cur(fail=True), source_table="t", source_id=1,
                        subjects=[{"entity_type": "SECTOR", "value": "Energy"}])
    assert r["links_written"] == 0
    assert r["misses"], "a swallowed failure must still be reported"


def test_an_unresolvable_subject_is_reported_not_silently_dropped():
    r = write_narrative(_Cur(), source_table="t", source_id=1,
                        subjects=[{"entity_type": "SECTOR", "value": "Not A Sector"}])
    assert r["links_built"] == 0 and r["misses"]


# --- the behaviour rail ------------------------------------------------------

def test_a_narrative_may_never_carry_a_behaviour_field():
    for field in ("stop_price", "quantity", "target_weight", "side"):
        try:
            write_narrative(_Cur(), source_table="t", source_id=1, subjects=[],
                            **{field: 1})
            raise AssertionError(f"{field} was accepted")
        except NarrativeBehaviorRefused:
            pass


# --- grounding ----------------------------------------------------------------

def test_a_sentence_citing_evidence_not_in_the_dossier_is_dropped():
    """An unresolvable citation is indistinguishable from an invention."""
    r = write_narrative(
        _Cur(), source_table="t", source_id=1,
        subjects=[{"entity_type": "SECTOR", "value": "Energy"}],
        sentences=[{"sentence": "Real.", "cites": ["news:1"]},
                   {"sentence": "Invented.", "cites": ["news:999"]}],
        dossier_ids=["news:1"])
    assert [s["sentence"] for s in r["sentences"]] == ["Real."]
    assert r["cited_ids"] == ["news:1"]


# --- rotation is sector-first -------------------------------------------------

def _stub_lookup(sym, root=None):
    """Resolve any symbol, so the test exercises the wiring and not the registry.

    identity_registry.json is RUNTIME data and is absent in CI. Three tests in
    this wave passed locally and failed on the runner for exactly that reason —
    they were asserting on the contents of a file that only exists on the box.
    A unit test that depends on runtime data tests the data.
    """
    return {"subject_guid": f"guid-{str(sym).upper()}", "identity_status": "CONFIRMED"}


def test_rotation_tags_the_SECTOR_as_subject_and_the_symbol_as_mention(monkeypatch):
    captured = []

    def ex(sql, params=None):
        captured.append(params)
        return 1

    import scripts.lib.cio_subject_guid as csg
    monkeypatch.setattr(csg, "lookup_subject", _stub_lookup, raising=False)
    twc._tag_directive("rotation",
                       {"directive_id": "d1", "directive_kind": "sector_rotation",
                        "spec": {"gics_sector": "Energy", "symbol": "XLE"}}, ex)
    by_type = {p[4]: p for p in captured}
    assert by_type["SECTOR"][7] == "subject", "rotation must be tagged sector-first"
    assert by_type["SECURITY"][7] == "mentioned"


def test_defense_tags_the_SECURITY_as_subject(monkeypatch):
    captured = []

    def ex(sql, params=None):
        captured.append(params)
        return 1

    import scripts.lib.cio_subject_guid as csg
    monkeypatch.setattr(csg, "lookup_subject", _stub_lookup, raising=False)
    twc._tag_directive("defense",
                       {"directive_id": "d2", "directive_kind": "defensive_lean",
                        "spec": {"gics_sector": "Utilities", "symbol": "NEE"}}, ex)
    by_type = {p[4]: p for p in captured}
    assert by_type["SECURITY"][7] == "subject"
    assert by_type["SECTOR"][7] == "mentioned"


def test_rotation_without_a_sector_stages_anyway_and_tags_nothing_wrong():
    """No sector means no subject -- but the directive must still stage."""
    captured = []
    twc._tag_directive("rotation", {"directive_id": "d3", "spec": {}},
                       lambda sql, params=None: captured.append(params))
    assert captured == []


# --- row identity -------------------------------------------------------------

def test_row_guid_is_deterministic_for_a_lane_without_its_own_guid():
    a = row_guid_for("inference_sizing_recommendations", 42)
    b = row_guid_for("inference_sizing_recommendations", 42)
    c = row_guid_for("watchlist_final_synthesis", 42)
    assert a == b and a != c
