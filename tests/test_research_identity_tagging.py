"""The identity tags downstream agents are told to trust.

Two defects are pinned here, both committed on 2026-09-06 by the code written to
prevent them:

VOCABULARY COLLISION
    The first backfill passed the aegis `sector` column straight through. That
    column mixes GICS sectors with FUND STRATEGY labels — "Dividend Equity",
    "Income / Covered Call", "Growth Equity" — and 3,639 rows of mandate landed in
    gics_sector. A column that means two things means neither.

SILENT DOWNGRADE
    Re-running must not let a feed that stopped publishing CUSIPs turn a
    CONFIRMED entity back into a bare ticker alias.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import research_identity as RI  # noqa: E402


# ── the sector allowlist ────────────────────────────────────────────────────

def test_fund_strategy_labels_are_not_sectors():
    """The exact values that polluted the column."""
    for bad in ("Dividend Equity", "Income / Covered Call", "Growth Equity",
                "Innovation", "Fixed Income", "Industrials and Materials Fund"):
        assert RI.normalize_sector(bad) is None, f"{bad!r} is a mandate, not a sector"


def test_real_sectors_normalise_to_one_canonical_spelling():
    assert RI.normalize_sector("Financial") == "Financials"
    assert RI.normalize_sector("financials") == "Financials"
    assert RI.normalize_sector("Technology") == "Information Technology"
    assert RI.normalize_sector("Healthcare") == "Health Care"
    assert RI.normalize_sector("Consumer Cyclical") == "Consumer Discretionary"
    assert RI.normalize_sector("Basic Materials") == "Materials"


def test_two_spellings_of_one_sector_never_split_the_corpus():
    """'Financial' and 'Financials' must not be two buckets — the whole point of
    the column is that a query for one sector returns that sector."""
    assert RI.normalize_sector("Financial") == RI.normalize_sector("Financials")
    assert RI.normalize_sector("Healthcare") == RI.normalize_sector("Health Care")


def test_the_canonical_set_is_exactly_gics():
    canon = set(RI.GICS_SECTORS.values())
    assert canon == {
        "Energy", "Materials", "Industrials", "Consumer Discretionary",
        "Consumer Staples", "Health Care", "Financials",
        "Information Technology", "Communication Services", "Utilities",
        "Real Estate",
    }, "gics_sector drifted off GICS"


def test_empty_and_junk_resolve_to_none():
    for v in (None, "", "   ", "not a sector"):
        assert RI.normalize_sector(v) is None


# ── identity rank: one-way ──────────────────────────────────────────────────

def test_a_confirmed_tag_is_never_downgraded():
    assert RI.is_upgrade("CONFIRMED", "CANDIDATE") is False
    assert RI.is_upgrade("CONFIRMED", "UNRESOLVED") is False


def test_better_evidence_is_an_upgrade():
    assert RI.is_upgrade("UNRESOLVED", "CANDIDATE") is True
    assert RI.is_upgrade("CANDIDATE", "CONFIRMED") is True


def test_equal_status_is_not_an_upgrade():
    """Re-running must be a no-op, not a rewrite."""
    for st in ("CONFIRMED", "CANDIDATE", "UNRESOLVED"):
        assert RI.is_upgrade(st, st) is False


def test_unknown_status_cannot_displace_a_known_one():
    assert RI.is_upgrade("CONFIRMED", "banana") is False


# ── a tag is whole or absent ────────────────────────────────────────────────

def test_resolve_returns_none_rather_than_a_null_subject():
    """A tag with a null subject_guid is indistinguishable downstream from an
    untagged row, and writing one inflates apparent coverage."""
    assert RI.resolve({"entities": {}}, "NOSUCHTICKER") is None
    assert RI.resolve({"entities": {}}, "") is None
    assert RI.resolve({"entities": {}}, None) is None


def test_the_backfill_routes_every_sector_through_the_allowlist():
    """A future edit must not reintroduce the passthrough."""
    src = (ROOT / "scripts" / "backfill_research_identity.py").read_text(encoding="utf-8")
    assert "normalize_sector" in src
    fn = src.split("def _sector_map", 1)[1].split("\ndef ", 1)[0]
    assert fn.count("normalize_sector") >= 2, (
        "a sector source bypasses the allowlist — that is how the fund labels got in")


def test_the_backfill_defaults_to_dry_run():
    src = (ROOT / "scripts" / "backfill_research_identity.py").read_text(encoding="utf-8")
    assert '"--apply", action="store_true"' in src
