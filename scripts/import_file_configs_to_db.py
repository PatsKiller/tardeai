#!/usr/bin/env python3
"""
import_file_configs_to_db.py — Import YAML/JSON config files into config_documents table.

Usage:
    python import_file_configs_to_db.py --dry-run          # preview only
    python import_file_configs_to_db.py --apply            # actually import
    python import_file_configs_to_db.py --apply --path config/strategies/momentum_scalp.yaml
    python import_file_configs_to_db.py --apply --type strategy_config
"""
import argparse, hashlib, json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Files to import and their config keys
IMPORT_TARGETS = [
    # Strategy configs
    *[{"path": f"config/strategies/{f}", "key": f"strategy:{Path(f).stem}",
       "type": "strategy_config"} for f in [
        "bond_income.yaml", "cash_or_stable.yaml", "core_growth_compounder.yaml",
        "core_index.yaml", "covered_call_income.yaml", "defense_thesis.yaml",
        "dividend_growth_compounder.yaml", "earnings_catalyst.yaml", "gap_and_go.yaml",
        "high_yield_income_bdc.yaml", "income_add.yaml", "international_dividend.yaml",
        "momentum_scalp.yaml", "recovery_watch.yaml", "reit_income.yaml",
        "sector_rotation.yaml", "speculative_growth.yaml", "swing_breakout.yaml",
        "swing_trade.yaml", "tax_loss_harvest.yaml",
        "shared_risk_rules.yaml", "strategy_schema.yaml", "recommendation_schema.yaml",
    ]],
    # Screener config
    {"path": "assets/screeners.yaml", "key": "screeners", "type": "screener_config"},
    # Agent configs
    {"path": "config/agents.yaml", "key": "agents:yaml", "type": "agent_config"},
    {"path": "config/agents.json", "key": "agents:json", "type": "agent_config"},
    {"path": "config/agent_runtime.json", "key": "agent_runtime", "type": "agent_config"},
    {"path": "config/agent_discovery_config.json", "key": "agent_discovery_config", "type": "agent_config"},
    {"path": "config/agents_data_sources.yaml", "key": "agents_data_sources", "type": "agent_config"},
    {"path": "config/agents_sec_interaction.yaml", "key": "agents_sec_interaction", "type": "agent_config"},
    {"path": "agents/openai.yaml", "key": "openai_fallback", "type": "agent_config"},
    # Portfolio/asset configs
    {"path": "assets/portfolio_accounts.yaml", "key": "portfolio_accounts", "type": "portfolio_config"},
    {"path": "assets/portfolio_intent.yaml", "key": "portfolio_intent", "type": "portfolio_config"},
    {"path": "assets/weights.yaml", "key": "asset_weights", "type": "portfolio_config"},
    # Runtime configs
    {"path": "config/indicator_strategies.yaml", "key": "indicator_strategies", "type": "runtime_config"},
    {"path": "config/asset_classification_rules.json", "key": "asset_classification_rules", "type": "runtime_config"},
    {"path": "config/manual_beta_overrides.json", "key": "manual_beta_overrides", "type": "runtime_config"},
    {"path": "config/thesis.json", "key": "thesis", "type": "runtime_config"},
]

# Never import these
SECRET_PATTERNS = ["cookie", "token", "password", "secret", ".env", "credential"]


def main():
    parser = argparse.ArgumentParser(description="Import config files to DB")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--apply", action="store_true", help="Actually import")
    parser.add_argument("--path", help="Import single file by path")
    parser.add_argument("--type", help="Import only files of this type")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Must specify --dry-run or --apply")
        sys.exit(1)

    from config_db_loader import load_yaml_or_json_file, upsert_config_document

    targets = IMPORT_TARGETS
    if args.path:
        targets = [t for t in targets if t["path"] == args.path]
    if args.type:
        targets = [t for t in targets if t["type"] == args.type]

    stats = {"total_seen": 0, "imported": 0, "skipped": 0, "failed": 0,
             "changed": 0, "unchanged": 0}

    for t in targets:
        stats["total_seen"] += 1
        path = t["path"]
        key = t["key"]
        config_type = t["type"]

        # Safety: never import secrets
        if any(s in path.lower() for s in SECRET_PATTERNS):
            print(f"  SKIP (secret): {path}")
            stats["skipped"] += 1
            continue

        full_path = PROJECT_ROOT / path
        if not full_path.exists():
            print(f"  SKIP (missing): {path}")
            stats["skipped"] += 1
            continue

        # Size guard: skip files > 500KB
        if full_path.stat().st_size > 500_000:
            print(f"  SKIP (too large {full_path.stat().st_size}): {path}")
            stats["skipped"] += 1
            continue

        try:
            content = load_yaml_or_json_file(str(full_path))
            if content is None:
                print(f"  SKIP (parse error): {path}")
                stats["skipped"] += 1
                continue
        except Exception as e:
            print(f"  FAIL (parse): {path} — {e}")
            stats["failed"] += 1
            continue

        if args.dry_run:
            shape = "object" if isinstance(content, dict) else "array" if isinstance(content, list) else "scalar"
            print(f"  WOULD IMPORT: {key} ← {path} ({config_type}, {shape})")
            stats["imported"] += 1
        else:
            try:
                result = upsert_config_document(
                    config_key=key, content=content, config_type=config_type,
                    source_path=path, notes=f"Imported from {path}"
                )
                if result == "inserted":
                    stats["imported"] += 1
                    print(f"  INSERTED: {key} ← {path}")
                elif result == "updated":
                    stats["changed"] += 1
                    print(f"  UPDATED: {key} ← {path}")
                else:
                    stats["unchanged"] += 1
                    print(f"  UNCHANGED: {key}")
            except Exception as e:
                print(f"  FAIL (db): {key} — {e}")
                stats["failed"] += 1

    print(f"\n{'='*50}")
    print(f"  Import Summary ({'DRY RUN' if args.dry_run else 'APPLIED'})")
    print(f"  Total seen: {stats['total_seen']}")
    print(f"  Imported:   {stats['imported']}")
    print(f"  Changed:    {stats['changed']}")
    print(f"  Unchanged:  {stats['unchanged']}")
    print(f"  Skipped:    {stats['skipped']}")
    print(f"  Failed:     {stats['failed']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
