"""Classify every remaining CIO / advisory filename reference.

CANONICAL_STORAGE_LAYER | LEGACY_COMPAT | STALE_READER | TEST_FIXTURE | DOC_ONLY
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

TARGETS = (
    "cio_investment_product_latest.json",
    "cio_investment_brief.json",
    "cio_investment_briefs.jsonl",
    "advisory_latest.json",
    "advisory_desk_latest.json",
)

CANONICAL_NAMES = {
    "cio_investment_brief.json",
    "cio_investment_briefs.jsonl",
    "advisory_desk_latest.json",
}
STALE_NAMES = {
    "cio_investment_product_latest.json",
    "advisory_latest.json",
}
REGISTRY_FILES = {"canonical_store_registry.py", "filename_drift_audit.py"}


def _classify(path: Path, name: str) -> str:
    rel = str(path).replace("\\", "/")
    if path.suffix in {".md", ".txt", ".rst"} or "/docs/" in rel or rel.startswith("docs/"):
        return "DOC_ONLY"
    if "/tests/" in rel or path.name.startswith("test_"):
        return "TEST_FIXTURE"
    if path.name in REGISTRY_FILES or name in CANONICAL_NAMES:
        if name in STALE_NAMES:
            return "LEGACY_COMPAT"
        return "CANONICAL_STORAGE_LAYER"
    if name in STALE_NAMES:
        if "canonical_store_registry" in rel or "aliases" in rel:
            return "LEGACY_COMPAT"
        return "STALE_READER"
    return "CANONICAL_STORAGE_LAYER"


def audit(*, root: Path | str) -> dict[str, Any]:
    base = Path(root)
    rows = []
    stale_readers = []
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__", "exports", "dist", "data", "logs", "htmlcov", "coverage"}
    for dirpath, dirnames, filenames in os_walk_limited(base, skip_dirs):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith((".py", ".md", ".json", ".ts", ".tsx", ".sh", ".yml", ".yaml")):
                continue
            p = Path(dirpath) / fn
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for name in TARGETS:
                if name not in text:
                    continue
                klass = _classify(p, name)
                rec = {
                    "file": str(p.relative_to(base)) if str(p).startswith(str(base)) else str(p),
                    "filename": name,
                    "class": klass,
                }
                rows.append(rec)
                if klass == "STALE_READER":
                    stale_readers.append(rec)
    return {
        "schema": "FilenameDriftAudit@v1",
        "n": len(rows),
        "stale_readers": stale_readers,
        "stale_reader_n": len(stale_readers),
        "rows": rows[:400],
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def os_walk_limited(base: Path, skip_dirs: set[str]):
    import os
    return os.walk(base)
