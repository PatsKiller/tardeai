"""Acceptance purity — the auditor must not mutate the audited book.

Hash holdings / quote caches / the committed manifest before and after
collection. Only newly generated evidence under the current run directory
may change.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"

DEFAULT_AUDITED = (
    Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/holdings.json"),
    Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/finviz_quote_cache.json"),
    Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/price_cache.json"),
)


def file_sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_audited_files(
    *,
    extra: Optional[Iterable[Path]] = None,
    holdings: Optional[Path] = None,
) -> dict[str, Any]:
    paths = list(DEFAULT_AUDITED)
    if holdings is not None:
        paths[0] = Path(holdings)
    if extra:
        paths.extend(Path(p) for p in extra)
    out: dict[str, Any] = {}
    for p in paths:
        key = str(p)
        out[key] = {
            "path": key,
            "exists": p.is_file(),
            "sha256": file_sha256(p),
            "bytes": p.stat().st_size if p.is_file() else 0,
        }
    return out


def compare_audited(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changed: list[str] = []
    for key, rec in (before or {}).items():
        nxt = (after or {}).get(key) or {}
        if rec.get("sha256") != nxt.get("sha256"):
            changed.append(key)
    return {
        "authority": AUTHORITY,
        "audited_state_unchanged": len(changed) == 0,
        "changed": changed,
        "holdings_before_sha": _holdings_sha(before),
        "holdings_after_sha": _holdings_sha(after),
    }


def _holdings_sha(snap: dict[str, Any]) -> Optional[str]:
    for rec in (snap or {}).values():
        if str(rec.get("path") or "").endswith("holdings.json"):
            return rec.get("sha256")
    return None
