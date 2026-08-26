"""DataStoreInventory@v1 — bounded inventory of persisted intelligence stores."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.canonical_store_registry import STORES, production_state_root, resolve_store

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "DataStoreInventory@v1"


def _row_count(path: Path, fmt: str) -> int | None:
    if not path.is_file():
        return None
    try:
        if fmt == "jsonl":
            return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
        if fmt == "json":
            return 1
    except OSError:
        return None
    return None


def inventory(*, root: Path | str | None = None) -> dict[str, Any]:
    base = production_state_root(root)
    rows = []
    for store_id, spec in STORES.items():
        loc = resolve_store(store_id, root=base)
        path = Path(loc.get("path") or loc.get("primary_path"))
        real = path.resolve() if path.exists() else path
        st = path.stat() if path.exists() else None
        rows.append({
            "store_id": store_id,
            "path": str(path),
            "realpath": str(real),
            "format": spec.get("format"),
            "bytes": st.st_size if st else 0,
            "row_count": _row_count(path, str(spec.get("format") or "")),
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat() if st else None,
            "exists": bool(path.exists()),
            "writer": spec.get("writer"),
            "readers": spec.get("readers") or [],
            "schema": spec.get("schema"),
            "authority": spec.get("authority"),
            "append_only": spec.get("append_only"),
            "rebuildable": spec.get("rebuildable"),
            "used_alias": loc.get("used_alias"),
            "root_drift": path.exists() and "trade-ai-releases" not in str(real) and "data/" in str(real),
        })
    return {
        "schema": SCHEMA,
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "state_root": str(base),
        "n": len(rows),
        "present": sum(1 for r in rows if r["exists"]),
        "missing": sum(1 for r in rows if not r["exists"]),
        "rows": rows,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def writer_reader_graph() -> dict[str, Any]:
    flags = []
    for store_id, spec in STORES.items():
        if spec.get("stale_reader_filenames"):
            flags.append({"store_id": store_id, "flag": "STALE_READER", "filenames": spec["stale_reader_filenames"]})
        if not spec.get("writer"):
            flags.append({"store_id": store_id, "flag": "NO_WRITER"})
        if spec.get("kind") == "current" and spec.get("aliases"):
            flags.append({"store_id": store_id, "flag": "DUPLICATE_CURRENT_PROJECTION_ALIASES"})
    return {
        "schema": "WriterStoreReaderGraph@v1",
        "stores": [
            {"store_id": k, "writer": v.get("writer"), "readers": v.get("readers") or [], "path": v.get("path")}
            for k, v in STORES.items()
        ],
        "flags": flags,
        "authority": AUTHORITY,
        "financial_action": False,
    }
