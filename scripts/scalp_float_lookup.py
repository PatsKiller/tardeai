#!/usr/bin/env python3
"""Float (and reference price) lookup for scalp-universe symbols the scanner left without one.

Operator 2026-10-05: an unknown float must FAIL CLOSED, but look it up before excluding. Bare
social rows (HPE, DELL, CHPT) carried no float in scalp_scan_results; a real small cap the scanner
never enriched would be lost too.

Operator 2026-10-16 (option A): "stop calling Alpha Vantage OVERVIEW for float; use the float data
we already have from Finviz via the data broker". Before, this module fetched Finviz Elite v=131
itself (one export request per 20 tickers) and then called Alpha Vantage OVERVIEW through the
owner's ``scalp_float`` job — 10 counted calls 2026-10-12..16, every one "This is a premium
endpoint", 0 floats. Now the ONLY source is Finviz "Shs Float" (``float_m``, millions) as already
stored in ``data/state/ticker_enrichment_cache.json`` by its single writer
(``scripts/finviz_enrichment.py``), read through the data broker projection
``lib.data_broker.finviz_enrichment_snapshot``. Zero provider calls (AGENTS.md: alerts and lanes get
data only through the Command Center data broker).

A symbol whose Finviz float is missing, zero (the writer's "absent"), or older than
``float_lookup.finviz_max_age_hours`` is reported ``float: unavailable (<reason>)`` and left out of
the result, so the universe fails it closed (``float_unknown``). Never a default number.

READ-ONLY: no provider, no network, no file written.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

#: The projection every float now comes through (named in each result row).
VIA = "data_broker.finviz_enrichment_snapshot"
#: Default staleness window when config does not set one: Finviz float moves on offerings and
#: splits, not intraday; 168 h keeps a weekly-refreshed record usable and refuses older ones.
DEFAULT_MAX_AGE_HOURS = 168.0


def _positive(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None   # finviz_enrichment stores an absent float as 0.0 — that is unknown


def broker_batch(symbols: list[str], *, max_age_hours: float, now: Optional[datetime] = None) -> dict:
    """The broker read (``get_enrichment_batch``). Injectable in tests; reads one local file."""
    from lib.data_broker.finviz_enrichment_snapshot import get_enrichment_batch
    return get_enrichment_batch(symbols, max_age_hours=max_age_hours, now=now)


def lookup_floats_detail(symbols: list[str], u: dict, *,
                         broker: Callable[..., dict] = broker_batch,
                         now: Optional[float] = None) -> dict[str, Any]:
    """{"found": {SYM: {"float_mm", "price", "source", "via", "as_of", "age_hours"}},
        "unavailable": {SYM: reason}, "provider_calls": 0, "envelope": {...}}"""
    fl = u["float_lookup"]
    syms = list(dict.fromkeys(str(x).upper().strip() for x in (symbols or []) if str(x or "").strip()))
    out: dict[str, Any] = {"found": {}, "unavailable": {}, "provider_calls": 0, "envelope": {}}
    if not fl.get("enabled") or not syms:
        return out
    max_age = float(fl.get("finviz_max_age_hours") or DEFAULT_MAX_AGE_HOURS)
    ref = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    try:
        batch = broker(syms, max_age_hours=max_age, now=ref) or {}
    except Exception as e:  # noqa: BLE001 — an unreadable broker leaves every float unavailable
        reason = f"finviz broker read failed: {type(e).__name__}"
        out["unavailable"] = {s: reason for s in syms}
        return out
    out["provider_calls"] = int(batch.get("provider_calls") or 0)
    out["envelope"] = {k: batch.get(k) for k in ("schema", "as_of", "age_hours", "stale", "source")
                       if k in batch}
    per = batch.get("symbols") or {}
    for s in syms:
        row = per.get(s) or {}
        rec = row.get("record")
        if not isinstance(rec, dict):
            out["unavailable"][s] = "not in Finviz enrichment cache"
            continue
        if not row.get("as_of"):
            out["unavailable"][s] = "Finviz record has no cached_at"
            continue
        if row.get("stale"):
            out["unavailable"][s] = f"Finviz record {float(row.get('age_hours') or 0):.0f}h old > {max_age:.0f}h"
            continue
        flt = _positive(rec.get("float_m"))
        if flt is None:
            out["unavailable"][s] = "Finviz Shs Float absent"
            continue
        out["found"][s] = {"float_mm": flt, "price": _positive(rec.get("price")), "source": "finviz",
                           "via": VIA, "as_of": row.get("as_of"), "age_hours": row.get("age_hours")}
    return out


def lookup_floats(symbols: list[str], u: dict, **kw) -> dict:
    """{SYM: {"float_mm", "price", "source", ...}} for symbols with a fresh Finviz float.

    Same shape the universe consumer (``scalp_shadow_logger.resolve_universe_detail``) always read;
    a symbol left out stays unknown and is excluded. Each unavailable symbol is printed with its
    reason."""
    d = lookup_floats_detail(symbols, u, **kw)
    for s, why in sorted(d["unavailable"].items()):
        print(f"  [float-lookup] {s} float: unavailable ({why})")
    if d["found"] or d["unavailable"]:
        print(f"  [float-lookup] finviz via broker: {len(d['found'])} found, "
              f"{len(d['unavailable'])} unavailable, provider_calls={d['provider_calls']}")
    return d["found"]


if __name__ == "__main__":  # read-only dry run: python scripts/scalp_float_lookup.py SYM [SYM ...]
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import yaml

    cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "scalp_signal_engine.yaml").read_text())
    print(json.dumps(lookup_floats_detail(sys.argv[1:], cfg["universe"]), indent=1, default=str))
