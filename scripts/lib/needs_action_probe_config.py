"""Config for the needs-action probes that were missing the 5s budget (LQ-20261107-1510).

Numbers live in config/needs_action_probes.json. A missing or unreadable file keeps the
same defaults the code used before this task. This module does not probe anything.
"""
from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "config" / "needs_action_probes.json"
_DEFAULTS = {"n8n_today_ttl_s": 60.0, "n8n_today_stale_s": 180.0}


def load() -> dict:
    try:
        doc = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(_DEFAULTS)
    if not isinstance(doc, dict):
        return dict(_DEFAULTS)
    out = dict(_DEFAULTS)
    for key, default in _DEFAULTS.items():
        raw = doc.get(key, default)
        try:
            out[key] = float(raw)
        except (TypeError, ValueError):
            out[key] = default
    return out


def n8n_today_ttl_s() -> float:
    return load()["n8n_today_ttl_s"]


def n8n_today_stale_s() -> float:
    return load()["n8n_today_stale_s"]
