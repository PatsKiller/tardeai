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

STATES = ("ok", "absent", "empty", "unparseable", "not_object", "unreadable")


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
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "unparseable"
    if not isinstance(doc, dict):
        return None, "not_object"
    return doc, "ok"


def read_json_object(path: Path | str, *, default: Any = None) -> Any:
    """The object at ``path``, or ``default`` when it is absent, empty, corrupt or not an object."""
    doc, _state = read_json_state(path)
    return doc if doc is not None else default


__all__ = ["STATES", "read_json_state", "read_json_object"]
