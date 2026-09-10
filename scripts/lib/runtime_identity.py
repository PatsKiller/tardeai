"""Trusted runtime identity for durable producer stamps.

Wake / research / commitment / cortex producers previously read only env vars and
fell through to ``"unknown"`` when cron did not export BUILD_SHA. Every organic
artifact on 2026-09-10 carried ``source_sha=unknown``, which blocks exact-SHA
epoch acceptance.

This module mirrors ``api_v2._source_sha``: env → CURRENT/release stamp files →
git HEAD → ``"unknown"``. Callers must not accept a user-supplied SHA that
disagrees with the resolved identity when fail-closed mode is requested.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping

DEFAULT_CURRENT = Path(
    "/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT"
)

_ENV_KEYS = (
    "TRADEAI_SOURCE_SHA",
    "BUILD_SHA",
    "SOURCE_COMMIT",
    "CIO_SOURCE_SHA",
    "SOURCE_SHA",
    "GIT_SHA",
)


def _read_stamp_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        if path.suffix == ".json" or path.name.endswith(".json"):
            blob = json.loads(path.read_text(encoding="utf-8"))
            for key in ("build_sha", "source_sha", "git_sha", "sha", "SOURCE_COMMIT", "BUILD_SHA"):
                val = blob.get(key)
                if val:
                    text = str(val).strip()
                    if text and text.lower() != "unknown":
                        return text
            return None
        text = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        if text and text.lower() != "unknown":
            return text
    except Exception:
        return None
    return None


def resolve_source_sha(
    env: Mapping[str, str] | None = None,
    *,
    project_root: Path | str | None = None,
    current_release: Path | str | None = None,
    allow_git: bool = True,
) -> str:
    """Resolve the deployed source SHA for durable stamps.

    Order: explicit env → CURRENT release stamps → project-local stamps → git HEAD.
    Returns ``"unknown"`` only when every source fails (legacy fallback; new
    producers should treat unknown as fail-closed for acceptance epochs).
    """
    src = env if env is not None else os.environ
    for key in _ENV_KEYS:
        val = str(src.get(key) or "").strip()
        if val and val.lower() != "unknown":
            return val

    current = Path(current_release) if current_release else DEFAULT_CURRENT
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]

    for path in (
        current / "BUILD_SHA",
        current / "SOURCE_COMMIT",
        current / "GIT_SHA",
        current / "BUILD_STAMP.json",
        root / "BUILD_SHA",
        root / "SOURCE_COMMIT",
        root / "BUILD_STAMP.json",
    ):
        hit = _read_stamp_file(path)
        if hit:
            return hit

    if allow_git:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if out.returncode == 0:
                text = (out.stdout or "").strip()
                if text and text.lower() != "unknown":
                    return text
        except Exception:
            pass

    return "unknown"


def require_source_sha(
    env: Mapping[str, str] | None = None,
    *,
    project_root: Path | str | None = None,
    current_release: Path | str | None = None,
    supplied: str | None = None,
) -> str:
    """Fail closed: refuse unknown / mismatched user-supplied SHAs."""
    resolved = resolve_source_sha(
        env, project_root=project_root, current_release=current_release
    )
    if supplied is not None and str(supplied).strip():
        got = str(supplied).strip()
        if got.lower() == "unknown":
            raise ValueError("user-supplied source_sha=unknown is refused")
        if resolved != "unknown" and got != resolved:
            raise ValueError(
                f"user-supplied source_sha={got} mismatches runtime identity {resolved}"
            )
        if resolved == "unknown":
            # Do not let a caller invent a SHA when the runtime cannot identify itself.
            raise ValueError("runtime identity unknown; refusing user-supplied source_sha")
        return got
    if resolved == "unknown" or not resolved:
        raise ValueError("runtime source_sha unresolved (unknown)")
    return resolved
