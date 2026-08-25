"""Historical-regime laboratory. Similarity is evidence, not destiny."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI

SCHEMA = "HistoricalEpisode@v1"
CMP = "RegimeAnalogue@v1"
PATH = "data/cio/office/historical_episodes.jsonl"
AXES = (
    "macro_regime", "inflation", "rates", "credit", "volatility",
    "breadth", "valuation", "earnings", "sector_leadership", "liquidity",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def register_episode(root: Path | str, *, label: str, statement: str, axes: dict[str, Any],
                     differences: list[str] | None = None) -> dict[str, Any]:
    eid = "ep_" + hashlib.sha256(f"{label}|{statement}".encode()).hexdigest()[:16]
    row = {
        "schema": SCHEMA,
        "episode_id": eid,
        "label": label,
        "statement": statement,
        "axes": {k: axes.get(k) for k in AXES},
        "known_differences": list(differences or []),
        "not_destiny": True,
        "created_at": _now(),
        "authority": AUTHORITY,
    }
    path = Path(root) / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return {"ok": True, "episode": row}


def _load(root: Path) -> list[dict[str, Any]]:
    path = root / PATH
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def compare(root: Path | str, current: dict[str, Any]) -> dict[str, Any]:
    """Every analogue must show similarity AND meaningful differences."""
    episodes = _load(Path(root))
    analogues = []
    for ep in episodes:
        similar, different = [], []
        axes = ep.get("axes") or {}
        for key in AXES:
            a, b = axes.get(key), current.get(key)
            if a is None or b is None:
                continue
            if a == b:
                similar.append(key)
            else:
                different.append({"axis": key, "episode": a, "current": b})
        different.extend({"axis": "stated", "note": d} for d in (ep.get("known_differences") or []))
        if similar and not different:
            continue  # refuse destiny-without-difference
        if similar:
            analogues.append({
                "episode_id": ep.get("episode_id"),
                "label": ep.get("label"),
                "similar_axes": similar,
                "differences": different,
                "not_destiny": True,
            })
    return {
        "schema": CMP,
        "current": {k: current.get(k) for k in AXES},
        "analogues": analogues,
        "n": len(analogues),
        "question": "When has something like this happened before?",
        "historical_similarity_is_not_destiny": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
