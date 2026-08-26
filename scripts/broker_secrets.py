"""broker_secrets.py — load broker credentials saved by the Tier-2 broker-admin app.

The broker-admin console writes credentials to config/broker_credentials.env (chmod 600,
gitignored). The adapters call load_into_env() at construction so those credentials take
effect — but it NEVER overrides a value already present in the environment (the main .env
still wins for already-live brokers like Alpaca). Idempotent and side-effect-free beyond
setting os.environ defaults.

Exact-main releases do not copy gitignored secrets. Search order (first existing file):
  1. ~/.config/tradeai/broker_credentials.env   (stable across promotes)
  2. PROJECT_ROOT/config/broker_credentials.env (this tree / CURRENT)
  3. CURRENT release config/broker_credentials.env
  4. canonical rebuild config/broker_credentials.env

Never log values. Never mint a new encryption key here.
"""
from __future__ import annotations

import os
from pathlib import Path

_PROJECT_SECRETS = Path(__file__).resolve().parent.parent / "config" / "broker_credentials.env"
_STABLE = Path.home() / ".config" / "tradeai" / "broker_credentials.env"
_CURRENT = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "config" / "broker_credentials.env"
_CANONICAL = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/broker_credentials.env")
_SECRETS_FILE = _PROJECT_SECRETS  # back-compat alias
_loaded = False


def iter_secrets_files() -> list[Path]:
    """Existing candidate files, first match wins. Deduped by resolved path."""
    seen: set[str] = set()
    out: list[Path] = []
    for p in (_STABLE, _PROJECT_SECRETS, _CURRENT, _CANONICAL):
        try:
            if not p.is_file():
                continue
            key = str(p.resolve())
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def secrets_file() -> Path | None:
    found = iter_secrets_files()
    return found[0] if found else None


def load_into_env(force: bool = False) -> int:
    """Set any broker credential keys from the secrets file that aren't already in the
    environment. Returns the count of keys applied. Safe to call repeatedly."""
    global _loaded
    if _loaded and not force:
        return 0
    _loaded = True
    applied = 0
    for path in iter_secrets_files():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"")
            if k and v and not os.environ.get(k):
                os.environ[k] = v
                applied += 1
        if applied:
            break
    return applied
