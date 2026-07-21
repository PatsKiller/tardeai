#!/usr/bin/env python3
"""
atm_config_manager.py — Load, validate, save ATM config with versioned backups.

No hardcoded broker or account names. All account validation against DB registry.
"""
import hashlib, json, os, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "atm_config.yaml"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    from db_adapter import _get_conn as _gc
    return _gc()


def _hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]


def load_config() -> tuple[dict, str]:
    """Load and validate config YAML. Returns (config_dict, sha256_hash)."""
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    # Validate account labels exist in DB
    conn = _get_conn()
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT account_label FROM accounts")
        valid = {r[0] for r in cur.fetchall()}
        for label in (cfg.get("accounts") or {}):
            if label not in valid:
                raise ValueError(f"Account '{label}' in config not found in accounts table. Valid: {valid}")

    return cfg, _hash(cfg)


def save_config(new_config: dict, changed_by: str) -> str:
    """Validate, backup, save config. Returns new hash."""
    # Load old config for diff
    old_config, old_hash = load_config()

    # Validate new config structure
    if "defaults" not in new_config:
        raise ValueError("Config must have 'defaults' section")

    # Validate account labels
    conn = _get_conn()
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT account_label FROM accounts")
        valid = {r[0] for r in cur.fetchall()}
        for label in (new_config.get("accounts") or {}):
            if label not in valid:
                raise ValueError(f"Account '{label}' not in accounts table")

    new_hash = _hash(new_config)

    # Write timestamped backup
    backup_dir = PROJECT_ROOT / (new_config.get("global", {}).get("config_backup_dir", "config/.atm_config_backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup_path = backup_dir / f"atm_config_{ts}.yaml"
    shutil.copy2(CONFIG_PATH, backup_path)

    # Write new config
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(new_config, f, default_flow_style=False, sort_keys=False)

    # Compute diff
    diff = {"changed": {}}
    for key in set(list(old_config.keys()) + list(new_config.keys())):
        old_v = old_config.get(key)
        new_v = new_config.get(key)
        if old_v != new_v:
            diff["changed"][key] = {"old": str(old_v)[:200], "new": str(new_v)[:200]}

    # Log to DB
    if conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO atm_config_history (changed_by, old_config, new_config,
                                            old_hash, new_hash, change_diff, backup_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (changed_by, json.dumps(old_config, default=str), json.dumps(new_config, default=str),
              old_hash, new_hash, json.dumps(diff), str(backup_path)))
        cur.execute("UPDATE atm_state SET config_hash = %s WHERE id = 1", (new_hash,))
        conn.commit()

    return new_hash


def get_effective_limits(account_label: str) -> dict:
    """Merge defaults with per-account overrides."""
    cfg, _ = load_config()
    defaults = cfg.get("defaults", {}).get("position_limits", {})
    acct = (cfg.get("accounts") or {}).get(account_label, {})
    overrides = acct.get("position_limits", {})
    return {**defaults, **overrides}


def get_enabled_accounts() -> list[str]:
    """Return ATM-eligible account keys.

    R1: prefer broker_accounts + account_automation_policies (source of truth for
    which accounts may auto-run). YAML accounts.*enabled remains a DEPRECATED
    intersection filter when present (legacy), not the sole list.
    """
    cfg, _ = load_config()
    yaml_accounts = cfg.get("accounts") or {}
    yaml_enabled = {k for k, v in yaml_accounts.items()
                    if isinstance(v, dict) and v.get("enabled")}

    conn = _get_conn()
    if not conn:
        return sorted(yaml_enabled)
    cur = conn.cursor()
    # Canonical: paper + AUTO_PAPER (or AUTO_LIVE later) and is_enabled
    try:
        cur.execute("""
            SELECT ba.account_key
              FROM broker_accounts ba
              JOIN account_automation_policies aap ON aap.account_id = ba.id
             WHERE COALESCE(ba.is_enabled, false) = true
               AND aap.automation_mode IN ('AUTO_PAPER', 'AUTO_LIVE')
        """)
        db_auto = {r[0] for r in cur.fetchall()}
    except Exception:
        db_auto = set()

    if db_auto:
        # If yaml still lists accounts, intersect (yaml is deprecated filter only)
        if yaml_enabled:
            return sorted(db_auto & yaml_enabled) or sorted(db_auto)
        return sorted(db_auto)

    # Fallback: legacy accounts.enabled ∩ yaml
    cur.execute("SELECT account_label FROM accounts WHERE enabled = true")
    db_enabled = {r[0] for r in cur.fetchall()}
    return sorted(yaml_enabled & db_enabled)


def is_bucket2_excluded(strategy_id: str, now: datetime = None) -> bool:
    """True if B-1 tracking excludes this strategy from ATM."""
    cfg, _ = load_config()
    b1 = cfg.get("b1_tracking", {})
    if not b1.get("enabled"):
        return False
    if not b1.get("exclude_bucket2_during_observation"):
        return False
    end = b1.get("observation_end")
    if end:
        from datetime import date
        end_date = date.fromisoformat(str(end)) if isinstance(end, str) else end
        if (now or datetime.now(timezone.utc)).date() >= end_date:
            return False
    return strategy_id in (b1.get("bucket2_strategies") or [])


def is_same_day_skip(strategy_id: str) -> bool:
    """True if strategy is in the same-day skip list."""
    cfg, _ = load_config()
    return strategy_id in (cfg.get("same_day_skip_strategies") or [])


def get_strategy_filter() -> dict:
    """Return strategy filter config (min_classifier_health, whitelist, blacklist)."""
    cfg, _ = load_config()
    return cfg.get("defaults", {}).get("strategy_filter", {})


def get_operating_hours() -> dict:
    """Return operating hours config."""
    cfg, _ = load_config()
    return cfg.get("defaults", {}).get("operating_hours", {})


def get_kill_switch_thresholds() -> dict:
    """Return kill switch thresholds."""
    cfg, _ = load_config()
    per_account = cfg.get("defaults", {}).get("kill_switches", {}).get("daily_loss_pct_hard_pause", 10.0)
    aggregate = cfg.get("global", {}).get("daily_loss_pct_hard_pause_aggregate", 10.0)
    return {"per_account": per_account, "aggregate": aggregate}
