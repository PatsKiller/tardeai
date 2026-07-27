#!/usr/bin/env python3
"""resolve_secret — single secret resolution path for Bitwarden SM tmpfs + disk .env.

Precedence (first non-empty wins):
  1) Bitwarden SM render on tmpfs ($XDG_RUNTIME_DIR/tradeai/env or /run/user/<uid>/tradeai/env)
  2) os.environ
  3) disk repo .env

Never logs or prints secret values. Compatible with secrets_admin / render_env quoting
(KEY=value or KEY='shell-escaped').

Usage:
    from resolve_secret import resolve_secret
    cookie = resolve_secret("FINVIZ_COOKIE")
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping, Optional

# scripts/secrets/ → repo root is parents[2]
_DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def render_env_path(uid: Optional[int] = None) -> Path:
    """Path to SM tmpfs render file (may not exist yet)."""
    if uid is None:
        uid = os.getuid()
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        p = Path(xdg) / "tradeai" / "env"
        if p.is_file():
            return p
        # Prefer XDG path even if missing (caller checks is_file)
        return p
    return Path(f"/run/user/{uid}/tradeai/env")


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=value lines; strip surrounding quotes (secrets_admin / render_env style).

    Does not expand shell vars. Never logs values.
    """
    out: dict[str, str] = {}
    if not path or not Path(path).is_file():
        return out
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, val = raw.partition("=")
        key = key.strip()
        if not key or key.upper().startswith("BWS_"):
            continue
        val = val.strip()
        # Strip one layer of matching quotes (render uses single quotes with shell escapes)
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
            # Unescape shell single-quote form: '"'"' → '
            if "'" in val:
                val = val.replace("'\"'\"'", "'")
        out[key] = val
    return out


def resolve_secret(
    name: str,
    default: str = "",
    *,
    project_root: Optional[Path] = None,
    tmpfs_path: Optional[Path] = None,
    disk_env_path: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Return secret value for ``name`` using tmpfs → process env → disk .env.

    Empty / whitespace-only values are skipped so a blank tmpfs entry does not
    block a good process env or disk fallback.
    """
    name = (name or "").strip()
    if not name:
        return default

    root = Path(project_root) if project_root is not None else _DEFAULT_ROOT
    tmpfs = Path(tmpfs_path) if tmpfs_path is not None else render_env_path()
    disk = Path(disk_env_path) if disk_env_path is not None else (root / ".env")
    env_map = environ if environ is not None else os.environ

    # 1) SM tmpfs render
    if tmpfs.is_file():
        v = parse_env_file(tmpfs).get(name, "")
        if isinstance(v, str) and v.strip():
            return v.strip()

    # 2) Process environment
    v = env_map.get(name, "") if env_map is not None else ""
    if isinstance(v, str) and v.strip():
        return v.strip()

    # 3) Disk repo .env (legacy cron that only sources disk)
    if disk.is_file():
        v = parse_env_file(disk).get(name, "")
        if isinstance(v, str) and v.strip():
            return v.strip()

    return default


def resolve_finviz_auth(*, project_root: Optional[Path] = None) -> dict[str, str]:
    """Convenience: FINVIZ_COOKIE, FINVIZ_API_TOKEN, FINVIZ_USER_AGENT (may be empty)."""
    return {
        "FINVIZ_COOKIE": resolve_secret("FINVIZ_COOKIE", project_root=project_root),
        "FINVIZ_API_TOKEN": resolve_secret("FINVIZ_API_TOKEN", project_root=project_root),
        "FINVIZ_USER_AGENT": resolve_secret("FINVIZ_USER_AGENT", project_root=project_root),
    }


def validate_finviz_cookie_value(value: str) -> None:
    """Raise ValueError if cookie is truncated/invalid. Never include value in message."""
    v = (value or "").strip()
    if not v:
        raise ValueError("FINVIZ_COOKIE is empty")
    if len(v) < 50:
        raise ValueError(
            f"FINVIZ_COOKIE too short (len={len(v)}; need >= 50). "
            "Paste the full Elite session cookie including .ASPXAUTH=."
        )
    if ".ASPXAUTH=" not in v:
        raise ValueError(
            "FINVIZ_COOKIE missing .ASPXAUTH= — truncated or incomplete cookie rejected."
        )


def format_env_line(key: str, value: str) -> str:
    """Quote .env values that break shell parsing (match secrets_admin)."""
    if re.search(r"[;() $&|<>!#'\"\\]", value) or " " in value or "\n" in value:
        escaped = value.replace("'", "'\"'\"'")
        return f"{key}='{escaped}'"
    return f"{key}={value}"


def upsert_disk_env_key(
    key: str,
    value: str,
    *,
    disk_env_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
    only_if_exists: bool = True,
) -> bool:
    """Write/update one key in disk .env. Returns True if file was modified.

    When only_if_exists=True (default), only updates keys already present on disk
    so SM remains SoT without inventing new disk-only secrets.
    Never logs the value.
    """
    root = Path(project_root) if project_root is not None else _DEFAULT_ROOT
    path = Path(disk_env_path) if disk_env_path is not None else (root / ".env")
    key = (key or "").strip()
    if not key:
        return False
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        k, _, _ = line.partition("=")
        if k.strip() == key:
            found = True
            new_lines.append(format_env_line(key, value))
        else:
            new_lines.append(line)
    if not found:
        if only_if_exists and path.is_file():
            return False
        if only_if_exists and not path.is_file():
            return False
        new_lines.append(format_env_line(key, value))
    text = "\n".join(new_lines) + ("\n" if new_lines else "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


def mirror_rendered_keys_to_disk(
    secrets: Mapping[str, str],
    *,
    disk_env_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> int:
    """Update disk .env for keys that already exist there. Returns count updated."""
    root = Path(project_root) if project_root is not None else _DEFAULT_ROOT
    path = Path(disk_env_path) if disk_env_path is not None else (root / ".env")
    if not path.is_file() or not secrets:
        return 0
    existing = parse_env_file(path)
    n = 0
    for key, val in secrets.items():
        if key not in existing:
            continue
        if upsert_disk_env_key(
            key, val if val is not None else "",
            disk_env_path=path, project_root=root, only_if_exists=True,
        ):
            n += 1
    return n


if __name__ == "__main__":
    # CLI: print length/presence only — never values
    import json
    import sys

    names = sys.argv[1:] or ["FINVIZ_COOKIE", "FINVIZ_API_TOKEN"]
    out = {}
    for n in names:
        v = resolve_secret(n)
        out[n] = {"present": bool(v), "len": len(v)}
    print(json.dumps(out, indent=2))
