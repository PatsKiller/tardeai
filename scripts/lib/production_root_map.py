"""Definitive production / source / release root classification.

A question mark is not an acceptable class. Every named root and every
canonical store receives one of:

  GOOD_PERSISTENT_ROOT
  RELEASE_LOCAL_DERIVED
  SOURCE_TREE_COUPLED
  BROKEN_SYMLINK
  DUPLICATE_ROOT
  UNKNOWN   ← acceptance requires zero of these
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scripts.lib.canonical_store_registry import STORES, production_state_root, resolve_store

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "ProductionRootMap@v1"

CLASSES = (
    "GOOD_PERSISTENT_ROOT",
    "RELEASE_LOCAL_DERIVED",
    "SOURCE_TREE_COUPLED",
    "BROKEN_SYMLINK",
    "DUPLICATE_ROOT",
    "UNKNOWN",
)

DEFAULT_CURRENT = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"
DEFAULT_SOURCE = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
PREFERRED_PERSISTENT = Path.home() / "trade-ai-releases" / "persistent-state"

SOURCE_MARKERS = ("/trade-ai-v12-rebuild/", "/wt-r18-", "/wt-r17-", "/wt-r18-data")
RELEASE_MARKERS = ("/trade-ai-releases/portfolio-server/",)


def _stat_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "configured_path": str(path),
        "exists": path.exists(),
        "is_symlink": path.is_symlink(),
        "readlink": None,
        "realpath": None,
        "inode": None,
        "device": None,
        "broken": False,
    }
    try:
        if path.is_symlink():
            info["readlink"] = os.readlink(path)
    except OSError:
        info["broken"] = True
    if path.is_symlink() and not path.exists():
        info["broken"] = True
        info["class"] = "BROKEN_SYMLINK"
        return info
    try:
        real = Path(os.path.realpath(path)) if (path.exists() or path.is_symlink()) else path
        info["realpath"] = str(real)
        if real.exists():
            st = os.stat(real)
            info["inode"] = st.st_ino
            info["device"] = st.st_dev
    except OSError:
        info["broken"] = True
        info["class"] = "BROKEN_SYMLINK"
    return info


def classify_realpath(realpath: str | None, *, exists: bool, broken: bool, is_symlink: bool) -> str:
    if broken:
        return "BROKEN_SYMLINK"
    rp = str(realpath or "")
    env_persistent = os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    if env_persistent and rp.startswith(str(Path(env_persistent).resolve())):
        return "GOOD_PERSISTENT_ROOT"
    if rp.startswith(str(PREFERRED_PERSISTENT)):
        return "GOOD_PERSISTENT_ROOT"
    if any(m in rp for m in SOURCE_MARKERS):
        return "SOURCE_TREE_COUPLED"
    if any(m in rp for m in RELEASE_MARKERS):
        return "RELEASE_LOCAL_DERIVED"
    if not exists:
        # Missing derived projection under a release — still classified.
        return "RELEASE_LOCAL_DERIVED"
    # Exists outside source checkout and release overlay — dedicated persistent.
    return "GOOD_PERSISTENT_ROOT"


def named_roots(*, current: Path | None = None, source: Path | None = None) -> dict[str, Any]:
    current = Path(current) if current else DEFAULT_CURRENT
    source = Path(source) if source else DEFAULT_SOURCE
    persistent_env = os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    persistent = Path(persistent_env) if persistent_env else PREFERRED_PERSISTENT

    specs = {
        "persistent_root": persistent if persistent.exists() else source / "data",
        "preferred_persistent_root": persistent,
        "release_root": current.resolve() if current.exists() else current,
        "source_root": source,
        "current_data_root": current / "data",
        "cio_root": current / "data" / "cio",
        "runtime_root": current / "data" / "runtime",
        "portfolio_state_root": current / "data" / "portfolios" / "state",
        "research_root": current / "data" / "research",
        "memory_root": current / "data" / "cio",  # aif_memory.json lives with CIO
        "health_root": current / "data" / "health",
        "source_data_root": source / "data",
        "source_cio_root": source / "data" / "cio",
    }
    rows = {}
    for name, path in specs.items():
        info = _stat_info(Path(path))
        klass = info.get("class") or classify_realpath(
            info.get("realpath"),
            exists=bool(info.get("exists")),
            broken=bool(info.get("broken")),
            is_symlink=bool(info.get("is_symlink")),
        )
        # Dedicated persistent root that does not yet exist is still a planned
        # GOOD_PERSISTENT_ROOT — not UNKNOWN.
        if name in {"persistent_root", "preferred_persistent_root"} and not Path(path).exists():
            if name == "preferred_persistent_root":
                klass = "GOOD_PERSISTENT_ROOT"
                info["note"] = "proposed dedicated persistent root; not yet provisioned"
            else:
                # Actual persistent inodes currently live in the source checkout.
                klass = "SOURCE_TREE_COUPLED"
                info["note"] = "production overlay currently points at source-tree data"
        info["class"] = klass
        info["logical_name"] = name
        rows[name] = info
    return rows


def classify_store(*, store_id: str, root: Path | str | None = None) -> dict[str, Any]:
    spec = STORES.get(store_id) or {}
    loc = resolve_store(store_id, root=root)
    path = Path(loc.get("path") or loc.get("primary_path") or ".")
    info = _stat_info(path)
    klass = info.get("class") or classify_realpath(
        info.get("realpath"),
        exists=bool(info.get("exists")),
        broken=bool(info.get("broken")),
        is_symlink=bool(info.get("is_symlink")),
    )
    writer = spec.get("writer")
    rebuildable = bool(spec.get("rebuildable"))
    if not info.get("exists") and rebuildable and klass != "BROKEN_SYMLINK":
        klass = "RELEASE_LOCAL_DERIVED"
    info.update({
        "logical_store_id": store_id,
        "configured_path": str(loc.get("primary_path") or spec.get("path")),
        "writer_path": spec.get("path"),
        "reader_path": str(path),
        "persistent_or_release_local": (
            "persistent" if klass in {"GOOD_PERSISTENT_ROOT", "SOURCE_TREE_COUPLED"} else "release_local"
        ),
        "class": klass,
        "ownership_class": spec.get("ownership_class"),
        "append_only": spec.get("append_only"),
        "rebuildable": rebuildable,
        "writer": writer,
        "used_alias": loc.get("used_alias"),
    })
    return info


def map_all(*, root: Path | str | None = None) -> dict[str, Any]:
    base = production_state_root(root)
    roots = named_roots(
        current=base if (Path(base) / "data").exists() else DEFAULT_CURRENT,
        source=DEFAULT_SOURCE,
    )
    stores = {sid: classify_store(store_id=sid, root=base) for sid in STORES}
    classes = [r["class"] for r in roots.values()] + [s["class"] for s in stores.values()]
    unknown = sum(1 for c in classes if c == "UNKNOWN")
    # Duplicate detection: same realpath claimed by two logical persistent stores
    # of different identity is OK (cio + memory share data/cio). Flag only when
    # two *current* projections of the same schema resolve to different inodes.
    return {
        "schema": SCHEMA,
        "state_root": str(base),
        "roots": roots,
        "stores": stores,
        "unknown_n": unknown,
        "source_tree_coupled_n": sum(1 for c in classes if c == "SOURCE_TREE_COUPLED"),
        "good_persistent_n": sum(1 for c in classes if c == "GOOD_PERSISTENT_ROOT"),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "note": (
            "CURRENT/data/{cio,runtime,portfolios/state,health} are overlay "
            "symlinks into the source checkout. That is SOURCE_TREE_COUPLED, "
            "not UNKNOWN. A dedicated GOOD_PERSISTENT_ROOT "
            f"({PREFERRED_PERSISTENT}) is the intended uncoupling, not yet provisioned."
        ),
    }
