#!/usr/bin/env python3
"""
seed_pipeline_controller.py — Seed pipeline stages from bootstrap YAML into DB.

Usage:
    python seed_pipeline_controller.py --dry-run
    python seed_pipeline_controller.py --apply
"""
import argparse, json, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

def _env(key, default=""):
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.getenv(key, default)

def _get_conn():
    import psycopg2
    return psycopg2.connect(host="localhost", dbname="trade_ai",
                            user="trade_ai", password=_env("DB_PASSWORD"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply")
        sys.exit(1)

    import yaml
    boot_path = PROJECT_ROOT / "config" / "pipeline_controller.bootstrap.yaml"
    boot = yaml.safe_load(boot_path.read_text())

    pipeline_key = "daily"
    stages = boot.get("stages", [])
    deps = boot.get("dependencies", [])

    stats = {"new": 0, "updated": 0, "unchanged": 0, "deps": 0}

    if args.dry_run:
        print(f"Pipeline: {pipeline_key}")
        print(f"Stages: {len(stages)}")
        print(f"Dependencies: {len(deps)}")
        for s in stages:
            active = s.get("active", True)
            print(f"  {'[ON] ' if active else '[OFF]'} {s['stage_key']:<35} {s['group_key']:<18} {s['name']}")
        for d in deps:
            print(f"  DEP: {d['stage_key']} <- {d['depends_on']}")
        return

    conn = _get_conn()
    cur = conn.cursor()

    for s in stages:
        cur.execute("SELECT id, command FROM pipeline_stages WHERE pipeline_key=%s AND stage_key=%s",
                    (pipeline_key, s["stage_key"]))
        existing = cur.fetchone()
        if existing:
            # Check if command changed
            if existing[1] != s["command"]:
                cur.execute("""
                    UPDATE pipeline_stages SET command=%s, group_key=%s, name=%s,
                        timeout_seconds=%s, max_retries=%s, sla_seconds=%s,
                        sort_order=%s, can_degrade=%s, degradation_policy=%s,
                        active=%s, updated_at=NOW()
                    WHERE pipeline_key=%s AND stage_key=%s
                """, (s["command"], s.get("group_key"), s["name"],
                      s.get("timeout_seconds", 1800), s.get("max_retries", 1),
                      s.get("sla_seconds"), s.get("sort_order", 0),
                      s.get("can_degrade", False), s.get("degradation_policy"),
                      s.get("active", True), pipeline_key, s["stage_key"]))
                stats["updated"] += 1
                print(f"  UPDATED: {s['stage_key']}")
            else:
                stats["unchanged"] += 1
        else:
            cur.execute("""
                INSERT INTO pipeline_stages
                    (pipeline_key, stage_key, group_key, name, command,
                     timeout_seconds, max_retries, retry_backoff_seconds,
                     sla_seconds, sort_order, can_degrade, degradation_policy, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (pipeline_key, s["stage_key"], s.get("group_key"), s["name"],
                  s["command"], s.get("timeout_seconds", 1800), s.get("max_retries", 1),
                  s.get("retry_backoff_seconds", 60), s.get("sla_seconds"),
                  s.get("sort_order", 0), s.get("can_degrade", False),
                  s.get("degradation_policy"), s.get("active", True)))
            stats["new"] += 1
            print(f"  NEW: {s['stage_key']}")

    for d in deps:
        cur.execute("""
            INSERT INTO pipeline_stage_dependencies (pipeline_key, stage_key, depends_on_stage_key)
            VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
        """, (pipeline_key, d["stage_key"], d["depends_on"]))
        stats["deps"] += 1

    conn.commit()
    conn.close()

    print(f"\nSeed complete: {stats['new']} new, {stats['updated']} updated, "
          f"{stats['unchanged']} unchanged, {stats['deps']} deps")

if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
