"""GOOD_PERSISTENT_ROOT — machine-level persistent state, not a git worktree.

Convention: ~/trade-ai-releases/persistent-state
Sibling of portfolio-server releases. Independent of any checkout.

Copy first. Never delete the legacy source-tree copy in this tranche.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.atomic_json_store import atomic_write_json

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "PersistentStateRoot@v1"
STAMP_NAME = "PERSISTENT_STATE_ROOT.json"
LEGACY_MARK = "LEGACY_MIGRATION_SOURCE.json"

GOOD_PERSISTENT_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"
DEFAULT_LEGACY_SOURCE = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")

# Trees that must survive deploy. CACHE exceptions are documented, not copied.
# G1: logs joins the set — release-local logs/ forks orphan escalation queues
# and append-only health history on every promote (#569).
PERSISTENT_TREES = (
    "data/cio",
    "data/portfolios/state",
    "data/research",
    "data/hermes",
    "data/health",
    "data/runtime",
    "logs",
)
PERSISTENT_FILES: tuple[str, ...] = ()
CACHE_EXCLUDES = (
    "hermes_governed_universe_history",
    "schwab_browser_profile",
    "trade_ai_cache.json",
)
EXCEPTIONS = {
    "CACHE": ["data/runtime/hermes_governed_universe_history", "data/runtime/schwab_browser_profile", "data/runtime/trade_ai_cache.json"],
    "OPS_LOG": ["data/health"],
    "REBUILDABLE_PROJECTION": ["data/cio/cio_operator_product.json", "data/runtime/advisory_desk_latest.json"],
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def good_persistent_root() -> Path:
    env = os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    return Path(env) if env else GOOD_PERSISTENT_ROOT


def _realpath_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def durable_write_targets(
    rel: str,
    checkout_root: Path | str,
    *,
    require_persistent_dir: bool = True,
) -> list[Path]:
    """Resolution-layer dual-write targets for a checkout-relative path.

    WAVE G1 — five instances of the same defect: a writer whose path resolves
    from `Path(__file__)` / cron cwd lands in the hub tree, while the served
    release reads GOOD_PERSISTENT_ROOT (or a symlink into it). Fix the path
    here, not the cron's `cd`.

    Returns the served/persistent copy first (when present), then the checkout
    copy. Deduped by realpath so a release whose tree already symlinks the
    persistent root yields one target. Callers that still have hub-tree readers
    must write both; collapsing to one copy is an irreversible operator
    decision (same hold as the two holdings copies).
    """
    rel_path = Path(rel)
    targets: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        key = _realpath_key(path)
        if key not in seen:
            seen.add(key)
            targets.append(path)

    persistent = good_persistent_root() / rel_path
    if require_persistent_dir:
        # Directory form (state dirs, logs/, runtime/).
        if persistent.is_dir() or is_provisioned():
            _add(persistent)
    else:
        # File form (evening packet JSON, risk_management.json, …).
        if persistent.parent.is_dir() or is_provisioned():
            _add(persistent)

    _add(Path(checkout_root) / rel_path)
    return targets


def portfolio_state_write_targets(checkout_root: Path | str) -> list[Path]:
    """State dirs a portfolio writer must update, served copy first.

    Every deployed release symlinks `data/portfolios/state` at
    GOOD_PERSISTENT_ROOT, so that copy is what the live server reads. A writer
    that resolves its own path from `Path(__file__).parent.parent` writes only
    the checkout it happens to live in, which the server never reads — the
    writer then reports success while the served numbers go stale.

    Returns the served copy first (when provisioned), then the checkout copy.
    Both are written because ~1100 call sites still resolve state
    checkout-relative; dropping that copy would starve them. De-duplicated by
    realpath, so a checkout already symlinked at the persistent root yields one
    target rather than two writes to the same inode.
    """
    return durable_write_targets("data/portfolios/state", checkout_root)


def resolve_durable_dir(rel: str, checkout_root: Path | str | None = None) -> Path:
    """Single directory resolution independent of cron cwd.

    Prefers the persistent root when provisioned; else the checkout (or
    DEFAULT_LEGACY_SOURCE). This is the cron→dev-tree fix at the resolution
    layer: callers ask for a logical rel and get the served path.
    """
    checkout = Path(checkout_root) if checkout_root else DEFAULT_LEGACY_SOURCE
    targets = durable_write_targets(rel, checkout)
    return targets[0]


def logs_root(checkout_root: Path | str | None = None) -> Path:
    """Canonical logs/ directory — persistent when provisioned, else checkout."""
    return resolve_durable_dir("logs", checkout_root)


def evening_packet_rel() -> str:
    return "data/runtime/aegis_evening_packet.json"


def evening_packet_write_targets(checkout_root: Path | str) -> list[Path]:
    """Paths that must receive the evening packet, served copy first."""
    return durable_write_targets(
        evening_packet_rel(), checkout_root, require_persistent_dir=False
    )


def evening_packet_path(checkout_root: Path | str | None = None) -> Path:
    """Primary evening-packet path (persistent/runtime when available)."""
    checkout = Path(checkout_root) if checkout_root else DEFAULT_LEGACY_SOURCE
    return evening_packet_write_targets(checkout)[0]


def report_authoritative_divergence(
    *paths: Path | str,
    label: str = "",
) -> dict[str, Any]:
    """Compare authoritative copies by byte identity. NEVER merges them.

    AGENTS.md §9.4 / WAVE G1: divergent holdings / risk / packet copies are
    reported to the operator. Auto-remediation is forbidden — detection must
    not become resolution.
    """
    rows: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        row: dict[str, Any] = {
            "path": str(path),
            "exists": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
            "bytes": path.stat().st_size if path.is_file() else None,
            "mtime": (
                datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                if path.is_file()
                else None
            ),
            "realpath": str(Path(os.path.realpath(path))) if path.exists() or path.is_symlink() else str(path),
        }
        rows.append(row)

    shas = {r["sha256"] for r in rows if r["sha256"]}
    identical = len(shas) <= 1 and all(r["exists"] for r in rows) and len(rows) >= 1
    present = [r for r in rows if r["exists"]]
    if len(present) < 2:
        identical = True  # nothing to diverge against

    return {
        "schema": "AuthoritativeDivergenceReport@v1",
        "label": label or "unspecified",
        "as_of": _now(),
        "copies": rows,
        "identical": identical,
        "diverged": not identical and len(present) >= 2,
        "auto_remediate": False,
        "action": (
            "REPORT_BOTH_ESCALATE"
            if (not identical and len(present) >= 2)
            else "NONE"
        ),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "note": (
            "Never merge divergent authoritative copies. Report both; escalate. "
            "Future dual-writes from one in-memory object prevent re-divergence; "
            "they do not reconcile historical forks."
        ),
    }


def stamp_path(root: Path | None = None) -> Path:
    return (root or good_persistent_root()) / STAMP_NAME


def is_provisioned(root: Path | None = None) -> bool:
    return stamp_path(root).is_file()


def load_stamp(root: Path | None = None) -> dict[str, Any]:
    p = stamp_path(root)
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_count(path: Path) -> int | None:
    if not path.is_file():
        return None
    if path.suffix == ".jsonl":
        try:
            return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
        except OSError:
            return None
    return 1


def inventory_path(path: Path, *, logical: str, writer: str = "", readers: list[str] | None = None,
                   persistence_class: str = "CANONICAL_PERSISTENT_STATE") -> dict[str, Any]:
    exists = path.exists()
    st = path.stat() if exists else None
    real = Path(os.path.realpath(path)) if exists else path
    return {
        "logical_store": logical,
        "configured_path": str(path),
        "realpath": str(real),
        "inode": st.st_ino if st else None,
        "device": st.st_dev if st else None,
        "bytes": st.st_size if st and path.is_file() else (None if not exists else "dir"),
        "row_count": _row_count(path) if path.is_file() else None,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat() if st else None,
        "exists": exists,
        "writer": writer,
        "readers": readers or [],
        "required_persistence_class": persistence_class,
        "source_tree_coupled": "/trade-ai-v12-rebuild/" in str(real) or "/wt-r18" in str(real),
    }


def inventory(*, source: Path | str) -> dict[str, Any]:
    src = Path(source)
    rows = [
        inventory_path(src / "data/cio/cio_investment_briefs.jsonl", logical="cio.product.history", writer="cio_investment_product", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/cio/cio_decisions.jsonl", logical="cio.decisions", writer="cio_decision_pipeline", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/cio/outcome_checkpoints.jsonl", logical="cio.checkpoints", writer="r17_checkpoint_binding", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/cio/outcome_observations.jsonl", logical="cio.outcomes", writer="cio_institutional_learning", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/cio/aif_memory.json", logical="memory.canonical", writer="agent_durable_memory", persistence_class="CANONICAL_PERSISTENT_STATE"),
        inventory_path(src / "data/cio/cio_theses_projection.json", logical="ticker.cognition", writer="cio_theses", persistence_class="CANONICAL_PERSISTENT_STATE"),
        inventory_path(src / "data/cio/cio_research_impacts.jsonl", logical="research.state", writer="cio_research", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/cio/decision_dispositions.jsonl", logical="operator.feedback", writer="api_v3_cio", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/cio/operator_ticker_feedback.jsonl", logical="operator.ticker_feedback", writer="cio_operator_ticker_feedback", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/runtime/advisory_kb_lessons.jsonl", logical="lessons", writer="advisory_desk", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/cio/cio_operator_learning.jsonl", logical="hypotheses", writer="cio_learning", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/cio/cio_notification_metrics.jsonl", logical="model.performance", writer="cio_notification_signal", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/cio/cio_notification_outbox.jsonl", logical="notification.history", writer="cio_notification_outbox", persistence_class="APPEND_ONLY_EVIDENCE"),
        inventory_path(src / "data/portfolios/state/holdings.json", logical="portfolio.persistent_metadata", writer="holdings reconciliation", persistence_class="AUTHORITATIVE"),
        inventory_path(src / "data/runtime/sector_momentum_latest.json", logical="sector.momentum.current", writer="sector_momentum_engine", persistence_class="DERIVED_CURRENT_PROJECTION"),
        inventory_path(src / "data/runtime/industry_momentum_latest.json", logical="industry.momentum.current", writer="industry_momentum", persistence_class="DERIVED_CURRENT_PROJECTION"),
    ]
    coupled = sum(1 for r in rows if r.get("source_tree_coupled") and r.get("exists"))
    return {
        "schema": "PersistentStoreInventory@v1",
        "source": str(src),
        "n": len(rows),
        "source_tree_coupled_n": coupled,
        "rows": rows,
        "exceptions": EXCEPTIONS,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def migration_manifest(*, source: Path, dest: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    src = Path(source)
    for rel in PERSISTENT_TREES:
        base = src / rel
        if not base.exists():
            continue
        if base.is_file():
            files.append(_manifest_row(src, dest, rel))
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if any(ex in p.parts for ex in CACHE_EXCLUDES):
                continue
            rel_p = str(p.relative_to(src))
            files.append(_manifest_row(src, dest, rel_p))
    for rel in PERSISTENT_FILES:
        if (src / rel).is_file():
            files.append(_manifest_row(src, dest, rel))
    return {
        "schema": "PersistentMigrationSnapshot@v1",
        "as_of": _now(),
        "source": str(src),
        "destination_candidate": str(dest),
        "n": len(files),
        "files": files,
        "destructive_changes": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def _manifest_row(src: Path, dest: Path, rel: str) -> dict[str, Any]:
    p = src / rel
    st = p.stat()
    return {
        "relative": rel,
        "logical_store": rel,
        "sha256": sha256_file(p),
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        "record_count": _row_count(p),
        "source_path": str(p),
        "destination_candidate_path": str(dest / rel),
    }


def copy_verified(*, source: Path, dest: Path, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Populate dest by copy. Never deletes source."""
    src = Path(source)
    dst = Path(dest)
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    mismatches = []
    man = manifest or migration_manifest(source=src, dest=dst)
    for row in man.get("files") or []:
        rel = row["relative"]
        sp = src / rel
        dp = dst / rel
        dp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sp, dp)
        got = sha256_file(dp)
        ok = got == row.get("sha256")
        rec = {**row, "copied": True, "dest_sha256": got, "hash_equal": ok}
        copied.append(rec)
        if not ok:
            mismatches.append(rel)
    stamp = {
        "schema": SCHEMA,
        "as_of": _now(),
        "path": str(dst),
        "legacy_source": str(src),
        "legacy_read_only": False,
        "n_copied": len(copied),
        "mismatches": mismatches,
        "authority": AUTHORITY,
        "financial_action": False,
        "note": "Copy verified. Source tree not deleted. LEGACY_MIGRATION_SOURCE until soak.",
    }
    atomic_write_json(dst / STAMP_NAME, stamp)
    return {
        "ok": not mismatches,
        "copied_n": len(copied),
        "mismatches": mismatches,
        "stamp": stamp,
        "destructive_applied": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def hashes_match(manifest_rows: list[dict[str, Any]]) -> bool:
    return all(r.get("hash_equal") is True for r in manifest_rows if r.get("copied"))


def mark_legacy_read_only(legacy: Path) -> dict[str, Any]:
    mark = {
        "schema": "LegacyMigrationSource@v1",
        "read_only": True,
        "as_of": _now(),
        "note": "No longer canonical persistent authority. Cleanup requires separate approval after soak.",
        "destructive_cleanup": False,
        "authority": AUTHORITY,
    }
    atomic_write_json(Path(legacy) / LEGACY_MARK, mark)
    return mark


def decommission_plan(*, old: Path, new: Path, cutover: str | None = None) -> dict[str, Any]:
    return {
        "schema": "STATE_ROOT_DECOMMISSION_PLAN@v1",
        "old_path": str(old),
        "new_path": str(new),
        "backup": str(new),
        "cutover_time": cutover or _now(),
        "rollback_expiry": "retain legacy copy until soak + operator approval",
        "safe_deletion_date": "NOT_BEFORE_SEPARATE_APPROVAL",
        "destructive_cleanup": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
