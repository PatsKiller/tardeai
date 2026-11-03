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

STATES = ("ok", "absent", "empty", "unparseable", "not_object", "unreadable", "invalid_shape")


def read_json_state(path: Path | str) -> tuple[Optional[dict], str]:
    """``(document, state)`` from one bounded read; the document only when state is ``ok``.

    ``state`` is one of ``ok | absent | empty | unparseable | not_object | unreadable``.
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


def read_holdings_state(path: Path | str) -> tuple[Optional[dict], str]:
    """A holdings document whose ``holdings`` member is a list of mappings, or ``(None, why)``.

    ``state`` is the read state, or ``invalid_shape`` when the file parsed but its consumer
    shape is wrong (``holdings`` null, a mapping, or containing scalar rows). Callers must
    render an unavailable snapshot, never an empty book, when the document is ``None``.
    """
    doc, state = read_json_state(path)
    if state != "ok" or doc is None:
        return None, state
    if object_rows(doc.get("holdings")) is None:
        return None, "invalid_shape"
    return doc, "ok"


def read_json_object(path: Path | str, *, default: Any = None) -> Any:
    """The object at ``path``, or ``default`` when it is absent, empty, corrupt or not an object."""
    doc, _state = read_json_state(path)
    return doc if doc is not None else default


__all__ = ["STATES", "object_rows", "read_holdings_state", "read_json_object", "read_json_state"]
