#!/usr/bin/env python3
"""watch_directive_dedup.py — analyze / clean up watch-directive clutter.

Read-only by default (dry-run). Produces a concrete plan across three tiers:

  Tier 1  MALFORMED   — garbage labels (bare taxonomy words like "trend analyst",
                        "trend industry", "Energy") → archive.
  Tier 2  DEAD        — claude_challenger trend directives with 0 lifetime hits and
                        cold (no activity) → archive.
  Tier 3  NEAR-DUP    — think_tank/operator trend directives that collapse to the same
                        canonical family key → merge onto the survivor (most hits, then
                        oldest), reassigning watch_directive_hits, archiving the rest.

Merges NEVER delete: dup directives are set status='archived' (reversible) and their
hits are re-pointed at the survivor. The (directive_id, symbol, surfaced_at) unique key
is respected — colliding hits are dropped, not duplicated.

Usage:
    python3 scripts/watch_directive_dedup.py            # dry-run: print the plan
    python3 scripts/watch_directive_dedup.py --apply    # execute (single transaction)
    python3 scripts/watch_directive_dedup.py --tier 1   # limit to a tier (repeatable)
"""
import argparse
import sys
from collections import defaultdict

sys.path.insert(0, "scripts")
from db_adapter import _execute  # noqa: E402
from watch_directive_canonical import canonical_family, norm_label  # noqa: E402

# ── malformed-label handling (operator decision 2026-07-01: relabel/merge, don't lose hits) ──
# High-hit bare/garbage labels are NOT archived — they carry real active surfacing. Instead:
#   RELABEL       — give the working think_tank theme a proper human-readable name (stays active).
#   MERGE_MALFORMED — a bare label that just duplicates a canonical sector directive → merge into it.
# Keyed by normalized label so it survives id churn.
RELABEL = {
    "trend analyst": "trend Analyst revision & upgrade momentum",
    "trend industry": "trend Industry rotation leaders",
}
# normalized malformed label -> (kind, normalized target label) of the canonical directive to merge into
MERGE_MALFORMED = {
    "energy": ("sector", "sector energy"),
}

# survivor precedence for Tier-3 family merges (operator wins, then most hits — operator decision)
AUTHOR_RANK = {"operator": 0, "rotation_advisor": 1, "sector_universe": 1, "think_tank": 2, "claude_challenger": 3}


def _survivor_key(m):
    # min() picks: lowest author rank, then most hits (via negation), then lowest id (oldest)
    return (AUTHOR_RANK.get(m["created_by"], 2), -(m["hits"] or 0), m["id"])


def load_active_trend():
    return _execute(
        """SELECT d.id, d.label, d.created_by, d.status, d.created_at,
                  (SELECT count(*) FROM watch_directive_hits h WHERE h.directive_id=d.id) hits,
                  d.last_serviced_at
           FROM watch_directives d
           WHERE d.kind='trend' AND d.status='active'
           ORDER BY d.created_at""",
        fetch="all",
    ) or []


def _lookup_directive(kind, target_norm):
    for r in _execute(
        "SELECT id, label FROM watch_directives WHERE kind=%s AND status='active'", (kind,), fetch="all"
    ) or []:
        if norm_label(r["label"]) == target_norm:
            return r["id"]
    return None


def plan(tiers):
    rows = load_active_trend()
    actions = {"relabel": [], "malformed_merge": [], "dead": [], "merges": []}
    consumed = set()

    # Tier 1 — malformed: relabel working themes, merge bare dups into their canonical directive
    if 1 in tiers:
        for r in rows:
            norm = norm_label(r["label"])
            if norm in RELABEL:
                actions["relabel"].append({**r, "new_label": RELABEL[norm]})
                consumed.add(r["id"])
            elif norm in MERGE_MALFORMED:
                kind, tgt_norm = MERGE_MALFORMED[norm]
                tgt = _lookup_directive(kind, tgt_norm)
                if tgt:
                    actions["malformed_merge"].append({**r, "target_id": tgt, "target_label": tgt_norm})
                    consumed.add(r["id"])

    # Tier 2 — dead challengers (0 hits, from claude_challenger)
    if 2 in tiers:
        for r in rows:
            if r["id"] in consumed:
                continue
            if r["created_by"] == "claude_challenger" and (r["hits"] or 0) == 0:
                actions["dead"].append(r)
                consumed.add(r["id"])

    # Tier 3 — near-dup families
    if 3 in tiers:
        fam_members = defaultdict(list)
        for r in rows:
            if r["id"] in consumed:
                continue
            fam = canonical_family(r["label"])
            if fam:
                fam_members[fam].append(r)
        for fam, members in fam_members.items():
            if len(members) < 2:
                continue  # nothing to merge
            # survivor = operator wins, then most hits, then oldest (operator decision 2026-07-01)
            survivor = min(members, key=_survivor_key)
            dups = [m for m in members if m["id"] != survivor["id"]]
            actions["merges"].append({"family": fam, "survivor": survivor, "dups": dups})
    return actions


def print_plan(actions):
    tot_arch = len(actions["malformed_merge"]) + len(actions["dead"]) + sum(len(m["dups"]) for m in actions["merges"])
    print(f"\n{'='*78}\nWATCH-DIRECTIVE CLEANUP PLAN (dry-run)\n{'='*78}")
    print(f"Would relabel {len(actions['relabel'])}, archive {tot_arch} active trend directives "
          f"({len(actions['malformed_merge'])} bare-dup merged, {len(actions['dead'])} dead, "
          f"{sum(len(m['dups']) for m in actions['merges'])} family-merged into {len(actions['merges'])} survivors).\n")

    if actions["relabel"]:
        print("── TIER 1a: RELABEL (stays active, keeps hits) ──")
        for r in actions["relabel"]:
            print(f"   #{r['id']:>4} {r['label']!r} → {r['new_label']!r} ({r['hits']} hits)")
    if actions["malformed_merge"]:
        print("\n── TIER 1b: BARE-DUP MERGE (into canonical, keeps hits) ──")
        for r in actions["malformed_merge"]:
            print(f"   #{r['id']:>4} {r['label']!r} → merge into '{r['target_label']}' (#{r['target_id']}); {r['hits']} hits reassigned")
    if actions["dead"]:
        print("\n── TIER 2: DEAD challengers (archive, 0 hits) ──")
        for r in actions["dead"]:
            print(f"   #{r['id']:>4} {r['label'][:52]!r}")
    if actions["merges"]:
        print("\n── TIER 3: NEAR-DUP FAMILIES (merge → survivor) ──")
        for m in actions["merges"]:
            s = m["survivor"]
            moved = sum(d["hits"] or 0 for d in m["dups"])
            print(f"\n   [{m['family']}]  survivor #{s['id']} {s['label'][:46]!r} ({s['hits']} hits)")
            print(f"      absorbs {len(m['dups'])} dups (+{moved} hits reassigned):")
            for d in m["dups"]:
                print(f"        #{d['id']:>4} {d['label'][:50]!r} ({d['hits']} hits, {d['created_by']})")
    print(f"\n{'='*78}")


def _reassign_and_archive(stmts, src_id, tgt_id):
    """Move src's hits onto tgt (skipping unique-key collisions), delete leftovers, mark src for archive."""
    stmts.append((
        """UPDATE watch_directive_hits h SET directive_id=%s
           WHERE h.directive_id=%s
             AND NOT EXISTS (SELECT 1 FROM watch_directive_hits s
                             WHERE s.directive_id=%s AND s.symbol=h.symbol
                               AND s.surfaced_at=h.surfaced_at)""",
        (tgt_id, src_id, tgt_id),
    ))
    stmts.append(("DELETE FROM watch_directive_hits WHERE directive_id=%s", (src_id,)))


def apply_plan(actions):
    """Execute in ONE transaction. Reassign hits (conflict-safe), relabel, then archive dups."""
    to_archive = [r["id"] for r in actions["dead"]]
    stmts = []
    # Tier 1a — relabel (stays active)
    for r in actions["relabel"]:
        stmts.append(("UPDATE watch_directives SET label=%s, updated_at=NOW() WHERE id=%s",
                      (r["new_label"], r["id"])))
    # Tier 1b — bare-dup merge into canonical
    for r in actions["malformed_merge"]:
        _reassign_and_archive(stmts, r["id"], r["target_id"])
        to_archive.append(r["id"])
    # Tier 3 — family merges
    for m in actions["merges"]:
        surv = m["survivor"]["id"]
        for d in m["dups"]:
            _reassign_and_archive(stmts, d["id"], surv)
            to_archive.append(d["id"])
    if to_archive:
        stmts.append((
            """UPDATE watch_directives
               SET status='archived', updated_at=NOW(),
                   rationale=COALESCE(rationale,'')||' [archived by watch_directive_dedup]'
               WHERE id = ANY(%s)""",
            (to_archive,),
        ))
    # db_adapter runs each _execute in its own commit; wrap explicitly for atomicity
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    try:
        for sql, params in stmts:
            cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    n_merged = len(actions["malformed_merge"]) + sum(len(m["dups"]) for m in actions["merges"])
    print(f"APPLIED: relabeled {len(actions['relabel'])}, archived {len(set(to_archive))} directives, "
          f"reassigned hits for {n_merged} merged dups.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute the plan (default: dry-run)")
    ap.add_argument("--tier", type=int, action="append", choices=[1, 2, 3], help="limit to tier(s)")
    args = ap.parse_args()
    tiers = set(args.tier) if args.tier else {1, 2, 3}
    actions = plan(tiers)
    print_plan(actions)
    if args.apply:
        apply_plan(actions)
    else:
        print("Dry-run only. Re-run with --apply to execute.")


if __name__ == "__main__":
    main()
