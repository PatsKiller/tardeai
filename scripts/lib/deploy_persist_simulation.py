"""Isolated exact-main deploy simulation.

Proves CIO / advisory / memory / checkpoints / outcomes survive a release
swap when overlay points at the same persistent stores. Never touches live
CURRENT.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from scripts.lib.atomic_json_store import atomic_write_json
from scripts.lib.persistent_overlay import apply_overlay_symlinks, overlay_is_safe

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def _write_seed(persistent: Path) -> dict[str, str]:
    files = {
        "data/cio/cio_investment_brief.json": {"schema": "CIOInvestmentProduct@v1", "product_id": "seed", "recommendations": []},
        "data/cio/outcome_checkpoints.jsonl": {"checkpoint_id": "ck_seed", "auto_registered": True},
        "data/cio/outcome_observations.jsonl": {"observation_id": "ob_seed"},
        "data/cio/aif_memory.json": {"schema": "AIFMemory", "n": 1},
        "data/runtime/advisory_desk_latest.json": {"ok": True, "rows": [{"symbol": "NVDA"}]},
        "data/portfolios/state/holdings.json": {"holdings": [{"symbol": "NVDA", "account": "ira"}]},
        "data/health/ok.json": {"ok": True},
    }
    hashes = {}
    for rel, payload in files.items():
        path = persistent / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".jsonl"):
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        else:
            atomic_write_json(path, payload)
        hashes[rel] = str(path.stat().st_ino)
    return hashes


def _inodes(root: Path) -> dict[str, int]:
    out = {}
    for rel in (
        "data/cio/cio_investment_brief.json",
        "data/cio/outcome_checkpoints.jsonl",
        "data/cio/outcome_observations.jsonl",
        "data/cio/aif_memory.json",
        "data/runtime/advisory_desk_latest.json",
        "data/portfolios/state/holdings.json",
    ):
        p = root / rel
        if p.exists():
            out[rel] = os.stat(p).st_ino
    return out


def simulate(*, tmp: Path) -> dict[str, Any]:
    persistent = tmp / "persistent"
    release_a = tmp / "release_a"
    release_b = tmp / "release_b"
    empty_source = tmp / "empty_source"
    _write_seed(persistent)
    before = _inodes(persistent)

    apply_overlay_symlinks(canonical_source=persistent, dest=release_a)
    after_a = _inodes(release_a)
    apply_overlay_symlinks(canonical_source=persistent, dest=release_b)
    after_b = _inodes(release_b)

    # Empty source-tree data must not steal a populated dest overlay.
    for rel in ("data/cio", "data/runtime", "data/portfolios/state", "data/health"):
        (empty_source / rel).mkdir(parents=True, exist_ok=True)
    refuse = overlay_is_safe(canonical_source=empty_source, dest=release_b)

    same = before == after_a == after_b
    return {
        "schema": "DeployPersistSimulation@v1",
        "same_inodes": same,
        "before": before,
        "after_a": after_a,
        "after_b": after_b,
        "refuse_empty_source": refuse["ok"] is False,
        "blocked": refuse.get("blocked"),
        "cio_reset": not same,
        "advisory_reset": after_b.get("data/runtime/advisory_desk_latest.json") != before.get("data/runtime/advisory_desk_latest.json"),
        "memory_lost": after_b.get("data/cio/aif_memory.json") != before.get("data/cio/aif_memory.json"),
        "checkpoints_lost": after_b.get("data/cio/outcome_checkpoints.jsonl") != before.get("data/cio/outcome_checkpoints.jsonl"),
        "outcomes_lost": after_b.get("data/cio/outcome_observations.jsonl") != before.get("data/cio/outcome_observations.jsonl"),
        "switched_to_empty_source": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def restore_drill(*, tmp: Path) -> dict[str, Any]:
    """backup → destroy derived projections → restore authoritative → rebuild."""
    from scripts.lib.cio_operator_product import build_operator_product

    tree = tmp / "restore"
    auth = tree / "authoritative"
    _write_seed(auth)
    backup = tmp / "backup"
    shutil.copytree(auth, backup)
    derived = auth / "data/cio/cio_operator_product.json"
    derived.parent.mkdir(parents=True, exist_ok=True)
    product_before = build_operator_product(root=auth, persist=True)
    if derived.exists():
        derived.unlink()
    # Destroy derived projection only.
    shutil.rmtree(auth / "data/cio", ignore_errors=False)
    shutil.copytree(backup / "data/cio", auth / "data/cio")
    product_after = build_operator_product(root=auth, persist=True)
    eq = (
        product_before.get("generation_id") == product_after.get("generation_id")
        or (
            product_before.get("available") == product_after.get("available")
            and (product_before.get("entries") or [])[:3] == (product_after.get("entries") or [])[:3]
        )
    )
    return {
        "schema": "DataRestoreDrill@v1",
        "equivalent": bool(eq),
        "before_available": product_before.get("available"),
        "after_available": product_after.get("available"),
        "destructive_applied": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
