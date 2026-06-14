"""snaptrade_credentials.py — read / write / status for the SnapTrade API keys.

SnapTrade auth has TWO halves:
  • the CLIENT pair (clientId + consumerKey) — from your SnapTrade dashboard "API Keys" page. These are
    APP-level, the same for every end-user. They live in .env (chmod 600, gitignored) — the SAME store the
    central "API Keys & Secrets" page (secrets_admin) manages, so both UIs agree. Add them there OR via the
    Connect SnapTrade modal; the consumer key registers as a masked secret, the client id as a config value.
  • the per-USER secret (userId + userSecret) — minted later by registerUser during the connect flow and
    stored in the DB, NOT here. (See the connect scaffold.)

This module ONLY manages the client pair so the UI modal can drop them into the env file. It is
write-then-mask: status() never returns the consumer key, only whether it is set + a masked client id.
No network, no orders, no trading — pure local secret storage.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

# Unified store: the SAME .env the central "API Keys & Secrets" manager (secrets_admin.py) writes to, so the
# secrets page, this modal, and the connect flow all read/write one file. (.env is 0600 + gitignored.)
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

# Load .env into the process env so standalone scripts (snaptrade_sync.py / _connect.py) see the keys —
# the long-running server already loads .env at startup; this covers cron/CLI runs. Never overrides an
# already-exported value (shell/server env wins).
try:
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE)
except Exception:
    pass
CLIENT_ID_KEY = "SNAPTRADE_CLIENT_ID"
CONSUMER_KEY_KEY = "SNAPTRADE_CONSUMER_KEY"
# per-end-user connection secret, minted by registerUser during the connect flow
USER_ID_KEY = "SNAPTRADE_USER_ID"
USER_SECRET_KEY = "SNAPTRADE_USER_SECRET"

# SnapTrade client ids look like SNAPTRADE-XYZ / alnum-dash; consumer keys are long opaque tokens. Keep the
# validation permissive but non-empty + no whitespace/newlines (so we never corrupt the KEY=VALUE file).
_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-\.]{8,200}$")


def _read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _mask(v: str | None) -> str | None:
    if not v:
        return None
    if len(v) <= 6:
        return "•" * len(v)
    return f"{v[:4]}…{v[-2:]}"


def status() -> dict:
    """Non-secret status for the UI. NEVER returns the consumer key value."""
    env = _read_env()
    # the env file wins, but a value already exported in the process env also counts as "set"
    cid = env.get(CLIENT_ID_KEY) or os.environ.get(CLIENT_ID_KEY) or ""
    csk = env.get(CONSUMER_KEY_KEY) or os.environ.get(CONSUMER_KEY_KEY) or ""
    return {
        "client_id_set": bool(cid),
        "consumer_key_set": bool(csk),
        "client_id_masked": _mask(cid),
        "ready": bool(cid and csk),
        "env_file": str(_ENV_FILE),
    }


def _write_keys(updates: dict[str, str]) -> None:
    """Atomically write/replace KEY=VALUE pairs in .env, preserving every other line, chmod 600, and
    exporting into the live process env. Atomic (tmp + os.replace) so a crash can't corrupt .env — same
    discipline as secrets_admin.set_secret."""
    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = _ENV_FILE.read_text().splitlines() if _ENV_FILE.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"\s*([A-Za-z0-9_]+)\s*=", line)
        if m and m.group(1) in updates:
            out.append(f"{m.group(1)}={updates[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    fd, tmp = tempfile.mkstemp(dir=str(_ENV_FILE.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, _ENV_FILE)
    for k, v in updates.items():
        os.environ[k] = v


def save(client_id: str, consumer_key: str) -> dict:
    """Write/replace the SnapTrade client pair. Raises ValueError on malformed input. Returns status()."""
    client_id = (client_id or "").strip()
    consumer_key = (consumer_key or "").strip()
    if not _VALUE_RE.match(client_id):
        raise ValueError("client_id missing or malformed (expected 8–200 chars, no spaces)")
    if not _VALUE_RE.match(consumer_key):
        raise ValueError("consumer_key missing or malformed (expected 8–200 chars, no spaces)")
    _write_keys({CLIENT_ID_KEY: client_id, CONSUMER_KEY_KEY: consumer_key})
    return status()


def user_status() -> dict:
    """Non-secret status of the per-user connection (userId + userSecret). Never returns the secret."""
    env = _read_env()
    uid = env.get(USER_ID_KEY) or os.environ.get(USER_ID_KEY) or ""
    usec = env.get(USER_SECRET_KEY) or os.environ.get(USER_SECRET_KEY) or ""
    return {"user_id_set": bool(uid), "user_secret_set": bool(usec),
            "user_id_masked": _mask(uid), "ready": bool(uid and usec)}


def save_user(user_id: str, user_secret: str) -> dict:
    """Persist the per-user connection secret from registerUser. Returns user_status()."""
    user_id = (user_id or "").strip()
    user_secret = (user_secret or "").strip()
    if not user_id or not user_secret:
        raise ValueError("user_id and user_secret are both required")
    _write_keys({USER_ID_KEY: user_id, USER_SECRET_KEY: user_secret})
    return user_status()


def clear() -> dict:
    """Remove ALL SnapTrade keys (client pair + user secret) from the env file. Returns status()."""
    keys = (CLIENT_ID_KEY, CONSUMER_KEY_KEY, USER_ID_KEY, USER_SECRET_KEY)
    if _ENV_FILE.exists():
        kept = [ln for ln in _ENV_FILE.read_text().splitlines()
                if not re.match(rf"\s*({'|'.join(keys)})\s*=", ln)]
        _ENV_FILE.write_text("\n".join(kept) + ("\n" if kept else ""))
    for k in keys:
        os.environ.pop(k, None)
    return status()


if __name__ == "__main__":
    import json
    print(json.dumps(status(), indent=2))
