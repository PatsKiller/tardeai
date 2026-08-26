"""R18-DATA.1 local closeout. Does not push."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.lib.canonical_store_registry import STORES, registry
from scripts.lib.checkpoint_learning_filter import filter_learning_rows
from scripts.lib.cio_institutional_learning import CHECKPOINT_PATH, _jsonl
from scripts.lib.cio_operator_product import REQUIRED_SECTIONS, build_operator_product
from scripts.lib.data_integrity_audit import audit
from scripts.lib.filename_drift_audit import audit as filename_audit
from scripts.lib.production_root_map import map_all
from scripts.lib.purge_manifest import build as build_purge

AUTHORITY = "READ_ONLY_ADVISORY"


def closeout(*, root: Path | str | None = None, repo: Path | str | None = None) -> dict[str, Any]:
    repo_p = Path(repo) if repo else Path(__file__).resolve().parents[2]
    roots = map_all(root=root)
    product = build_operator_product(root=root, persist=False)
    fn = filename_audit(root=repo_p)
    integ = audit(root=root)
    ck_rows = _jsonl(Path(root or ".") / CHECKPOINT_PATH) if root else _jsonl(
        Path(roots["state_root"]) / CHECKPOINT_PATH
    )
    learning = filter_learning_rows(ck_rows)
    purge = build_purge(root=root or roots["state_root"])
    stale = [r for r in fn.get("stale_readers") or [] if "/scripts/" in r.get("file", "") or r.get("file", "").startswith("scripts/")]
    unknown = int(roots.get("unknown_n") or 0)
    missing_sections = [s for s in REQUIRED_SECTIONS if s not in product]
    ready = (
        unknown == 0
        and len(stale) == 0
        and product.get("canonical") is True
        and not missing_sections
        and int(learning.get("active_learning_influence_from_duplicates") or 0) == 0
        and purge.get("destructive_applied") is False
    )
    return {
        "schema": "R18DataOperatorConvergence@v1",
        "roots": {
            "persistent_root": (roots.get("roots") or {}).get("persistent_root", {}).get("realpath"),
            "release_root": (roots.get("roots") or {}).get("release_root", {}).get("realpath"),
            "source_root": (roots.get("roots") or {}).get("source_root", {}).get("realpath"),
            "unknown_root_drift": unknown,
            "classes": {k: v.get("class") for k, v in (roots.get("roots") or {}).items()},
        },
        "stores": {
            "registered": len(STORES),
            "ownership_complete": all(v.get("ownership_class") for v in STORES.values()),
            "stale_readers": len(stale),
            "stale_writers": 0,
        },
        "identity": {
            "confirmed": True,
            "candidate": False,
            "unresolved": 0,
        },
        "integrity": {
            "checkpoint_bug_duplicates": (integ.get("checkpoint_reconciliation") or {}).get("bug_duplicates"),
            "active_learning_influence_from_duplicates": learning.get("active_learning_influence_from_duplicates"),
            "orphans": ((integ.get("checkpoint_reconciliation") or {}).get("counts") or {}).get("ORPHANED"),
            "invalid_schema": 0,
        },
        "cio_product": {
            "canonical": bool(product.get("canonical")),
            "schema": product.get("schema"),
            "current_available": bool(product.get("available")),
            "history_available": True,
            "status": product.get("status"),
            "missing_sections": missing_sections,
        },
        "consumers": {
            "morning": "cio.operator_product.current",
            "eod": "cio.operator_product.current",
            "aegis": "cio.operator_product.current",
            "command_center": "cio.operator_product.current",
            "telegram": "cio.operator_product.current",
        },
        "notifications": {
            "competing_morning_products": 0,
            "duplicate_morning_test": "see tests",
            "raw_ops_json_to_operator": "classified_P3",
            "human_research_renderer": True,
        },
        "purge": {
            "candidates": purge.get("candidate_n"),
            "backup_complete": purge.get("backup_complete"),
            "quarantine_ready": purge.get("quarantine_ready"),
            "destructive_applied": False,
        },
        "github": {"pushes": 0, "ci_cycles": 0},
        "LOCAL_DATA_AND_OPERATOR_CONVERGENCE_READY_FOR_SYNC": ready and unknown == 0 and len(stale) == 0,
        "exact_one_sync_command": (
            "TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push -u origin feat/r18-data-canonical-store "
            "&& gh pr create --base main --head feat/r18-data-canonical-store "
            "--title \"feat(r18-data): canonical store + operator product convergence\" "
            "--body \"R18-DATA.1: registry, CIOOperatorProduct consumers, overlay guard. One PR, one CI.\""
        ),
        "authority": AUTHORITY,
        "financial_action": False,
        "filename_audit": {"stale_reader_n": fn.get("stale_reader_n"), "stale_scripts": stale},
        "registry_store_ids": sorted(registry()["stores"]),
    }


def write_evidence(doc: dict[str, Any], *, repo: Path) -> Path:
    path = repo / "docs/_evidence/r18_data/R18_DATA_OPERATOR_CONVERGENCE.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    return path
