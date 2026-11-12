"""Home v010 read handlers (LQ-20261107-2149/2150). Thin and side-effect free: api_v2.py delegates here.

``diagnostics`` only READS the snapshot the ``home-diagnostics`` n8n lane wrote; it never probes the database, never
writes, and a snapshot older than the registry's ``max_snapshot_age_s`` grades every row UNKNOWN (COLLECTOR_STALE).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from lib import home_diagnostics as hd


def diagnostics(state_dir: Path | str, now: Optional[datetime] = None, registry: Optional[dict] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    snap: Any = None
    try:
        snap = json.loads((Path(state_dir) / hd.SNAPSHOT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snap = None
    try:
        reg = registry or hd.load_registry()
    except (hd.RegistryError, OSError, ValueError) as exc:
        return {"schema": hd.SCHEMA, "status": "registry_invalid", "reason": f"{type(exc).__name__}: {exc}"[:240],
                "served_at": now.isoformat(), "widgets": []}
    return hd.serve(snap, reg, now)
