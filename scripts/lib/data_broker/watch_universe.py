"""Watch › Full universe — the CIO curator's ranked list as the Watch page shows it (operator 2026-10-23).
Read-only. Zero provider calls. No new store.

The ranking is the curator's (``cio_opportunity_projection.json``, registry domain ``opportunity_assessment``) — the
same list System Suggests takes its top from. On Watch each row also carries the position facts
(``watch_position_facts``): held / formerly held / never held from the Watch held reader (positions_store reader
batch #1), the last round trip and the re-entry advice from the CIO prospect lifecycle.

Ownership on Watch follows the broker-synced held reader. Where the curator still treats a sold name as owned (it
reads the holdings file until positions_store reader batch #4 is granted — NAVN "Add-On / ADD" the day after it was
sold, operator 2026-10-23), the row shows Type "Re-entry", status "formerly held", and keeps the curator's own
values beside them (``curator_type``, ``curator_stance``, ``ownership_note``) — shown, never silently dropped
(AGENTS.md §26.5).

Filters: every curator filter (``opportunity.passes``, applied to the Watch values) plus the position filters in
``watch_position_facts.FILTERS``; all are query parameters, so a filtered view is a bookmarkable URL.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from lib.data_broker import watch_position_facts as wpf

SCHEMA = "WatchUniverse@v1"
HELD_ONLY_TYPES = {"add_on", "existing", "exit_candidate"}
HELD_ONLY_STANCES = {"ADD", "HOLD", "TRIM", "EXIT"}
PRESET_REENTRY = "reentry"


def overlay(a: dict[str, Any], pf: dict[str, Any]) -> dict[str, Any]:
    """The curator item as Watch shows it: position facts attached, type/stance/status following the broker-synced
    held reader, the curator's own values kept beside them."""
    out = dict(a)
    out.pop("rank_history", None)
    state = pf.get("position_state")
    ctype, cstance, cstatus = a.get("type"), str(a.get("stance") or "").upper(), a.get("position_status")
    typ, stance, status, note = ctype, cstance or None, cstatus, None
    if state == "formerly_held":
        typ, status = "re_entry", "formerly_held"
        if cstance in HELD_ONLY_STANCES:
            stance = "RE_ENTER" if (pf.get("reentry") or {}).get("readiness") == "ready" else "WATCH"
        if ctype != "re_entry" or cstatus == "owned":
            note = (
                f"Sold {str(pf.get('last_sell_at') or '')[:10]} per the broker; the curator still says "
                f"{str(ctype or '—').replace('_', '-')} / {cstance or '—'} ({cstatus or '—'}) — it reads the "
                "holdings file until positions reader batch #4 is approved"
            )
    elif state == "held":
        status = "owned"
        if cstatus != "owned":
            typ = ctype if ctype in HELD_ONLY_TYPES else "existing"
            note = f"Held per the broker; the curator says {cstatus or '—'}"
    out.update(
        {
            "type": typ,
            "stance": stance,
            "position_status": status,
            "curator_type": ctype,
            "curator_stance": a.get("stance"),
            "curator_position_status": cstatus,
            "ownership_note": note,
            **{
                k: pf.get(k) for k in ("position_state", "position_label", "last_sell_at", "last_round_trip", "reentry")
            },
        }
    )
    return out


def build_universe(
    items: dict[str, dict[str, Any]],
    *,
    facts_for,
    q: dict[str, Any],
    now: datetime,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Pure: curator items → the filtered, sorted, paged Watch view with count chips."""
    from lib.data_broker import opportunity as op

    q = dict(q or {})
    preset = str(q.get("preset") or "").lower()
    if preset == PRESET_REENTRY:
        q.pop("preset", None)
        q.setdefault("sort", "formerly_held_first")
    else:
        q = op.apply_preset(q)
    rows = [overlay(a, facts_for(s)) for s, a in items.items() if isinstance(a, dict)]
    base = [r for r in rows if op.passes(r, q)]
    if preset == PRESET_REENTRY:
        base = [r for r in base if r.get("position_state") == "formerly_held" or r.get("type") == "re_entry"]
    pos_q = wpf.active_filters(q)
    matched = [r for r in base if wpf.passes(r, pos_q, now=now)]
    sort = str(q.get("sort") or "conviction")
    if sort in wpf.SORTS:
        ranked = sorted(matched, key=lambda r: (*wpf.sort_key(sort, r, r.get("conviction")), r["symbol"]))
    else:
        ranked = op.sort_items(matched, sort)
    try:
        limit = max(1, min(200, int(q.get("limit") or 100)))
    except (TypeError, ValueError):
        limit = 100
    try:
        page = max(1, int(q.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    facets = {
        k: dict(Counter(str(r.get(k)) for r in matched if r.get(k)))
        for k in ("type", "technical_condition", "cap_band", "position_status", "stance", "sector")
    }
    return {
        "ok": True,
        "schema": SCHEMA,
        **(meta or {}),
        "universe": len(rows),
        "total": len(matched),
        "page": page,
        "page_size": limit,
        "sort": sort,
        "query": {k: v for k, v in q.items() if k != "_"},
        "presets": list((op.load_config().get("presets") or {}).keys()) + [PRESET_REENTRY],
        "sorts": list(op.SORTS) + list(wpf.SORTS),
        "facets": facets,
        "position_facets": wpf.facet_counts(base, now=now),
        "position_filters": wpf.FILTERS,
        "position_sorts": wpf.SORTS,
        "items": ranked[(page - 1) * limit : page * limit],
        "authority": "READ_ONLY_ADVISORY",
        "mbi_behavior": 0,
        "provider_calls": 0,
    }


def list_watch_universe(query: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-universe — the Full universe on Watch, with position facts and filters."""
    from lib.data_broker.watch_prospects import gather

    q = dict(query or {})
    g = gather({})
    now = datetime.now(timezone.utc)
    rsi = {s: r.get("rsi") for s, r in (g.get("rows") or {}).items() if r.get("rsi") is not None}
    pmeta = wpf.load(
        held=set(g.get("held") or ()),
        opps=g.get("opps") or {},
        rsi=rsi,
        fresh=str(q.get("fresh") or "") in ("1", "true"),
    )
    pm = g.get("proj_meta") or {}
    meta = {
        "as_of": pm.get("as_of"),
        "run_id": pm.get("run_id"),
        "store": pm.get("store"),
        "curated_by": "cio_opportunity_curator → CIO memory",
        "ranking": "curator rank (conviction order)",
        "held": {
            "source": g.get("held_source"),
            "as_of": (g.get("held_detail") or {}).get("as_of"),
            "stale": (g.get("held_detail") or {}).get("stale"),
        },
        "position_facts": wpf.public(pmeta),
    }
    out = build_universe(g.get("opps") or {}, facts_for=pmeta["facts_for"], q=q, now=now, meta=meta)
    out["data_broker"] = {
        "package": "scripts/lib/data_broker",
        "projection": "watch_universe",
        "read_only": True,
        "provider_calls": 0,
    }
    return out
