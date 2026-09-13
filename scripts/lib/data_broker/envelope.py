"""Shared response envelope for every Data Broker projection read.

One Source of Truth, Phase 4 (2026-09-13). AGENTS.md §7A rule 3: "Every projection
response carries as_of, age, source, stale." This module is that contract, in one
place, so a hub handler cannot serve a 454-hour-old Sectors snapshot as current
(measured 2026-09-13: sector_momentum_latest.json served 436–454h old while a
fresh copy existed) and a dead desk cannot render 131-day-old debate rows as
today's activity.

Pure: no DB, no filesystem beyond reading config/data_source_authority.json (and
that path is injectable). Every projection calls :func:`envelope`.

Fields
------
    as_of              ISO-8601 UTC of the newest row/file the projection read, or None
    age_hours          hours between as_of and now (None when as_of is None)
    source             {domain, table, file, writer, projection, provider} from the registry
    stale              age_hours > stale_after_hours (True when as_of is None)
    stale_after_hours  the registry window the verdict was measured against
    gap                absent when the feed is alive; otherwise
                       {"kind": "no_producer" | "no_coverage", "last_as_of": as_of}

Gap semantics
-------------
    no_coverage   the store answered nothing for this question (no rows / no file).
    no_producer   the registry says the domain is a dead_feed, the caller says the
                  producer is gone, OR nothing has been written for longer than
                  ``dead_after_hours`` (default DEAD_AFTER_HOURS_DEFAULT = 720h, 30d).
                  The 30-day default is deliberate: the four dead desks measured
                  2026-09-13 were 42d/52d/131d/59d silent; the live feeds are <3d.
                  A feed that comes back to life clears the gap on its own.

AUTHORITY: READ_ONLY_ADVISORY. Adds metadata; never changes a projection's data.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "BrokerReadEnvelope@v1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
AUTHORITY_PATH = PROJECT_ROOT / "config" / "data_source_authority.json"

#: A feed silent this long has no producer, whatever the registry's stale window says.
DEAD_AFTER_HOURS_DEFAULT = 24.0 * 30

_registry_cache: dict[str, Any] = {"path": None, "mtime": None, "domains": {}}


# ── registry ─────────────────────────────────────────────────────────────────


def load_stale_windows(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """{domain: spec} from config/data_source_authority.json (mtime-cached).

    Each spec carries: stale_after_hours, stale_after_hours_closed, class, writer,
    projection, table, file, primary_provider, no_coverage, dead_after_hours.
    Missing/unreadable file → {} (the caller then passes explicit windows; the
    envelope still renders, it just cannot cite the registry).
    """
    p = path or AUTHORITY_PATH
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    if _registry_cache["path"] == str(p) and _registry_cache["mtime"] == mtime:
        return _registry_cache["domains"]
    try:
        auth = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for d in auth.get("domains") or []:
        store = d.get("store") or {}
        out[d["domain"]] = {
            "domain": d["domain"],
            "class": d.get("class"),
            "table": store.get("table"),
            "file": store.get("file"),
            "writer": d.get("writer"),
            "writer_status": d.get("writer_status"),
            "projection": d.get("projection"),
            "primary_provider": d.get("primary_provider"),
            "stale_after_hours": d.get("stale_after_hours"),
            "stale_after_hours_closed": d.get("stale_after_hours_closed"),
            "no_coverage": d.get("no_coverage"),
            "dead_after_hours": d.get("dead_after_hours"),
        }
    _registry_cache.update(path=str(p), mtime=mtime, domains=out)
    return out


def registry_spec(domain: str, *, registry: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The registry row for a domain, or an empty spec naming the domain."""
    reg = registry if registry is not None else load_stale_windows()
    return dict(reg.get(domain) or {"domain": domain})


# ── time helpers ─────────────────────────────────────────────────────────────


def to_utc_iso(value: Any) -> str | None:
    """Normalise datetime / date / ISO string / epoch to ISO-8601 UTC; None on failure."""
    if value is None or value == "":
        return None
    dt = _coerce_dt(value)
    return dt.isoformat() if dt else None


def _coerce_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    dt = datetime.strptime(s[:10], "%Y-%m-%d")
                except ValueError:
                    return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_hours(as_of: Any, now: datetime | None = None) -> float | None:
    dt = _coerce_dt(as_of)
    if dt is None:
        return None
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return round(max(0.0, (ref - dt).total_seconds() / 3600.0), 2)


def newest(values: list[Any]) -> str | None:
    """Newest timestamp among a list (rows' as_of columns) as ISO UTC."""
    best: datetime | None = None
    for v in values:
        dt = _coerce_dt(v)
        if dt and (best is None or dt > best):
            best = dt
    return best.isoformat() if best else None


# ── the envelope ─────────────────────────────────────────────────────────────


def envelope(
    domain: str,
    as_of: Any,
    *,
    now: datetime | None = None,
    registry: dict[str, dict[str, Any]] | None = None,
    stale_after_hours: float | None = None,
    dead_after_hours: float | None = None,
    producer_status: str | None = None,
    market_closed: bool | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the read envelope for one projection response.

    Args:
        domain: registry domain (config/data_source_authority.json ``domains[].domain``).
        as_of: newest row/file timestamp the projection read (None → no_coverage).
        now: injectable clock for tests.
        registry: injectable registry (tests); default loads the config file.
        stale_after_hours: overrides the registry window (for domains not yet registered).
        dead_after_hours: overrides DEAD_AFTER_HOURS_DEFAULT / registry ``dead_after_hours``.
        producer_status: "none" declares the producer gone regardless of age.
        market_closed: when True and the registry has ``stale_after_hours_closed``, use it.
        source: extra source fields merged over the registry's (e.g. a file path).
    """
    spec = registry_spec(domain, registry=registry)
    window = stale_after_hours
    if window is None:
        if market_closed and spec.get("stale_after_hours_closed") is not None:
            window = spec.get("stale_after_hours_closed")
        else:
            window = spec.get("stale_after_hours")
    dead_h = dead_after_hours if dead_after_hours is not None else (spec.get("dead_after_hours") or DEAD_AFTER_HOURS_DEFAULT)

    as_of_iso = to_utc_iso(as_of)
    age = age_hours(as_of_iso, now) if as_of_iso else None

    if as_of_iso is None:
        stale = True
    elif window is None:
        stale = False  # registry says this domain has no freshness contract (manual / on-demand)
    else:
        stale = bool(age is not None and age > float(window))

    src = {
        "domain": domain,
        "table": spec.get("table"),
        "file": spec.get("file"),
        "writer": spec.get("writer") or ("UNCONSOLIDATED" if spec.get("writer_status") == "UNCONSOLIDATED" else None),
        "projection": spec.get("projection"),
        "provider": spec.get("primary_provider"),
        "registry": "config/data_source_authority.json" if spec.get("class") else None,
    }
    if source:
        src.update(source)

    out: dict[str, Any] = {
        "schema": SCHEMA,
        "as_of": as_of_iso,
        "age_hours": age,
        "source": src,
        "stale": stale,
        "stale_after_hours": window,
    }

    gap: dict[str, Any] | None = None
    if producer_status == "none" or spec.get("class") == "dead_feed":
        gap = {"kind": "no_producer", "last_as_of": as_of_iso}
    elif as_of_iso is None:
        gap = {"kind": "no_coverage", "last_as_of": None}
    elif age is not None and dead_h and age > float(dead_h):
        gap = {"kind": "no_producer", "last_as_of": as_of_iso, "dead_after_hours": float(dead_h)}
    if gap is not None:
        if spec.get("no_coverage"):
            gap["declared_behaviour"] = spec["no_coverage"]
        out["gap"] = gap
    return out


def wrap(payload: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    """Merge an envelope into a projection/handler payload without clobbering data keys.

    Envelope keys win only for the envelope's own field names; a payload that already
    carries ``as_of`` keeps it under ``payload_as_of`` so nothing is silently lost.
    """
    out = dict(payload)
    for k, v in env.items():
        if k in out and k not in ("schema",) and out[k] != v:
            out[f"payload_{k}"] = out[k]
        out[k] = v
    return out
