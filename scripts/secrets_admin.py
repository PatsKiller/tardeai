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
SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD", "_COOKIE", "_DSN", "_MD5")
# Always offered (so the operator can add even if currently absent)
KNOWN = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY", "FINNHUB_API_KEY",
         "POLYGON_API_KEY", "FMP_API_KEY", "ALPHA_VANTAGE_API_KEY", "NEWSAPI_KEY", "BRAVE_SEARCH_API_KEY",
         "FINVIZ_API_TOKEN", "FINVIZ_COOKIE", "TELEGRAM_BOT_TOKEN", "TWILIO_AUTH_TOKEN", "SMTP_PASSWORD",
         "SCHWAB_APP_KEY", "SCHWAB_APP_SECRET",
         # Agentic runtime LAB/SHADOW DSNs (Bitwarden SM SoT; never log values)
         "LAB_DSN", "SHADOW_DSN", "SHADOW_READER_DSN",
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
         "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
         # moomoo OpenD data plane. MD5 of the login password, never the plaintext —
         # OpenD takes -login_pwd_md5 natively, so the reusable password never lands
         # on this host. Replaces the cleartext <login_pwd> in OpenD.xml, which held
         # the vendor placeholder "123456" and failed login (2026-07-23).
         "MOOMOO_OPEND_LOGIN_PWD_MD5"]
# NOTE: BWS_* machine tokens are NEVER stored in SM or managed here (Rule 1).
# Editable CONFIG values (NOT secrets) managed in the same modal for completeness — shown in full, not
# masked. SCHWAB_REFRESH_TOKEN and SCHWAB_TOKEN_ENC_KEY are DELIBERATELY excluded (the refresh token is
# OAuth-flow-owned by schwab_token_manager; rotating the Fernet key orphans every stored token).
KNOWN_CONFIG = ["SCHWAB_CALLBACK_URL", "SNAPTRADE_CLIENT_ID", "SNAPTRADE_USER_ID",
                # moomoo login id/email — an identifier, not a secret; the credential
                # is MOOMOO_OPEND_LOGIN_PWD_MD5.
                "MOOMOO_OPEND_LOGIN_ACCOUNT"]
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


# Display labels for Alpaca live slots (READ-ONLY DATA · execution not built)
_ALPACA_LIVE_LABELS = {
    "ALPACA_TAXABLE_API_KEY": "Alpaca Taxable (Live) — API key",
    "ALPACA_TAXABLE_SECRET_KEY": "Alpaca Taxable (Live) — secret",
    "ALPACA_IRA_API_KEY": "Alpaca IRA (Live) — API key",
    "ALPACA_IRA_SECRET_KEY": "Alpaca IRA (Live) — secret",
    "ALPACA_PAPER_API_KEY": "Alpaca Paper — API key",
    "ALPACA_PAPER_SECRET_KEY": "Alpaca Paper — secret",
}

def _render_env_path() -> Path:
    uid = os.getuid()
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        p = Path(xdg) / "tradeai" / "env"
        if p.is_file():
            return p
    return Path(f"/run/user/{uid}/tradeai/env")


def _read_secret_store():
    """Prefer tmpfs SM render, else disk .env (names+values for mask only)."""
    rp = _render_env_path()
    if rp.is_file():
        return _read_env_file(rp)
    return _read_env()


def _read_env_file(path: Path):
    lines = path.read_text().splitlines() if path.exists() else []
    d = {}
    for l in lines:
        if "=" in l and not l.lstrip().startswith("#"):
            k, _, v = l.partition("=")
            d[k.strip()] = v.strip().strip("'\"")
    return lines, d


def list_secrets():
    """Names + presence + masked hint. NEVER full values."""
    _, d = _read_secret_store()
    # never surface BWS_*
    d = {k: v for k, v in d.items() if not k.upper().startswith("BWS_")}
    keys = sorted((set(KNOWN) | {k for k in d if k.endswith(SECRET_SUFFIXES)}) - set(KNOWN_READONLY))
    out = []
    for k in keys:
        if k.upper().startswith("BWS_"):
            continue
        row = {"key": k, "present": bool(d.get(k)), "masked": _mask(d.get(k)), "is_config": False}
        if k in _ALPACA_LIVE_LABELS:
            row["label"] = _ALPACA_LIVE_LABELS[k]
            row["badge"] = (
                "READ-ONLY DATA · execution not built"
                if "TAXABLE" in k or "IRA" in k
                else "paper trading"
            )
        out.append(row)
    # config values are NOT secrets → shown in full (still editable here)
    out += [{"key": k, "present": bool(d.get(k)), "masked": d.get(k) or None, "is_config": True} for k in KNOWN_CONFIG]
    # read-only status rows (connect-flow-owned) — masked, present/absent only, NOT editable here
    out += [{"key": k, "present": bool(d.get(k)), "masked": _mask(d.get(k)), "is_config": False, "read_only": True}
            for k in KNOWN_READONLY]
    return {"secrets": out,
            "note": "Secrets are write-only. Backend: Bitwarden Secrets Manager (trade-ai-prod) → tmpfs render. BWS machine tokens are never stored here."}


def _audit(key, actor):
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_PATH, "a") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "key": key,
                                "actor": actor, "action": "set"}) + "\n")
    except Exception:
        pass


def _sm_upsert(key: str, value: str) -> str:
    """Create or edit secret in SM project. Returns 'created'|'edited'. Never logs value."""
    import json
    import subprocess
    from pathlib import Path as _P

    bws = str(_P.home() / ".local" / "bin" / "bws")
    write_tok = (_P.home() / ".openclaw" / "credentials" / "bws_write_token").read_text().strip()
    read_tok = (_P.home() / ".openclaw" / "credentials" / "bws_read_token").read_text().strip()
    env_w = os.environ.copy()
    env_w["BWS_ACCESS_TOKEN"] = write_tok
    env_r = os.environ.copy()
    env_r["BWS_ACCESS_TOKEN"] = read_tok
    # project id
    pr = subprocess.run([bws, "project", "list", "--output", "json"], env=env_r,
                        capture_output=True, text=True, timeout=60)
    if pr.returncode != 0:
        raise RuntimeError("SM project list failed")
    pid = None
    for item in json.loads(pr.stdout or "[]"):
        if item.get("name") == "trade-ai-prod":
            pid = item.get("id")
            break
    if not pid:
        raise RuntimeError("trade-ai-prod not found")
    # existing?
    lr = subprocess.run([bws, "secret", "list", str(pid), "--output", "json"], env=env_r,
                        capture_output=True, text=True, timeout=90)
    existing_id = None
    if lr.returncode == 0:
        for item in json.loads(lr.stdout or "[]"):
            if item.get("key") == key:
                existing_id = item.get("id")
                break
    if existing_id:
        r = subprocess.run(
            [bws, "secret", "edit", str(existing_id), "--value", value, "--output", "json"],
            env=env_w, capture_output=True, text=True, timeout=90,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").replace(value, "[REDACTED]")[:160]
            raise RuntimeError(f"SM edit failed: {err}")
        return "edited"
    r = subprocess.run(
        [bws, "secret", "create", "--output", "json", "--", key, value, str(pid)],
        env=env_w, capture_output=True, text=True, timeout=90,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").replace(value, "[REDACTED]")[:160]
        raise RuntimeError(f"SM create failed: {err}")
    return "created"


def set_secret(key, value, actor="operator"):
    """Write/rotate one secret: Bitwarden SM → render tmpfs → process env. Never returns the value."""
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise ValueError("invalid key name (must be UPPER_SNAKE_CASE)")
    if key.upper().startswith("BWS_"):
        raise ValueError("BWS_* machine tokens cannot be stored via this modal (Rule 1)")
    if key in KNOWN_READONLY:
        raise ValueError(f"{key} is read-only here — it is managed by its own flow (e.g. snaptrade_connect.py)")
    is_config = key in KNOWN_CONFIG
    if not is_config and not key.endswith(SECRET_SUFFIXES):
        raise ValueError(f"key must end with one of {SECRET_SUFFIXES} (secret keys only) or be a known config key")
    value = (value or "").strip()
    # allow blank clear (stores SM sentinel); real secrets still min length when non-empty
    if value and len(value) < 4:
        raise ValueError("value too short")
    # FINVIZ_COOKIE: reject truncated cookies before SM upsert (never log the value)
    if key == "FINVIZ_COOKIE" and value:
        try:
            import sys as _sys
            _sp = str(Path(__file__).resolve().parent / "secrets")
            if _sp not in _sys.path:
                _sys.path.insert(0, _sp)
            from resolve_secret import validate_finviz_cookie_value
            validate_finviz_cookie_value(value)
        except ValueError:
            raise
        except Exception:
            if len(value) < 50 or ".ASPXAUTH=" not in value:
                raise ValueError(
                    "FINVIZ_COOKIE rejected: need len>=50 and .ASPXAUTH= (truncated cookies fail Elite CSV export)."
                )
    try:
        import sys
        from pathlib import Path as _P
        _sp = str(_P(__file__).resolve().parent / "secrets")
        if _sp not in sys.path:
            sys.path.insert(0, _sp)
        from empty_sentinel import encode_empty
        sm_value = encode_empty(value)
    except Exception:
        sm_value = value if value else "__TRADEAI_EMPTY__"

    # S5: SM is source of truth
    action = _sm_upsert(key, sm_value)
    # re-render tmpfs
    try:
        import subprocess
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent.parent
        subprocess.run(
            [str(root / ".venv" / "bin" / "python"), str(root / "scripts" / "secrets" / "render_env.py"), "--now"],
            cwd=str(root), capture_output=True, text=True, timeout=180,
        )
    except Exception:
        pass
    # Dual-write: keep disk .env aligned for keys already present (legacy cron that only sources .env)
    if value:
        try:
            import sys as _sys
            _sp = str(Path(__file__).resolve().parent / "secrets")
            if _sp not in _sys.path:
                _sys.path.insert(0, _sp)
            from resolve_secret import upsert_disk_env_key
            upsert_disk_env_key(key, value, only_if_exists=True)
        except Exception:
            pass
    os.environ[key] = value
    _audit(key, actor)
    # Telegram confirm (no values)
    try:
        from telegram_alert import send_telegram
        send_telegram(f"🔐 Secret {action}: `{key}` (SM → tmpfs render). Actor={actor}.", bypass_router=True)
    except Exception:
        pass
    return {
        "ok": True,
        "key": key,
        "masked": (value if is_config else _mask(value)),
        "is_config": is_config,
        "rotated": action == "edited",
        "backend": "bitwarden_sm",
        "action": action,
        "note": "Written to Bitwarden SM + tmpfs render (+ disk .env if key already existed). Long-running services pick up on next restart.",
    }


if __name__ == "__main__":
    print(json.dumps(list_secrets(), indent=2, ensure_ascii=False))
