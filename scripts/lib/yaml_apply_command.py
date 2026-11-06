"""Argument list for POST /api/yaml-apply (injection triage 2026-11-06).

The handler used to join the request body's ``suggestion_ids`` into a ``shell=True`` command line, so any id carrying
shell syntax ran as a command on the host. The ids are now validated (advisor ids look like ``sug_001``) and passed as
separate argv entries with no shell. A leading ``-`` is refused so an id cannot become a writer option.
"""
from __future__ import annotations

import re
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_IDS = 200


def yaml_apply_argv(python: str, writer: str, suggestion_ids: Any, project_root: str) -> list[str]:
    """The writer's argv, or ValueError naming why the request is refused."""
    if not isinstance(suggestion_ids, list) or not suggestion_ids:
        raise ValueError("suggestion_ids must be a non-empty list")
    if len(suggestion_ids) > MAX_IDS:
        raise ValueError(f"at most {MAX_IDS} suggestion_ids")
    bad = [s for s in suggestion_ids if not isinstance(s, str) or not _ID.match(s)]
    if bad:
        raise ValueError(f"invalid suggestion id(s): {[str(b)[:40] for b in bad[:3]]}")
    return [python, writer, "--apply", *suggestion_ids, "--project-root", project_root]
