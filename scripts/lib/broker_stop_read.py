"""The stop section's read receipt, published beside the rows (SPRINT 8H-2, PR-003 / PR-017).

A row that says **NO STOP** is a *negative observation*, and a negative observation is evidence only
when the read that produced it succeeded. "No resting stop on this position, from a broker read at
14:58 ET, 4 minutes old" is a fact a page may show. "No stop" from a read nobody can date is not —
it is the same shape as an unreadable store. ``cio_truth.stop_clock`` already computes that clock
inside the CIO document's ``stops`` section; this module lifts it into a standalone block so a
payload that publishes only the holdings rows can still carry the receipt (PR-003).

Two facts that must not be merged (PR-017):

* **observed** — a resting broker order, dated by the broker read that saw it;
* **planned** — a level recorded in ``stops.json``, dated by when it was set. It proves no order
  exists at the broker. ``planned_facet`` keeps it as ``{level, source, as_of}`` beside the evidence
  state, so a page can render “planned 180.00 (set 2026-11-12)” and “no broker read since …” at the
  same time, instead of one borrowing the other's date.

Nothing here reads: no DB, no file, no broker, no clock. The section it is given already carries
every value; this module only lifts and labels.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

#: Keys lifted verbatim from the CIO document's ``stops`` section. The clock belongs to
#: ``cio_truth.stop_clock``; re-deriving it here would create a second stop clock.
_RECEIPT_KEYS: tuple[str, ...] = (
    "last_broker_read_at",
    "last_broker_read_label",
    "as_of",
    "age_hours",
    "stale",
    "stale_after_hours",
    "partial_observation_as_of",
    "gap",
)

_COUNT_KEYS: tuple[str, ...] = ("active_count", "pending_count", "unprotected_count", "awaiting_fill_count")


def planned_facet(level: Any, *, source: Any = None, as_of: Any = None) -> dict[str, Any] | None:
    """A planned stop level as its own typed fact, or None when there is no level.

    ``level`` is the recorded price; ``source`` names the record it came from (``stops.json`` unless
    the record says otherwise); ``as_of`` is when the level was set — never when it was read. A level
    of None is *no planned fact*, not a zero, so it returns None rather than an empty facet.
    """
    if level is None:
        return None
    return {"level": level, "source": source or "stops.json", "as_of": as_of}


def stops_read(section: Any) -> dict[str, Any]:
    """The receipt for the stop rows that travel with a payload: when they were read, and how old.

    ``status`` is one of:

    * ``READ``    — a broker stop read is recorded and within its window; a NO STOP row means the
      broker was read and held no stop for that position;
    * ``STALE``   — a read is recorded but older than the declared window (``gap`` says how old);
    * ``PARTIAL`` — some recorded positions carry no usable observation time, so no single complete
      refresh time is known; ``partial_observation_as_of`` is the last complete one;
    * ``UNKNOWN`` — no readable broker stop read; a NO STOP row proves nothing and a page must say
      so. ``gap.reason`` names why.

    The counts are the section's own (``active_count`` is None when the stop store was unreadable —
    None is kept as None, never turned into 0).
    """
    src = section if isinstance(section, Mapping) else {}
    out: dict[str, Any] = {key: deepcopy(src.get(key)) for key in _RECEIPT_KEYS}
    out["counts"] = {key: src.get(key) for key in _COUNT_KEYS}
    if src.get("partial_observation_as_of"):
        out["status"] = "PARTIAL"
    elif out.get("last_broker_read_at"):
        out["status"] = "STALE" if src.get("stale") else "READ"
    else:
        out["status"] = "UNKNOWN"
    if out["status"] in ("PARTIAL", "UNKNOWN") and not out.get("gap"):
        out["gap"] = {"reason": "no complete broker stop read is recorded for the current holdings"}
    return out
