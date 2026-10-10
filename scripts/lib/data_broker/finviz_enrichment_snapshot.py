"""Finviz Enrichment Snapshot — Data Broker read model over the Finviz enrichment cache.

Consolidation step 1 (2026-10-10, ``CONSOLIDATION_PLAN.md`` in the verification workspace).
The store is ``data/state/ticker_enrichment_cache.json``; its single writer is
``scripts/finviz_enrichment.py`` (``save_cache``: locked, merged, atomic). Every record carries
``cached_at``, the time the writer fetched it from Finviz Elite (six export views merged).

This projection is the read path consumers use instead of fetching from Finviz themselves:
they ask for a batch of symbols with a ``max_age_hours`` and get, per symbol, the record plus
``as_of`` / ``age_hours`` / ``stale``, and for the batch a ``BrokerReadEnvelope@v1``. A stale or
missing symbol is reported as such (``stale_or_missing``); this module never fetches. Whether to
ask the owner to refresh is the caller's decision, through the owner (``finviz_enrichment``).

Registry status: the domain is NOT yet a row in ``config/data_source_authority.json``. Adding it is
an operator decision (AGENTS.md §17, §7A "Adding or changing a source"); the proposed row is in the
consolidation-step1 packet. Until then the freshness window is passed explicitly and the envelope's
``source.registry_status`` says ``PROPOSED_UNREGISTERED``.

Zero provider calls. Read-only: it never creates a directory or writes a file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from lib.data_broker.envelope import envelope

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

DOMAIN = "finviz_enrichment"
CACHE_REL = "data/state/ticker_enrichment_cache.json"
WRITER = "scripts/finviz_enrichment.py"
PROJECTION = "finviz_enrichment_snapshot"
#: same window as the writer's CACHE_TTL_HOURS: a record older than this is refetched by the owner
DEFAULT_MAX_AGE_HOURS = 6.0


def read_cache(root: Path | str | None = None) -> dict[str, Any]:
    """The cache as a dict, read-only. Missing or unreadable file -> {} (reported as no_coverage)."""
    path = Path(root or PROJECT_ROOT) / CACHE_REL
    try:
        data = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_as_of(record: Any) -> datetime | None:
    """``cached_at`` as an aware UTC datetime.

    The writer stamps ``datetime.now().isoformat()``: naive host-local time. A naive value is
    therefore read as host-local (not UTC, which would age every record by the UTC offset).
    """
    if not isinstance(record, dict):
        return None
    raw = record.get("cached_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # host-local -> aware
    return dt.astimezone(timezone.utc)


def _norm(symbols: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in symbols or []:
        sym = str(s or "").upper().strip()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def get_enrichment_batch(
    symbols: Iterable[Any],
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    root: Path | str | None = None,
    now: datetime | None = None,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-symbol enrichment records with freshness, plus a batch envelope.

    Returns::

        {"ok": True, "provider_calls": 0,
         "symbols": {SYM: {"record": dict | None, "as_of": iso | None,
                           "age_hours": float | None, "stale": bool}},
         "fresh": [SYM, ...], "stale_or_missing": [SYM, ...],
         <BrokerReadEnvelope@v1 over the newest as_of among the requested symbols>}

    ``cache`` is injectable (tests, or a caller that already holds a snapshot).
    """
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    snap = cache if cache is not None else read_cache(root)
    per: dict[str, dict[str, Any]] = {}
    fresh: list[str] = []
    stale_or_missing: list[str] = []
    newest: datetime | None = None
    for sym in _norm(symbols):
        rec = snap.get(sym)
        dt = record_as_of(rec)
        age = round(max(0.0, (ref - dt).total_seconds() / 3600.0), 3) if dt else None
        is_stale = dt is None or age is None or age > float(max_age_hours)
        per[sym] = {
            "record": rec if isinstance(rec, dict) else None,
            "as_of": dt.isoformat() if dt else None,
            "age_hours": age,
            "stale": is_stale,
        }
        (stale_or_missing if is_stale else fresh).append(sym)
        if dt and (newest is None or dt > newest):
            newest = dt
    env = envelope(
        DOMAIN,
        newest,
        now=ref,
        stale_after_hours=float(max_age_hours),
        source={
            "file": CACHE_REL,
            "writer": WRITER,
            "projection": PROJECTION,
            "provider": "finviz",
            "registry_status": "PROPOSED_UNREGISTERED",
        },
    )
    out: dict[str, Any] = {
        "ok": True,
        "provider_calls": 0,
        "symbols": per,
        "fresh": fresh,
        "stale_or_missing": stale_or_missing,
    }
    out.update(env)
    return out


def get_enrichment(symbol: Any, **kwargs: Any) -> dict[str, Any]:
    """Single-symbol convenience over :func:`get_enrichment_batch`."""
    batch = get_enrichment_batch([symbol], **kwargs)
    sym = str(symbol or "").upper().strip()
    row = batch["symbols"].get(sym) or {"record": None, "as_of": None, "age_hours": None, "stale": True}
    out = {k: v for k, v in batch.items() if k not in ("symbols", "fresh", "stale_or_missing")}
    out.update({"symbol": sym, **row})
    return out
