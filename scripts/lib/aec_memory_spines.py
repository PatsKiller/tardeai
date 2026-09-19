"""aec_memory_spines.py — Strategic / Operational / Relationship / Learning memory.

Operator license 2026-09-19 granted parallel memory spines. This module is the
single read/write facade. It does NOT replace InstrumentRecord — Strategic and
Learning spines *link* subject_key / workflow_id into existing cognition fields.

AUTHORITY: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0 (cognition fields only on apply).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "AecMemorySnapshot@v1"
SPINES = ("strategic", "operational", "relationship", "learning")


@dataclass
class MemorySnapshot:
    schema: str
    as_of: str
    spines: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def spines_path(root: Path | None = None) -> Path:
    env = os.environ.get("TRADEAI_AEC_MEMORY")
    if env:
        return Path(env)
    persistent = Path.home() / "trade-ai-releases/persistent-state/data/cio/aec_memory_spines.json"
    if persistent.parent.is_dir():
        return persistent
    base = root or Path.cwd()
    return base / "data" / "cio" / "aec_memory_spines.json"


def empty_snapshot() -> MemorySnapshot:
    return MemorySnapshot(
        schema=SCHEMA,
        as_of=_utc_now(),
        spines={s: [] for s in SPINES},
    )


def load(path: Path | None = None) -> MemorySnapshot:
    p = path or spines_path()
    if not p.is_file():
        return empty_snapshot()
    raw = json.loads(p.read_text(encoding="utf-8"))
    spines = {s: list(raw.get("spines", {}).get(s) or []) for s in SPINES}
    return MemorySnapshot(schema=SCHEMA, as_of=str(raw.get("as_of") or _utc_now()), spines=spines)


def save(snap: MemorySnapshot, path: Path | None = None, *, dry_run: bool = False) -> Path:
    p = path or spines_path()
    snap.as_of = _utc_now()
    if dry_run:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def append_fact(
    spine: str,
    fact: dict[str, Any],
    *,
    path: Path | None = None,
    dry_run: bool = False,
) -> MemorySnapshot:
    if spine not in SPINES:
        raise ValueError(f"unknown spine={spine!r}; expected one of {SPINES}")
    # Behavior rail
    forbidden = {
        "recommended_delta_usd", "size_usd", "shares", "qty", "order", "stop",
        "limit", "target_weight_pct", "trade", "execution",
    }
    bad = forbidden.intersection(fact)
    if bad:
        raise ValueError(f"MBI_BEHAVIOR=0: refused behavior fields in memory: {sorted(bad)}")
    snap = load(path)
    row = dict(fact)
    row.setdefault("recorded_at", _utc_now())
    snap.spines[spine].append(row)
    save(snap, path, dry_run=dry_run)
    return snap


def retrieve_relevant(
    snap: MemorySnapshot,
    *,
    subject_key: str | None = None,
    limit_per_spine: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Load-before-decide helper: recent facts, optionally filtered by subject_key."""
    out: dict[str, list[dict[str, Any]]] = {}
    for spine, rows in snap.spines.items():
        picked = []
        for row in reversed(rows):
            if subject_key and row.get("subject_key") not in (None, subject_key):
                continue
            picked.append(row)
            if len(picked) >= limit_per_spine:
                break
        out[spine] = list(reversed(picked))
    return out


def claim_fingerprint(text: str) -> str:
    """Stable anti-repetition key for recommendation / briefing text."""
    import hashlib

    norm = " ".join(str(text).lower().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def seen_claim(snap: MemorySnapshot, fingerprint: str) -> bool:
    for row in snap.spines.get("learning") or []:
        if row.get("claim_fp") == fingerprint or row.get("fingerprint") == fingerprint:
            return True
    return False
