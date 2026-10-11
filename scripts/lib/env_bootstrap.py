#!/usr/bin/env python3
"""env_bootstrap — load order for Trade AI secrets (S4).

1. tmpfs SM render:  $XDG_RUNTIME_DIR/tradeai/env  or /run/user/<uid>/tradeai/env
2. legacy disk .env: $PROJECT_ROOT/.env  (or .env.pre-sm-migration during cutover)
3. fail loud if neither yields required keys (optional)

Never logs values. Call early in process entrypoints:

    from env_bootstrap import load_env
    load_env()                                  # legacy: every name in the file (see below)
    load_env(names=("DB_HOST", "DB_PASSWORD"))  # only the names this caller reads

Narrowing (2026-10-11, canary blocker — AGENTS §23.18, N8N_ONBOARDING_STANDARD §2 rule 6):

- ``names`` copies only those names. A broker name (``is_broker_name``) in ``names`` is still copied: naming it
  is the caller's explicit claim to it.
- Bound mode. The n8n run executor sets ``TRADEAI_ENV_BOUND_NAMES`` (comma-separated) on a child it runs under
  enforce: the lane's allowlist ``env_names``. In such a process every ``load_env`` call copies only names in that
  set (intersected with ``names`` when given) and NEVER a broker name, even one the set or ``names`` lists. So no
  loader call can re-expand an enforced child beyond its allowlist, whichever module makes it (``db_adapter``,
  ``telegram_alert.ensure_loaded``, ...).
- ``names=None`` outside bound mode is the legacy whole-file copy, unchanged. It is kept because ~460 crontab
  lines source no env file and rely on this in-process load for names their closure reads (e.g.
  ``market_quote_provider.fetch_alpaca_quote`` reads ALPACA_API_KEY with no loader of its own); dropping broker
  names from it is an operator decision (AGENTS §17), not a loader refactor.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable

_LOADED = False

ENV_BOUND_NAMES_ENV = "TRADEAI_ENV_BOUND_NAMES"
# Explicit candidate list (os.pathsep-separated), replacing the tmpfs render and the checkout .env. Set by the
# hermetic test bootstrap (tests/conftest.py -> scripts/lib/hermetic_test_guard.py) to an empty fixture so no test,
# and no script a test launches, loads the live render (AGENTS §24.6). Production never sets it.
ENV_FILES_ENV = "TRADEAI_ENV_BOOTSTRAP_FILES"

# Broker credential / broker-config names (AGENTS §0 rule 2, §23.18 ruling 3; config/secret_registry.yaml renders
# ALPACA_* and SCHWAB_* and SNAPTRADE_* into the env file). Matched on the upper-cased name.
BROKER_NAME_PREFIXES = ("ALPACA_", "SCHWAB_", "MOOMOO_", "IBKR_", "SNAPTRADE_", "TRADING_", "BROKER_")
_BROKER_INFIX = re.compile(r"_BROKER(_|$)")


def is_broker_name(name: str) -> bool:
    """True for a name no bounded or default-narrowed load may copy. Pure."""
    up = str(name or "").strip().upper()
    return up.startswith(BROKER_NAME_PREFIXES) or bool(_BROKER_INFIX.search(up))


def bound_names(env=None) -> frozenset[str] | None:
    """The executor-set bound (``TRADEAI_ENV_BOUND_NAMES``), or None when this process is not bound.
    An empty value is a bound of nothing (an enforced lane with an empty ``env_names``). Pure over ``env``."""
    env = os.environ if env is None else env
    if ENV_BOUND_NAMES_ENV not in env:
        return None
    return frozenset(n.strip() for n in str(env.get(ENV_BOUND_NAMES_ENV) or "").split(",") if n.strip())


def _candidates() -> list[Path]:
    override = os.environ.get(ENV_FILES_ENV)
    if override is not None:
        return [Path(p) for p in override.split(os.pathsep) if p.strip()]
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


def _apply_file(path: Path, *, override: bool = False, allowed: frozenset[str] | None = None,
                deny_broker: bool = False) -> tuple[int, int]:
    """Copy names from ``path`` into os.environ. ``allowed`` None = every name. Returns (applied, skipped)."""
    n = skipped = 0
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return 0, 0
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if not k or k.upper().startswith("BWS_"):
            continue  # Rule 1: never load BWS_* into process from env files
        if (allowed is not None and k not in allowed) or (deny_broker and is_broker_name(k)):
            skipped += 1
            continue
        v = v.strip().strip("'\"")
        if override or k not in os.environ:
            os.environ[k] = v
            n += 1
    return n, skipped


def load_env(names: Iterable[str] | None = None, *, override: bool = False,
             required: list[str] | None = None) -> dict:
    """Load env from tmpfs render then disk fallback. Returns metadata (no values).

    ``names``: copy only these names (None = every name, unless the process is bound — module docstring)."""
    global _LOADED
    if isinstance(names, str):
        names = (names,)
    allowed = None if names is None else frozenset(names)
    bound = bound_names()
    if bound is not None:
        allowed = bound if allowed is None else allowed & bound
    meta = {"source": None, "path": None, "keys_applied": 0, "keys_skipped": 0, "ok": False,
            "scope": "bound" if bound is not None else ("all" if allowed is None else "names")}
    try:  # attribute this process's Postgres connections (libpq PGAPPNAME fallback)
        from pg_attribution import ensure_pgappname
    except ImportError:
        try:
            from lib.pg_attribution import ensure_pgappname
        except ImportError:
            try:
                from .pg_attribution import ensure_pgappname  # type: ignore[no-redef]
            except ImportError:
                ensure_pgappname = None
    if ensure_pgappname is not None:
        ensure_pgappname()
    for path in _candidates():
        if path.is_file() and path.stat().st_size > 0:
            n, skipped = _apply_file(path, override=override, allowed=allowed, deny_broker=bound is not None)
            meta.update({
                "source": "tmpfs" if "tradeai/env" in str(path) else "disk",
                "path": str(path),
                "keys_applied": n,
                "keys_skipped": skipped,
                "ok": True,
            })
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
