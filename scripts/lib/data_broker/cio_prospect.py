"""Data Broker projection — ``cio_prospect``: the CIO's per-security truth, read-only, for every page.

AGENTS.md §26.3 (18.0.0, ACTIVE): pages and alerts read the prospect only through this projection, with
``as_of``, age, source and stale. Registry row ``cio_prospect`` is PROPOSED (operator grant pending, §17),
so this projection answers from one of two places and says which, every time:

* ``source.kind == "store"`` — the ``cio_prospect`` Postgres table, ONLY when
  ``cio_instrument_record.prospect_store_status`` is live (row granted + operator flag + table present)
  and the caller injected a read-only ``db_query``.
* ``source.kind == "shadow"`` — otherwise: the shadow build artifact (data/cio/cio_prospect_shadow.json,
  written by ``scripts/cio_prospect_shadow_build.py --write-shadow``), labelled "SHADOW — not the store",
  with the reasons the store is not live. A missing artifact is ``gap.kind == no_coverage`` with the declared
  behaviour ``say_so`` — never an empty list presented as "no prospects".

Freshness: the envelope window is passed explicitly (the registry row is proposed, so the envelope's own
registry lookup would see no window): 0.5 h in market hours, 26 h closed. Every row also carries its own
``stale`` (now > ``expires_at``) and ``age_hours`` — a page renders "stale" after ``expires_at``, never a
stale value as current (§7A rule 3). Conflicts are returned on every row (§26.5).

Zero provider calls, zero writes, no broker. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from lib.data_broker.envelope import age_hours, envelope

DOMAIN = "cio_prospect"
PROJECTION = "cio_prospect"
MARKET_STALE_H = 0.5
CLOSED_STALE_H = 26.0
NO_COVERAGE = "say_so"
WRITER = "scripts/lib/cio_instrument_record.py (InstrumentRecordStore)"
SHADOW_WRITER = "scripts/cio_prospect_shadow_build.py --write-shadow"
SHADOW_REL = "data/cio/cio_prospect_shadow.json"
SHADOW_ENV = "TRADEAI_CIO_PROSPECT_SHADOW_PATH"
STORE_COLUMNS = (
    "security_guid, issuer_guid, symbol, subject_key, aliases, stage, stage_changed_at, conviction, "
    "conviction_components, stance, catalyst_grade, next_trigger, whats_missing, next_action, thesis_ref, research, "
    "position_ref, watchlist, stage_phase, origin, position_lifecycle, post_exit_review, reentry_advice, conflicts, "
    "evidence_at, expires_at, as_of, revision")


def _ir():
    try:
        from scripts.lib import cio_instrument_record as ir
    except ImportError:  # scripts/ (not the repo root) on sys.path
        from lib import cio_instrument_record as ir  # type: ignore
    return ir


def shadow_path(base: Path | None = None) -> Path:
    if base is not None:
        return Path(base)
    if os.environ.get(SHADOW_ENV):
        return Path(os.environ[SHADOW_ENV])
    try:
        from lib.canonical_store_registry import production_state_root
    except ImportError:
        from scripts.lib.canonical_store_registry import production_state_root  # type: ignore
    return Path(production_state_root()) / SHADOW_REL


def _ts(v: Any) -> Optional[datetime]:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _market_closed(now: datetime) -> bool:
    try:
        from scripts.lib.cio_prospect_builder import market_open
    except ImportError:
        from lib.cio_prospect_builder import market_open  # type: ignore
    return not market_open(now)


def _row_view(r: dict[str, Any], now: datetime) -> dict[str, Any]:
    exp = _ts(r.get("expires_at"))
    out = {k: r.get(k) for k in (
        "security_guid", "issuer_guid", "symbol", "subject_key", "aliases", "stage", "stage_changed_at", "conviction",
        "conviction_components", "stance", "catalyst_grade", "next_trigger", "whats_missing", "next_action",
        "thesis_ref", "research", "position_ref", "watchlist", "conflicts", "evidence_at", "expires_at", "as_of",
        "revision", "shadow_rank", "rankable", "stage_phase", "origin", "position_lifecycle", "post_exit_review",
        "reentry_advice", "lifecycle_events")}
    for k in ("evidence_at", "expires_at", "as_of", "stage_changed_at"):
        if isinstance(out.get(k), datetime):
            out[k] = out[k].isoformat()
    if out.get("conviction") is not None:
        out["conviction"] = float(out["conviction"])
    out["conflicts"] = out.get("conflicts") or []
    out["conflict_count"] = len(out["conflicts"])
    out["age_hours"] = age_hours(r.get("evidence_at"), now)
    out["stale"] = exp is None or now > exp
    return out


def _load_shadow(base: Path | None) -> tuple[Optional[dict[str, Any]], str]:
    p = shadow_path(base)
    try:
        return json.loads(p.read_text(encoding="utf-8")), str(p)
    except (OSError, ValueError):
        return None, str(p)


def get_prospects(*, db_query: Optional[Callable[..., Any]] = None, shadow_base: Path | None = None,
                  symbols: Optional[Iterable[str]] = None, stage: Optional[str] = None,
                  limit: Optional[int] = None, now: Optional[datetime] = None,
                  status: Optional[dict[str, Any]] = None, market_closed: Optional[bool] = None) -> dict[str, Any]:
    """{prospects: [...], count, source{kind, ...}, as_of, age_hours, stale[, gap]} — never raises."""
    now = now or datetime.now(timezone.utc)
    ir = _ir()
    if status is None:
        probe = None
        if db_query is not None:
            def probe() -> bool:
                rows = db_query("SELECT to_regclass('public.cio_prospect') IS NOT NULL AS present") or []
                return bool(rows and (rows[0].get("present") if isinstance(rows[0], dict) else rows[0][0]))
        status = ir.prospect_store_status(table_probe=probe)
    want = {str(s).upper() for s in symbols} if symbols is not None else None
    closed = _market_closed(now) if market_closed is None else market_closed
    window = CLOSED_STALE_H if closed else MARKET_STALE_H

    rows: list[dict[str, Any]] = []
    out: dict[str, Any] = {"ok": True, "provider_calls": 0, "writes": 0, "memory_behavior_influence": 0}
    as_of = None
    if status.get("live") and db_query is not None:
        kind = "store"
        try:
            raw = db_query(f"SELECT {STORE_COLUMNS} FROM cio_prospect ORDER BY conviction DESC, symbol") or []
            rows = [dict(r) for r in raw]
            as_of = max((r.get("as_of") for r in rows if r.get("as_of") is not None), default=None)
        except Exception as exc:  # noqa: BLE001
            out.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:200])
        src_extra = {"table": "cio_prospect", "writer": WRITER, "label": "cio_prospect store"}
    else:
        kind = "shadow"
        doc, path = _load_shadow(shadow_base)
        rows = list((doc or {}).get("prospects") or [])
        as_of = (doc or {}).get("as_of")
        src_extra = {"file": SHADOW_REL, "path": path, "writer": SHADOW_WRITER,
                     "label": "SHADOW — the cio_prospect shadow build, not the store",
                     "store_not_live": status.get("reasons")}
    if want is not None:
        rows = [r for r in rows if str(r.get("symbol") or "").upper() in want
                or str(r.get("security_guid") or "").upper() in want]
    if stage:
        rows = [r for r in rows if r.get("stage") == stage]
    views = [_row_view(r, now) for r in rows]
    if limit is not None:
        views = views[: int(limit)]
    out["prospects"] = views
    out["count"] = len(views)
    out["stale_rows"] = sum(1 for v in views if v["stale"])
    out["with_conflicts"] = sum(1 for v in views if v["conflict_count"])
    env = envelope(DOMAIN, as_of, now=now, registry={}, stale_after_hours=window,
                   source={"kind": kind, "projection": PROJECTION, "provider": "internal",
                           "registry": "PROPOSED (operator grant pending)", **src_extra})
    if env.get("gap"):
        env["gap"]["declared_behaviour"] = NO_COVERAGE
    out.update(env)
    out["store_status"] = {k: status.get(k) for k in ("live", "mode", "reasons")}
    return out


def get_prospect(symbol_or_guid: str, **kw: Any) -> dict[str, Any]:
    """One security's prospect (by symbol or security_guid). ``prospect`` is None when there is none —
    with ``reason`` "identity unresolved or not covered", never a placeholder."""
    res = get_prospects(symbols=[symbol_or_guid], **kw)
    rows = res.pop("prospects")
    res["prospect"] = rows[0] if rows else None
    if not rows:
        res["reason"] = "no prospect: identity unresolved or not covered by the build"
    return res


def get_position_view(symbol_or_guid: str, **kw: Any) -> dict[str, Any]:
    """The one record TradeInView, Open Trades and Watch read for a position (operator 2026-10-22, NAVN): where it
    came from (``origin``: internal vs operator-initiated, the surfaces and values at the entry fill), what happened
    (``position_lifecycle``: fills, every observed stop, excursion, exit cause, P/L), why it ended
    (``post_exit_review``) and when to get back in (``reentry_advice``), with the append-only ``events`` — all from the
    same cio_prospect record, never a second store. ``position`` is None when the security has no position history."""
    res = get_prospect(symbol_or_guid, **kw)
    p = res.pop("prospect", None) or {}
    view = None
    if p.get("position_lifecycle") or p.get("origin"):
        view = {"symbol": p.get("symbol"), "security_guid": p.get("security_guid"), "stage": p.get("stage"),
                "stage_phase": p.get("stage_phase"), "stance": p.get("stance"), "conviction": p.get("conviction"),
                "origin": p.get("origin"), "lifecycle": p.get("position_lifecycle"),
                "post_exit_review": p.get("post_exit_review"), "reentry_advice": p.get("reentry_advice"),
                "events": p.get("lifecycle_events") or [], "conflicts": p.get("conflicts") or [],
                "next_action": p.get("next_action"), "stale": p.get("stale"), "age_hours": p.get("age_hours")}
    res["position"] = view
    if view is None and "reason" not in res:
        res["reason"] = "no position history for this security in the window the lane reads"
    return res
