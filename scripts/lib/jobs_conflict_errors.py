"""Jobs reads W10's canonical DATA_ERROR section without interpreting findings.

The engine owns filtering, ordering, paging, conversion and conflict semantics.
This reader reports availability only; it never opens or writes the ledger.
"""
from __future__ import annotations

from importlib import import_module
from pathlib import Path


def get_data_errors(root: Path, *, provider=None) -> dict:
    if provider is None:
        try:
            provider = import_module("scripts.lib.conflicts.api").data_error_section
        except (ImportError, AttributeError):
            return {"section": None, "unavailable_reason": "Conflict data is unavailable: the canonical reader is not installed"}
    try:
        section = provider(root=root)
    except (OSError, ValueError, RuntimeError, TypeError):
        return {"section": None, "unavailable_reason": "Conflict data could not be read from its canonical source"}
    if not isinstance(section, dict) or not {"findings", "headline", "gap"} <= section.keys():
        return {"section": None, "unavailable_reason": "Conflict data is unavailable: the canonical section is incomplete"}
    # Preserve the whole section, including future fields, nulls and engine gaps.
    # Do not convert ConflictRecord, pick a headline, sort, filter or count here.
    return {"section": section, "unavailable_reason": None}
