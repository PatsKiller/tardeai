"""Semantic publication keys for morning / EOD operator briefs.

MORNING:{session_date}:{material_generation}
EOD:{session_date}:{material_generation}

Two equivalent scheduler invocations: first publishes, second is
semantic_duplicate. Underlying events are never deleted.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.atomic_json_store import atomic_write_json

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "BriefSemanticDedupe@v1"


def session_date(now: datetime | None = None) -> str:
    n = now or datetime.now(timezone.utc)
    return n.astimezone().strftime("%Y-%m-%d") if n.tzinfo else n.strftime("%Y-%m-%d")


def morning_key(session: str, material_generation: str) -> str:
    return f"MORNING:{session}:{material_generation}"


def eod_key(session: str, material_generation: str) -> str:
    return f"EOD:{session}:{material_generation}"


def _state_path(root: Path, kind: str) -> Path:
    return Path(root) / "data" / "cio" / f"{kind}_brief_semantic_state.json"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"published": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"published": {}}
    return doc if isinstance(doc, dict) else {"published": {}}


def claim(
    *,
    kind: str,
    session: str,
    material_generation: str,
    root: Path | str,
) -> dict[str, Any]:
    """First claim publishes; subsequent identical keys are semantic duplicates."""
    kind = kind.upper()
    key = morning_key(session, material_generation) if kind == "MORNING" else eod_key(session, material_generation)
    path = _state_path(Path(root), kind.lower())
    state = _load_state(path)
    published = state.setdefault("published", {})
    if key in published:
        return {
            "schema": SCHEMA,
            "published": False,
            "reason": "semantic_duplicate",
            "key": key,
            "prior": published[key],
            "authority": AUTHORITY,
            "financial_action": False,
        }
    rec = {
        "key": key,
        "session_date": session,
        "material_generation": material_generation,
        "claimed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    published[key] = rec
    state["schema"] = SCHEMA
    atomic_write_json(path, state)
    return {
        "schema": SCHEMA,
        "published": True,
        "reason": None,
        "key": key,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def immediate_material(*, generation_id: str, prior_generation_id: str | None, material: bool) -> dict[str, Any]:
    """Immediate CIO pages only for NEW MATERIAL generations."""
    if not material:
        return {"send": False, "reason": "not_material", "authority": AUTHORITY, "financial_action": False}
    if prior_generation_id and prior_generation_id == generation_id:
        return {"send": False, "reason": "same_semantic_state", "authority": AUTHORITY, "financial_action": False}
    return {"send": True, "reason": "new_material_generation", "authority": AUTHORITY, "financial_action": False}
