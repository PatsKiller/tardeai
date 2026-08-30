"""Unified research source index (ResearchSourceIndex@v1).

content_hash is sha256 of the *source payload* (inputs). Never hash
recommendation / confidence / prose — those are downstream diffs
(`research_scheduler._research_fingerprint`), not skip-before-call.

execute_set = due ∩ (changed ∪ stale ∪ triggered)

READ_ONLY_ADVISORY. JSON under data/cio/. No new datastore.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ResearchSourceIndex@v1"

RESEARCH_EXECUTED = "RESEARCH_EXECUTED"
SKIP_UNCHANGED = "SKIP_UNCHANGED"
SKIP_FRESH = "SKIP_FRESH"
RESEARCH_TRIGGERED = "RESEARCH_TRIGGERED"
CODES = (
    RESEARCH_EXECUTED,
    SKIP_UNCHANGED,
    SKIP_FRESH,
    RESEARCH_TRIGGERED,
)

# Class freshness (docs/ops/RESEARCH_LIFECYCLE_STANDARD.md)
FRESHNESS_HELD_INCOME_DAYS = 14
FRESHNESS_HELD_GROWTH_DAYS = 30
FRESHNESS_HELD_INDEX_BOND_DAYS = 90
FRESHNESS_REENTRY_READY_NEAR_DAYS = 14
FRESHNESS_WATCHLIST_DAYS = 45

INCOME_ROLES = frozenset({"INCOME"})
BDC_LIKE = frozenset({
    "ARCC", "MAIN", "HTGC", "PSEC", "OBDC", "BXSL", "GBDC", "FSK", "CSWC", "TSLX",
})
BOND_LIKE = frozenset({
    "BND", "BNDX", "AGG", "TLT", "IEF", "TIP", "LQD", "HYG", "VCIT", "VGIT",
    "BIV", "GOVT", "SHY", "IEF", "SGOV",
})

# Downstream output fields — never part of the skip hash.
_OUTPUT_KEYS = frozenset({
    "recommendation", "confidence", "prose", "text", "analysis", "rationale",
    "summary", "verdict",
})


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def index_path(*, root: Path | None = None) -> Path:
    env = (os.getenv("RESEARCH_SOURCE_INDEX_PATH") or "").strip()
    if env:
        return Path(env)
    return (root or _project_root()) / "data" / "cio" / "research_source_index.json"


def _now(now: datetime | None = None) -> datetime:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        dt = val
    else:
        s = str(val).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return _now(dt).replace(microsecond=0).isoformat()


def canonicalize(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def compute_hash(payload: Any) -> str:
    """sha256 of canonical source JSON (or raw string). Never used for prose."""
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = canonicalize(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def source_id_for_symbol(sym: str, lane: str) -> str:
    return f"symbol:{str(sym or '').upper().strip()}:lane:{lane}"


def source_payload_for_symbol(
    sym: str,
    *,
    tier: str,
    catalyst: Any,
    thesis_version: Any,
    source_as_of: Any,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Canonical inputs for a symbol research pass. Outputs are excluded."""
    payload: dict[str, Any] = {
        "catalyst": bool(catalyst),
        "source_as_of": source_as_of if source_as_of not in (None, "") else None,
        "symbol": str(sym or "").upper().strip(),
        "thesis_version": thesis_version if thesis_version not in (None, "") else None,
        "tier": str(tier or ""),
    }
    if extra:
        cleaned = {
            k: v
            for k, v in extra.items()
            if str(k).lower() not in _OUTPUT_KEYS
        }
        if cleaned:
            payload["extra"] = cleaned
    return payload


def freshness_days_for(
    *,
    tier: str = "",
    portfolio_role: str | None = None,
    reentry_ready_near: bool = False,
    symbol: str | None = None,
    extra: dict | None = None,
) -> int:
    """Class SLA in days. Defaults: INCOME/BDC 14d, BND-like 90d, T0 30d, else 45d."""
    extra = extra or {}
    if reentry_ready_near or extra.get("reentry_ready_near") or extra.get("class") == "reentry_ready_near":
        return FRESHNESS_REENTRY_READY_NEAR_DAYS
    role = str(portfolio_role or extra.get("portfolio_role") or "").upper()
    sym = str(symbol or extra.get("symbol") or "").upper().strip()
    if role in INCOME_ROLES or extra.get("income_critical") or sym in BDC_LIKE:
        return FRESHNESS_HELD_INCOME_DAYS
    if extra.get("index_bond") or extra.get("bond_like") or sym in BOND_LIKE:
        return FRESHNESS_HELD_INDEX_BOND_DAYS
    if str(tier).startswith("T0"):
        return FRESHNESS_HELD_GROWTH_DAYS
    return FRESHNESS_WATCHLIST_DAYS


def empty_index() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "updated_at": None,
        "sources": {},
    }


def load_index(*, path: Path | None = None, root: Path | None = None) -> dict[str, Any]:
    p = Path(path) if path is not None else index_path(root=root)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return empty_index()
    if not isinstance(data, dict):
        return empty_index()
    sources = data.get("sources")
    if not isinstance(sources, dict):
        data["sources"] = {}
    data.setdefault("schema", SCHEMA)
    data.setdefault("authority", AUTHORITY)
    return data


def get_row(
    source_id: str,
    *,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    idx = load_index(path=path, root=root)
    row = (idx.get("sources") or {}).get(source_id)
    return row if isinstance(row, dict) else None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def upsert_row(
    source_id: str,
    *,
    content_hash: str,
    last_modified_at: str | None = None,
    last_researched_at: str | None = None,
    fresh_until: str | None = None,
    extra: dict | None = None,
    path: Path | None = None,
    root: Path | None = None,
    now: datetime | None = None,
    freshness_days: int | None = None,
    tier: str = "",
    symbol: str | None = None,
    portfolio_role: str | None = None,
    reentry_ready_near: bool = False,
) -> dict[str, Any]:
    """Insert or replace one source row. Sets fresh_until from class SLA if omitted."""
    now_dt = _now(now)
    p = Path(path) if path is not None else index_path(root=root)
    idx = load_index(path=p, root=root)
    days = freshness_days
    if days is None:
        days = freshness_days_for(
            tier=tier,
            portfolio_role=portfolio_role,
            reentry_ready_near=reentry_ready_near,
            symbol=symbol,
            extra=extra,
        )
    researched = last_researched_at or iso(now_dt)
    if not fresh_until:
        base = parse_dt(researched) or now_dt
        fresh_until = iso(base + timedelta(days=int(days)))
    row: dict[str, Any] = {
        "source_id": source_id,
        "last_modified_at": last_modified_at or researched,
        "last_researched_at": researched,
        "content_hash": content_hash,
        "fresh_until": fresh_until,
    }
    if extra:
        row["extra"] = extra
    if tier:
        row.setdefault("extra", {})
        if isinstance(row["extra"], dict):
            row["extra"]["tier"] = tier
    sources = idx.setdefault("sources", {})
    sources[source_id] = row
    idx["schema"] = SCHEMA
    idx["authority"] = AUTHORITY
    idx["updated_at"] = iso(now_dt)
    _atomic_write(p, json.dumps(idx, indent=2, sort_keys=True, default=str) + "\n")
    return row


def upsert_meta(
    source_id: str,
    *,
    meta: dict[str, Any],
    path: Path | None = None,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge librarian metadata (grade / last_seen / stale_after_days) into a row.

    Additive on purpose. This index already owns the freshness axis, so the
    librarian's grade and shelf-life belong on the same row rather than in a
    second store — two freshness laws over one source drift apart, and the
    drift is invisible until someone diffs them by hand.

    Unlike `upsert_row` this never touches `content_hash` or `fresh_until`:
    grading a source is not researching it, and must not reset its TTL. A row
    that does not exist yet is created empty-hashed, so a source can be graded
    before it has ever been fetched.
    """
    now_dt = _now(now)
    p = Path(path) if path is not None else index_path(root=root)
    idx = load_index(path=p, root=root)
    sources = idx.setdefault("sources", {})
    row = sources.get(source_id)
    if not isinstance(row, dict):
        row = {"source_id": source_id, "content_hash": "",
               "last_modified_at": None, "last_researched_at": None,
               "fresh_until": None}
    extra = dict(row.get("extra") or {})
    extra.update({k: v for k, v in (meta or {}).items() if v is not None})
    row["extra"] = extra
    sources[source_id] = row
    idx["schema"] = SCHEMA
    idx["authority"] = AUTHORITY
    idx["updated_at"] = iso(now_dt)
    _atomic_write(p, json.dumps(idx, indent=2, sort_keys=True, default=str) + "\n")
    return row


def is_stale(row: dict[str, Any] | None, now: datetime | None = None) -> bool:
    """True when missing, never researched, or fresh_until has passed."""
    now_dt = _now(now)
    if not row:
        return True
    fu = parse_dt(row.get("fresh_until"))
    if fu is not None:
        return now_dt >= fu
    if not parse_dt(row.get("last_researched_at")):
        return True
    # No TTL recorded — treat as stale (force a refresh rather than skip forever).
    return True


def decide(
    source_id: str,
    current_hash: str,
    *,
    triggered: bool = False,
    now: datetime | None = None,
    hours_window_fresh: bool = False,
    path: Path | None = None,
    root: Path | None = None,
) -> str:
    """Skip-before-call decision.

    RESEARCH_TRIGGERED — operator/event force; execute even if hash matches.
    SKIP_UNCHANGED — hash match and still inside freshness.
    SKIP_FRESH — hours-window / TTL skip without a source-hash compare
                 (backfill RESEARCH_BACKFILL_SKIP_FRESH_HOURS, queue reuse).
    RESEARCH_EXECUTED — hash changed, or stale (hash match but TTL passed), or no row.
    """
    now_dt = _now(now)
    if triggered:
        return RESEARCH_TRIGGERED
    if hours_window_fresh:
        return SKIP_FRESH
    row = get_row(source_id, path=path, root=root)
    if not row:
        return RESEARCH_EXECUTED
    stored = str(row.get("content_hash") or "")
    unchanged = bool(current_hash) and stored == str(current_hash)
    stale = is_stale(row, now_dt)
    if unchanged and not stale:
        return SKIP_UNCHANGED
    return RESEARCH_EXECUTED
