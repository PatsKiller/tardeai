"""Where the outlook's runtime JSON lives: the persistent-state root, never the checkout it runs from.

``$TRADEAI_STATE_ROOT`` when set (the repo-wide convention, e.g. ``scripts/db_trim.py``), else
``persistent_state_root.good_persistent_root()`` — ``~/trade-ai-releases/persistent-state``, the tree the served
release reads. A runtime file written into a release folder is lost at the next promote.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve(explicit: Path | str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    try:
        from scripts.lib.persistent_state_root import good_persistent_root
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        from lib.persistent_state_root import good_persistent_root  # type: ignore[no-redef]

    return good_persistent_root()


def runtime_dir(explicit: Path | str | None = None) -> Path:
    return resolve(explicit) / "data" / "runtime" / "market_outlook"


__all__ = ["resolve", "runtime_dir"]
