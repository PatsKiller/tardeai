"""Host-side writer of the defense engine's stops slice (DefenseStopsSlice@v1, lib.defense_engine.stops_slice).

HOST ONLY. This module reads positions and stops through cio_truth.resolve, whose import graph reaches
db_adapter -> holdings_guard -> schwab_position_sync (imported for write paths, never called on this read). The
n8n lane defense-engine-build must not import it: scripts/defense_engine_build.py reads the slice file this module
writes, and tests/test_defense_engine_lane_reach.py pins that the lane's import closure reaches no broker module.

Callers: the inverse-stoplights cron (scripts/defense_inverse_stoplights.py, 17:55 weekdays) refreshes the slice
before it evaluates; host callers that want a live build pass ``resolve_live(root)[0]`` to
``defense_engine_build.build(truth=...)``. Reads only (SELECTs); writes one file atomically; no broker call,
no credential read, no order.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from . import defense_engine as de


def resolve_live(root: Path) -> tuple[Optional[dict], Optional[str]]:
    """(cio_truth.resolve document, gap). Fails soft: any error is a stated gap, never a raise."""
    try:
        from . import cio_truth
        from .holdings_document import default_db_query
        return cio_truth.resolve(root, db_query=default_db_query()), None
    except Exception as e:  # noqa: BLE001
        return None, f"cio_truth unavailable: {type(e).__name__}"


def write_slice(root: Path, slice_doc: dict) -> Path:
    path = Path(root) / de.STOPS_SLICE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(slice_doc, fh, default=str)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)  # our own temp file, never a store
        raise
    return path


def refresh(root: Path, *, dry_run: bool = False) -> dict:
    """Resolve live, slice, and write (unless dry_run). Returns {"wrote", "path", "as_of", "rows", "error"}."""
    truth, gap = resolve_live(Path(root))
    doc = de.stops_slice(truth)
    out = {"wrote": False, "path": str(Path(root) / de.STOPS_SLICE_REL), "as_of": (doc or {}).get("as_of"),
           "rows": len(((doc or {}).get("positions") or {}).get("rows") or []), "error": gap}
    if doc is None:
        out["error"] = gap or "cio_truth returned no positions"
        return out
    if not dry_run:
        try:
            write_slice(Path(root), doc)
            out["wrote"] = True
        except Exception as e:  # noqa: BLE001 -- a failed slice write never breaks the caller
            out["error"] = f"{type(e).__name__}: {e}"[:300]
    return out
