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

# Staleness is SCHEDULE-AWARE. A fixed threshold marks a legitimate weekly or
# Tue/Thu screen broken merely for not having run today (2026-07-20 review).
# hours = the screen's own cadence + a grace allowance for a missed tick.
SCHEDULE_MAX_AGE_HOURS = {
    "daily": 36,
    "daily_1600": 36,
    "daily_1000_1600": 36,
    "twice_weekly": 5 * 24,       # Tue/Thu lists: longest gap is Thu->Tue
    "tue_thu_postclose": 5 * 24,
    "weekly": 9 * 24,
    "weekly_mon_1000": 9 * 24,
    "weekly_sun_1000": 9 * 24,
    "weekly_wed_1000": 9 * 24,
    "biweekly": 17 * 24,
    "monthly": 34 * 24,
}
DEFAULT_MAX_AGE_HOURS = 36


def max_age_hours(schedule: str | None) -> int:
    return SCHEDULE_MAX_AGE_HOURS.get((schedule or "").strip().lower(), DEFAULT_MAX_AGE_HOURS)


def filter_signature(url: str | None) -> str:
    """Normalized hash of a screen's SEMANTIC filter set, for duplicate detection.

    Only the filter terms matter: column packs, sort order, view and auth token
    do not change which symbols a screen selects. Filters are sorted so that
    ordering differences do not read as different screens.
    """
    import hashlib
    from urllib.parse import urlparse, parse_qs
    if not url:
        return ""
    try:
        q = parse_qs(urlparse(url).query)
    except Exception:
        return ""
    filters = []
    for key in ("f", "ft"):
        for raw in q.get(key, []):
            filters.extend(p.strip() for p in raw.split(",") if p.strip())
    if not filters:
        return ""
    canon = ",".join(sorted(set(filters)))
    return hashlib.sha1(canon.encode()).hexdigest()[:16]


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()


def load_canonical_ids() -> set:
    """Screen ids declared in the Phase-1 canonical registry (the source of record
    for anything the compiler deploys)."""
    path = ROOT / "config" / "finviz_screen_registry.yaml"
    try:
        return set((yaml.safe_load(path.read_text()) or {}).get("screens") or {})
    except Exception:
        return set()


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
                          last_run, results_count, finviz_url, description, schedule
                   FROM finviz_screeners""")
    out = {}
    for r in cur.fetchall():
        out[r[0]] = {"display_name": r[1], "strategy_type": r[2], "active": r[3],
                     "last_run": r[4], "results_count": r[5], "finviz_url": r[6],
                     "description": r[7], "schedule": r[8]}
    return out


def load_membership(cur) -> dict:
    """CURRENT membership, not just lifetime history.

    Counting every historical row made a collapsed screen look healthy:
    swing_momentum showed 7,065 lifetime rows while currently returning 26
    symbols (2026-07-20 review).
    """
    cur.execute("""SELECT screener_id,
                          count(*)                                           AS historical,
                          count(*) FILTER (WHERE present_this_run)            AS present_this_run,
                          count(*) FILTER (WHERE membership_status='active')  AS active,
                          count(*) FILTER (WHERE membership_status='stale')   AS stale,
                          count(*) FILTER (WHERE membership_status='dropped') AS dropped,
                          max(last_seen_in_screener_at)                       AS last_seen
                   FROM screener_symbol_membership GROUP BY 1""")
    return {r[0]: {"historical": r[1], "present_this_run": r[2], "active": r[3],
                   "stale": r[4], "dropped": r[5], "last_seen": r[6]}
            for r in cur.fetchall()}


def classify(sid, in_yaml, in_registry, db, mem, *, duplicate_of=None,
             superseded_by=None, in_canonical=False) -> tuple[str, str]:
    """Return (state, reason). Executor presence dominates: the DB is what runs."""
    now = datetime.now(timezone.utc)
    if superseded_by:
        return "SUPERSEDED", f"replaced by {superseded_by} (explicit supersedes lineage)"
    if duplicate_of:
        return "DUPLICATE", (f"identical normalized filter set to {duplicate_of} — "
                             f"same symbols, duplicated capture cost and split attribution")
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
    m = mem or {}
    historical = m.get("historical", 0)
    current = m.get("present_this_run", 0)
    limit_h = max_age_hours(db.get("schedule"))
    stale = (last_run is None
             or (now - last_run.astimezone(timezone.utc)) > timedelta(hours=limit_h))

    if not db.get("active"):
        # A canonical-registry screen that has never run is AWAITING PROMOTION,
        # not retired. Only a screen that once ran and was switched off is
        # retained-for-attribution.
        if in_canonical and (mem or {}).get("historical", 0) == 0:
            return "SHADOW", ("registered from the canonical registry, inactive by design — "
                              "awaiting operator promotion; captures nothing yet")
        return "RETIRED_EVIDENCE", "row present but active=false — retained for attribution only"
    if stale:
        age = "never" if last_run is None else f"{(now - last_run.astimezone(timezone.utc)).days}d ago"
        return "BROKEN", (f"active but last_run {age} — exceeds the "
                          f"{limit_h}h allowance for schedule '{db.get('schedule')}'")
    if historical == 0:
        return "BROKEN", "runs on schedule but has never captured a single member"
    if current == 0:
        return "BROKEN", (f"ran on schedule but currently returns ZERO symbols "
                          f"({historical} historical rows mask the collapse)")
    if not in_registry:
        return "SHADOW", (f"running ({current} current members) but no candidate_sources "
                          f"mapping — no strategy consumes it (attribution gap)")
    return "ACTIVE", f"running, mapped, {current} current members ({historical} historical)"


def reconcile() -> dict:
    from db_adapter import _get_conn
    cur = _get_conn().cursor()

    canonical_ids = load_canonical_ids()
    yaml_defs = load_yaml_defs()
    reg_by_screen, reg_sources = load_registry_map()
    db_state = load_db_state(cur)
    mem = load_membership(cur)

    all_ids = sorted(set(yaml_defs) | set(reg_by_screen) | set(db_state))

    # ── duplicate + supersession detection ──
    # Group by normalized filter signature; the earliest-named id in a group is
    # the canonical one and the rest are DUPLICATE. Explicit 'supersedes' in a
    # YAML definition records intentional replacement lineage.
    sig_groups: dict[str, list] = {}
    for sid in all_ids:
        url = (db_state.get(sid) or {}).get("finviz_url") or (yaml_defs.get(sid) or {}).get("finviz_url")
        sig = filter_signature(url)
        if sig:
            sig_groups.setdefault(sig, []).append(sid)
    duplicate_of: dict[str, str] = {}
    for sig, ids in sig_groups.items():
        if len(ids) > 1:
            canonical = sorted(ids)[0]
            for other in sorted(ids)[1:]:
                duplicate_of[other] = canonical
    superseded_by: dict[str, str] = {}
    for sid, d in yaml_defs.items():
        for old in ([d.get("supersedes")] if isinstance(d.get("supersedes"), str)
                    else (d.get("supersedes") or [])):
            if old:
                superseded_by[old] = sid

    rows = []
    for sid in all_ids:
        db = db_state.get(sid)
        m = mem.get(sid)
        state, reason = classify(sid, sid in yaml_defs, sid in reg_by_screen, db, m,
                                 duplicate_of=duplicate_of.get(sid),
                                 superseded_by=superseded_by.get(sid),
                                 in_canonical=sid in canonical_ids)
        ydef = yaml_defs.get(sid) or {}
        rows.append({
            "screen_id": sid,
            "display_name": (db or {}).get("display_name") or ydef.get("display_name") or "",
            "in_screeners_yaml": sid in yaml_defs,
            "in_candidate_sources": sid in reg_by_screen,
            "in_executor_db": db is not None,
            "db_active": (db or {}).get("active"),
            "schedule": (db or {}).get("schedule") or "",
            "max_age_hours": max_age_hours((db or {}).get("schedule")) if db else None,
            "last_run": str((db or {}).get("last_run") or ""),
            "results_count": (db or {}).get("results_count"),
            "members_historical": (m or {}).get("historical", 0),
            "members_present_this_run": (m or {}).get("present_this_run", 0),
            "members_active": (m or {}).get("active", 0),
            "members_stale": (m or {}).get("stale", 0),
            "members_dropped": (m or {}).get("dropped", 0),
            # results_count is what the screen returned; present_this_run is what
            # persisted. A wide gap means ingestion dropped rows silently.
            "result_vs_membership_variance": (
                ((db or {}).get("results_count") or 0) - ((m or {}).get("present_this_run", 0))
                if db else None),
            "filter_signature": filter_signature(
                (db or {}).get("finviz_url") or ydef.get("finviz_url")),
            "duplicate_of": duplicate_of.get(sid, ""),
            "superseded_by": superseded_by.get(sid, ""),
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
    print(f"{'STATE':<17}{'ID':<32}{'YML':<4}{'REG':<4}{'DB':<4}"
          f"{'NOW':>7}{'HIST':>8}  {'SCHEDULE':<16}")
    print("-" * 96)
    for r in sorted(rep["rows"], key=lambda x: (x["state"], x["screen_id"])):
        note = ""
        if r.get("duplicate_of"):
            note = f"  == {r['duplicate_of']}"
        elif r.get("superseded_by"):
            note = f"  -> {r['superseded_by']}"
        print(f"{r['state']:<17}{r['screen_id']:<32}"
              f"{'Y' if r['in_screeners_yaml'] else '-':<4}"
              f"{'Y' if r['in_candidate_sources'] else '-':<4}"
              f"{'Y' if r['in_executor_db'] else '-':<4}"
              f"{r['members_present_this_run']:>7}{r['members_historical']:>8}  "
              f"{r.get('schedule',''):<16}{note}")
    if rep["provider_claims"]:
        print("\nPROVIDER CLAIMS TO VERIFY:")
        for p in rep["provider_claims"]:
            print(f"  {p['source']}: provider={p['claimed_provider']} status={p['claimed_status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
