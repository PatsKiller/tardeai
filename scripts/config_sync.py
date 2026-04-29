#!/usr/bin/env python3
"""config_sync.py — Sync YAML configs into DB tables.

Loads agents_data_sources.yaml, agents_sec_interaction.yaml, screeners.yaml
and upserts them into DB tables for runtime access by agents.

Usage:
    python3 scripts/config_sync.py --dry-run   # Show what would change
    python3 scripts/config_sync.py --sync       # Apply to DB
    python3 scripts/config_sync.py --status     # Show current DB state
"""
import json, sys, yaml
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _ensure_tables(conn):
    """Create sync tables if they don't exist."""
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_data_source_rules (
            id BIGSERIAL PRIMARY KEY,
            agent TEXT NOT NULL,
            source_type TEXT NOT NULL,
            config JSONB NOT NULL DEFAULT '{}',
            auto_inject BOOLEAN DEFAULT TRUE,
            triggers JSONB DEFAULT '[]',
            changed_by TEXT DEFAULT 'config_sync',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(agent, source_type)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_sec_rules (
            id BIGSERIAL PRIMARY KEY,
            agent TEXT NOT NULL,
            sec_type TEXT NOT NULL,
            trigger_name TEXT NOT NULL,
            condition TEXT,
            severity TEXT DEFAULT 'medium',
            action TEXT,
            changed_by TEXT DEFAULT 'config_sync',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(agent, sec_type, trigger_name)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_intelligence_rules (
            id BIGSERIAL PRIMARY KEY,
            rule_type TEXT NOT NULL,
            rule_key TEXT NOT NULL,
            config JSONB NOT NULL DEFAULT '{}',
            changed_by TEXT DEFAULT 'config_sync',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(rule_type, rule_key)
        )
    """)

    conn.commit()
    print("[sync] Tables ensured: agent_data_source_rules, agent_sec_rules, agent_intelligence_rules")


def _load_yaml(filename: str) -> dict:
    for base in [PROJECT_ROOT / "config", PROJECT_ROOT / "assets"]:
        p = base / filename
        if p.exists():
            return yaml.safe_load(p.read_text()) or {}
    print(f"  WARNING: {filename} not found in config/ or assets/")
    return {}


def sync_data_sources(conn, dry_run: bool = False) -> int:
    """Sync agents_data_sources.yaml → agent_data_source_rules."""
    data = _load_yaml("agents_data_sources.yaml")
    agents = data.get("agents", {})
    data_sources = data.get("data_sources", {})
    count = 0

    for agent_name, agent_cfg in agents.items():
        auto_inject = agent_cfg.get("auto_inject", True)
        triggers = agent_cfg.get("triggers", [])
        sources = agent_cfg.get("sources", [])

        for source_entry in sources:
            if isinstance(source_entry, dict):
                for src_type, desc in source_entry.items():
                    if dry_run:
                        print(f"  [dry-run] UPSERT agent_data_source_rules: {agent_name}/{src_type}")
                    else:
                        cur = conn.cursor()
                        cur.execute("""
                            INSERT INTO agent_data_source_rules (agent, source_type, config, auto_inject, triggers, changed_by, updated_at)
                            VALUES (%s, %s, %s, %s, %s, 'config_sync', NOW())
                            ON CONFLICT (agent, source_type) DO UPDATE SET
                                config = EXCLUDED.config, auto_inject = EXCLUDED.auto_inject,
                                triggers = EXCLUDED.triggers, changed_by = 'config_sync', updated_at = NOW()
                        """, (agent_name, src_type,
                              json.dumps({"description": desc, "global": data_sources.get(src_type, {})}),
                              auto_inject, json.dumps(triggers)))
                    count += 1

    if not dry_run:
        conn.commit()

    # Also sync global data source configs
    for src_name, src_cfg in data_sources.items():
        if dry_run:
            print(f"  [dry-run] UPSERT agent_intelligence_rules: data_source/{src_name}")
        else:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                VALUES ('data_source', %s, %s, 'config_sync', NOW())
                ON CONFLICT (rule_type, rule_key) DO UPDATE SET
                    config = EXCLUDED.config, changed_by = 'config_sync', updated_at = NOW()
            """, (src_name, json.dumps(src_cfg if isinstance(src_cfg, dict) else {"value": src_cfg})))
        count += 1

    if not dry_run:
        conn.commit()

    print(f"[data-sources] {'Would sync' if dry_run else 'Synced'} {count} rules from agents_data_sources.yaml")
    return count


def sync_sec_rules(conn, dry_run: bool = False) -> int:
    """Sync agents_sec_interaction.yaml → agent_sec_rules."""
    data = _load_yaml("agents_sec_interaction.yaml")
    triggers = data.get("triggers", {})
    agents = data.get("agents", {})
    count = 0

    # Sync trigger rules per agent
    for sec_type, trigger_list in triggers.items():
        for trigger in trigger_list:
            trigger_name = trigger.get("name", "unknown")
            condition = trigger.get("condition", "")
            severity = trigger.get("severity", "medium")
            action = trigger.get("action", "")
            target_agents = trigger.get("agents", [])

            for agent_name in target_agents:
                if dry_run:
                    print(f"  [dry-run] UPSERT agent_sec_rules: {agent_name}/{sec_type}/{trigger_name}")
                else:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO agent_sec_rules (agent, sec_type, trigger_name, condition, severity, action, changed_by, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'config_sync', NOW())
                        ON CONFLICT (agent, sec_type, trigger_name) DO UPDATE SET
                            condition = EXCLUDED.condition, severity = EXCLUDED.severity,
                            action = EXCLUDED.action, changed_by = 'config_sync', updated_at = NOW()
                    """, (agent_name, sec_type, trigger_name, condition, severity, action))
                count += 1

    # Sync agent SEC focus as intelligence rules
    for agent_name, agent_cfg in agents.items():
        focus = agent_cfg.get("sec_focus", [])
        sources = agent_cfg.get("sources", [])
        if dry_run:
            print(f"  [dry-run] UPSERT agent_intelligence_rules: sec_agent/{agent_name}")
        else:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                VALUES ('sec_agent', %s, %s, 'config_sync', NOW())
                ON CONFLICT (rule_type, rule_key) DO UPDATE SET
                    config = EXCLUDED.config, changed_by = 'config_sync', updated_at = NOW()
            """, (agent_name, json.dumps({
                "focus": focus,
                "sources": sources,
                "auto_inject": agent_cfg.get("auto_inject", True),
            })))
        count += 1

    if not dry_run:
        conn.commit()

    print(f"[sec-rules] {'Would sync' if dry_run else 'Synced'} {count} rules from agents_sec_interaction.yaml")
    return count


def sync_screeners(conn, dry_run: bool = False) -> int:
    """Sync screeners.yaml → agent_intelligence_rules (screener configs)."""
    data = _load_yaml("screeners.yaml")
    screeners = data.get("screeners", {})
    run_windows = data.get("run_windows", {})
    count = 0

    for screener_id, cfg in screeners.items():
        if dry_run:
            print(f"  [dry-run] UPSERT agent_intelligence_rules: screener/{screener_id}")
        else:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                VALUES ('screener', %s, %s, 'config_sync', NOW())
                ON CONFLICT (rule_type, rule_key) DO UPDATE SET
                    config = EXCLUDED.config, changed_by = 'config_sync', updated_at = NOW()
            """, (screener_id, json.dumps(cfg)))
        count += 1

    # Sync run windows
    for window_id, window_cfg in run_windows.items():
        if dry_run:
            print(f"  [dry-run] UPSERT agent_intelligence_rules: run_window/{window_id}")
        else:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                VALUES ('run_window', %s, %s, 'config_sync', NOW())
                ON CONFLICT (rule_type, rule_key) DO UPDATE SET
                    config = EXCLUDED.config, changed_by = 'config_sync', updated_at = NOW()
            """, (window_id, json.dumps(window_cfg)))
        count += 1

    if not dry_run:
        conn.commit()

    print(f"[screeners] {'Would sync' if dry_run else 'Synced'} {count} rules from screeners.yaml")
    return count


def show_status():
    """Show current DB state of synced rules."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("\n" + "=" * 60)
    print("Config Sync Status")
    print("=" * 60)

    for table, label in [
        ("agent_data_source_rules", "Agent Data Source Rules"),
        ("agent_sec_rules", "Agent SEC Rules"),
        ("agent_intelligence_rules", "Intelligence Rules"),
    ]:
        try:
            cur.execute(f"SELECT count(*) as cnt FROM {table}")
            cnt = cur.fetchone()["cnt"]
            print(f"\n  {label}: {cnt} rows")

            if table == "agent_data_source_rules":
                cur.execute("SELECT agent, count(*) as cnt FROM agent_data_source_rules GROUP BY agent ORDER BY agent")
                for r in cur.fetchall():
                    print(f"    {r['agent']}: {r['cnt']} sources")

            elif table == "agent_sec_rules":
                cur.execute("SELECT agent, count(*) as cnt FROM agent_sec_rules GROUP BY agent ORDER BY agent")
                for r in cur.fetchall():
                    print(f"    {r['agent']}: {r['cnt']} rules")

            elif table == "agent_intelligence_rules":
                cur.execute("SELECT rule_type, count(*) as cnt FROM agent_intelligence_rules GROUP BY rule_type ORDER BY rule_type")
                for r in cur.fetchall():
                    print(f"    {r['rule_type']}: {r['cnt']} entries")

        except Exception as e:
            print(f"\n  {label}: ERROR — {e}")

    conn.close()


def main():
    dry_run = "--dry-run" in sys.argv
    do_sync = "--sync" in sys.argv
    do_status = "--status" in sys.argv

    if do_status:
        show_status()
        return

    if not dry_run and not do_sync:
        print("Usage: --dry-run | --sync | --status")
        return

    print(f"\n{'=' * 60}")
    print(f"Config Sync {'(DRY RUN)' if dry_run else '(LIVE)'} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}\n")

    conn = _get_conn()
    _ensure_tables(conn)

    total = 0
    total += sync_data_sources(conn, dry_run)
    total += sync_sec_rules(conn, dry_run)
    total += sync_screeners(conn, dry_run)

    conn.close()

    print(f"\n{'=' * 60}")
    print(f"Total: {total} rules {'would be synced' if dry_run else 'synced'}")
    print(f"{'=' * 60}")

    if not dry_run:
        show_status()


if __name__ == "__main__":
    main()
