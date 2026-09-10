"""Controls for NarrativeSubjectLink@v1.

Fifteen narrative surfaces, one tagged. The concrete defect: `material_changes`
fires `sector_move` (14 rows, 13 with a subject_guid) under a representative
MEMBER symbol, so a SECTOR event carries a SECURITY guid — which AGENTS.md §17A
forbids in words and nothing enforced in code.

Each control below must go red if the corresponding guarantee is removed.
"""
from __future__ import annotations

import pytest

from scripts.lib.cio_narrative_subjects import (
    CONFIDENCE_CONFIRMED,
    NARRATIVE_SUBJECT_TYPES,
    SubjectTypeRejected,
    build_links,
    canonical_name,
    resolve_subject,
)
from scripts.lib.ticker_knowledge_graph import ENTITY_KINDS
from scripts.lib.tradeai_record_envelope import ENTITY_TYPES


def _fake_lookup(sym, root=None):
    return {"subject_guid": f"guid-for-{sym}", "identity_status": "CONFIRMED"} if sym == "NVDA" else {}


# --- the property the whole rollup depends on --------------------------------

def test_two_spellings_of_one_sector_mint_ONE_guid():
    """The failure this blocks is silent: a split rollup that still looks fine.

    entity_guid casefolds but does not canonicalise, so without normalize_sector
    'Consumer Cyclical' and 'Consumer Discretionary' would be two sectors.
    """
    a = resolve_subject("SECTOR", "Consumer Cyclical")
    b = resolve_subject("SECTOR", "consumer discretionary")
    c = resolve_subject("SECTOR", "  CONSUMER DISCRETIONARY  ")
    assert a["entity_guid"] == b["entity_guid"] == c["entity_guid"]
    assert a["semantic_subject"] == "Consumer Discretionary"


def test_a_non_sector_is_None_not_a_minted_guid():
    """A fund mandate is not a sector. None is a result, not a failure."""
    assert resolve_subject("SECTOR", "Global Macro Fund") is None
    assert canonical_name("SECTOR", "Global Macro Fund") is None


# --- the sector_move defect ---------------------------------------------------

def test_a_sector_subject_is_NEVER_a_security_guid():
    """The 2026-09-10 defect, pinned.

    13 of 14 sector_move rows carried a security guid for a sector event. A
    SECTOR ref must resolve from the sector NAME, never from a member symbol.
    """
    sector = resolve_subject("SECTOR", "Industrials")
    security = resolve_subject("SECURITY", "NVDA", symbol_lookup=_fake_lookup)
    assert sector["entity_guid"] != security["entity_guid"]
    assert sector["entity_type"] == "SECTOR"
    assert sector["ticker_guid_is_not_security"] is True


# --- fail loud, never silently ------------------------------------------------

def test_an_unknown_entity_type_RAISES_rather_than_becoming_OTHER():
    """entity_ref() downgrades unknown types to 'OTHER', which is not even in
    ENTITY_TYPES. Permissive is right for an envelope and wrong for a subject
    link: a typo would join to nothing and report no error."""
    with pytest.raises(SubjectTypeRejected):
        resolve_subject("SECTORR", "Energy")
    assert "OTHER" not in ENTITY_TYPES


def test_an_unknown_relationship_raises():
    with pytest.raises(SubjectTypeRejected):
        resolve_subject("SECTOR", "Energy", relationship="sort-of-about")


def test_an_unknown_author_agent_raises():
    with pytest.raises(SubjectTypeRejected):
        build_links(row_guid="r", source_table="t", source_id=1,
                    subjects=[{"entity_type": "SECTOR", "value": "Energy"}],
                    author_agent_id="not-an-agent")


def test_an_unresolvable_security_is_a_MISS_not_a_null_guid():
    """A link with a null guid joins to nothing and would overstate coverage."""
    links, misses = build_links(
        row_guid="r", source_table="t", source_id=1,
        subjects=[{"entity_type": "SECURITY", "value": "ZZZZNOTREAL"}],
        symbol_lookup=_fake_lookup)
    assert links == []
    assert misses and misses[0]["value"] == "ZZZZNOTREAL"


# --- many-to-many, which is the whole point -----------------------------------

def test_one_thesis_carries_theme_sector_and_securities_at_once():
    """rotation/defense theses are about a theme AND a sector AND securities.
    A single subject_guid column cannot express this."""
    links, _ = build_links(
        row_guid="r1", source_table="defense_directive_hits_staging", source_id=42,
        subjects=[{"entity_type": "THEME", "value": "defense spending"},
                  {"entity_type": "SECTOR", "value": "Industrials"},
                  {"entity_type": "SECURITY", "value": "NVDA"}],
        symbol_lookup=_fake_lookup)
    assert {l["entity_type"] for l in links} == {"THEME", "SECTOR", "SECURITY"}


def test_pair_shaped_rows_carry_from_and_to():
    """rec_rotation_links / aegis_rotation_candidates are from->to."""
    links, _ = build_links(
        row_guid="r2", source_table="rec_rotation_links", source_id=7,
        subjects=[{"entity_type": "SECTOR", "value": "Energy", "relationship": "from"},
                  {"entity_type": "SECTOR", "value": "Utilities", "relationship": "to"}])
    assert {l["relationship"] for l in links} == {"from", "to"}
    assert links[0]["subject_guid"] != links[1]["subject_guid"]


# --- determinism and idempotence ---------------------------------------------

def test_link_guid_is_deterministic_so_replay_never_duplicates():
    kw = dict(row_guid="r3", source_table="t", source_id=1,
              subjects=[{"entity_type": "THEME", "value": "AI capex"}])
    assert build_links(**kw)[0][0]["link_guid"] == build_links(**kw)[0][0]["link_guid"]


def test_the_same_subject_twice_yields_one_link():
    links, _ = build_links(
        row_guid="r4", source_table="t", source_id=1,
        subjects=[{"entity_type": "SECTOR", "value": "Energy"},
                  {"entity_type": "SECTOR", "value": "energy"}])
    assert len(links) == 1


# --- vocabulary is real, not aspirational ------------------------------------

def test_every_narrative_subject_type_is_a_real_envelope_type():
    for t in NARRATIVE_SUBJECT_TYPES:
        assert t in ENTITY_TYPES, f"{t} is not in tradeai_record_envelope.ENTITY_TYPES"


def test_every_non_security_type_has_a_minter():
    """STRATEGY and PORTFOLIO were added to ENTITY_KINDS for this contract."""
    for kind in ("sector", "industry", "theme", "strategy", "portfolio"):
        assert kind in ENTITY_KINDS


def test_security_is_never_minted_from_a_name():
    """cio_subject_guid is lookup-only: 'memory is not an identity authority'.
    If the registry has no answer, there is no security link — not a made-up one."""
    assert resolve_subject("SECURITY", "NVDA", symbol_lookup=lambda s, root=None: {}) is None


def test_confidence_is_carried_not_assumed():
    r = resolve_subject("SECURITY", "NVDA", symbol_lookup=_fake_lookup)
    assert r["confidence"] == CONFIDENCE_CONFIRMED
