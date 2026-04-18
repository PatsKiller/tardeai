"""catalyst_cache.py — Disk-based catalyst enrichment cache for continuous runner.

Saves enrichment results to data/catalyst_cache_{date}.json.
Each entry has a timestamp. get() returns None if entry is older than TTL.
set() writes immediately (atomic via temp file).

Used by continuous_runner.py to avoid hammering 5 APIs every 15 minutes.
Enrichment is typically stable for 20-30 minutes — only new catalysts matter.
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_TTL_MINUTES = 20


def _cache_path(project_root: str, date_str: str) -> Path:
    p = Path(project_root) / "data" / f"catalyst_cache_{date_str}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)   # atomic rename


def get(
    symbol: str,
    project_root: str = ".",
    date_str: Optional[str] = None,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> Optional[Dict[str, Any]]:
    """Return cached enrichment for symbol if fresher than ttl_minutes, else None."""
    if ttl_minutes <= 0:
        return None
    ds   = date_str or _now_utc().strftime("%Y-%m-%d")
    path = _cache_path(project_root, ds)
    data = _load(path)
    entry = data.get(symbol)
    if not entry:
        return None
    cached_at = entry.get("_cached_at")
    if not cached_at:
        return None
    try:
        ts = datetime.fromisoformat(cached_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_minutes = (_now_utc() - ts).total_seconds() / 60
        if age_minutes <= ttl_minutes:
            return entry.get("enrichment")
    except Exception:
        pass
    return None


def set(
    symbol: str,
    enrichment: Dict[str, Any],
    project_root: str = ".",
    date_str: Optional[str] = None,
) -> None:
    """Cache enrichment result for symbol."""
    ds   = date_str or _now_utc().strftime("%Y-%m-%d")
    path = _cache_path(project_root, ds)
    data = _load(path)
    data[symbol] = {
        "_cached_at": _now_utc().isoformat(timespec="seconds"),
        "enrichment": enrichment,
    }
    _save(path, data)


def set_bulk(
    enrichments: Dict[str, Dict[str, Any]],
    project_root: str = ".",
    date_str: Optional[str] = None,
) -> None:
    """Cache a full dict of {symbol: enrichment} results in one write."""
    ds   = date_str or _now_utc().strftime("%Y-%m-%d")
    path = _cache_path(project_root, ds)
    data = _load(path)
    ts   = _now_utc().isoformat(timespec="seconds")
    for sym, enrichment in enrichments.items():
        data[sym] = {"_cached_at": ts, "enrichment": enrichment}
    _save(path, data)


def get_bulk(
    symbols: list,
    project_root: str = ".",
    date_str: Optional[str] = None,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> tuple[Dict[str, Any], list]:
    """Batch get. Returns (hits_dict, misses_list).

    hits_dict  : {symbol: enrichment} for symbols found and fresh
    misses_list: symbols that need a fresh fetch
    """
    if ttl_minutes <= 0:
        return {}, list(symbols)
    ds   = date_str or _now_utc().strftime("%Y-%m-%d")
    path = _cache_path(project_root, ds)
    data = _load(path)
    now  = _now_utc()
    hits: Dict[str, Any] = {}
    misses: list = []
    for sym in symbols:
        entry = data.get(sym)
        if not entry:
            misses.append(sym); continue
        try:
            ts = datetime.fromisoformat(entry.get("_cached_at",""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if (now - ts).total_seconds() / 60 <= ttl_minutes:
                hits[sym] = entry["enrichment"]
            else:
                misses.append(sym)
        except Exception:
            misses.append(sym)
    return hits, misses


def clear(project_root: str = ".", date_str: Optional[str] = None) -> None:
    """Delete today's cache file (useful for testing)."""
    ds   = date_str or _now_utc().strftime("%Y-%m-%d")
    path = _cache_path(project_root, ds)
    if path.exists():
        path.unlink()
