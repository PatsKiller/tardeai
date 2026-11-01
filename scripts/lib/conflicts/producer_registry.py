"""R1 producer freshness registry reader (config/conflict_producer_registry.json). Pure; no source reads.

EXCEPTIONS_MATRIX.md R1: a side's age is its OLDEST MATERIAL INPUT, not its run time; it is superseded when older
than min(14 d, 2 x its cadence); refresh is queued only to a producer that writes the compared input.

``annotate`` stamps three things on an engine Input from the registry row of its source:
  cadence_days           the producer's cadence (the security profile supersedes after min(14, 2 x cadence))
  writes_compared_input  whether a running producer rewrites the value being compared (R1 queue_refresh gate)
  inputs_as_of           for producers with several materials (the re-entry desk: quote + plan), the time of the
                         BINDING material: the one furthest past its own limit, with cadence_days set to that
                         material's limit, so "superseded" means "some material is past its own limit"
Explicit producer values win: a row that already carries cadence_days / writes_compared_input keeps them.
Quotes age in session time (AGENTS.md 7A, config/data_source_authority.json quote_price stale_after_hours):
a closed market does not age a quote taken at or after the last official close.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "config/conflict_producer_registry.json"
AUTHORITY_PATH = ROOT / "config/data_source_authority.json"
SCHEMA = "ConflictProducerRegistry@v1"


def _at(value):
    if isinstance(value, datetime):
        return value if value.tzinfo and value.utcoffset() is not None else None
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo and parsed.utcoffset() is not None else None


def validate(doc: dict) -> dict:
    if doc.get("schema") != SCHEMA or not isinstance(doc.get("producers"), dict):
        raise ValueError("unsupported conflict producer registry")
    cap = doc.get("max_supersede_days")
    if not isinstance(cap, (int, float)) or isinstance(cap, bool) or cap <= 0:
        raise ValueError("max_supersede_days must be positive")
    for name, row in doc["producers"].items():
        if not isinstance(row.get("writes_compared_input"), bool):
            raise ValueError(f"{name}: writes_compared_input must be true or false")
        if row.get("writes_compared_input") is False and row.get("role") != "material" and not (
                row.get("writes_compared_input_reason") or "").strip():
            raise ValueError(f"{name}: a producer that does not write its compared input must say why")
        if row["writes_compared_input"] and row.get("role") in {"claim", "gate"} and not row.get("refresh_lane"):
            raise ValueError(f"{name}: a refreshable producer names its refresh lane")
        sources = [row] if "materials" not in row else list(row["materials"].values())
        for material in sources:
            cadence = material.get("cadence_days")
            if material.get("clock") == "session" or material.get("authority_domain") == "quote_price":
                if not material.get("authority_domain"):
                    raise ValueError(f"{name}: a session-clock material names its authority domain")
                continue
            if not isinstance(cadence, (int, float)) or isinstance(cadence, bool) or cadence <= 0:
                raise ValueError(f"{name}: cadence_days must be a positive number")
    return doc


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return validate(json.loads(Path(path).read_text(encoding="utf-8")))


def load_registry(path: Path | None = None) -> dict:
    return _load(str(path or REGISTRY_PATH))


@lru_cache(maxsize=4)
def _authority_stale_hours(domain: str, path: str) -> float:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = doc.get("domains") or []
    rows = rows if isinstance(rows, list) else list(rows.values())
    for row in rows:
        if (row.get("domain") or row.get("name") or row.get("id")) == domain:
            hours = row.get("stale_after_hours")
            if isinstance(hours, (int, float)) and not isinstance(hours, bool) and hours > 0:
                return float(hours)
    raise ValueError(f"authority domain {domain} has no positive stale_after_hours")


def _closed_gap(now: datetime) -> timedelta:
    """Time since the last official close when the market is closed now (0 while a session is open)."""
    from scripts.lib.cio_market_session import NYSESessionService
    service = NYSESessionService()
    local = now.astimezone(service.tz)
    day = local.date()
    for _ in range(15):
        if service.is_trading_day(day):
            opened, closed, _early = service.official_bounds(day)
            if opened and closed and opened <= local < closed:
                return timedelta(0)
            if closed and closed <= local:
                return local - closed
        day -= timedelta(days=1)
    return timedelta(0)


def material_limit(material: dict, *, now: datetime, authority_path: Path | None = None) -> timedelta:
    """The allowed age of one material right now (2 x cadence, or the 7A stale_after in session time)."""
    if material.get("clock") == "session" or material.get("authority_domain") == "quote_price":
        hours = _authority_stale_hours(material["authority_domain"], str(authority_path or AUTHORITY_PATH))
        return timedelta(hours=hours) + _closed_gap(now)
    return timedelta(days=2 * float(material["cadence_days"]))


def binding_material(row: dict, times: dict, *, now: datetime, cap_days: float, authority_path=None):
    """(name, time, limit) of the material furthest past its own limit; time None when a material time is missing."""
    worst = None
    for name, material in (row.get("materials") or {}).items():
        at = _at(times.get(name))
        limit = min(material_limit(material, now=now, authority_path=authority_path), timedelta(days=cap_days))
        if at is None:
            return name, None, limit
        ratio = (now - at) / limit if limit > timedelta(0) else float("inf")
        if worst is None or ratio > worst[0]:
            worst = (ratio, name, at, limit)
    return (worst[1], worst[2], worst[3]) if worst else (None, None, None)


def annotate(item, *, now: datetime, registry: dict | None = None, authority_path: Path | None = None):
    """Return a copy of ``item`` (engine Input) carrying the registry's R1 metadata; unknown sources pass through."""
    registry = registry or load_registry()
    row = registry["producers"].get(item.source)
    if not row:
        return item
    meta = dict(item.metadata)
    meta.setdefault("producer", item.source)
    meta.setdefault("writes_compared_input", row["writes_compared_input"])
    if row.get("refresh_lane"):
        meta.setdefault("refresh_lane", row["refresh_lane"])
    changes = {}
    materials = meta.get("materials")
    if row.get("materials") and isinstance(materials, dict) and item.inputs_as_of is None:
        if any(value not in (None, "") and _at(value) is None for value in materials.values()):
            meta["time_error"] = True
        name, at, limit = binding_material(row, materials, now=now, cap_days=registry["max_supersede_days"],
                                           authority_path=authority_path)
        meta["binding_material"] = name
        meta["material_time_required"] = True
        if limit is not None and "cadence_days" not in item.metadata:
            meta["cadence_days"] = limit / timedelta(days=2)
        changes["inputs_as_of"] = at
    elif "cadence_days" not in meta and row.get("cadence_days"):
        meta["cadence_days"] = row["cadence_days"]
    return replace(item, metadata=meta, **changes)


def annotate_all(items, *, now: datetime, registry: dict | None = None):
    registry = registry or load_registry()
    return [annotate(item, now=now, registry=registry) for item in items]
