"""broker_secrets.py — load broker credentials saved by the Tier-2 broker-admin app.

The broker-admin console writes credentials to config/broker_credentials.env (chmod 600,
gitignored). The adapters call load_into_env() at construction so those credentials take
effect — but it NEVER overrides a value already present in the environment (the main .env
still wins for already-live brokers like Alpaca). Idempotent and side-effect-free beyond
setting os.environ defaults.
"""
import os
from pathlib import Path

_SECRETS_FILE = Path(__file__).resolve().parent.parent / "config" / "broker_credentials.env"
_loaded = False


def load_into_env(force: bool = False) -> int:
    """Set any broker credential keys from the secrets file that aren't already in the
    environment. Returns the count of keys applied. Safe to call repeatedly.

    If the secrets file is missing on first call we do NOT latch success — a later
    deploy that restores config/broker_credentials.env (symlink) must be able to load
    without restarting the process. Only latch after a successful read of an existing file.
    """
    global _loaded
    if _loaded and not force:
        return 0
    if not _SECRETS_FILE.exists():
        # Leave _loaded=False so a subsequently-created symlink/file is picked up.
        return 0
    applied = 0
    try:
        for line in _SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and not os.environ.get(k):   # main .env / shell env wins
                os.environ[k] = v
                applied += 1
        _loaded = True
    except Exception:
        # Read failed — allow retry on next call.
        pass
    return applied
