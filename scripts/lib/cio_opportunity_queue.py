"""cio_opportunity_queue.py — Alex's single desk-suggestion opportunity surface.

Phase 5 increment: turn the firewalled desk-suggestion pool (staged/undrained
curation from cio/advisory/defense/rotation/reentry) into ONE deterministic,
hash-pinned "opportunity queue" that Alex (the CIO agent) consumes — instead of a
page the operator has to watch all day.

The queue is a READ-ONLY projection. It never promotes or mutates anything; Alex
reads it and then acts through the existing governed promote path
(promote_directive_lead / drain_curation_sources). This keeps the firewall intact.

Every function here is pure and deterministic: the DB-reading entrypoint
(`fetch_desk_suggestions`) is separated from the pure logic so the latter is
dry-testable with no live database, broker, or LLM.

Canonical opportunity envelope:
    {
        "opportunity_key": "<sha256[:32]>",
        "source": "cio|advisory|defense|rotation|reentry",
        "symbol": "NVDA",
        "directive_label": "…",
        "verdict": "ADD" | "RE_ENTER" | None,     # advisory verdict if present
        "state": "READY TO REVIEW" | …,          # reentry state if present
        "rs_score": 82 | None,                   # rotation RS if present
        "surfaced_at": "2026-08-13T…",
    }
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable, Optional

# Executor signature matches db_adapter._execute(sql, params=None, fetch=None).
Executor = Callable[..., Any]

# ── Taxonomy (single source of truth lives in lib.two_way_curation) ──────────
OPPORTUNITY_SOURCES = ("cio", "advisory", "defense", "rotation", "reentry")

# Rank weight for ordering the queue. Higher = surfaces first for Alex.
# Re-entry READY and rotation leading-sectors are the most actionable forward
# signals; advisory verdicts carry specific evidence; CIO/defense are contextual.
SOURCE_RANK = {
    "reentry": 5,
    "rotation": 4,
    "advisory": 3,
    "cio": 2,
    "defense": 1,
}

# Advisory verdicts that are actionable watchlist signals (mirror two_way_curation).
ACTIONABLE_VERDICTS = frozenset({"ADD", "TRIM", "EXIT", "RE_ENTER"})

# Re-entry states that are actionable (mirror two_way_curation).
ACTIONABLE_REENTRY_STATES = frozenset({"READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW"})

# Minimum distinct sources before the queue is "material" enough to wake Alex.
# A single-source trickle should not page the CIO; a multi-desk confluence should.
MATERIAL_MIN_SOURCES = 2


# ─────────────────────────────────────────────────────────────────────────────
# Pure logic (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def opportunity_key(source: str, symbol: str, directive_label: str,
                    verdict: Optional[str] = None) -> str:
    """Deterministic dedup key for one opportunity (source+symbol+label+verdict)."""
    raw = "|".join([
        str(source or "").strip().lower(),
        str(symbol or "").strip().upper(),
        str(directive_label or "").strip(),
        str(verdict or "").strip().upper(),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def normalize_opportunity(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Normalize one raw suggestion row into a canonical opportunity, or None.

    Accepts rows from either `watch_directive_hits` (STAGED_FOR_REVIEW) or a
    source staging table. Only rows with a symbol and a recognized source are
    kept — an empty/thin row never becomes an opportunity.
    """
    if not isinstance(raw, dict):
        return None

    source = str(raw.get("source") or raw.get("surfaced_by") or "").strip().lower()
    if source not in OPPORTUNITY_SOURCES:
        return None

    symbol = str(raw.get("symbol") or "").strip().upper()
    if not symbol:
        return None

    label = str(
        raw.get("directive_label")
        or raw.get("label")
        or raw.get("thesis")
        or f"{source} suggestion"
    ).strip()[:200]

    verdict = str(raw.get("verdict") or "").strip().upper() or None
    state = str(raw.get("state") or "").strip().upper() or None

    # Filter non-actionable verdicts/states at the boundary so the queue only
    # surfaces things Alex can actually act on.
    if verdict and verdict not in ACTIONABLE_VERDICTS:
        return None
    if state and state not in ACTIONABLE_REENTRY_STATES:
        return None

    rs_score = raw.get("rs_score")
    try:
        rs_score = float(rs_score) if rs_score is not None else None
    except (TypeError, ValueError):
        rs_score = None

    surfaced_at = str(raw.get("surfaced_at") or raw.get("proposed_at") or "").strip() or None

    return {
        "opportunity_key": opportunity_key(source, symbol, label, verdict),
        "source": source,
        "symbol": symbol,
        "directive_label": label,
        "verdict": verdict,
        "state": state,
        "rs_score": rs_score,
        "surfaced_at": surfaced_at,
    }


def _rank_score(opp: dict[str, Any]) -> tuple[int, int, str]:
    """Deterministic ordering tuple: source rank desc, rs_score desc, symbol asc."""
    source = opp.get("source", "")
    rs = opp.get("rs_score")
    return (
        -SOURCE_RANK.get(source, 0),
        -(rs if rs is not None else -1),
        str(opp.get("symbol", "")),
    )


def build_opportunity_queue(rows: list[dict[str, Any]], *,
                            now: Optional[datetime] = None) -> dict[str, Any]:
    """Build the deterministic opportunity queue from raw suggestion rows.

    Returns a hash-pinned digest suitable for idempotent wake creation and a
    compact `top` list for Alex's synthesis. `material` is True only when the
    queue has opportunities from >= MATERIAL_MIN_SOURCES distinct desks.
    """
    now = now or datetime.now(timezone.utc)
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        opp = normalize_opportunity(row)
        if opp is None:
            continue
        key = opp["opportunity_key"]
        existing = by_key.get(key)
        if existing is None or (opp.get("surfaced_at") or "") > (existing.get("surfaced_at") or ""):
            by_key[key] = opp

    items = sorted(by_key.values(), key=_rank_score)
    by_source: dict[str, int] = {}
    for it in items:
        by_source[it["source"]] = by_source.get(it["source"], 0) + 1

    digest_raw = "|".join(
        f"{it['opportunity_key']}:{it.get('surfaced_at') or ''}" for it in items
    )
    digest = hashlib.sha256(digest_raw.encode("utf-8")).hexdigest()

    material = len([s for s, n in by_source.items() if n > 0]) >= MATERIAL_MIN_SOURCES

    return {
        "computed_at": now.isoformat(),
        "digest": digest,
        "count": len(items),
        "material": material,
        "distinct_sources": len(by_source),
        "by_source": by_source,
        "top": items[:12],
        "items": items,
    }


def material_new_opportunities(digest: Optional[str],
                               previous_digest: Optional[str]) -> bool:
    """True when the queue digest changed AND is non-empty (i.e. new material work).

    An empty queue (digest of zero items) never wakes Alex. A digest change with
    content does. Missing previous digest (first run) counts as new only if the
    current digest is non-empty.
    """
    if not digest:
        return False
    if previous_digest is None:
        return True
    return digest != previous_digest


# ─────────────────────────────────────────────────────────────────────────────
# Live reader (injectable executor; separated from pure logic)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_desk_suggestions(executor: Executor, *, limit: int = 200) -> list[dict[str, Any]]:
    """Read staged/undrained desk suggestions into raw rows via an executor.

    Sources: (1) watch_directive_hits STAGED_FOR_REVIEW from desk sources, and
    (2) undrained rows in each desk staging table. Fail-soft: any source error
    returns what was collected so far — the reader never raises.
    """
    rows: list[dict[str, Any]] = []
    try:
        hits = executor(
            """SELECT h.symbol, h.surfaced_by AS source, d.label AS directive_label,
                      h.surfaced_at
               FROM watch_directive_hits h
               JOIN watch_directives d ON d.id = h.directive_id
               WHERE h.promotion_status = 'STAGED_FOR_REVIEW'
                 AND h.surfaced_by = ANY(%s)
                 AND h.surfaced_at > now() - interval '7 days'
               ORDER BY h.surfaced_at DESC
               LIMIT %s""",
            (list(OPPORTUNITY_SOURCES), limit),
            fetch="all",
        )
        rows.extend(dict(r) for r in (hits or []))
    except Exception:
        pass

    for source in OPPORTUNITY_SOURCES:
        tbl = {
            "cio": "cio_directive_hits_staging",
            "advisory": "advisory_directive_hits_staging",
            "defense": "defense_directive_hits_staging",
            "rotation": "rotation_directive_hits_staging",
            "reentry": "reentry_directive_hits_staging",
        }[source]
        try:
            staged = executor(
                f"""SELECT symbol, '{source}' AS source,
                           (source_detail->>'directive_label') AS directive_label,
                           (source_detail->>'verdict') AS verdict,
                           (source_detail->>'state') AS state,
                           (source_detail->>'rs_score') AS rs_score,
                           proposed_at AS surfaced_at
                    FROM {tbl}
                    WHERE NOT drained
                    ORDER BY proposed_at DESC
                    LIMIT %s""",
                (limit,),
                fetch="all",
            )
            rows.extend(dict(r) for r in (staged or []))
        except Exception:
            continue

    return rows


def build_queue_from_executor(executor: Executor, *,
                              limit: int = 200,
                              now: Optional[datetime] = None) -> dict[str, Any]:
    """Convenience: read desk suggestions and build the queue in one call."""
    return build_opportunity_queue(fetch_desk_suggestions(executor, limit=limit), now=now)
