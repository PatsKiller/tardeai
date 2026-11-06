"""One place every SEC EDGAR caller gets its User-Agent and request spacing (DSN-20261101 §2.6, P0-T2).

SEC fair access requires a declared contact in the User-Agent; a request without one gets HTTP 403
(measured 2026-11-01). This repository is public, so the contact is never in code or committed config:

1. ``config/sec_edgar_client.json`` (committed) carries ``app``, ``max_rps``, ``spacing_s`` and the
   placeholder ``contact``.
2. The local override (``local_override_path`` in that file, or the ``SEC_EDGAR_CLIENT_LOCAL`` environment
   variable) may set ``contact``. It lives outside the repository and is never committed.

Fail closed: when the resolved contact is empty, still the placeholder, or not an e-mail address,
:func:`user_agent` raises :class:`SecContactError` and no request is sent. There is no fallback address.
Nothing here prints, logs or returns the contact except inside the header handed to ``urllib``; error
messages name the problem and the file, never the value.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "sec_edgar_client.json"
LOCAL_ENV = "SEC_EDGAR_CLIENT_LOCAL"
PLACEHOLDER_PREFIX = "REQUIRED"
_ADDRESS = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,}$")


class SecContactError(RuntimeError):
    """The SEC contact is missing, still the placeholder, or not an address. No request was sent."""


@dataclass(frozen=True)
class SecClientConfig:
    app: str
    contact: str
    max_rps: float
    spacing_s: float
    timeout_s: float
    contact_source: str  # "local_override" | "config" — never the value

    @property
    def min_interval_s(self) -> float:
        rps = self.max_rps if self.max_rps and self.max_rps > 0 else 1.0
        return max(float(self.spacing_s or 0.0), 1.0 / min(float(rps), 10.0))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise SecContactError(f"SEC client config unreadable: {path} ({type(exc).__name__})") from None
    return doc if isinstance(doc, dict) else {}


def local_override_path(base: dict[str, Any], env: Optional[dict[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    raw = env.get(LOCAL_ENV) or str(base.get("local_override_path") or "~/.config/tradeai/sec_edgar_client.local.json")
    return Path(os.path.expanduser(raw))


def load_config(config_path: Optional[Path] = None, local_path: Optional[Path] = None,
                env: Optional[dict[str, str]] = None) -> SecClientConfig:
    """Committed config, then the local override (only the keys in ``local_override_keys``)."""
    base = _read_json(Path(config_path) if config_path else CONFIG_PATH)
    if not base:
        raise SecContactError(f"SEC client config missing: {config_path or CONFIG_PATH}")
    allowed = set(base.get("local_override_keys") or ["contact"])
    lp = Path(local_path) if local_path else local_override_path(base, env)
    local = _read_json(lp)
    merged = dict(base)
    source = "config"
    for k, v in local.items():
        if k in allowed:
            merged[k] = v
            if k == "contact":
                source = "local_override"
    return SecClientConfig(
        app=str(merged.get("app") or "TradeAI").strip(),
        contact=str(merged.get("contact") or "").strip(),
        max_rps=float(merged.get("max_rps") or 8),
        spacing_s=float(merged.get("spacing_s") or 0.15),
        timeout_s=float(merged.get("timeout_s") or 20),
        contact_source=source,
    )


def contact_problem(contact: str) -> Optional[str]:
    """Why a contact is unusable (``empty`` / ``placeholder`` / ``not_an_address``), or None when usable."""
    c = (contact or "").strip()
    if not c:
        return "empty"
    if c.upper().startswith(PLACEHOLDER_PREFIX):
        return "placeholder"
    if not _ADDRESS.match(c):
        return "not_an_address"
    return None


def user_agent(cfg: Optional[SecClientConfig] = None) -> str:
    """``"<app> <contact>"`` — or raise :class:`SecContactError`. The message never contains the value."""
    cfg = cfg or load_config()
    problem = contact_problem(cfg.contact)
    if problem:
        raise SecContactError(
            f"SEC contact {problem}: set 'contact' in the local override "
            f"({LOCAL_ENV} or local_override_path in config/sec_edgar_client.json); refusing to send any SEC request"
        )
    return f"{cfg.app} {cfg.contact}"


def headers(accept: str = "application/json", cfg: Optional[SecClientConfig] = None) -> dict[str, str]:
    return {"User-Agent": user_agent(cfg), "Accept": accept}


_LOCK = threading.Lock()
_LAST = [0.0]


def throttle(cfg: Optional[SecClientConfig] = None, *, sleep=time.sleep, clock=time.monotonic) -> None:
    """Process-wide spacing between SEC requests (``max(spacing_s, 1/max_rps)``; SEC's ceiling is 10/s)."""
    interval = (cfg or load_config()).min_interval_s
    with _LOCK:
        wait = _LAST[0] + interval - clock()
        if wait > 0:
            sleep(wait)
        _LAST[0] = clock()


def fetch_bytes(url: str, accept: str = "application/json", timeout: Optional[float] = None,
                cfg: Optional[SecClientConfig] = None) -> bytes:
    """One rate-limited GET with the declared User-Agent. Raises SecContactError before any network I/O."""
    cfg = cfg or load_config()
    hdrs = headers(accept, cfg)  # fail closed first
    throttle(cfg)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout or cfg.timeout_s) as resp:  # noqa: S310 — sec.gov only
        return resp.read()


def fetch_json(url: str, timeout: Optional[float] = None, cfg: Optional[SecClientConfig] = None) -> Any:
    return json.loads(fetch_bytes(url, "application/json", timeout, cfg))


# One module object whichever way it is imported (``lib.`` with scripts/ on sys.path, or ``scripts.lib.`` from the
# repository root), so every caller shares one SecContactError class and one request-spacing clock.
for _alias in ("lib.sec_edgar_client", "scripts.lib.sec_edgar_client"):
    sys.modules.setdefault(_alias, sys.modules[__name__])
