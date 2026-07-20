#!/usr/bin/env python3
"""finviz_registry_reconcile.py — Phase 0: machine-generated Finviz source-of-truth
reconciliation. READ-ONLY: reports state, changes nothing, runs no screener.

Reconciles the three places a Finviz screen can be declared:

  1. assets/screeners.yaml         — checked-in definitions
  2. config/candidate_sources.yaml — strategy/play-family mappings
  3. finviz_screeners (DB table)   — what the production runner ACTUALLY executes

Key structural fact this tool exists to make visible (verified 2026-07-20):
scripts/finviz_screener_runner.py reads the DB table, NOT the YAML
(finviz_screener_runner.py:196-198). The YAML's only production reader is
finviz_ingestion.py, which is on NO cron. A screen added to the YAML alone
therefore never runs — it is dead on arrival.

States (per the Phase 0 spec; no definition may vanish without one):
  ACTIVE           — defined, mapped, in DB, running, producing members
  SHADOW           — in DB but explicitly human-review-only / not proposal-eligible
  DUPLICATE        — same semantic filter set as another id
  SUPERSEDED       — replaced by a newer id (supersedes chain recorded)
  ORPHANED         — declared in one place, absent from the executor
  BROKEN           — in DB and scheduled, but failing (no members / stale run)
  RETIRED_EVIDENCE — retained for historical attribution only

Usage:
  finviz_registry_reconcile.py            # human table + exit code
  finviz_registry_reconcile.py --json     # machine artifact
  finviz_registry_reconcile.py --write-artifact   # persist to docs/_findings/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SCREENERS_YAML = ROOT / "assets" / "screeners.yaml"
CANDIDATE_SOURCES = ROOT / "config" / "candidate_sources.yaml"
ARTIFACT = ROOT / "docs" / "_findings" / "FINVIZ_REGISTRY_RECONCILIATION.json"

# The executor of record. Anything not here does not run, whatever the YAML says.
EXECUTOR = "scripts/finviz_screener_runner.py (reads finviz_screeners DB table)"
STALE_RUN_HOURS = 36


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()


def load_yaml_defs() -> dict:
    try:
        d = yaml.safe_load(SCREENERS_YAML.read_text()) or {}
        return d.get("screeners") or {}
    except Exception:
        return {}


def load_registry_map() -> tuple[dict, dict]:
    """Return (screen_id -> [source_names], source_name -> source_block)."""
    try:
        d = yaml.safe_load(CANDIDATE_SOURCES.read_text()) or {}
    except Exception:
        return {}, {}
    sources = d.get("sources") or {}
    by_screen: dict[str, list] = {}
    for name, blk in sources.items():
        for sid in (blk.get("screener_ids") or []):
            by_screen.setdefault(sid, []).append(name)
    return by_screen, sources


def load_db_state(cur) -> dict:
    cur.execute("""SELECT screener_id, display_name, strategy_type, active,
                          last_run, results_count, finviz_url, description
                   FROM finviz_screeners""")
    out = {}
    for r in cur.fetchall():
        out[r[0]] = {"display_name": r[1], "strategy_type": r[2], "active": r[3],
                     "last_run": r[4], "results_count": r[5], "finviz_url": r[6],
                     "description": r[7]}
    return out


def load_membership(cur) -> dict:
    cur.execute("""SELECT screener_id, count(*), max(last_seen_in_screener_at)
                   FROM screener_symbol_membership GROUP BY 1""")
    return {r[0]: {"members": r[1], "last_seen": r[2]} for r in cur.fetchall()}


def classify(sid, in_yaml, in_registry, db, mem) -> tuple[str, str]:
    """Return (state, reason). Executor presence dominates: the DB is what runs."""
    now = datetime.now(timezone.utc)
    if db is None:
        if in_yaml and in_registry:
            return "ORPHANED", ("defined in screeners.yaml and mapped in candidate_sources, "
                                "but absent from the executor DB — never runs")
        if in_yaml:
            return "ORPHANED", ("defined in screeners.yaml only — absent from executor DB "
                                "and unmapped in candidate_sources; never runs")
        if in_registry:
            return "ORPHANED", ("referenced by candidate_sources but defined nowhere — "
                                "dangling strategy mapping")
        return "ORPHANED", "referenced nowhere resolvable"

    # present in the executor
    last_run = db.get("last_run")
    members = (mem or {}).get("members", 0)
    stale = (last_run is None
             or (now - last_run.astimezone(timezone.utc)) > timedelta(hours=STALE_RUN_HOURS))
    if not db.get("active"):
        return "RETIRED_EVIDENCE", "row present but active=false — retained for attribution only"
    if stale and members == 0:
        return "BROKEN", f"active in DB but last_run={last_run} and zero members captured"
    if stale:
        return "BROKEN", f"active in DB but last_run is stale ({last_run})"
    if members == 0:
        return "BROKEN", "runs but has never captured a member"
    if not in_registry:
        return "SHADOW", ("running and producing members, but no candidate_sources mapping — "
                          "no strategy consumes it (attribution gap, not proposal-eligible)")
    return "ACTIVE", f"running, mapped, {members} member rows"


def reconcile() -> dict:
    from db_adapter import _get_conn
    cur = _get_conn().cursor()

    yaml_defs = load_yaml_defs()
    reg_by_screen, reg_sources = load_registry_map()
    db_state = load_db_state(cur)
    mem = load_membership(cur)

    all_ids = sorted(set(yaml_defs) | set(reg_by_screen) | set(db_state))
    rows = []
    for sid in all_ids:
        db = db_state.get(sid)
        m = mem.get(sid)
        state, reason = classify(sid, sid in yaml_defs, sid in reg_by_screen, db, m)
        ydef = yaml_defs.get(sid) or {}
        rows.append({
            "screen_id": sid,
            "display_name": (db or {}).get("display_name") or ydef.get("display_name") or "",
            "in_screeners_yaml": sid in yaml_defs,
            "in_candidate_sources": sid in reg_by_screen,
            "in_executor_db": db is not None,
            "db_active": (db or {}).get("active"),
            "last_run": str((db or {}).get("last_run") or ""),
            "results_count": (db or {}).get("results_count"),
            "member_rows": (m or {}).get("members", 0),
            "last_member_seen": str((m or {}).get("last_seen") or ""),
            "mapped_sources": reg_by_screen.get(sid, []),
            "strategy_type": (db or {}).get("strategy_type") or ydef.get("strategy_class") or "",
            "machine_url": (db or {}).get("finviz_url") or ydef.get("finviz_url") or "",
            "state": state,
            "reason": reason,
        })

    # provider-claim audit: registry statements vs verifiable reality
    provider_claims = []
    for name, blk in reg_sources.items():
        prov, status = blk.get("provider"), blk.get("status")
        if prov or status in ("BLOCKED_PROVIDER_MISSING", "SHADOW"):
            provider_claims.append({"source": name, "claimed_provider": prov,
                                    "claimed_status": status, "notes": blk.get("notes", "")})

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": _commit(),
        "executor_of_record": EXECUTOR,
        "read_only": True,
        "totals": {
            "screeners_yaml_definitions": len(yaml_defs),
            "candidate_sources_referenced_ids": len(reg_by_screen),
            "executor_db_rows": len(db_state),
            "distinct_ids_across_all_three": len(all_ids),
        },
        "state_counts": counts,
        "rows": rows,
        "provider_claims": provider_claims,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Finviz source-of-truth reconciliation (read-only)")
    ap.add_argument("--json", action="store_true", help="emit the machine artifact")
    ap.add_argument("--write-artifact", action="store_true",
                    help="persist the artifact under docs/_findings/")
    args = ap.parse_args()

    rep = reconcile()

    if args.write_artifact:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(rep, indent=1, sort_keys=True, default=str))

    if args.json:
        print(json.dumps(rep, indent=1, default=str))
        return 0

    t = rep["totals"]
    print(f"FINVIZ REGISTRY RECONCILIATION @ {rep['commit']}  (READ-ONLY)")
    print(f"executor of record: {rep['executor_of_record']}")
    print(f"  screeners.yaml definitions : {t['screeners_yaml_definitions']}")
    print(f"  candidate_sources refs     : {t['candidate_sources_referenced_ids']}")
    print(f"  executor DB rows           : {t['executor_db_rows']}")
    print(f"  distinct ids               : {t['distinct_ids_across_all_three']}")
    print(f"\nstate counts: {rep['state_counts']}\n")
    print(f"{'STATE':<17}{'ID':<34}{'YML':<5}{'REG':<5}{'DB':<4}{'MEMBERS':>8}")
    print("-" * 76)
    for r in sorted(rep["rows"], key=lambda x: (x["state"], x["screen_id"])):
        print(f"{r['state']:<17}{r['screen_id']:<34}"
              f"{'Y' if r['in_screeners_yaml'] else '-':<5}"
              f"{'Y' if r['in_candidate_sources'] else '-':<5}"
              f"{'Y' if r['in_executor_db'] else '-':<4}"
              f"{r['member_rows']:>8}")
    if rep["provider_claims"]:
        print("\nPROVIDER CLAIMS TO VERIFY:")
        for p in rep["provider_claims"]:
            print(f"  {p['source']}: provider={p['claimed_provider']} status={p['claimed_status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
