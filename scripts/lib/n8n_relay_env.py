"""Environment allowlist for the n8n run relay (B2-D2, 2026-10-09). Names only; never a value in any output.

The relay needs two secrets (TRADEAI_N8N_RELAY_BEARER, TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N) plus the rotation
overlap TRADEAI_N8N_RELAY_BEARER_PREVIOUS, which scripts/secrets/render_env.py writes during a weekly bearer
rotation (config/secret_registry.yaml overlap_previous). Every other read is non-secret config. The full
inventory of environment reads by scripts/n8n_run_relay.py and its imports (2026-10-09):

  scripts/n8n_run_relay.py                 TRADEAI_N8N_RELAY_BEARER, TRADEAI_N8N_RELAY_BEARER_PREVIOUS,
                                           TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N, TRADEAI_N8N_RELAY_LIVE_LANES,
                                           TRADEAI_N8N_GATEWAY_URL, TRADEAI_STATE_ROOT, RELAY_STRICT_ENV
  scripts/lib/n8n_coordination_projection  TRADEAI_N8N_COORDINATION_LEDGER, TRADEAI_STATE_ROOT (ledger_path)
  scripts/n8n_coordination_gateway         nothing at import (its key loaders are not called by the relay)
  scripts/lib/n8n_coordination_gateway     nothing
  Path.home()                              HOME

The relay never spawns a subprocess, so nothing downstream inherits its environment.

Two layers:
  1. render_relay_env() -> the unit's dedicated EnvironmentFile holds only RELAY_SECRET_NAMES
     (scripts/render_n8n_relay_env.py, ExecStartPre of tradeai-n8n-run-relay.service).
  2. enforce() at relay startup: under RELAY_STRICT_ENV=1 any broker / provider / other credential name
     outside the allowlist fails closed; then os.environ is scrubbed to RELAY_ALLOWED_NAMES. The scrub
     cannot rewrite /proc/<pid>/environ (the kernel's copy of the exec-time block); layer 1 keeps that clean.
"""

from __future__ import annotations

import re
from typing import Iterable, MutableMapping

from scripts.lib.secret_name_classes import classify_name

RELAY_SECRET_NAMES = (
    "TRADEAI_N8N_RELAY_BEARER",
    "TRADEAI_N8N_RELAY_BEARER_PREVIOUS",
    "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N",
)
RELAY_REQUIRED_SECRET_NAMES = ("TRADEAI_N8N_RELAY_BEARER", "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N")
RELAY_CONFIG_NAMES = (
    "TRADEAI_N8N_RELAY_LIVE_LANES",
    "TRADEAI_N8N_GATEWAY_URL",
    "TRADEAI_STATE_ROOT",
    "TRADEAI_N8N_COORDINATION_LEDGER",
    "RELAY_STRICT_ENV",
)
# Process plumbing the interpreter, logging, and systemd journal use. Nothing secret.
RELAY_RUNTIME_NAMES = (
    "HOME",
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "USER",
    "LOGNAME",
    "SHELL",
    "XDG_RUNTIME_DIR",
    "INVOCATION_ID",
    "JOURNAL_STREAM",
    "SYSTEMD_EXEC_PID",
    "PYTHONUNBUFFERED",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONIOENCODING",
)
RELAY_ALLOWED_NAMES = frozenset(RELAY_SECRET_NAMES + RELAY_CONFIG_NAMES + RELAY_RUNTIME_NAMES)
STRICT_ENV = "RELAY_STRICT_ENV"
_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def forbidden_names(names: Iterable[str]) -> dict[str, list[str]]:
    """{class: names} for broker / provider / credential names outside the allowlist. Names only."""
    out: dict[str, list[str]] = {}
    for name in sorted(set(names)):
        if name in RELAY_ALLOWED_NAMES:
            continue
        cls = classify_name(name)
        if cls:
            out.setdefault(cls, []).append(name)
    return out


def scrub(environ: MutableMapping[str, str]) -> list[str]:
    """Delete every name outside RELAY_ALLOWED_NAMES in place; return the dropped names, sorted."""
    dropped = sorted(name for name in list(environ) if name not in RELAY_ALLOWED_NAMES)
    for name in dropped:
        del environ[name]
    return dropped


def strict(environ: MutableMapping[str, str]) -> bool:
    return environ.get(STRICT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def enforce(environ: MutableMapping[str, str]) -> dict:
    """Fail closed (ok False) under strict when a forbidden name is present; otherwise scrub.

    Returns a names-only report: {"ok", "strict", "forbidden", "dropped_count"}.
    """
    is_strict = strict(environ)
    forbidden = forbidden_names(environ)
    if is_strict and forbidden:
        return {"ok": False, "reason": "relay_forbidden_env", "strict": True, "forbidden": forbidden}
    dropped = scrub(environ)
    return {"ok": True, "strict": is_strict, "forbidden": forbidden, "dropped_count": len(dropped)}


def render_relay_env(source_text: str) -> tuple[str, list[str], list[str]]:
    """(file text, kept names, missing required names) from a full secrets env file's text.

    Lines for RELAY_SECRET_NAMES are copied byte-for-byte, so systemd parses each value exactly as it parses
    the source file today. Every other line is dropped. A kept line whose value is an unterminated single
    quote (a multi-line value) raises ValueError naming the variable only.
    """
    kept: dict[str, str] = {}
    for line in source_text.splitlines():
        match = _ASSIGN_RE.match(line)
        if not match or match.group(1) not in RELAY_SECRET_NAMES:
            continue
        raw = match.group(2).strip()
        if raw.startswith("'") and (len(raw) < 2 or not raw.endswith("'")):
            raise ValueError(f"multi-line value for {match.group(1)} is not supported")
        kept[match.group(1)] = f"{match.group(1)}={raw}"
    header = [
        "# tradeai-n8n-run-relay EnvironmentFile; rendered by scripts/render_n8n_relay_env.py.",
        "# Allowlisted names only (scripts/lib/n8n_relay_env.py RELAY_SECRET_NAMES). Do not edit by hand.",
    ]
    names = [name for name in RELAY_SECRET_NAMES if name in kept]
    text = "\n".join(header + [kept[name] for name in names]) + "\n"
    missing = [name for name in RELAY_REQUIRED_SECRET_NAMES if name not in kept]
    return text, names, missing
