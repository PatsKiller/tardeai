#!/usr/bin/env python3
"""strategy_config_loader.py — Load, validate, and sync strategy YAML configs.

Usage:
    .venv/bin/python scripts/strategy_config_loader.py --validate
    .venv/bin/python scripts/strategy_config_loader.py --sync-db
    .venv/bin/python scripts/strategy_config_loader.py --strategy momentum_scalp --print-prompt-context
"""
import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "config" / "strategies"
SCHEMA_PATH = STRATEGIES_DIR / "strategy_schema.yaml"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("strategy_config_loader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

SKIP_FILES = {"strategy_schema.yaml", "shared_risk_rules.yaml", "recommendation_schema.yaml"}

REQUIRED_FIELDS = [
    "strategy_id", "display_name", "version", "status", "purpose",
    "eligible_accounts", "timeframe", "timeframe_class",
]


def compute_strategy_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_strategy_config(strategy_id: str) -> dict:
    path = STRATEGIES_DIR / f"{strategy_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Strategy YAML not found: {path}")
    with open(path) as f:
        config = yaml.safe_load(f)
    config["_file_path"] = str(path)
    config["_config_hash"] = compute_strategy_hash(path)
    return config


def load_all_strategy_configs() -> dict:
    configs = {}
    for path in sorted(STRATEGIES_DIR.glob("*.yaml")):
        if path.name in SKIP_FILES:
            continue
        try:
            with open(path) as f:
                config = yaml.safe_load(f)
            if not config or not config.get("strategy_id"):
                continue
            config["_file_path"] = str(path)
            config["_config_hash"] = compute_strategy_hash(path)
            configs[config["strategy_id"]] = config
        except Exception as e:
            log.warning(f"Failed to load {path.name}: {e}")
    return configs


def get_shared_risk_rules() -> dict:
    path = STRATEGIES_DIR / "shared_risk_rules.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def validate_strategy_config(config: dict) -> list:
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in config:
            errors.append(f"Missing required field: {field}")
    sid = config.get("strategy_id", "?")
    if config.get("timeframe_class") not in (
        "INTRADAY", "SHORT_SWING", "MEDIUM_SWING", "POSITION", "CASH", None
    ):
        errors.append(f"{sid}: invalid timeframe_class: {config.get('timeframe_class')}")
    if config.get("status") not in (
        "UNVALIDATED", "TESTING", "VALIDATED", "PAUSED", "KILLED", None
    ):
        errors.append(f"{sid}: invalid status: {config.get('status')}")
    exec_cfg = config.get("execution", {})
    if exec_cfg.get("live_allowed"):
        errors.append(f"{sid}: live_allowed must be false")
    return errors


def get_strategy_prompt_context(strategy_id: str, proposal: dict = None) -> str:
    try:
        config = load_strategy_config(strategy_id)
    except FileNotFoundError:
        return f"Strategy {strategy_id}: No YAML configuration found."

    pc = config.get("prompt_context", {})
    summary = pc.get("summary", config.get("purpose", ""))
    questions = pc.get("key_questions", [])

    risk = config.get("risk", {})
    lifecycle = config.get("lifecycle", {})
    co = config.get("co_enables", {})
    entry = config.get("entry_criteria", [])
    disq = config.get("auto_disqualifiers", [])
    agent = config.get("agent_responsibilities", {})

    entry_text = "\n".join(f"  - {c.get('id', '?')}: {c.get('description', '')}"
                           for c in (entry if isinstance(entry, list) else []))
    disq_text = "\n".join(f"  - {d.get('id', '?')}: {d.get('description', d.get('condition', ''))}"
                          for d in (disq if isinstance(disq, list) else []))
    q_text = "\n".join(f"  - {q}" for q in questions)

    lines = [
        f"STRATEGY RULES ({strategy_id} v{config.get('version', '?')}):",
        f"Purpose: {summary}",
        f"Timeframe: {config.get('timeframe')} ({config.get('timeframe_class')})",
        f"Accounts: {config.get('eligible_accounts')}",
        f"Risk/trade: {risk.get('risk_per_trade_pct', '?')} of portfolio",
        f"Max position: ${risk.get('max_position_size', '?')}",
        f"Target R:R: {risk.get('target_rr', '?')}",
        f"Expiry: {lifecycle.get('proposal_expiry_hours', '?')}h, overnight={lifecycle.get('overnight_allowed', '?')}",
        f"Entry criteria:\n{entry_text}" if entry_text else "Entry criteria: see YAML",
        f"Auto-disqualifiers:\n{disq_text}" if disq_text else "Auto-disqualifiers: see YAML",
        f"Co-enables: promotes_to={co.get('promotes_to', [])}, strengthens={co.get('strengthens', [])}",
        f"Key questions:\n{q_text}" if q_text else "",
    ]

    if proposal:
        lines.append(f"\nProposal context: {proposal.get('symbol', '?')} entry=${proposal.get('proposed_entry', '?')} "
                     f"stop=${proposal.get('proposed_stop', '?')} target=${proposal.get('proposed_target1', '?')}")

    return "\n".join(l for l in lines if l)


def sync_to_db():
    from session13_db import get_conn
    conn = get_conn()
    cur = conn.cursor()
    configs = load_all_strategy_configs()
    synced = 0

    for sid, config in configs.items():
        config_hash = config["_config_hash"]
        file_path = config["_file_path"]
        version = config.get("version", "1.0.0")
        status = config.get("status", "UNVALIDATED")

        # Upsert into strategy_config_versions
        cur.execute("""
            INSERT INTO strategy_config_versions
                (strategy_id, version, config_hash, file_path, status, config_snapshot)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (strategy_id, config_hash) DO UPDATE
            SET version=EXCLUDED.version, status=EXCLUDED.status,
                config_snapshot=EXCLUDED.config_snapshot, loaded_at=NOW()
        """, [sid, version, config_hash, file_path, status,
              json.dumps(config, default=str)])

        # Upsert strategy_registry (INSERT if missing, UPDATE if exists).
        # strategy_id must always be set (convention: strategy_id == strategy_type) — omitting it
        # here created NULL-strategy_id rows the weekly review rendered as "None (UNVALIDATED)".
        display = config.get("name", sid.replace("_", " ").title())
        cur.execute("""
            INSERT INTO strategy_registry (strategy_type, strategy_id, display_name, config_hash, yaml_version, active, last_yaml_sync_at)
            VALUES (%s, %s, %s, %s, %s, TRUE, NOW())
            ON CONFLICT (strategy_type) DO UPDATE
            SET config_hash=EXCLUDED.config_hash, yaml_version=EXCLUDED.yaml_version,
                strategy_id=COALESCE(strategy_registry.strategy_id, EXCLUDED.strategy_id),
                last_yaml_sync_at=NOW()
        """, [sid, sid, display, config_hash, version])

        # Cache prompt context
        prompt_ctx = get_strategy_prompt_context(sid)
        cur.execute("""
            INSERT INTO strategy_prompt_context_cache (strategy_id, config_hash, prompt_context)
            VALUES (%s, %s, %s)
            ON CONFLICT (strategy_id, config_hash) DO UPDATE
            SET prompt_context=EXCLUDED.prompt_context, created_at=NOW()
        """, [sid, config_hash, prompt_ctx])

        synced += 1
        log.info(f"  Synced {sid} v{version} hash={config_hash}")

    conn.commit()
    conn.close()
    return synced


def main():
    parser = argparse.ArgumentParser(description="Strategy config loader")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--sync-db", action="store_true")
    parser.add_argument("--strategy", type=str)
    parser.add_argument("--print-prompt-context", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.validate:
        configs = load_all_strategy_configs()
        all_errors = []
        for sid, config in configs.items():
            errors = validate_strategy_config(config)
            if errors:
                all_errors.extend(errors)
                for e in errors:
                    print(f"  [FAIL] {e}")
            else:
                print(f"  [OK] {sid} v{config.get('version')}")
        if all_errors:
            print(f"\nValidation FAILED: {len(all_errors)} errors")
            sys.exit(1)
        else:
            print(f"\nAll {len(configs)} strategies validated OK")

    elif args.sync_db:
        count = sync_to_db()
        print(f"Synced {count} strategies to DB")

    elif args.strategy and args.print_prompt_context:
        ctx = get_strategy_prompt_context(args.strategy)
        print(ctx)

    elif args.list:
        configs = load_all_strategy_configs()
        for sid, c in sorted(configs.items()):
            print(f"  {sid:32} v{c.get('version','?'):8} {c.get('timeframe_class','?'):15} {c.get('status','?')}")

    else:
        print("Usage: --validate | --sync-db | --strategy <id> --print-prompt-context | --list")


if __name__ == "__main__":
    main()
