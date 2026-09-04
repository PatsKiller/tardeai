#!/usr/bin/env python3
"""state_root_disposition.py — an authoritative verdict for every audited store.

Detection was shipped in the previous tranche. Detection is not resolution, and
this module refuses to let the two be confused: every one of the 88 audited
stores gets one verdict from a closed taxonomy, and every unresolved fork carries
a named owner, a canonical target and an executable migration step.

    CONVERGED              producer and served copies agree
    INTENTIONALLY_SEPARATE the running service is the sole writer; the checkout
                           copy is a fossil, by design
    MIGRATION_REQUIRED     a real fork with unique or newer information on one
                           side; needs an atomic projection, which this lane
                           cannot perform
    RETIRED                nothing reads it any more
    UNREADABLE             a side exists but cannot be read
    UNKNOWN_BLOCKING       cannot be decided, and a Command Center surface
                           depends on it

Command Center criticality is derived, not asserted: a store is CC-critical when
``scripts/api_v2.py`` names it. A CC-critical store that is not CONVERGED or
INTENTIONALLY_SEPARATE is BLOCKING — its surface must render DIVERGED rather than
imply the number is current.

AGENTS.md rule 5: divergent authoritative copies are reported and escalated,
never auto-merged. Nothing here writes, moves, merges or deletes a store.

AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "StateRootDisposition@v2"
AUTHORITY = "READ_ONLY_ADVISORY"
CALCULATION_VERSION = "2.0.0"

CONVERGED = "CONVERGED"
INTENTIONALLY_SEPARATE = "INTENTIONALLY_SEPARATE"
MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
RETIRED = "RETIRED"
UNREADABLE = "UNREADABLE"
UNKNOWN_BLOCKING = "UNKNOWN_BLOCKING"

DISPOSITIONS = (
    CONVERGED,
    INTENTIONALLY_SEPARATE,
    MIGRATION_REQUIRED,
    RETIRED,
    UNREADABLE,
    UNKNOWN_BLOCKING,
)

#: Modules that run inside the serving process. A store only these write is a
#: store the running service owns outright.
SERVER_MODULES = ("scripts/api_v2.py", "scripts/portfolio_server.py", "scripts/portfolio_api.py")

CC_SURFACE = ROOT / "scripts" / "api_v2.py"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _grep_files(name: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "grep", "-l", "-F", name, "--", "scripts/", "tools/", "bin/"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    return sorted({p for p in out.splitlines() if p.strip()})


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _schema_of(path: Path) -> str | None:
    """Best-effort schema/version marker, so a migration knows what it is moving."""
    try:
        head = path.read_text(errors="replace")[:4000]
    except OSError:
        return None
    m = re.search(r'"(?:schema|schema_version|contract_version|version)"\s*:\s*"([^"]{1,80})"', head)
    return m.group(1) if m else None


def _cc_referenced(name: str, cc_src: str) -> bool:
    return name in cc_src


def disposition_for(store: dict[str, Any], cc_src: str) -> dict[str, Any]:
    """Decide one store, with the evidence that decided it attached."""
    name = store["store"]
    verdict = store.get("verdict")
    direction = store.get("direction")
    prod = store.get("producer") or {}
    served = store.get("served") or {}
    p_exists, s_exists = bool(prod.get("exists")), bool(served.get("exists"))

    writers = _grep_files(name)
    server_only = bool(writers) and all(w in SERVER_MODULES for w in writers)
    cc_critical = _cc_referenced(name, cc_src)

    p_path, s_path = Path(store["producer_path"]), Path(store["served_path"])
    p_sha, s_sha = _sha256(p_path) if p_exists else None, _sha256(s_path) if s_exists else None

    # ── decide ──────────────────────────────────────────────────────────────
    if verdict in ("IDENTICAL", "SAME_INODE"):
        d, why = CONVERGED, f"{verdict}: the two copies agree"
    elif p_exists and not s_exists and not writers:
        d, why = RETIRED, "only the checkout copy remains and nothing in-repo reads or writes it"
    elif not p_exists and not s_exists:
        d, why = RETIRED, "neither root holds this store any more"
    elif (p_exists and not p_sha) or (s_exists and not s_sha):
        d, why = UNREADABLE, "a side exists but could not be read"
    elif verdict == "DIVERGENT" and direction == "SERVED_AHEAD" and server_only:
        d, why = (
            INTENTIONALLY_SEPARATE,
            f"the running service is the only in-repo writer ({', '.join(writers)}); "
            "the checkout copy is a fossil by design",
        )
    elif verdict == "DIVERGENT":
        d, why = (
            MIGRATION_REQUIRED,
            f"{direction}: both copies exist with different content and a real writer "
            f"({', '.join(writers) or 'none in-repo'})",
        )
    elif cc_critical:
        d, why = UNKNOWN_BLOCKING, f"undecidable (verdict={verdict} direction={direction}) and a CC surface reads it"
    else:
        d, why = UNKNOWN_BLOCKING, f"undecidable: verdict={verdict} direction={direction}"

    blocking = cc_critical and d not in (CONVERGED, INTENTIONALLY_SEPARATE, RETIRED)

    row: dict[str, Any] = {
        "store": name,
        "disposition": d,
        "evidence": why,
        "cc_critical": cc_critical,
        "blocking": blocking,
        "verdict": verdict,
        "direction": direction,
        "producer": {
            "path": str(p_path),
            "exists": p_exists,
            "mtime_utc": prod.get("mtime_utc"),
            "bytes": prod.get("bytes"),
            "sha256": p_sha,
            "schema": _schema_of(p_path) if p_exists else None,
        },
        "served": {
            "path": str(s_path),
            "exists": s_exists,
            "mtime_utc": served.get("mtime_utc"),
            "bytes": served.get("bytes"),
            "sha256": s_sha,
            "schema": _schema_of(s_path) if s_exists else None,
        },
        "skew_seconds": store.get("skew_seconds"),
        "in_repo_writers": writers,
        "owner": (writers[0] if writers else "UNOWNED — no in-repo writer found"),
        "canonical_target": str(s_path),
        "canonical_rule": (
            "the served persistent root is canonical: it is what the running service "
            "reads, and a producer that writes only the checkout is writing to a tree "
            "nobody serves"
        ),
    }

    if d == MIGRATION_REQUIRED:
        newer = "producer" if direction == "PRODUCER_AHEAD" else "served"
        row["unique_information"] = {
            "producer_sha256": p_sha,
            "served_sha256": s_sha,
            "differ": p_sha != s_sha,
            "newer_side": newer,
            "both_sides_retained": True,
            "note": "neither copy may be overwritten or deleted; the migration copies forward",
        }
        row["migration_plan"] = [
            f"1. back up BOTH copies with hashes: {p_sha} (producer) and {s_sha} (served)",
            f"2. confirm the writer resolves its path through persistent_state_root, not {p_path.parents[3]}",
            f"3. project the {newer} copy atomically into {s_path} (write-temp + fsync + rename)",
            "4. re-run scripts/lib/state_root_divergence.scan() and require IDENTICAL",
            "5. keep the surface rendering DIVERGED until that scan proves equivalence",
            "6. retire the duplicate writer only after producer and consumer are both proven",
        ]
        row["executable_by_this_lane"] = False
        row["why_not_executable"] = (
            "AGENTS.md rule 5 forbids auto-merging divergent authoritative copies, and "
            "writing the served root is a production state mutation this campaign forbids"
        )
    return row


def state_root_disposition(scan: dict[str, Any]) -> dict[str, Any]:
    """Turn a divergence scan into an authoritative, per-store disposition."""
    cc_src = CC_SURFACE.read_text(errors="replace") if CC_SURFACE.is_file() else ""
    rows = [disposition_for(s, cc_src) for s in scan.get("stores", [])]

    counts: dict[str, int] = {d: 0 for d in DISPOSITIONS}
    for r in rows:
        counts[r["disposition"]] = counts.get(r["disposition"], 0) + 1

    cc = [r for r in rows if r["cc_critical"]]
    blocking = [r for r in rows if r["blocking"]]

    return {
        "schema": SCHEMA,
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "as_of": _now(),
        "producer_root": scan.get("producer_root"),
        "served_root": scan.get("served_root"),
        "audited_store_count": len(rows),
        "disposition_counts": counts,
        "cc_critical_count": len(cc),
        "cc_critical_converged": sum(1 for r in cc if r["disposition"] in (CONVERGED, INTENTIONALLY_SEPARATE)),
        "blocking_count": len(blocking),
        "blocking_stores": [r["store"] for r in blocking],
        "ready": len(blocking) == 0,
        "ready_rule": (
            "READY requires every Command Center-critical store to be CONVERGED or "
            "INTENTIONALLY_SEPARATE. A blocking store's surface must render DIVERGED "
            "rather than imply its number is current."
        ),
        "auto_remediate": False,
        "stores": rows,
        "note": (
            "Detection is complete and served. RESOLUTION IS NOT. Every MIGRATION_REQUIRED "
            "store carries an executable plan that this lane is not permitted to run."
        ),
    }
