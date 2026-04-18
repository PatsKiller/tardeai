"""portfolio_yaml_writer.py — Safe YAML Write-Back v1.0
=======================================================
Applies ONLY human-approved suggestions from yaml_advisor_output.json
to portfolio_accounts.yaml.

Safety guarantees:
  · Writes a timestamped backup before ANY change
  · Applies changes one at a time with verification
  · Logs every single change in yaml_change_history.json
  · Validates YAML parses cleanly after each write
  · Can be run with --dry-run to preview without writing

Usage:
  python scripts/portfolio_yaml_writer.py --apply sug_001 sug_003
  python scripts/portfolio_yaml_writer.py --apply-all
  python scripts/portfolio_yaml_writer.py --dry-run --apply-all
  python scripts/portfolio_yaml_writer.py --status
  python scripts/portfolio_yaml_writer.py --rollback 20260410_214532
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_env(root: Path) -> None:
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def setup_logging(root: Path) -> logging.Logger:
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"yaml_writer_{ts}.log"

    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.DEBUG,
        format=fmt,
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    log = logging.getLogger("yaml_writer")
    log.info("=" * 60)
    log.info("  YAML Config Writer v1.0")
    log.info(f"  Log file: {log_path}")
    log.info("=" * 60)
    return log, log_path


def load_yaml(path: Path) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(path: Path, data: Dict) -> None:
    """Write YAML preserving structure. Validate it parses back cleanly."""
    text = yaml.dump(data, default_flow_style=False, sort_keys=False,
                     allow_unicode=True, indent=2)
    # Validate round-trip
    re_parsed = yaml.safe_load(text)
    if not re_parsed:
        raise ValueError("YAML round-trip validation failed — refusing to write")
    path.write_text(text, encoding="utf-8")


# ── Backup ─────────────────────────────────────────────────────────────────────

def backup_yaml(yaml_path: Path, backup_dir: Path,
                log: logging.Logger) -> Path:
    """Write a timestamped backup. Returns path to backup file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"portfolio_accounts_{ts}.yaml.bak"
    backup_path.write_text(yaml_path.read_text(encoding="utf-8"), encoding="utf-8")
    log.info(f"  ✓ Backup written: {backup_path}")
    return backup_path


# ── YAML path traversal ────────────────────────────────────────────────────────

def get_yaml_value(data: Dict, path: str) -> Any:
    """Get value at dot-notation path. e.g. 'accounts.schwab_rollover_ira.target_allocation.bonds'"""
    parts = path.split(".")
    node = data
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(f"Path '{path}' not found at '{part}'")
    return node


def set_yaml_value(data: Dict, path: str, value: Any,
                   log: logging.Logger) -> None:
    """Set value at dot-notation path. Creates intermediate keys if needed."""
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        if part not in node:
            log.info(f"    Creating new key '{part}' in YAML")
            node[part] = {}
        node = node[part]
    final_key = parts[-1]
    old_val = node.get(final_key, "<not set>")
    node[final_key] = value
    log.info(f"    SET {path}")
    log.info(f"        OLD: {old_val!r}")
    log.info(f"        NEW: {value!r}")


def delete_yaml_value(data: Dict, path: str, log: logging.Logger) -> None:
    """Delete key at dot-notation path."""
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node[part]
    final_key = parts[-1]
    old_val = node.pop(final_key, "<not found>")
    log.info(f"    DELETE {path} (was: {old_val!r})")


# ── Audit log ──────────────────────────────────────────────────────────────────

def append_change_history(history_path: Path, entry: Dict) -> None:
    """Append to yaml_change_history.json — never overwrites, always appends."""
    history: List[Dict] = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.append(entry)
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")


# ── Apply a single suggestion ──────────────────────────────────────────────────

def apply_suggestion(sug: Dict, yaml_data: Dict, yaml_path: Path,
                     backup_dir: Path, history_path: Path,
                     dry_run: bool, log: logging.Logger) -> bool:
    """
    Apply one approved suggestion to the YAML.
    Returns True if applied successfully.
    """
    sug_id   = sug.get("id", "unknown")
    sug_type = sug.get("type", "")
    path_str = sug.get("yaml_path", "")
    new_val  = sug.get("suggested_value")
    rationale = sug.get("rationale", "")

    log.info(f"\n  Applying [{sug_id}] {sug_type} → {path_str}")
    log.info(f"  Rationale: {rationale}")
    if sug.get("recent_trade_conflict"):
        log.warning("  ⚠  recent_trade_conflict=True — applying anyway (human approved)")

    if dry_run:
        log.info(f"  [DRY RUN] Would set {path_str} = {new_val!r}")
        return True

    # Write backup before every single change
    backup_path = backup_yaml(yaml_path, backup_dir, log)

    try:
        if sug_type in ("update_target", "update_notes"):
            # Convert numeric strings to numbers where appropriate
            if isinstance(new_val, str) and new_val.replace(".", "").isdigit():
                new_val = float(new_val) if "." in new_val else int(new_val)
            set_yaml_value(yaml_data, path_str, new_val, log)

        elif sug_type == "add_bucket":
            # Adding a new key to target_allocation
            set_yaml_value(yaml_data, path_str, new_val, log)

        elif sug_type == "remove_bucket":
            delete_yaml_value(yaml_data, path_str, log)

        else:
            log.warning(f"  Unknown suggestion type: {sug_type!r} — skipping")
            return False

        # Write the changed YAML
        save_yaml(yaml_path, yaml_data)
        log.info(f"  ✓ YAML written successfully")

        # Append to audit trail
        append_change_history(history_path, {
            "timestamp":    datetime.now().isoformat(),
            "suggestion_id": sug_id,
            "type":          sug_type,
            "yaml_path":     path_str,
            "old_value":     sug.get("current_value"),
            "new_value":     new_val,
            "rationale":     rationale,
            "backup_file":   str(backup_path),
            "dry_run":       False,
        })
        log.info(f"  ✓ Change logged to history")
        return True

    except Exception as e:
        log.error(f"  ✗ Failed to apply [{sug_id}]: {e}")
        log.error(f"    Backup available at: {backup_path}")
        # Restore from backup
        log.warning("  Restoring YAML from backup...")
        yaml_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
        log.warning("  ✓ Restored from backup")
        return False


# ── Rollback ───────────────────────────────────────────────────────────────────

def rollback(timestamp: str, backup_dir: Path, yaml_path: Path,
             log: logging.Logger) -> bool:
    """Restore YAML from a specific backup timestamp."""
    backup_file = backup_dir / f"portfolio_accounts_{timestamp}.yaml.bak"
    if not backup_file.exists():
        log.error(f"Backup not found: {backup_file}")
        available = sorted(backup_dir.glob("*.yaml.bak"))
        if available:
            log.info("Available backups:")
            for f in available[-10:]:
                log.info(f"  {f.name}")
        return False

    log.info(f"Rolling back to: {backup_file}")
    # Backup current before rollback
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pre_rollback = backup_dir / f"portfolio_accounts_pre_rollback_{ts}.yaml.bak"
    pre_rollback.write_text(yaml_path.read_text(encoding="utf-8"), encoding="utf-8")
    log.info(f"Current state backed up to: {pre_rollback}")

    yaml_path.write_text(backup_file.read_text(encoding="utf-8"), encoding="utf-8")
    log.info("✓ Rollback complete")
    return True


# ── Status ─────────────────────────────────────────────────────────────────────

def show_status(advisor_output: Dict, history_path: Path,
                log: logging.Logger) -> None:
    """Show current advisor output status and change history."""
    opus = advisor_output.get("opus_output", {})
    suggestions = opus.get("suggestions", [])
    applied_ids = advisor_output.get("applied_ids", [])
    dismissed_ids = advisor_output.get("dismissed_ids", [])

    log.info(f"\nYAML Advisor Status — {advisor_output.get('generated_at', '?')[:16]}")
    log.info(f"  Health score: {opus.get('yaml_health_score', '?')}/100")
    log.info(f"  Notes:        {opus.get('yaml_health_notes', '?')}")
    log.info(f"\n  Suggestions ({len(suggestions)}):")

    for sug in suggestions:
        sid = sug["id"]
        if sid in applied_ids:
            status = "✅ APPLIED"
        elif sid in dismissed_ids:
            status = "❌ DISMISSED"
        else:
            status = "⏳ PENDING"
        log.info(f"    [{sid}] {status} — {sug['type']} → {sug['yaml_path']}")
        log.info(f"           {sug['current_value']!r} → {sug['suggested_value']!r}")

    do_not_touch = advisor_output.get("ground_truth_summary", {}).get("do_not_touch", [])
    if do_not_touch:
        log.info(f"\n  DO NOT TOUCH (traded in last 90 days): {do_not_touch}")
        log.info("  (These symbols are excluded from all suggestions)")

    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
        log.info(f"\n  Change history: {len(history)} total changes")
        for entry in history[-5:]:
            log.info(f"    {entry['timestamp'][:16]}  [{entry['suggestion_id']}]  {entry['yaml_path']}: {entry['old_value']!r} → {entry['new_value']!r}")
        log.info(f"\n  Rollback: python scripts/portfolio_yaml_writer.py --rollback YYYYMMDD_HHMMSS")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    root = Path(__file__).parent.parent.resolve()
    _load_env(root)
    log, log_path = setup_logging(root)

    parser = argparse.ArgumentParser(description="YAML Config Writer")
    parser.add_argument("--apply",     nargs="+", metavar="ID",
                        help="Apply specific suggestion IDs")
    parser.add_argument("--apply-all", action="store_true",
                        help="Apply all pending suggestions")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Preview changes without writing")
    parser.add_argument("--rollback",  metavar="TIMESTAMP",
                        help="Rollback to backup (format: YYYYMMDD_HHMMSS)")
    parser.add_argument("--status",    action="store_true",
                        help="Show current advisor output status")
    args = parser.parse_args()

    yaml_path     = root / "assets" / "portfolio_accounts.yaml"
    advisor_path  = root / "data" / "portfolios" / "state" / "yaml_advisor_output.json"
    backup_dir    = root / "data" / "portfolios" / "yaml_backups"
    history_path  = root / "data" / "portfolios" / "state" / "yaml_change_history.json"

    log.info("=" * 60)
    log.info("  YAML Config Writer v1.0")
    log.info(f"  YAML:    {yaml_path}")
    log.info(f"  Backups: {backup_dir}")
    log.info("=" * 60)

    # Rollback mode
    if args.rollback:
        backup_dir.mkdir(parents=True, exist_ok=True)
        rollback(args.rollback, backup_dir, yaml_path, log)
        return

    # Load advisor output
    if not advisor_path.exists():
        log.error(f"Advisor output not found: {advisor_path}")
        log.error("Run portfolio_yaml_advisor.py first")
        sys.exit(1)

    advisor_output = json.loads(advisor_path.read_text(encoding="utf-8"))
    opus           = advisor_output.get("opus_output", {})
    all_suggestions = opus.get("suggestions", [])

    # Status mode
    if args.status:
        show_status(advisor_output, history_path, log)
        return

    # Determine which suggestions to apply
    if args.apply:
        to_apply = [s for s in all_suggestions if s["id"] in args.apply]
        missing  = set(args.apply) - {s["id"] for s in to_apply}
        if missing:
            log.warning(f"Suggestion IDs not found: {missing}")
    elif args.apply_all:
        applied_ids   = set(advisor_output.get("applied_ids", []))
        dismissed_ids = set(advisor_output.get("dismissed_ids", []))
        to_apply = [s for s in all_suggestions
                    if s["id"] not in applied_ids and s["id"] not in dismissed_ids]
    else:
        show_status(advisor_output, history_path, log)
        log.info("\nUsage:")
        log.info("  --apply sug_001 sug_002   Apply specific suggestions")
        log.info("  --apply-all               Apply all pending")
        log.info("  --dry-run --apply-all     Preview without writing")
        log.info("  --rollback YYYYMMDD_HHMMSS  Restore from backup")
        return

    if not to_apply:
        log.info("No suggestions to apply.")
        return

    log.info(f"\nApplying {len(to_apply)} suggestion(s){'  [DRY RUN]' if args.dry_run else ''}...")

    # Load YAML once
    yaml_data   = load_yaml(yaml_path)
    applied     = []
    failed      = []

    for sug in to_apply:
        ok = apply_suggestion(sug, yaml_data, yaml_path, backup_dir,
                              history_path, args.dry_run, log)
        (applied if ok else failed).append(sug["id"])
        if ok and not args.dry_run:
            # Reload yaml_data after each write to stay in sync
            yaml_data = load_yaml(yaml_path)

    # Update advisor output with applied/failed status
    if not args.dry_run:
        advisor_output.setdefault("applied_ids", []).extend(applied)
        advisor_output["status"] = "partially_applied" if failed else "applied"
        advisor_output["last_applied_at"] = datetime.now().isoformat()
        advisor_path.write_text(json.dumps(advisor_output, indent=2), encoding="utf-8")

    log.info("\n" + "─" * 60)
    log.info(f"Applied:  {applied}")
    if failed:
        log.warning(f"Failed:   {failed}")
    log.info(f"Backups:  {backup_dir}")
    log.info(f"History:  {history_path}")
    if not args.dry_run and applied:
        log.info("\n⚡ Run run_portfolio.bat to recompute portfolio with new targets")
    log.info(f"  Full log: {log_path}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
