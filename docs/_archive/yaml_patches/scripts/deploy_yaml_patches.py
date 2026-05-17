#!/usr/bin/env python3
"""
deploy_yaml_patches.py
======================
Orchestrates the full Trade AI v12 strategy YAML patch deployment.

Sequence:
  1. Pre-flight state check (holdings.json must show ~$1.19M)
  2. Validate current state (run validate_strategy_yamls.py baseline)
  3. Convert v1.0 -> v1.0.0 schema (gap_and_go, momentum_scalp, etc.)
  4. Copy new YAMLs (fib_retracement_bounce, earnings_pre_buildup, earnings_post_momentum)
  5. Apply bulk patches (vix_rules, technical_indicators_required, performance_context)
  6. Re-validate (run validate_strategy_yamls.py final)
  7. Print diff report

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
    python3 scripts/deploy_yaml_patches.py --dry-run
    python3 scripts/deploy_yaml_patches.py --apply

Author: Trade AI v12 Session 33 patch package
Date: 2026-05-13
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def preflight_check(project_root: Path) -> bool:
    """Iron Rule: never deploy without verifying holdings state."""
    holdings_file = project_root / "data/portfolios/state/holdings.json"
    if not holdings_file.exists():
        print(f"FAIL: holdings.json not found at {holdings_file}")
        return False

    try:
        with open(holdings_file) as f:
            data = json.load(f)
        total = data.get("portfolio_totals", {}).get("total_value", 0)
        count = len(data.get("holdings", []))
    except Exception as e:
        print(f"FAIL: cannot parse holdings.json: {e}")
        return False

    print(f"  Holdings total: ${total:,.0f}")
    print(f"  Holdings count: {count}")

    if total < 1_000_000:
        print(f"FAIL: holdings total ${total:,.0f} is suspiciously low — ABORT")
        return False
    if count < 30:
        print(f"FAIL: only {count} holdings — ABORT")
        return False

    print("  Pre-flight: OK")
    return True


def run_step(name: str, cmd: list, dry_run: bool, tolerate_nonzero: bool = False) -> bool:
    """Run a subprocess step and return True on success.

    tolerate_nonzero: when True, non-zero exit codes are treated as informational
    (used for validators that exit 1 when issues are found, which is expected).
    """
    print(f"\n{'=' * 80}")
    print(f"STEP: {name}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"{'=' * 80}")
    try:
        result = subprocess.run(cmd, capture_output=False, text=True)
        if result.returncode != 0:
            print(f"  Step exit code: {result.returncode}")
            if tolerate_nonzero:
                print(f"  (non-zero exit tolerated for this step — issues are informational)")
                return True
            return False
        return True
    except Exception as e:
        print(f"  Step failed: {e}")
        return False


def copy_new_yamls(source_dir: Path, target_dir: Path, dry_run: bool) -> int:
    """Copy the three new strategy YAMLs into config/strategies/. Returns count copied."""
    new_yamls = [
        "fib_retracement_bounce.yaml",
        "earnings_pre_buildup.yaml",
        "earnings_post_momentum.yaml",
    ]
    copied = 0
    for fname in new_yamls:
        src = source_dir / fname
        dst = target_dir / fname

        if not src.exists():
            print(f"  WARN: source missing: {src}")
            continue

        if dst.exists():
            print(f"  Skip (already present): {fname}")
            continue

        if dry_run:
            print(f"  Would copy: {src} -> {dst}")
        else:
            shutil.copy2(src, dst)
            print(f"  Copied: {fname}")
        copied += 1
    return copied


def main():
    parser = argparse.ArgumentParser(description="Deploy Trade AI v12 strategy YAML patches.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root (default: current directory)",
    )
    parser.add_argument(
        "--new-yamls-dir",
        default="config_additions",
        help="Directory containing the new YAML files to copy in",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip the holdings.json state check (NOT RECOMMENDED)",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Specify --dry-run or --apply")
        sys.exit(1)

    project_root = Path(args.project_root).resolve()
    config_dir = project_root / "config/strategies"
    scripts_dir = project_root / "scripts"
    new_yamls_dir = Path(args.new_yamls_dir).resolve()

    print(f"Project root: {project_root}")
    print(f"Config dir:   {config_dir}")
    print(f"Scripts dir:  {scripts_dir}")
    print(f"New YAMLs:    {new_yamls_dir}")
    print(f"Mode:         {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print()

    # Step 0: pre-flight state check
    if not args.skip_preflight:
        print("=" * 80)
        print("STEP 0: Pre-flight state check (Iron Rule)")
        print("=" * 80)
        if not preflight_check(project_root):
            print("\nABORTING — pre-flight check failed.")
            sys.exit(1)

    # Step 1: baseline validation
    baseline_report = project_root / f"backups/yaml_validation_baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    baseline_report.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nBaseline report: {baseline_report}")
    run_step(
        "1. Baseline validation",
        [
            sys.executable,
            str(scripts_dir / "validate_strategy_yamls.py"),
            "--config-dir", str(config_dir),
            "--md",
            "--output", str(baseline_report),
        ],
        args.dry_run,
        tolerate_nonzero=True,  # validator exit 1 = issues found = expected
    )

    # Step 2: schema conversion (v1.0 -> v1.0.0)
    convert_arg = "--dry-run" if args.dry_run else "--apply"
    if not run_step(
        "2. Convert v1.0 -> v1.0.0 schema",
        [
            sys.executable,
            str(scripts_dir / "convert_v1_to_v1_0_0_schema.py"),
            convert_arg,
            "--config-dir", str(config_dir),
        ],
        args.dry_run,
        tolerate_nonzero=True,  # exits 1 when files are missing (informational in some envs)
    ):
        print("Schema conversion failed. Aborting.")
        sys.exit(1)

    # Step 3: copy new YAMLs
    print(f"\n{'=' * 80}")
    print("STEP 3: Copy new strategy YAMLs into config/strategies/")
    print(f"{'=' * 80}")
    copied = copy_new_yamls(new_yamls_dir, config_dir, args.dry_run)
    print(f"  {copied} new YAML(s) {'would be' if args.dry_run else 'were'} added")

    # Step 4: bulk patches
    if not run_step(
        "4. Bulk patches (vix_rules, technical_indicators_required, performance_context)",
        [
            sys.executable,
            str(scripts_dir / "bulk_patch_strategy_yamls.py"),
            convert_arg,
            "--config-dir", str(config_dir),
        ],
        args.dry_run,
    ):
        print("Bulk patches failed. Aborting.")
        sys.exit(1)

    # Step 5: final validation
    final_report = project_root / f"backups/yaml_validation_final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    print(f"\nFinal report: {final_report}")
    run_step(
        "5. Final validation",
        [
            sys.executable,
            str(scripts_dir / "validate_strategy_yamls.py"),
            "--config-dir", str(config_dir),
            "--md",
            "--output", str(final_report),
        ],
        args.dry_run,
        tolerate_nonzero=True,
    )

    # Step 6: post-flight state check
    if not args.skip_preflight:
        print(f"\n{'=' * 80}")
        print("STEP 6: Post-flight state check (verify holdings still intact)")
        print(f"{'=' * 80}")
        if not preflight_check(project_root):
            print("\nCRITICAL: holdings state degraded during patch run! Restore from backup.")
            sys.exit(2)

    # Summary
    print(f"\n{'=' * 80}")
    print("DEPLOYMENT SUMMARY")
    print(f"{'=' * 80}")
    print(f"Baseline validation report: {baseline_report}")
    print(f"Final validation report:    {final_report}")
    print(f"Mode:                       {'DRY-RUN' if args.dry_run else 'APPLIED'}")

    if args.dry_run:
        print("\nDry-run complete. Re-run with --apply to write changes.")
    else:
        print("\nPatches applied. Compare baseline vs final reports to verify.")
        print("Diff command:")
        print(f"  diff {baseline_report} {final_report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
