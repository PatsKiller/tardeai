"""Read-path health registration for Moomoo Stage 0.

Writes a local JSON registry only. Does NOT enable systemd timers, cron,
order routing, or agent OPERATIONAL status.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .config import Stage0Config


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_health_record(
    config: Stage0Config,
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "moomoo-stage0-health-v1",
        "stage": 0,
        "read_path_only": True,
        "order_routing": False,
        "trade_unlock": False,
        "agents_marked_operational": 0,
        "schedule_enabled": False,
        "registered_at": _utc_now(),
        "config_path": str(config.path),
        "opend": {
            "host": config.host,
            "port": config.port,
            # Never include secret values
            "secret_names_required": list(config.required_secret_names),
        },
        "preflight_ok": bool(preflight.get("ok")),
        "preflight_gates": preflight.get("gates"),
        "note": (
            "Stage 0 read-path health registration only. "
            "No order routing. No OpenD trade unlock. No agent timers."
        ),
    }


def write_health_registry(
    record: Mapping[str, Any],
    path: Path | None = None,
) -> Path:
    dest = Path(path) if path else None
    if dest is None:
        raise ValueError("health registry path required")
    dest.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(record, indent=2, sort_keys=True)
    # Hard refuse if payload claims order path
    if '"order_routing": true' in blob.lower().replace(" ", ""):
        raise RuntimeError("health registry must not enable order_routing")
    if '"trade_unlock": true' in blob.lower().replace(" ", ""):
        raise RuntimeError("health registry must not enable trade_unlock")
    dest.write_text(blob + "\n", encoding="utf-8")
    return dest
