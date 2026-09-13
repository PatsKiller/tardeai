"""Desk Feeds — read envelopes for the Reports and Redeploy desks' dead stores.

Measured 2026-09-13:
    ai_reports                                   46 rows, newest generated_at 2026-08-02 (42d)
    portfolios/state/redeploy_analytics_cache.json newest _cached_at 52d old (30-min TTL cache
                                                 that nothing has refreshed — every entry expired)

Both desks rendered these as current. Each reader here returns the shared envelope
(lib.data_broker.envelope) so the handler carries ``gap.kind == "no_producer"`` and
the last as_of. Proposed registry domains ``ai_reports`` and ``redeploy_analytics``
are in docs/implementation/sot/phase4_registry_patch.json; until they land the
windows are declared here and passed explicitly (same numbers as the patch).

Zero provider calls. Read-only. Nothing is deleted; the rows stay readable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.data_broker.envelope import envelope

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
REDEPLOY_CACHE_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "redeploy_analytics_cache.json"

DOMAIN_REPORTS = "ai_reports"
DOMAIN_REDEPLOY = "redeploy_analytics"
FALLBACK_WINDOWS = {DOMAIN_REPORTS: 168.0, DOMAIN_REDEPLOY: 24.0}

REPORTS_SQL = """SELECT report_type, count(*) AS n, max(generated_at) AS latest
                 FROM ai_reports GROUP BY report_type ORDER BY latest DESC NULLS LAST"""


def _win(domain: str, registry) -> float | None:
    from lib.data_broker.envelope import registry_spec
    spec = registry_spec(domain, registry=registry)
    return spec.get("stale_after_hours") if spec.get("class") else FALLBACK_WINDOWS.get(domain)


def get_report_feed(db_query, *, now=None, registry=None) -> dict[str, Any]:
    """{ok, by_type: [{report_type, n, latest}], total, <envelope>} over ai_reports."""
    rows: list[dict[str, Any]] = []
    error = None
    try:
        rows = db_query(REPORTS_SQL) or []
    except Exception as e:  # noqa: BLE001
        error = str(e)[:200]
    latest = None
    total = 0
    by_type = []
    for r in rows:
        l = r.get("latest")
        if l is not None and (latest is None or l > latest):
            latest = l
        total += int(r.get("n") or 0)
        by_type.append({"report_type": r.get("report_type"), "n": int(r.get("n") or 0),
                        "latest": l.isoformat() if hasattr(l, "isoformat") else l})
    env = envelope(DOMAIN_REPORTS, latest, now=now, registry=registry,
                   stale_after_hours=_win(DOMAIN_REPORTS, registry),
                   source={"table": "ai_reports", "writer": None})
    out = {"ok": error is None, "by_type": by_type, "total": total, "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out


def get_redeploy_cache_feed(path: Path | None = None, *, now=None, registry=None) -> dict[str, Any]:
    """{ok, entries, newest_key, <envelope>} over the redeploy analytics disk cache."""
    p = path or REDEPLOY_CACHE_PATH
    cache: dict[str, Any] = {}
    error = None
    try:
        cache = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception as e:  # noqa: BLE001
        error = str(e)[:200]
    newest_ts = None
    newest_key = None
    for k, v in (cache.items() if isinstance(cache, dict) else []):
        try:
            ts = float((v or {}).get("_cached_at") or 0)
        except (TypeError, ValueError):
            continue
        if ts and (newest_ts is None or ts > newest_ts):
            newest_ts, newest_key = ts, k
    env = envelope(DOMAIN_REDEPLOY, newest_ts, now=now, registry=registry,
                   stale_after_hours=_win(DOMAIN_REDEPLOY, registry),
                   source={"file": "portfolios/state/redeploy_analytics_cache.json", "writer": "scripts/api_v2.py:_redeploy_analytics_cache"})
    out = {"ok": error is None, "entries": len(cache) if isinstance(cache, dict) else 0,
           "newest_key": newest_key, "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out
