"""agent_registry.py — the ONE agent registry (Wave 4 O-W4-2; config/agent_registry.json, AgentRegistry@v1).

* ``canonical(any_id)`` → the canonical agent_id (aliases absorbed; unknown → None).
* ``subscribers(event_type)`` → canonical ids whose ``bus_events`` match (fnmatch patterns allowed).
* ``wake_eligible()`` → ids the persistent wake may run for.
* ``model_caller(agent_id)`` → the model-policy caller key.

Fail-soft: a missing / broken file yields an empty registry and every caller keeps its legacy list
(``cio_event_bus.route_to_agents`` falls back to AGENT_EVENT_ROUTING, the wake to KNOWN_AGENTS).
"""
from __future__ import annotations

import fnmatch
import json
import os
from functools import lru_cache
from pathlib import Path

SCHEMA = "AgentRegistry@v1"


def _path(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_AGENT_REGISTRY") or Path(__file__).resolve().parents[2] / "config" / "agent_registry.json")


@lru_cache(maxsize=4)
def _load_cached(path: str, mtime: float) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if d.get("schema") == SCHEMA else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load(env: dict | None = None) -> dict:
    p = _path(env)
    try:
        mt = p.stat().st_mtime
    except OSError:
        return {}
    return _load_cached(str(p), mt)


def agents(env: dict | None = None) -> list[dict]:
    return list(load(env).get("agents") or [])


def alias_map(env: dict | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in agents(env):
        aid = str(a.get("agent_id") or "")
        if not aid:
            continue
        out[aid.lower()] = aid
        for al in a.get("aliases") or []:
            out[str(al).lower()] = aid
    return out


def canonical(any_id: str | None, env: dict | None = None) -> str | None:
    if not any_id:
        return None
    return alias_map(env).get(str(any_id).strip().lower())


def get(any_id: str | None, env: dict | None = None) -> dict | None:
    cid = canonical(any_id, env)
    if not cid:
        return None
    for a in agents(env):
        if a.get("agent_id") == cid:
            return a
    return None


def subscribers(event_type: str, env: dict | None = None) -> list[str]:
    out = []
    for a in agents(env):
        if a.get("status") not in ("ACTIVE",):
            continue
        if any(fnmatch.fnmatch(event_type, pat) for pat in a.get("bus_events") or []):
            out.append(a["agent_id"])
    return out


def wake_eligible(env: dict | None = None) -> tuple[str, ...]:
    return tuple(a["agent_id"] for a in agents(env) if a.get("wake_eligible") and a.get("status") == "ACTIVE")


def model_caller(any_id: str | None, env: dict | None = None) -> str | None:
    a = get(any_id, env)
    return (a or {}).get("model_caller")


def known_ids(env: dict | None = None) -> set[str]:
    return set(alias_map(env).keys())
