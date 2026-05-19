#!/usr/bin/env python3
"""backfill_screener_membership_transitions.py — Detect dropped/reentered/stale/expired transitions.

Compares prior membership against daily scan sets to detect lifecycle transitions.
Default: dry-run. No trades. No orders. No deletions.

Usage:
    .venv/bin/python scripts/backfill_screener_membership_transitions.py --dry-run --verbose
    .venv/bin/python scripts/backfill_screener_membership_transitions.py --apply --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

STALE_THRESHOLD = 3     # consecutive missing runs before stale
EXPIRE_THRESHOLD = 7    # consecutive missing runs before expired
MASS_DROP_PCT = 0.50    # if >50% of prior symbols disappear, flag for review


def load_prior_memberships(conn, screener_id):
    """Load current membership snapshot for a screener."""
    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, membership_status, consecutive_missing_count,
               consecutive_seen_count, last_seen_run_id, present_this_run
        FROM screener_symbol_membership
        WHERE screener_id = %s
    """, [screener_id])
    cols = [d[0] for d in cur.description]
    return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}


def build_daily_symbol_sets(conn, screener_id, since):
    """Build per-day symbol sets from trade_ai_scans for a screener source."""
    cur = conn.cursor()
    cur.execute("""
        SELECT scanned_at::date as run_date, array_agg(DISTINCT symbol) as symbols,
               count(DISTINCT symbol) as sym_count
        FROM trade_ai_scans
        WHERE source = %s AND scanned_at > %s
        GROUP BY scanned_at::date
        ORDER BY run_date
    """, [screener_id, since])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def event_exists(conn, symbol, screener_id, run_id, event_type):
    """Check if a history event already exists (idempotent guard)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM screener_symbol_membership_history
        WHERE symbol = %s AND screener_id = %s AND run_id = %s AND event_type = %s
        LIMIT 1
    """, [symbol, screener_id, run_id, event_type])
    return cur.fetchone() is not None


def classify_transitions(prior, current_symbols, run_id, conn, screener_id):
    """Classify membership transitions for one daily run.
    Returns list of (symbol, transition, reason) tuples.
    """
    transitions = []
    current_set = set(current_symbols)
    prior_symbols = set(prior.keys())

    # Symbols in current run
    for sym in current_set:
        if sym not in prior:
            transitions.append((sym, "entered", "First seen in screener"))
        elif prior[sym]["membership_status"] in ("dropped", "stale", "expired"):
            transitions.append((sym, "reentered", f"Was {prior[sym]['membership_status']}, now present again"))
        else:
            transitions.append((sym, "present", "Still present"))

    # Symbols in prior but missing from current run
    for sym in prior_symbols - current_set:
        old = prior[sym]
        miss = int(old.get("consecutive_missing_count", 0)) + 1
        if old["membership_status"] in ("expired",):
            continue  # already expired, no further transition needed
        if miss >= EXPIRE_THRESHOLD:
            transitions.append((sym, "expired", f"Missing {miss} consecutive runs (>= {EXPIRE_THRESHOLD})"))
        elif miss >= STALE_THRESHOLD:
            transitions.append((sym, "stale", f"Missing {miss} consecutive runs (>= {STALE_THRESHOLD})"))
        else:
            transitions.append((sym, "dropped", f"Missing {miss} consecutive run(s)"))

    return transitions


def apply_transition(conn, symbol, screener_id, run_id, transition, reason, run_date, dry_run=True):
    """Apply a single membership transition. Returns True if event was new."""
    if event_exists(conn, symbol, screener_id, run_id, transition):
        return False  # idempotent

    if dry_run:
        return True

    cur = conn.cursor()

    # Write history event
    cur.execute("""
        INSERT INTO screener_symbol_membership_history
            (symbol, screener_id, run_id, event_type, event_at, reason)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, [symbol, screener_id, run_id, transition, run_date, reason])

    # Update membership record
    if transition == "entered":
        cur.execute("""
            INSERT INTO screener_symbol_membership
                (symbol, screener_id, first_seen_in_screener_at, last_seen_in_screener_at,
                 last_seen_run_id, present_this_run, consecutive_seen_count,
                 consecutive_missing_count, membership_status)
            VALUES (%s, %s, %s, %s, %s, TRUE, 1, 0, 'present')
            ON CONFLICT (symbol, screener_id) DO UPDATE SET
                last_seen_in_screener_at = EXCLUDED.last_seen_in_screener_at,
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                present_this_run = TRUE,
                consecutive_seen_count = screener_symbol_membership.consecutive_seen_count + 1,
                consecutive_missing_count = 0,
                membership_status = 'present',
                updated_at = NOW()
        """, [symbol, screener_id, run_date, run_date, run_id])

    elif transition == "reentered":
        cur.execute("""
            UPDATE screener_symbol_membership SET
                last_seen_in_screener_at = %s,
                last_seen_run_id = %s,
                present_this_run = TRUE,
                consecutive_seen_count = 1,
                consecutive_missing_count = 0,
                membership_status = 'present',
                updated_at = NOW()
            WHERE symbol = %s AND screener_id = %s
        """, [run_date, run_id, symbol, screener_id])

    elif transition == "present":
        cur.execute("""
            UPDATE screener_symbol_membership SET
                last_seen_in_screener_at = %s,
                last_seen_run_id = %s,
                present_this_run = TRUE,
                consecutive_seen_count = consecutive_seen_count + 1,
                consecutive_missing_count = 0,
                membership_status = 'present',
                updated_at = NOW()
            WHERE symbol = %s AND screener_id = %s
        """, [run_date, run_id, symbol, screener_id])

    elif transition in ("dropped", "stale", "expired"):
        cur.execute("""
            UPDATE screener_symbol_membership SET
                present_this_run = FALSE,
                consecutive_seen_count = 0,
                consecutive_missing_count = consecutive_missing_count + 1,
                membership_status = %s,
                updated_at = NOW()
            WHERE symbol = %s AND screener_id = %s
        """, [transition, symbol, screener_id])

    return True


def main():
    p = argparse.ArgumentParser(description="Backfill membership transitions (default: dry-run)")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection")
        sys.exit(1)

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    mode = "DRY RUN" if args.dry_run else "APPLY"

    # Get distinct screener sources
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT screener_id FROM screener_symbol_membership ORDER BY screener_id")
    screener_ids = [r[0] for r in cur.fetchall()]

    if args.verbose:
        print(f"[{mode}] Processing {len(screener_ids)} screener sources: {screener_ids}")

    stats = {
        "screeners_analyzed": len(screener_ids),
        "runs_analyzed": 0,
        "entered": 0, "present": 0, "dropped": 0, "stale": 0, "expired": 0, "reentered": 0,
        "mass_drop_protections": 0,
        "partial_runs_skipped": 0,
        "events_already_existing": 0,
        "events_to_create": 0,
        "events_created": 0,
    }

    for sid in screener_ids:
        prior = load_prior_memberships(conn, sid)
        daily_sets = build_daily_symbol_sets(conn, sid, since)

        if args.verbose:
            print(f"\n  Screener '{sid}': {len(prior)} prior members, {len(daily_sets)} daily runs")

        for day in daily_sets:
            run_date = day["run_date"]
            current_symbols = day["symbols"] or []
            sym_count = day["sym_count"]
            run_id = f"{run_date}_{sid}"
            stats["runs_analyzed"] += 1

            # Mass-drop protection
            if len(prior) > 0 and sym_count == 0:
                stats["partial_runs_skipped"] += 1
                if args.verbose:
                    print(f"    {run_date}: SKIPPED (0 symbols — likely failed run)")
                continue

            if len(prior) > 10:
                missing_count = len(set(prior.keys()) - set(current_symbols))
                drop_pct = missing_count / len(prior)
                if drop_pct > MASS_DROP_PCT and sym_count < len(prior) * 0.5:
                    stats["mass_drop_protections"] += 1
                    if args.verbose:
                        print(f"    {run_date}: MASS DROP PROTECTION — {missing_count}/{len(prior)} ({drop_pct:.0%}) missing, only {sym_count} current. Skipping drops, processing additions only.")
                    # Only process entered/reentered/present, skip drops
                    transitions = classify_transitions(prior, current_symbols, run_id, conn, sid)
                    transitions = [(s, t, r) for s, t, r in transitions if t not in ("dropped", "stale", "expired")]
                else:
                    transitions = classify_transitions(prior, current_symbols, run_id, conn, sid)
            else:
                transitions = classify_transitions(prior, current_symbols, run_id, conn, sid)

            day_stats = defaultdict(int)
            for sym, transition, reason in transitions:
                stats[transition] += 1
                day_stats[transition] += 1

                if event_exists(conn, sym, screener_id=sid, run_id=run_id, event_type=transition):
                    stats["events_already_existing"] += 1
                    continue

                stats["events_to_create"] += 1
                was_new = apply_transition(conn, sym, sid, run_id, transition, reason, run_date, dry_run=args.dry_run)
                if was_new and not args.dry_run:
                    stats["events_created"] += 1

            # Update prior snapshot for next day's comparison
            for sym, transition, reason in transitions:
                if transition in ("entered", "reentered", "present"):
                    prior[sym] = {
                        "symbol": sym,
                        "membership_status": "present",
                        "consecutive_missing_count": 0,
                        "consecutive_seen_count": prior.get(sym, {}).get("consecutive_seen_count", 0) + 1,
                        "last_seen_run_id": run_id,
                        "present_this_run": True,
                    }
                elif transition in ("dropped", "stale", "expired"):
                    if sym in prior:
                        prior[sym]["membership_status"] = transition
                        prior[sym]["consecutive_missing_count"] = prior[sym].get("consecutive_missing_count", 0) + 1
                        prior[sym]["consecutive_seen_count"] = 0
                        prior[sym]["present_this_run"] = False

            if args.verbose:
                parts = [f"{k}={v}" for k, v in sorted(day_stats.items()) if v > 0]
                print(f"    {run_date}: {sym_count} symbols — {', '.join(parts) if parts else 'no transitions'}")

    if not args.dry_run:
        conn.commit()

    conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "apply",
        "since_days": args.since_days,
        **stats,
    }

    if args.verbose:
        print(f"\n{'='*60}")
        print(f"[{mode}] Summary:")
        print(f"  Screeners: {stats['screeners_analyzed']}")
        print(f"  Runs: {stats['runs_analyzed']}")
        print(f"  Entered: {stats['entered']}")
        print(f"  Present: {stats['present']}")
        print(f"  Dropped: {stats['dropped']}")
        print(f"  Stale: {stats['stale']}")
        print(f"  Expired: {stats['expired']}")
        print(f"  Reentered: {stats['reentered']}")
        print(f"  Mass-drop protections: {stats['mass_drop_protections']}")
        print(f"  Partial runs skipped: {stats['partial_runs_skipped']}")
        print(f"  Events already existing: {stats['events_already_existing']}")
        print(f"  Events to create: {stats['events_to_create']}")
        if not args.dry_run:
            print(f"  Events created: {stats['events_created']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            f"# Membership Transition Backfill {'DRY RUN' if args.dry_run else 'APPLIED'}\n",
            f"Generated: {report['generated_at']}\n",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Screeners analyzed | {stats['screeners_analyzed']} |",
            f"| Runs analyzed | {stats['runs_analyzed']} |",
            f"| Entered | {stats['entered']} |",
            f"| Present | {stats['present']} |",
            f"| Dropped | {stats['dropped']} |",
            f"| Stale | {stats['stale']} |",
            f"| Expired | {stats['expired']} |",
            f"| Reentered | {stats['reentered']} |",
            f"| Mass-drop protections | {stats['mass_drop_protections']} |",
            f"| Partial runs skipped | {stats['partial_runs_skipped']} |",
            f"| Events already existing | {stats['events_already_existing']} |",
            f"| Events to create | {stats['events_to_create']} |",
        ]
        if not args.dry_run:
            md.append(f"| Events created | {stats['events_created']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
