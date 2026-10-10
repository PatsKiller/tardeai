"""Single-position concentration limits from the ratified IPS config.

Every single-position concentration threshold (advisory-desk overweight flag,
CIO decision-engine human-review gates, look-through single-name guideline,
specialist-shadow severity) follows ``config/investment_policy_statement.json``
``constraints``:

* ``max_single_position_pct`` -- the IPS limit (operator policy, 12.0).
* ``critical_single_position_pct`` -- the second, "severe" tier used only where a
  caller already had a higher tier (derived key, added with operator approval
  2026-10-09 ~18:05 ET: "Okay to everything except extending the scout to
  closing").

Advisory / decision-support only. No order, stop or broker path reads this.

When the config is missing or a value is not a positive number, the stricter
pre-IPS value is used and a warning is logged once per (path, key).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
IPS_FILENAME = "investment_policy_statement.json"

# FALLBACKS only (config missing/invalid). Both are the stricter values the
# call sites used before they followed the IPS: 8% was the hardcoded
# human-review / guideline / validator line; 15% the severe tier.
FALLBACK_MAX_POSITION_PCT = 8.0
FALLBACK_CRITICAL_POSITION_PCT = 15.0

_warned: set[tuple[str, str]] = set()


def _constraints(config_dir: Path | None) -> tuple[dict[str, Any], Path]:
    path = (config_dir or CONFIG_DIR) / IPS_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, path
    c = raw.get("constraints") if isinstance(raw, dict) else None
    return (c if isinstance(c, dict) else {}), path


def _positive(c: dict[str, Any], key: str) -> float | None:
    try:
        v = float(c.get(key))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _fallback(path: Path, key: str, value: float) -> float:
    marker = (str(path), key)
    if marker not in _warned:
        _warned.add(marker)
        log.warning("IPS %s missing/invalid in %s; using stricter fallback %.1f%%", key, path, value)
    return value


def ips_max_position_pct(config_dir: Path | None = None) -> float:
    """The ratified IPS single-position max (``constraints.max_single_position_pct``)."""
    c, path = _constraints(config_dir)
    v = _positive(c, "max_single_position_pct")
    return v if v is not None else _fallback(path, "max_single_position_pct", FALLBACK_MAX_POSITION_PCT)


def ips_critical_position_pct(config_dir: Path | None = None) -> float:
    """The severe single-position tier (``constraints.critical_single_position_pct``).

    Never below the IPS max: a misconfigured critical tier cannot make the
    severe band fire before the limit itself.
    """
    c, path = _constraints(config_dir)
    v = _positive(c, "critical_single_position_pct")
    if v is None:
        v = _fallback(path, "critical_single_position_pct", FALLBACK_CRITICAL_POSITION_PCT)
    return max(v, ips_max_position_pct(config_dir))
