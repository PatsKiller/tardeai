#!/usr/bin/env python3
"""env_bootstrap — load order for Trade AI secrets (S4).

1. tmpfs SM render:  $XDG_RUNTIME_DIR/tradeai/env  or /run/user/<uid>/tradeai/env
2. legacy disk .env: $PROJECT_ROOT/.env  (or .env.pre-sm-migration during cutover)
3. fail loud if neither yields required keys (optional)

Never logs values. Call early in process entrypoints:

    from env_bootstrap import load_env
    load_env()
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_LOADED = False


def _candidates() -> list[Path]:
    uid = os.getuid()
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    paths = []
    if xdg:
        paths.append(Path(xdg) / "tradeai" / "env")
    paths.append(Path(f"/run/user/{uid}/tradeai/env"))
    # project root: scripts/lib -> scripts -> root
    root = Path(__file__).resolve().parents[2]
    paths.append(root / ".env")
    paths.append(root / ".env.pre-sm-migration")
    return paths


def _apply_file(path: Path, *, override: bool = False) -> int:
    n = 0
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return 0
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if not k or k.upper().startswith("BWS_"):
            continue  # Rule 1: never load BWS_* into process from env files
        v = v.strip().strip("'\"")
        if override or k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


def load_env(*, override: bool = False, required: list[str] | None = None) -> dict:
    """Load env from tmpfs render then disk fallback. Returns metadata (no values)."""
    global _LOADED
    meta = {"source": None, "path": None, "keys_applied": 0, "ok": False}
    for path in _candidates():
        if path.is_file() and path.stat().st_size > 0:
            n = _apply_file(path, override=override)
            meta = {
                "source": "tmpfs" if "tradeai/env" in str(path) else "disk",
                "path": str(path),
                "keys_applied": n,
                "ok": True,
            }
            _LOADED = True
            break
    if required:
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            meta["ok"] = False
            meta["missing"] = missing
            raise RuntimeError(f"env_bootstrap missing required keys: {missing}")
    return meta


def ensure_loaded() -> None:
    if not _LOADED:
        load_env()


if __name__ == "__main__":
    m = load_env()
    print({k: m[k] for k in m})  # no values
    sys.exit(0 if m.get("ok") else 1)
