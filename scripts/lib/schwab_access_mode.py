"""schwab_access_mode — the operator's Schwab pause switch (config/schwab_access_mode.yaml).

Operator deactivated the Schwab developer app ~15:00 ET 2026-10-14 (SPCX incident). Readers that used to call
Schwab, fail, retry and log (or worse, report "healthy" on an empty answer) consult this module first:

    from lib import schwab_access_mode as sam
    if not sam.reads_allowed():
        sam.log_skip("schwab_position_sync")          # one INFO line, then return an explicit paused status
        return {...status: sam.PAUSED_STATUS...}

Modes: ``normal`` (default when the file is absent), ``read_only``, ``forbidden``. An unreadable file or an
unknown value is treated as ``forbidden`` — fail closed: a pause switch that cannot be read must not silently
re-enable a deactivated broker. Overrides (tests, one-off runs): env ``TRADEAI_SCHWAB_ACCESS_MODE`` (a mode) and
``TRADEAI_SCHWAB_ACCESS_MODE_PATH`` (a file). Read-only: this module never calls Schwab and never reads tokens.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "schwab_access_mode.yaml"
MODES = ("forbidden", "read_only", "normal")
DEFAULT_MODE = "normal"
PAUSED_STATUS = "schwab_paused"
UNAVAILABLE = "UNAVAILABLE"
PAUSED_REMEDIATION = "Schwab app deactivated by operator (incident 2026-10-14) — expected; do not re-auth"

_AUTH_FAILURE_RE = re.compile(
    r"\b(401|403)\b|unauthori[sz]ed|forbidden|invalid[_ ]client|invalid[_ ]grant|rejected the login token|"
    r"no schwab login token|token (?:expired|revoked)|reauth", re.I)
_logged: set[str] = set()


def _path() -> Path:
    override = os.environ.get("TRADEAI_SCHWAB_ACCESS_MODE_PATH")
    return Path(override) if override else CONFIG_PATH


def _parse(text: str) -> dict:
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except ImportError:  # minimal "key: value" fallback when PyYAML is not installed
        out: dict[str, Any] = {}
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip().strip("'\"")
        return out
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {"mode": data}


def status() -> dict:
    """The full switch state: {mode, reads_allowed, paused, since, reason, source, error}."""
    env = (os.environ.get("TRADEAI_SCHWAB_ACCESS_MODE") or "").strip().lower()
    path = _path()
    info: dict[str, Any] = {"mode": DEFAULT_MODE, "since": None, "reason": None, "source": "default", "error": None}
    if env:
        info.update(mode=env, source="env:TRADEAI_SCHWAB_ACCESS_MODE")
    elif path.is_file():
        info["source"] = str(path)
        try:
            data = _parse(path.read_text(encoding="utf-8"))
            info.update(mode=str(data.get("mode") or DEFAULT_MODE).strip().lower(),
                        since=data.get("since"), reason=data.get("reason"))
        except Exception as exc:  # noqa: BLE001 — fail closed below
            info.update(mode="forbidden", error=f"unreadable: {type(exc).__name__}: {exc}")
    if info["mode"] not in MODES:
        info["error"] = info["error"] or f"unknown mode {info['mode']!r}"
        info["mode"] = "forbidden"
    if info["since"] is not None:
        info["since"] = str(info["since"])
    info["reads_allowed"] = info["mode"] != "forbidden"
    info["paused"] = info["mode"] == "forbidden"
    return info


def setting(path: str, default: Any = None) -> Any:
    """A dotted value from the switch file (e.g. "alerts.stop_data_unavailable_realert_hours"), else default."""
    try:
        p = _path()
        data: Any = _parse(p.read_text(encoding="utf-8")) if p.is_file() else {}
        for part in path.split("."):
            data = data.get(part) if isinstance(data, dict) else None
        return default if data is None else data
    except Exception:  # noqa: BLE001
        return default


def mode() -> str:
    return status()["mode"]


def reads_allowed() -> bool:
    return status()["reads_allowed"]


def is_paused() -> bool:
    return status()["paused"]


def skip_message(component: str) -> str:
    st = status()
    return (f"[{component}] Schwab access mode={st['mode']} — skipping Schwab call "
            f"({st.get('reason') or 'operator pause'}; config/schwab_access_mode.yaml)")


def log_skip(component: str, logger: Optional[logging.Logger] = None, *, once: bool = True,
             printer=None) -> str:
    """Emit ONE INFO line per component per process (no retry storm, no error spam). Returns the message."""
    msg = skip_message(component)
    if once and component in _logged:
        return msg
    _logged.add(component)
    if printer is not None:
        printer(msg)
    else:
        (logger or logging.getLogger("schwab_access_mode")).info(msg)
    return msg


def is_auth_failure(err: Any) -> bool:
    """True when an error (exception, dict or text) is an auth / forbidden failure rather than a data problem."""
    if err is None or err == "" or err == {}:
        return False
    if isinstance(err, dict):
        code = err.get("status_code") or err.get("http_status") or err.get("status")
        if str(code) in ("401", "403"):
            return True
        err = " ".join(str(v) for v in err.values())
    code = getattr(err, "status_code", None) or getattr(getattr(err, "response", None), "status_code", None)
    if str(code) in ("401", "403"):
        return True
    return bool(_AUTH_FAILURE_RE.search(str(err)))
