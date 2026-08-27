"""StoreConsistency@v1 — detect divergent state, and refuse to resolve it.

On 2026-08-27 the one store classed `AUTHORITATIVE` — `portfolio.holdings.current`
— existed as two divergent copies:

    SOURCE (hub)         sum(positions)+cash 1,284,251.64  stated 1,287,999.68  INCONSISTENT
    PERSIST (CIO reads)  sum(positions)+cash 1,287,999.68  stated 1,287,999.68  consistent

Different inodes, 18 of 30 positions differing, identical prices — so the
disagreement is in share counts. The source copy had ~30h fresher shares and
totals that no longer reconciled; the copy the CIO reads reconciled but was
30h stale. **Neither was simply correct.**

That is why nothing here remediates. Two candidate truths means a machine
picking one destroys the other, and the fresher copy was the wrong one to pick.
This module reports both paths, both timestamps, both hashes, and stops.

It also exists because `production_root_map.map_all()` reports this layout as
clean: `unknown_n: 0`, `source_tree_coupled_n: 3`, zero duplicates. All three are
hollow — `DUPLICATE_ROOT` is unreachable dead code, the STC count is three
hardcoded constants, and a missing file is reclassified `RELEASE_LOCAL_DERIVED`
rather than flagged. A green root map is not evidence of a healthy layout, so
this check reads the filesystem directly rather than trusting that map.

AUTHORITY: READ_ONLY_ADVISORY. Detects; never repairs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "StoreConsistency@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

SEV_CRITICAL = "critical"
SEV_WARNING = "warning"

# Findings this module can emit. `store_divergence` is deliberately excluded from
# any remediation map -- see the module docstring.
TYPE_DIVERGENCE = "store_divergence"
TYPE_MISSING = "store_missing"
TYPE_BROKEN_SYMLINK = "store_broken_symlink"
TYPE_SOURCE_TREE_COUPLED = "store_source_tree_coupled"
TYPE_INTERNALLY_INCONSISTENT = "store_internally_inconsistent"

NEVER_AUTO_REMEDIATE = frozenset({
    TYPE_DIVERGENCE, TYPE_INTERNALLY_INCONSISTENT, TYPE_SOURCE_TREE_COUPLED,
})


def _digest(path: Path, limit: int = 8_000_000) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            read = 0
            while read < limit:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                read += len(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _stat(path: Path) -> dict[str, Any] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return {
        "path": str(path),
        "inode": st.st_ino,
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
    }


def compare_copies(primary: Path, shadow: Path) -> dict[str, Any] | None:
    """Two paths that should be the same store. None when there is no conflict.

    Same inode is a hardlink or symlink — one file, not a fork.
    """
    a, b = _stat(Path(primary)), _stat(Path(shadow))
    if a is None or b is None:
        return None
    if a["inode"] == b["inode"]:
        return None
    da, db = _digest(Path(primary)), _digest(Path(shadow))
    if da is not None and da == db:
        return None  # byte-identical copies: wasteful, not divergent
    newer = "shadow" if b["mtime"] > a["mtime"] else "primary"
    return {
        "primary": {**a, "sha256": da},
        "shadow": {**b, "sha256": db},
        "newer_copy": newer,
        "newer_is_the_one_readers_use": newer == "primary",
    }


def holdings_reconciles(path: Path) -> dict[str, Any] | None:
    """Does a holdings file's stated total match the sum of its own positions?

    The audit's decisive test: the FRESHER copy failed this by $3,748 while the
    stale one passed. Freshness alone is not a tiebreak, so any consumer of a
    divergence finding needs this alongside the timestamps.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    positions = doc.get("holdings") or []
    totals = doc.get("portfolio_totals") or {}
    stated = totals.get("total_value")
    if not positions or stated is None:
        return None
    summed = sum(float(p.get("market_value") or 0) for p in positions)
    delta = round(summed - float(stated), 2)
    return {
        "path": str(path),
        "summed_positions": round(summed, 2),
        "stated_total": float(stated),
        "delta": delta,
        "reconciles": abs(delta) < 1.0,
    }


def check(pairs: list[tuple[str, Path, Path]]) -> list[dict[str, Any]]:
    """Findings for each (store_id, primary, shadow) triple.

    Emits health-agent finding shape: category / type / severity / message.
    """
    findings: list[dict[str, Any]] = []
    for store_id, primary, shadow in pairs:
        primary, shadow = Path(primary), Path(shadow)

        if primary.is_symlink() and not primary.exists():
            findings.append({
                "category": "store_consistency", "type": TYPE_BROKEN_SYMLINK,
                "severity": SEV_CRITICAL, "store_id": store_id,
                "message": f"{store_id}: broken symlink at {primary}",
                "primary_path": str(primary),
            })
            continue

        if not primary.exists():
            findings.append({
                "category": "store_consistency", "type": TYPE_MISSING,
                "severity": SEV_CRITICAL, "store_id": store_id,
                "message": f"{store_id}: canonical path absent — {primary}",
                "primary_path": str(primary),
                "shadow_exists": shadow.exists(),
            })
            continue

        conflict = compare_copies(primary, shadow)
        if conflict:
            recon_p = holdings_reconciles(primary)
            recon_s = holdings_reconciles(shadow)
            detail = ""
            if recon_p and recon_s:
                detail = (f" reconciles: canonical={recon_p['reconciles']} "
                          f"shadow={recon_s['reconciles']}")
            findings.append({
                "category": "store_consistency", "type": TYPE_DIVERGENCE,
                "severity": SEV_CRITICAL, "store_id": store_id,
                # Both paths, both timestamps, both hashes — the operator decides.
                "message": (
                    f"{store_id}: two divergent copies. "
                    f"canonical {conflict['primary']['path']} "
                    f"(mtime {conflict['primary']['mtime']}, sha {str(conflict['primary']['sha256'])[:12]}) "
                    f"vs shadow {conflict['shadow']['path']} "
                    f"(mtime {conflict['shadow']['mtime']}, sha {str(conflict['shadow']['sha256'])[:12]}); "
                    f"newer copy is the {conflict['newer_copy']}.{detail} "
                    f"NOT auto-remediated: the fresher copy may be the inconsistent one."),
                "conflict": conflict,
                "reconciliation": {"canonical": recon_p, "shadow": recon_s},
                "never_auto_remediate": True,
            })

        recon = holdings_reconciles(primary)
        if recon and not recon["reconciles"]:
            findings.append({
                "category": "store_consistency", "type": TYPE_INTERNALLY_INCONSISTENT,
                "severity": SEV_CRITICAL, "store_id": store_id,
                "message": (f"{store_id}: stated total {recon['stated_total']} does not match "
                            f"sum of positions {recon['summed_positions']} "
                            f"(delta {recon['delta']}) at {primary}"),
                "drift_pct": abs(recon["delta"]) / max(recon["stated_total"], 1) * 100,
                "never_auto_remediate": True,
            })
    return findings
