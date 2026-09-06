"""Resolve a research row's subject to the identity spine.

WHY THIS EXISTS
---------------
Research has always keyed on `symbol`. The identity advisory is explicit that a
ticker is an alias, not an identity: tickers are reassigned after delisting, so
two companies can collide on one symbol years apart, and a share-class change
silently splits one issuer's history in two.

Everything needed to fix that already existed and was dark. `identity_registry`
holds 10,279 minted entities; `security_identity` owns the GUID hierarchy;
`event_identity` (0 consumers) defines the event lifecycle. This module is the
missing adapter, not new machinery.

WHAT A TAGGED ROW CAN THEN ANSWER
---------------------------------
    issuer_guid   8dfc96ee…   "everything about Visa the ISSUER" — survives a
                              ticker change, a share-class split, a re-listing
    subject_guid  d1871bc6…   "this specific security"
    gics_sector   Financial   "every catalyst in this sector" — the fan-out the
                              operator asked for, so news about one financial
                              reaches an agent reasoning about another

GICS GOES IN ITS OWN COLUMN, DELIBERATELY
-----------------------------------------
`category_sector` already holds a *thesis* vocabulary — ai_chips, ai_datacenter,
defense — which is not GICS and does not map onto it. ai_chips has no GICS
equivalent, and GICS "Technology" (111 entities) has no thesis slug. Writing GICS
into that column would collide two vocabularies in one field and destroy the 74
thesis tags already there. They are different axes and they get different columns.

IDENTITY STATUS IS CARRIED, NOT DISCARDED
-----------------------------------------
The registry ranks entities CONFIRMED > CANDIDATE > UNRESOLVED. A row tagged from
a CUSIP-confirmed entity and one tagged from a bare ticker alias are not equally
trustworthy, so the status travels with the tag and an agent can weigh it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

SCHEMA = "ResearchIdentityTag@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Registry `identity_status` values, best first. Never downgrade an existing tag.
RANK = {"CONFIRMED": 3, "CANDIDATE": 2, "UNRESOLVED": 1}


def _registry():
    from lib import identity_registry as R  # noqa: PLC0415
    return R


def load_registry(root: Any = None) -> Mapping[str, Any]:
    return _registry().load(root)


def resolve(doc: Mapping[str, Any], symbol: Any) -> dict[str, Any] | None:
    """Symbol -> identity tag, or None when the symbol is not registered.

    Returns None rather than a partially-populated dict: a tag with a null
    subject_guid is indistinguishable downstream from an untagged row, and
    writing one would make coverage look higher than it is.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    R = _registry()
    row = R.lookup_symbol(doc, sym)
    if not row:
        return None
    subject = R.subject_guid_of(row, sym)
    if not subject:
        return None
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "symbol": sym,
        "subject_guid": subject,
        "issuer_guid": row.get("issuer_guid"),
        "listing_guid": row.get("listing_guid"),
        "identity_status": row.get("identity_status") or "UNRESOLVED",
        "identity_basis": row.get("identity_basis"),
        "financial_action": False,
    }


def is_upgrade(existing_status: Any, new_status: Any) -> bool:
    """True only when the new tag is strictly better evidence.

    Mirrors the registry's own one-way rule: a feed that stops publishing CUSIPs
    must not be able to downgrade a CONFIRMED entity to a bare ticker alias.
    """
    return RANK.get(str(new_status or "").upper(), 0) > RANK.get(
        str(existing_status or "").upper(), 0
    )

#: GICS sectors, plus the spellings this system's feeds actually emit.
#: An allowlist, not a passthrough — deliberately.
#:
#: The aegis snapshot's `sector` column mixes true sectors with FUND STRATEGY
#: labels: "Dividend Equity", "Income / Covered Call", "Growth Equity",
#: "Innovation", "Fixed Income". Those describe a mandate, not a sector. Letting
#: them through put 3,639 rows of strategy label into gics_sector on the first
#: backfill (2026-09-06) — the exact vocabulary collision this column exists to
#: prevent, committed by the code written to prevent it.
#:
#: A value not on this list is NOT a sector, and NULL is the honest answer.
GICS_SECTORS = {
    "energy": "Energy",
    "materials": "Materials",
    "basic materials": "Materials",
    "industrials": "Industrials",
    "consumer discretionary": "Consumer Discretionary",
    "consumer cyclical": "Consumer Discretionary",
    "consumer staples": "Consumer Staples",
    "consumer defensive": "Consumer Staples",
    "health care": "Health Care",
    "healthcare": "Health Care",
    "financials": "Financials",
    "financial": "Financials",
    "information technology": "Information Technology",
    "technology": "Information Technology",
    "communication services": "Communication Services",
    "utilities": "Utilities",
    "real estate": "Real Estate",
}


def normalize_sector(value: Any) -> str | None:
    """Map a feed's sector string onto canonical GICS, or None.

    None is a result, not a failure: a fund mandate is not a sector, and writing
    it into gics_sector would make the column mean two things at once.
    """
    return GICS_SECTORS.get(str(value or "").strip().lower())
