"""Merge Vite CC v3 build-meta with exact-main SHA stamps.

Vite writes ui_version (3.14+<stamp>) so cc-boot.js and the inline injector
agree. Exact-main deploy must KEEP that key — overwriting it with SHA-only
JSON made the boot path fall back to "1.6" and left the desk chip as "…".
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def merge_build_meta(
    existing: dict[str, Any] | None,
    *,
    sha: str,
    label: str = "main-exact-phase2",
    now: datetime | None = None,
) -> dict[str, Any]:
    base = dict(existing or {})
    now = now or datetime.now(timezone.utc)
    ui = str(base.get("ui_version") or "").strip()
    if not ui:
        ui = f"3.14+{sha[:8]}"
    out = {
        **base,
        "ui_version": ui,
        "git_sha": sha,
        "source_sha": sha,
        "build_sha": sha[:12],
        "source_commit": sha,
        "built_at": base.get("built_at") or now.isoformat(),
        "branch": "main",
        "release_label": label,
    }
    return out


def write_merged_build_meta(
    paths: list[Path],
    *,
    sha: str,
    label: str = "main-exact-phase2",
) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    for p in paths:
        if not p.is_file():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict) and obj.get("ui_version"):
            existing = obj
            break
        if isinstance(obj, dict) and not existing:
            existing = obj
    meta = merge_build_meta(existing, sha=sha, label=label)
    text = json.dumps(meta, indent=2) + "\n"
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return meta
