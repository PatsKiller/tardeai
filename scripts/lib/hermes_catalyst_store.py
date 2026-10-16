"""Where the Hermes momentum/scalp catalyst research lives (operator 2026-10-16).

Until 2026-10-16 ``hermes_momentum_catalyst_researcher.py`` wrote ``<code root>/data/hermes/momentum_catalysts`` —
under cron that is the RELEASE directory (``portfolio-server/CURRENT/data``), so every release started empty and the
canonical reader (``build_catalyst_graph.momentum_catalysts_dir`` -> persistent state) had seen nothing since
2026-08-26. The store is now the persistent state root (``canonical_store_registry.production_state_root``).

Backward compatibility: the single writer also mirrors the same day file to the legacy code-root path (a derived
copy written immediately after the primary, never read back by the writer), so readers that still resolve
``ROOT/data/hermes/momentum_catalysts`` keep working until they move to :func:`read_dirs`. Readers should call
:func:`day_file_for_read`, which prefers the persistent store and falls back to the legacy path.
"""
from __future__ import annotations

import os
from pathlib import Path

REL = Path("data") / "hermes" / "momentum_catalysts"
CODE_ROOT = Path(__file__).resolve().parent.parent.parent
#: tests / operators can pin the directory explicitly
DIR_ENV = "HERMES_MOMENTUM_CATALYSTS_DIR"


def state_dir() -> Path:
    """The canonical (persistent-state) directory."""
    env = os.environ.get(DIR_ENV, "").strip()
    if env:
        return Path(env)
    try:
        try:
            from lib.canonical_store_registry import production_state_root
        except ImportError:  # pragma: no cover
            from scripts.lib.canonical_store_registry import production_state_root  # type: ignore
        return Path(production_state_root()) / REL
    except Exception:  # noqa: BLE001
        return CODE_ROOT / REL


def legacy_dir(code_root: Path | str | None = None) -> Path:
    return Path(code_root or CODE_ROOT) / REL


def day_file(day: str) -> Path:
    return state_dir() / f"{day}_catalysts.jsonl"


def legacy_day_file(day: str, code_root: Path | str | None = None) -> Path:
    return legacy_dir(code_root) / f"{day}_catalysts.jsonl"


def read_dirs(code_root: Path | str | None = None) -> list[Path]:
    """Directories to read, canonical first; de-duplicated."""
    out: list[Path] = []
    for d in (state_dir(), legacy_dir(code_root)):
        try:
            key = d.resolve()
        except OSError:
            key = d
        if all(key != (x.resolve() if x.exists() else x) for x in out):
            out.append(d)
    return out


def day_file_for_read(day: str, code_root: Path | str | None = None) -> Path:
    """The day's file: canonical when it exists, else the legacy code-root copy (may not exist)."""
    primary = day_file(day)
    if primary.is_file():
        return primary
    return legacy_day_file(day, code_root)
