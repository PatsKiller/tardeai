#!/usr/bin/env python3
"""report_docs_inventory.py — Inventory and classify local docs.

Read-only. No moves/deletes. No trading changes.

Usage:
    .venv/bin/python scripts/report_docs_inventory.py --root docs --verbose
"""
import argparse, hashlib, json, os, re, sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

# Active canonical docs that must NEVER be archived/deleted
ACTIVE_KEEP = {
    "docs/A1A.md", "docs/MASTER_SYSTEM_DOCUMENTATION.md", "docs/ARCHITECTURE_OVERVIEW.md",
    "docs/RESTORE_GUIDE.md", "docs/CHEAT_SHEET.md", "docs/v4_1_deployment_log.md",
    "docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md", "docs/CLAUDE_CODE_EXECUTION_PROMPT_LLM_v4_1_FINAL.md",
    "docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md", "docs/project/PROJECT_DOC_INDEX.md",
}
ACTIVE_FOLDERS = {
    "docs/execution_safety/", "docs/recovery/", "docs/maturity_hardening/",
    "docs/project/", "docs/strategy/", "docs/generated/", "docs/design/",
}
ARCHIVE_PATTERNS = [
    r"\.bak", r"bak_", r"_backup", r"superseded", r"_old\b",
    r"V[56789]\.", r"v[2-4]\.\d", r"_pre_", r"_20260[34]",
]
ARTIFACT_EXTS = {".py", ".ts", ".tsx", ".css", ".xlsx", ".mmd", ".txt", ".sh"}
CODE_IN_DOCS = {".py", ".ts", ".tsx", ".css", ".sh"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(relpath, ext, size):
    rp = relpath.lower()

    # Active keep
    if relpath in ACTIVE_KEEP:
        return "active_keep", "canonical active doc", "high"
    for af in ACTIVE_FOLDERS:
        if relpath.startswith(af):
            return "current_phase_keep", f"in active folder {af}", "high"
    if "00_README.md" in relpath:
        return "current_phase_keep", "phase readme", "high"

    # Archive patterns
    for pat in ARCHIVE_PATTERNS:
        if re.search(pat, rp):
            return "archive_superseded", f"matches pattern {pat}", "medium"

    # Already in _archive
    if "_archive/" in rp or "/archive/" in rp:
        return "archive_superseded", "already in archive folder", "high"

    # Code artifacts in docs
    if ext in CODE_IN_DOCS:
        return "artifact_code_snapshot", f"code file ({ext}) in docs", "medium"

    # Artifact extensions
    if ext in ARTIFACT_EXTS and ext not in {".md", ".json", ".yaml", ".yml"}:
        return "artifact_raw_sync", f"non-doc extension {ext}", "low"

    # Old session docs
    if re.search(r"session[_\s]*\d+", rp, re.I):
        return "archive_session_handoff", "session handoff doc", "medium"

    # Legacy blueprints
    if any(x in rp for x in ["blueprint", "marl_blueprint", "classification_rule_engine"]):
        return "archive_legacy_blueprint", "legacy blueprint", "medium"

    # Default: review
    return "review_required", "not classified", "low"


def main():
    p = argparse.ArgumentParser(description="Docs inventory (read-only)")
    p.add_argument("--root", default="docs")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    root = PROJ / args.root
    inventory = []
    hash_groups = {}

    for filepath in sorted(root.rglob("*")):
        if not filepath.is_file():
            continue
        relpath = str(filepath.relative_to(PROJ))
        ext = filepath.suffix.lower()
        size = filepath.stat().st_size
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime).isoformat()
        fhash = sha256(filepath)

        status, reason, confidence = classify(relpath, ext, size)

        entry = {
            "path": relpath, "filename": filepath.name, "ext": ext,
            "size": size, "mtime": mtime, "sha256": fhash,
            "status_guess": status, "reason": reason, "confidence": confidence,
        }
        inventory.append(entry)
        hash_groups.setdefault(fhash, []).append(relpath)

    # Mark duplicates
    for entry in inventory:
        group = hash_groups.get(entry["sha256"], [])
        if len(group) > 1:
            entry["duplicate_count"] = len(group)
            entry["duplicate_group"] = group
            if entry["status_guess"] == "review_required":
                entry["status_guess"] = "delete_candidate_duplicate"
                entry["reason"] = f"byte-identical with {len(group)-1} other file(s)"

    # Summary
    by_status = {}
    for e in inventory:
        by_status[e["status_guess"]] = by_status.get(e["status_guess"], 0) + 1

    summary = {"total": len(inventory), "by_status": by_status,
               "duplicate_groups": sum(1 for g in hash_groups.values() if len(g) > 1)}

    if args.verbose:
        print(f"Docs Inventory: {len(inventory)} files")
        for status, count in sorted(by_status.items()):
            print(f"  {status}: {count}")
        print(f"  Duplicate groups: {summary['duplicate_groups']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps({"summary": summary, "inventory": inventory}, indent=2, default=str))
    if args.output_md:
        md = [f"# Docs Inventory — {len(inventory)} files", "",
              "| Status | Count |", "|--------|-------|"]
        for s, c in sorted(by_status.items()):
            md.append(f"| {s} | {c} |")
        md.append(f"\n## Duplicate groups: {summary['duplicate_groups']}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
