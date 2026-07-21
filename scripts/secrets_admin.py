#!/usr/bin/env python3
"""secrets_admin.py — Command Center secrets/API-key management (write-only, masked).

Lets the operator ADD/ROTATE API keys + secrets from the admin UI WITHOUT ever exposing existing values.
Security model:
  • NEVER returns, displays, or logs a full secret value — list shows presence + a masked '••••1234' hint only.
  • Writes to .env atomically (0600), preserving every other line. .env is gitignored (never committed).
  • Validates the key name + a minimum value length; updates the current process env too.
  • Audits each write (key name + actor + timestamp — NEVER the value).
Rotation note: long-running services pick up a new value on next restart; cron jobs on next run.
"""
from __future__ import annotations
import os, re, tempfile, json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
AUDIT_PATH = PROJECT_ROOT / "data" / "runtime" / "secrets_admin_audit.jsonl"
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,60}$")
SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD", "_COOKIE")
# Always offered (so the operator can add even if currently absent)
KNOWN = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY", "FINNHUB_API_KEY",
         "POLYGON_API_KEY", "FMP_API_KEY", "ALPHA_VANTAGE_API_KEY", "NEWSAPI_KEY", "BRAVE_SEARCH_API_KEY",
         "FINVIZ_API_TOKEN", "FINVIZ_COOKIE", "TELEGRAM_BOT_TOKEN", "TWILIO_AUTH_TOKEN", "SMTP_PASSWORD",
         "SCHWAB_APP_KEY", "SCHWAB_APP_SECRET",
         # SnapTrade (read-only holdings aggregation): consumer key + the per-user userSecret are secrets
         # (masked). For PERSONAL (PERS-) keys, SnapTrade provisions one user at signup and shows its
         # userId + userSecret in the dashboard — you PASTE them here (registerUser is production-only).
         "SNAPTRADE_CONSUMER_KEY", "SNAPTRADE_USER_SECRET",
         # Alpaca multi-account slots (R2 2026-07-21) — PAPER is active path; TAXABLE/IRA are
         # NOT ACTIVE scaffolds (write-only storage only; no live adapter / no validation ping).
         "ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY",
         "ALPACA_TAXABLE_API_KEY", "ALPACA_TAXABLE_SECRET_KEY",
         "ALPACA_IRA_API_KEY", "ALPACA_IRA_SECRET_KEY",
         # Legacy paper pair (deprecated — prefer ALPACA_PAPER_*)
         "ALPACA_API_KEY", "ALPACA_SECRET_KEY"]
# Editable CONFIG values (NOT secrets) managed in the same modal for completeness — shown in full, not
# masked. SCHWAB_REFRESH_TOKEN and SCHWAB_TOKEN_ENC_KEY are DELIBERATELY excluded (the refresh token is
# OAuth-flow-owned by schwab_token_manager; rotating the Fernet key orphans every stored token).
KNOWN_CONFIG = ["SCHWAB_CALLBACK_URL", "SNAPTRADE_CLIENT_ID", "SNAPTRADE_USER_ID"]
# READ-ONLY status rows: shown (present + masked) but NOT settable here.
KNOWN_READONLY = []


def _read_env():
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    d = {}
    for l in lines:
        if "=" in l and not l.lstrip().startswith("#"):
            k, _, v = l.partition("=")
            d[k.strip()] = v.strip().strip("'\"")
    return lines, d


def _mask(v):
    if not v:
        return None
    v = v.strip().strip("'\"")
    return ("••••" + v[-4:]) if len(v) >= 8 else "••••"


def _format_env_line(key: str, value: str) -> str:
    """Quote .env values that break shell parsing (Finviz cookies contain ; ( ) spaces)."""
    if re.search(r"[;() $&|<>!#'\"\\]", value) or " " in value:
        escaped = value.replace("'", "'\"'\"'")
        return f"{key}='{escaped}'"
    return f"{key}={value}"


def list_secrets():
    """Names + presence + masked hint. NEVER full values."""
    _, d = _read_env()
    keys = sorted((set(KNOWN) | {k for k in d if k.endswith(SECRET_SUFFIXES)}) - set(KNOWN_READONLY))
    out = [{"key": k, "present": bool(d.get(k)), "masked": _mask(d.get(k)), "is_config": False} for k in keys]
    # config values are NOT secrets → shown in full (still editable here)
    out += [{"key": k, "present": bool(d.get(k)), "masked": d.get(k) or None, "is_config": True} for k in KNOWN_CONFIG]
    # read-only status rows (connect-flow-owned) — masked, present/absent only, NOT editable here
    out += [{"key": k, "present": bool(d.get(k)), "masked": _mask(d.get(k)), "is_config": False, "read_only": True}
            for k in KNOWN_READONLY]
    return {"secrets": out,
            "note": "Secrets are write-only — the UI never shows or returns a secret value. Config values are shown in full. Read-only rows are managed by their own flow (e.g. SnapTrade connect). .env is 0600 + gitignored."}


def _audit(key, actor):
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_PATH, "a") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "key": key,
                                "actor": actor, "action": "set"}) + "\n")
    except Exception:
        pass


def set_secret(key, value, actor="operator"):
    """Write/rotate one secret in .env atomically. Returns masked confirmation only — never the value."""
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise ValueError("invalid key name (must be UPPER_SNAKE_CASE)")
    if key in KNOWN_READONLY:
        raise ValueError(f"{key} is read-only here — it is managed by its own flow (e.g. snaptrade_connect.py)")
    is_config = key in KNOWN_CONFIG
    if not is_config and not key.endswith(SECRET_SUFFIXES):
        raise ValueError(f"key must end with one of {SECRET_SUFFIXES} (secret keys only) or be a known config key")
    value = (value or "").strip()
    if len(value) < 4:
        raise ValueError("value too short")
    lines, _ = _read_env()
    newline = _format_env_line(key, value)
    out, replaced = [], False
    for l in lines:
        if "=" in l and l.split("=", 1)[0].strip() == key and not l.lstrip().startswith("#"):
            out.append(newline); replaced = True
        else:
            out.append(l)
    if not replaced:
        out.append(newline)
    fd, tmp = tempfile.mkstemp(dir=str(ENV_PATH.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_PATH)
    os.environ[key] = value           # current process picks it up immediately
    _audit(key, actor)
    return {"ok": True, "key": key, "masked": (value if is_config else _mask(value)), "is_config": is_config, "rotated": replaced,
            "note": "Written to .env (0600). Long-running services apply it on next restart; cron jobs on next run."}


if __name__ == "__main__":
    print(json.dumps(list_secrets(), indent=2, ensure_ascii=False))
