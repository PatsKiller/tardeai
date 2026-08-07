#!/usr/bin/env python3
"""
generate_integrity_manifest.py — Regenerate the file integrity manifest.

Run this as part of the deployment process after all state files are in place.
It scans all known critical state files, computes SHA-256 hashes, and writes
an updated manifest.

Usage:
    python scripts/generate_integrity_manifest.py                     # Regenerate all
    python scripts/generate_integrity_manifest.py --dry-run           # Show what would change
    python scripts/generate_integrity_manifest.py --file finviz_quote_cache  # Single file
    python scripts/generate_integrity_manifest.py --add data/path/to/new_file.json  # Add new file
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "data" / "runtime" / "file_integrity_manifest.json"

# Default critical file definitions — these are the known state files.
# Each entry has: key, canonical_path (relative to PROJECT_ROOT), source_pipeline, max_age_minutes, consumers
DEFAULT_FILES: list[dict[str, Any]] = [
    {
        "key": "finviz_quote_cache",
        "canonical_path": "data/portfolios/state/finviz_quote_cache.json",
        "source_pipeline": "external_market_data_ingest.py",
        "max_age_minutes": 30,
        "consumers": ["portfolio_dashboard", "holdings_cards", "system_health_agent"],
    },
    {
        "key": "trade_ai_cache",
        "canonical_path": "data/runtime/trade_ai_cache.json",
        "source_pipeline": "trade_ai_orchestrator.py",
        "max_age_minutes": 180,
        "consumers": ["portfolio_dashboard", "runtime_awareness", "strategy_signals"],
    },
    {
        "key": "holdings",
        "canonical_path": "data/portfolios/state/holdings.json",
        "source_pipeline": "portfolio_repricer.py",
        "max_age_minutes": 30,
        "consumers": ["portfolio_dashboard", "watch_intelligence", "system_health_agent", "risk_monitor"],
    },
    {
        "key": "ai_analysis_cache",
        "canonical_path": "data/portfolios/state/ai_analysis_cache.json",
        "source_pipeline": "ai_portfolio_analyzer.py",
        "max_age_minutes": 720,
        "consumers": ["portfolio_dashboard", "watch_intelligence"],
    },
    {
        "key": "ai_deep_holdings",
        "canonical_path": "data/portfolios/state/ai_deep_holdings.json",
        "source_pipeline": "ai_deep_holdings_analyzer.py",
        "max_age_minutes": 720,
        "consumers": ["portfolio_dashboard", "hermes_holdings_lifecycle"],
    },
    {
        "key": "ticker_enrichment_cache",
        "canonical_path": "data/portfolios/state/ticker_enrichment_cache.json",
        "source_pipeline": "ticker_enrichment_engine.py",
        "max_age_minutes": 360,
        "consumers": ["watch_intelligence", "symbol_profiles", "screening"],
    },
    {
        "key": "price_cache",
        "canonical_path": "data/portfolios/state/price_cache.json",
        "source_pipeline": "market_quote_ingest.py",
        "max_age_minutes": 30,
        "consumers": ["portfolio_dashboard", "market_quote_projection"],
    },
    {
        "key": "price_ohlc_cache",
        "canonical_path": "data/portfolios/state/price_ohlc_cache.json",
        "source_pipeline": "ohlc_ingest.py",
        "max_age_minutes": 60,
        "consumers": ["portfolio_dashboard", "charts", "technicals"],
    },
    {
        "key": "staleness_escalation_queue",
        "canonical_path": "data/runtime/staleness_escalation_queue.json",
        "source_pipeline": "system_health_agent.py",
        "max_age_minutes": 1440,
        "consumers": ["system_health_agent", "operator_alerts"],
    },
    {
        "key": "trade_ai_health",
        "canonical_path": "data/portfolios/state/trade_ai_health.json",
        "source_pipeline": "trade_ai_health.py",
        "max_age_minutes": 60,
        "consumers": ["system_health_agent", "hermes_health_inspector"],
    },
    {
        "key": "risk_management",
        "canonical_path": "data/portfolios/state/risk_management.json",
        "source_pipeline": "risk_autopilot.py",
        "max_age_minutes": 120,
        "consumers": ["portfolio_dashboard", "risk_monitor", "system_health_agent"],
    },
]


def compute_sha256(file_path: Path) -> str:
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def load_existing_manifest() -> dict[str, Any] | None:
    """Load existing manifest if it exists, preserving metadata."""
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def generate_manifest(
    selected_keys: list[str] | None = None,
    preserve_metadata: bool = True,
) -> dict[str, Any]:
    """
    Generate a new manifest. If selected_keys is provided, only update those keys.
    Otherwise regenerate all default files.
    """
    existing = load_existing_manifest() if preserve_metadata else None
    now_ts = datetime.now(timezone.utc).isoformat()

    manifest: dict[str, Any] = {
        "version": "1",
        "generated": now_ts,
        "description": (
            "File Integrity Manifest — canonical paths, expected hashes, and staleness "
            "thresholds for all critical state files. Regenerate on every deployment via "
            "scripts/generate_integrity_manifest.py."
        ),
        "files": {},
        "critical_basenames": [],
    }

    # Start from existing if preserving
    if existing and existing.get("files"):
        manifest["files"] = existing["files"]

    missing_files: list[tuple[str, str]] = []

    for entry in DEFAULT_FILES:
        key = entry["key"]
        # Skip if we're only updating specific keys
        if selected_keys and key not in selected_keys:
            continue

        file_path = PROJECT_ROOT / entry["canonical_path"]

        if not file_path.exists():
            missing_files.append((key, str(file_path)))
            continue

        sha = compute_sha256(file_path)
        size = file_path.stat().st_size

        # Preserve existing metadata if available (source_pipeline, max_age_minutes, consumers)
        existing_entry = manifest["files"].get(key, {})
        source_pipeline = entry.get("source_pipeline") or existing_entry.get("source_pipeline", "unknown")
        max_age = entry.get("max_age_minutes") or existing_entry.get("max_age_minutes")
        consumers = entry.get("consumers") or existing_entry.get("consumers", [])

        manifest["files"][key] = {
            "canonical_path": entry["canonical_path"],
            "sha256": sha,
            "size": size,
            "last_validated": now_ts,
            "source_pipeline": source_pipeline,
            "max_age_minutes": max_age,
            "consumers": consumers,
        }

    # Build critical_basenames list
    basenames = sorted(set(
        os.path.basename(entry["canonical_path"])
        for entry in manifest["files"].values()
    ))
    manifest["critical_basenames"] = basenames

    if missing_files:
        manifest["_warnings"] = [
            f"File not found on disk: {key} at {path}" for key, path in missing_files
        ]

    return manifest


def add_custom_file(key: str, relative_path: str, source_pipeline: str = "unknown",
                    max_age_minutes: int = 60, consumers: list[str] | None = None) -> dict[str, Any]:
    """Add a custom file entry to the manifest."""
    file_path = PROJECT_ROOT / relative_path
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    existing = load_existing_manifest()
    manifest = existing.copy() if existing else {
        "version": "1",
        "generated": datetime.now(timezone.utc).isoformat(),
        "description": "File Integrity Manifest",
        "files": {},
        "critical_basenames": [],
    }

    now_ts = datetime.now(timezone.utc).isoformat()
    sha = compute_sha256(file_path)
    size = file_path.stat().st_size

    manifest["files"][key] = {
        "canonical_path": relative_path,
        "sha256": sha,
        "size": size,
        "last_validated": now_ts,
        "source_pipeline": source_pipeline,
        "max_age_minutes": max_age_minutes,
        "consumers": consumers or [],
    }
    manifest["generated"] = now_ts

    # Rebuild basenames
    basenames = sorted(set(
        os.path.basename(entry["canonical_path"])
        for entry in manifest["files"].values()
    ))
    manifest["critical_basenames"] = basenames

    return manifest


def print_diff(old_manifest: dict | None, new_manifest: dict):
    """Print a human-readable diff of changes."""
    print("Changes from regeneration:\n")

    if old_manifest is None:
        print("  NEW: Creating fresh manifest with the following files:")
        for key, entry in new_manifest["files"].items():
            print(f"    + {key}: {entry['canonical_path']} (sha256={entry['sha256'][:16]}...)")
        return

    old_files = old_manifest.get("files", {})
    new_files = new_manifest.get("files", {})

    added = set(new_files.keys()) - set(old_files.keys())
    removed = set(old_files.keys()) - set(new_files.keys())
    common = set(new_files.keys()) & set(old_files.keys())

    for key in added:
        entry = new_files[key]
        print(f"  + ADDED: {key} → {entry['canonical_path']} (sha256={entry['sha256'][:16]}...)")

    for key in removed:
        entry = old_files[key]
        print(f"  - REMOVED: {key} was at {entry['canonical_path']}")

    for key in sorted(common):
        new = new_files[key]
        old = old_files[key]
        if new.get("sha256") != old.get("sha256"):
            print(f"  ~ HASH CHANGED: {key}")
            print(f"      old: {old.get('sha256', '?')[:16]}...")
            print(f"      new: {new.get('sha256', '?')[:16]}...")
        if new.get("size") != old.get("size"):
            print(f"  ~ SIZE CHANGED: {key} ({old.get('size')} → {new.get('size')} bytes)")
        if new.get("canonical_path") != old.get("canonical_path"):
            print(f"  ~ PATH CHANGED: {key} ({old.get('canonical_path')} → {new.get('canonical_path')})")

    if not added and not removed and not any(
        new_files[k].get("sha256") != old_files[k].get("sha256") for k in common
    ):
        print("  No changes — manifest up to date.")


def main():
    parser = argparse.ArgumentParser(
        description="Regenerate the file integrity manifest for Trade AI state files"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing")
    parser.add_argument("--file", type=str, action="append", dest="files",
                        help="Only regenerate specific file(s) by key (can repeat)")
    parser.add_argument("--add", type=str, nargs=2, metavar=("KEY", "RELATIVE_PATH"),
                        help="Add a custom file entry (key and relative path)")
    parser.add_argument("--add-source", type=str, default="unknown",
                        help="Source pipeline for --add (default: unknown)")
    parser.add_argument("--add-max-age", type=int, default=60,
                        help="Max age in minutes for --add (default: 60)")
    parser.add_argument("--no-preserve", action="store_true",
                        help="Do not preserve existing metadata — rebuild from defaults")
    args = parser.parse_args()

    # Ensure data/runtime directory exists
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    if args.add:
        key, rel_path = args.add
        try:
            new_manifest = add_custom_file(
                key, rel_path,
                source_pipeline=args.add_source,
                max_age_minutes=args.add_max_age,
            )
            if not args.dry_run:
                MANIFEST_PATH.write_text(
                    json.dumps(new_manifest, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8"
                )
                print(f"✅ Added {key} at {rel_path} to manifest.")
            else:
                print(f"[DRY RUN] Would add {key} at {rel_path} to manifest.")
            return
        except FileNotFoundError as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            sys.exit(1)

    old_manifest = load_existing_manifest()
    new_manifest = generate_manifest(
        selected_keys=args.files,
        preserve_metadata=not args.no_preserve,
    )

    if args.dry_run:
        print_diff(old_manifest, new_manifest)
        if new_manifest.get("_warnings"):
            for w in new_manifest["_warnings"]:
                print(f"  ⚠️ {w}")
        return

    # Write
    if "_warnings" in new_manifest:
        del new_manifest["_warnings"]

    MANIFEST_PATH.write_text(
        json.dumps(new_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )
    print(f"✅ Integrity manifest written to {MANIFEST_PATH}")
    print(f"   {len(new_manifest['files'])} files tracked")
    print(f"   Version: {new_manifest['version']}")
    print(f"   Generated: {new_manifest['generated']}")


if __name__ == "__main__":
    main()
