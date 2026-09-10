"""A sector event must carry a SECTOR subject, never a member's SECURITY guid.

The live defect, 2026-09-10: `material_changes` held 14 `sector_move` rows, 13
with a `subject_guid`, and every one of those was the guid of a representative
MEMBER symbol. `sector_moves()` picks `best = members[0]` and emits
`"symbol": best["symbol"]`, burying the sector in `evidence["sector"]`;
`persist()` then resolved identity from that symbol.

So "Energy is moving" was recorded as a statement about, say, XOM. Every rollup
of what the desk has said about a SECTOR silently returned nothing, and every
rollup about that security silently included an event that was not about it.

AGENTS.md §17A already stated the rule in words -- "Topics are subjects, not
securities... never give a theme a SECURITY guid". Nothing enforced it.
"""
from __future__ import annotations

from scripts.lib.cio_narrative_subjects import build_links, resolve_subject


def test_a_sector_subject_is_not_the_member_symbols_guid():
    """The regression control. Must go red if the declaration is dropped."""
    sector = resolve_subject("SECTOR", "Energy")
    member = resolve_subject("SECURITY", "NVDA",
                             symbol_lookup=lambda s, root=None: {
                                 "subject_guid": "guid-NVDA", "identity_status": "CONFIRMED"})
    assert sector["entity_type"] == "SECTOR"
    assert sector["entity_guid"] != member["entity_guid"]


def test_the_emitted_change_declares_its_own_subject():
    """sector_moves() must emit `subject`, so persist() never has to guess."""
    import inspect

    from scripts import material_change_detector as mcd

    src = inspect.getsource(mcd.sector_moves)
    assert '"subject": {"entity_type": "SECTOR"' in src, (
        "sector_moves no longer declares a SECTOR subject; persist() will fall "
        "back to the member symbol and re-stamp a SECURITY guid"
    )


def test_persist_prefers_the_declaration_over_the_symbol():
    import inspect

    from scripts import material_change_detector as mcd

    src = inspect.getsource(mcd.persist)
    assert 'c.get("subject")' in src
    assert "resolve_subject(" in src
    assert 'env["issuer_guid"] = None' in src, (
        "a sector has no issuer; inventing one corrupts the security spine"
    )


def test_members_are_linked_as_mentioned_not_as_subject():
    """The members are still reachable -- as mentions, which is what they are."""
    links, _ = build_links(
        row_guid="cg-1", source_table="material_changes", source_id="cg-1",
        subjects=[{"entity_type": "SECTOR", "value": "Energy", "relationship": "subject"},
                  {"entity_type": "SECURITY", "value": "NVDA", "relationship": "mentioned"}],
        symbol_lookup=lambda s, root=None: {"subject_guid": f"guid-{s}",
                                            "identity_status": "CONFIRMED"})
    by_rel = {l["relationship"]: l for l in links}
    assert by_rel["subject"]["entity_type"] == "SECTOR"
    assert by_rel["mentioned"]["entity_type"] == "SECURITY"


def test_an_unresolvable_sector_falls_back_rather_than_dropping_the_change():
    """A sector we cannot canonicalise must not silently delete the event.

    normalize_sector returns None for a non-GICS label (a fund mandate is not a
    sector). persist() keeps the member-derived envelope in that case, and the
    link row still says SECTOR -- so the gap stays visible instead of becoming
    truth by omission.
    """
    assert resolve_subject("SECTOR", "Global Macro Fund") is None
