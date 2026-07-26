#!/usr/bin/env python3
"""Stable reviewed-selection binding for bounded Watch Gate 6 writes."""
from __future__ import annotations

import hashlib
import json
from typing import Any

CONTRACT = "watch-quality-gate6-reviewed-selection-v1"
_VOLATILE_KEYS = frozenset({"projection_generated_at"})


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    if isinstance(value, tuple):
        return [_stable(item) for item in value]
    return value


def selection_payload(source_commit: str, limit: int, selected: list[dict]) -> dict:
    rows = []
    for item in selected:
        rows.append({
            "symbol": str(item.get("symbol") or "").upper(),
            "tier": item.get("tier"),
            "projection": _stable(item.get("projection") or {}),
        })
    return {
        "contract": CONTRACT,
        "source_commit": str(source_commit).lower(),
        "limit": int(limit),
        "rows": rows,
    }


def selection_hash(source_commit: str, limit: int, selected: list[dict]) -> str:
    payload = selection_payload(source_commit, limit, selected)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
