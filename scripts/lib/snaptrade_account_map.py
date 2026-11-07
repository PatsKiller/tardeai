"""Where the SnapTrade account map lives (LQ-20261107-251).

``config/snaptrade_accounts.json`` maps SnapTrade account ids to internal account keys. It is operator-specific, so
it is gitignored: it exists in the dev checkout and in no served release (releases are built from git). Every reader
used ``PROJECT_ROOT/config/...`` only, so on the served tree the map was always "missing" and the SnapTrade row went
DEGRADED with "no account mapping".

The map now resolves in this order, first file that exists wins:
  1. ``$SNAPTRADE_ACCOUNTS_MAP`` (explicit path)
  2. ``<persistent state root>/config/snaptrade_accounts.json`` (survives releases; where the operator places it)
  3. ``<repo>/config/snaptrade_accounts.json`` (the old location)
Contents are never logged or returned in errors; only the searched paths are named.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FILENAME = "snaptrade_accounts.json"
ENV_VAR = "SNAPTRADE_ACCOUNTS_MAP"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _state_root() -> Path:
    try:
        from lib.canonical_store_registry import production_state_root  # type: ignore
        return Path(production_state_root())
    except Exception:  # noqa: BLE001 -- fall back to the documented default location
        return Path.home() / "trade-ai-releases" / "persistent-state"


def candidates(*, repo_root: Path | None = None, state_root: Path | None = None) -> list[Path]:
    out: list[Path] = []
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        out.append(Path(env))
    out.append((state_root or _state_root()) / "config" / FILENAME)
    out.append((repo_root or _REPO_ROOT) / "config" / FILENAME)
    return out


def map_path(*, repo_root: Path | None = None, state_root: Path | None = None) -> Path | None:
    """The first existing map file, or None when none of the candidates exists."""
    for p in candidates(repo_root=repo_root, state_root=state_root):
        if p.is_file():
            return p
    return None


def searched(*, repo_root: Path | None = None, state_root: Path | None = None) -> str:
    return ", ".join(str(p) for p in candidates(repo_root=repo_root, state_root=state_root))


def load(*, repo_root: Path | None = None, state_root: Path | None = None) -> dict[str, str]:
    """{snaptrade_account_id: internal_account_key}; empty when no file or an unreadable/invalid one."""
    p = map_path(repo_root=repo_root, state_root=state_root)
    if p is None:
        return {}
    try:
        cfg = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    raw = cfg.get("accounts", cfg) if isinstance(cfg, dict) else {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
