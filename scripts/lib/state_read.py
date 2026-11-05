"""Read a state JSON object without reading a damaged file as an empty one.

2026-11-03: ``holdings.json`` was 0 bytes and readers that did
``json.loads(path.read_text()) if path.exists() else {}`` raised
``JSONDecodeError: Expecting value: line 1 column 1 (char 0)`` out of a lane
(``process_watchlist_agent_jobs`` 18 times, ``social_ingest`` once, the
incubator refresh on the write path). The bug is the conflation of two
different states:

* **absent** — there is no snapshot; "no positions" is the honest answer;
* **exists but empty/corrupt** — there *is* a snapshot and it is damaged.

This helper never crashes on the second and never invents rows for it. A reader
that only needs portfolio context gets its ``default`` (normally ``{}``) and can
say so; a reader that needs to report the damage uses ``read_json_state`` and
gets the state back. It performs no write and no network call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

#: Every state this module's readers can return. ``read_json_state`` returns all of them except
#: ``invalid_shape``, which ``read_holdings_state`` adds for a document whose consumer shape is wrong — a
#: consumer switching on ``STATES`` must not assume every member comes from the byte reader.
STATES = ("ok", "absent", "empty", "unparseable", "not_object", "unreadable", "invalid_shape")


def read_json_state(path: Path | str) -> tuple[Optional[dict], str]:
    """``(document, state)`` from one bounded read; the document only when state is ``ok``.

    ``state`` is one of ``ok | absent | empty | unparseable | not_object | unreadable``. ``invalid_shape`` is
    never returned here: it is a consumer-shape verdict and belongs to ``read_holdings_state``.
    """
    p = Path(path)
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return None, "absent"
    except OSError:
        return None, "unreadable"
    if not raw.strip():
        return None, "empty"
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        # JSONDecodeError is a ValueError; so is CPython's 4300-digit int-conversion refusal
        # (a ~5KB object with a 5000-digit integer). A deep-nesting RecursionError is the same
        # class of decoder refusal. All mean "there is a file here that we cannot read".
        return None, "unparseable"
    if not isinstance(doc, dict):
        return None, "not_object"
    return doc, "ok"


def object_rows(value: Any) -> Optional[list[dict]]:
    """The list of mappings at ``value``, or ``None`` when the shape is not a list of mappings.

    A list with even one non-mapping member is not a usable book: silently dropping the bad
    row would turn a damaged snapshot into a confident partial one.
    """
    if not isinstance(value, list):
        return None
    if any(not isinstance(row, dict) for row in value):
        return None
    return value


def _readable_row(row: dict) -> bool:
    """A holdings row the consumers can actually read: it names a security.

    ``symbol`` is the one field every consumer keys a position by (the prompt's "Position: …" line, the layer
    scan, the symbol list social_ingest builds). A row without it cannot answer "what do I hold", so a book
    containing one is not a shorter book — it is a document this module cannot read, and the destructive
    direction it must never allow is that unreadable rows render as an empty position ("NOT CURRENTLY HELD").
    The live store names a symbol on every row, cash rows included (``"symbol": "CASH", "is_cash": true``), so
    this demands no shape the writer does not already produce.
    """
    symbol = row.get("symbol")
    return isinstance(symbol, str) and bool(symbol.strip())


def read_holdings_state(path: Path | str) -> tuple[Optional[dict], str]:
    """A holdings document whose ``holdings`` member is a list of readable mappings, or ``(None, why)``.

    ``state`` is the read state, or ``invalid_shape`` when the file parsed but its consumer shape is wrong:
    ``holdings`` null, a mapping, scalar rows, or a row that names no symbol (``_readable_row``). A foreign
    document such as ``{"holdings": [{"ticker": "AAA"}]}`` is exactly that last case — it used to read ``ok``,
    and the consumer then asserted "NOT CURRENTLY HELD". Callers must render an unavailable snapshot, never an
    empty book, when the document is ``None``.
    """
    doc, state = read_json_state(path)
    if state != "ok" or doc is None:
        return None, state
    rows = object_rows(doc.get("holdings"))
    if rows is None:
        return None, "invalid_shape"
    if any(not _readable_row(row) for row in rows):
        return None, "invalid_shape"
    return doc, "ok"


def read_json_object(path: Path | str, *, default: Any = None) -> Any:
    """The object at ``path``, or ``default`` when it is absent, empty, corrupt or not an object."""
    doc, _state = read_json_state(path)
    return doc if doc is not None else default


__all__ = ["STATES", "object_rows", "read_holdings_state", "read_json_object", "read_json_state"]
