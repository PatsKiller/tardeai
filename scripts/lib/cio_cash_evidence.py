"""cio_cash_evidence.py — ONE derivation of the cash block's as-of.

The defect this module closes: the same cash figure was published at four
places on the CIO operator surface, each with its own idea of how old it was.
Measured on the served release 2026-08-30 (`4baf677d`, `/api/v3/cio/home`):

  * `capital_plan.cash_as_of.as_of`               → "2026-08-03"   (27 days)
  * `cio_now.decisions[].freshness.board[cash]`   → VERIFIED_CURRENT,
      source_as_of "2026-08-30T12:00:24+00:00", age 42,276 s (11.7 h)
  * `cash_letter.as_of`                           → "2026-08-30T23:45:01Z"
  * `/cash` (operator product)                    → no stamp at all

Only the first was honest. The other three were reading a *document* clock (the
holdings repricing time) or a *composition* clock (the moment the builder ran),
neither of which is evidence about when a broker last confirmed a balance.

THE RULE — the oldest contributing balance dates the block.

A total is only as current as its stalest member. A 27-day-old $500 makes the
whole block 27 days old, even beside $585,917 marked yesterday. Averaging, or
taking the freshest, or taking the composition time, all produce a number that
flatters the book. The oldest is the only choice that cannot overstate.

Corollaries, each of which was a real defect somewhere:

  * ``updated_at`` is LAST in the stamp precedence. It is when the collector
    touched the row, not when the broker confirmed the balance; preferring it
    makes an old source look fresh.
  * No stamp anywhere means ``as_of=None`` and ``unstamped=True``. A visible
    absence, never a fallback to ``now`` and never the document's stamp.
  * The document's own stamp is carried as ``document_as_of`` for contrast, and
    must never be promoted into ``as_of``.

AUTHORITY: READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE=0.
This module is a freshness LABEL. Nothing here computes, rounds, reallocates or
otherwise touches a dollar amount; the balances it copies are passed through
unchanged so the operator can see which account is dragging the block.
"""
from __future__ import annotations

from typing import Any, Optional

SCHEMA = "CashEvidenceAsOf@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

SOURCE = "holdings rows where is_cash, oldest stamp wins"
RULE_NOTE = (
    "The block is as current as its stalest account, never the moment "
    "the builder ran."
)
ABSENT_NOTE = (
    "cash age not supplied by the plan; do not read the page "
    "stamp as the age of these dollars"
)

# Stamps a cash row may carry, most specific first. `updated_at` is the row's
# write time and is deliberately LAST: it is when the collector touched the row,
# not when the broker last confirmed the balance.
CASH_STAMP_KEYS = (
    "canonical_mark_as_of", "broker_position_as_of", "as_of", "updated_at",
)

# Document-level stamps, carried for contrast only. Never promoted to `as_of`.
DOC_STAMP_KEYS = ("as_of", "generated_at", "updated_at")


def _fnum(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def cash_row_as_of(row: dict[str, Any]) -> Optional[str]:
    """The most specific stamp this cash row carries, or None."""
    for key in CASH_STAMP_KEYS:
        value = row.get(key)
        if value:
            return str(value)
    return None


def cash_rows(holdings_rows: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The cash rows out of a holdings row list."""
    return [r for r in (holdings_rows or [])
            if isinstance(r, dict) and r.get("is_cash")]


def cash_evidence_as_of(
    holdings_rows: Optional[list[dict[str, Any]]],
    doc: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """The cash block's OWN as-of, derived from the cash rows themselves.

    Report the OLDEST stamp as the block's as-of, because a total is only as
    current as its stalest member; keep the newest and the per-account spread so
    the operator can see which account is dragging; and never fall back to
    ``now``. No stamp anywhere means ``as_of=None`` and ``unstamped=True``,
    which is a visible absence rather than a false freshness.
    """
    rows = cash_rows(holdings_rows)
    per: list[dict[str, Any]] = []
    for row in rows:
        per.append({
            "account": str(row.get("account") or row.get("account_id") or "unknown"),
            "settled_cash_usd": round(_fnum(row.get("market_value")), 2),
            "as_of": cash_row_as_of(row),
        })
    stamps = sorted({p["as_of"] for p in per if p["as_of"]})
    doc_stamp = None
    for key in DOC_STAMP_KEYS:
        value = (doc or {}).get(key)
        if value:
            doc_stamp = str(value)
            break
    oldest = stamps[0] if stamps else None
    newest = stamps[-1] if stamps else None
    return {
        "as_of": oldest,
        "oldest_row_as_of": oldest,
        "newest_row_as_of": newest,
        "mixed_ages": bool(len(stamps) > 1),
        "distinct_stamps": len(stamps),
        "unstamped": not stamps,
        "unstamped_accounts": [p["account"] for p in per if not p["as_of"]],
        "by_account": sorted(per, key=lambda p: (p["as_of"] or "", p["account"])),
        "document_as_of": doc_stamp,
        "source": SOURCE,
        "note": RULE_NOTE,
    }


def unstamped_evidence(note: Optional[str] = None) -> dict[str, Any]:
    """The honest absence, in the same shape every publication point reads.

    Used where the cash age was not supplied upstream. It says "unknown", which
    is a fact; the alternative every publication point used to reach for was a
    clock that happened to be in scope, which is not.
    """
    return {
        "as_of": None,
        "oldest_row_as_of": None,
        "newest_row_as_of": None,
        "mixed_ages": False,
        "distinct_stamps": 0,
        "unstamped": True,
        "unstamped_accounts": [],
        "by_account": [],
        "document_as_of": None,
        "source": "not supplied",
        "note": note or ABSENT_NOTE,
    }


def is_evidence_block(obj: Any) -> bool:
    """True when `obj` is a cash-evidence block this module produced."""
    return (isinstance(obj, dict)
            and "unstamped" in obj
            and "by_account" in obj
            and "oldest_row_as_of" in obj)


def evidence_from_plan(plan: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The cash evidence a capital plan carries, or the honest absence.

    The plan is the one place that has already seen the raw cash rows, so every
    downstream publication point should read the block from here rather than
    reaching for whatever timestamp is nearest to hand.
    """
    block = (plan or {}).get("cash_as_of")
    if is_evidence_block(block):
        return block
    return unstamped_evidence()


def evidence_from_holdings_doc(doc: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The cash evidence in a holdings document, derived from its own rows."""
    if not isinstance(doc, dict):
        return unstamped_evidence()
    return cash_evidence_as_of(doc.get("holdings"), doc)


def oldest_as_of(evidence: Optional[dict[str, Any]]) -> Optional[str]:
    """The one stamp a publication point may print beside the cash figure."""
    if not is_evidence_block(evidence):
        return None
    return evidence.get("as_of")
