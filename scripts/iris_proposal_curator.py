#!/usr/bin/env python3
"""Iris taxonomy-proposal curator — closes the discovery loop.

Iris discovers aggressively (1,000+ taxonomy proposals) but nothing moved them out of
'pending', so they piled up and none were ever acted on. This curator drains the queue
on a sane, conservative policy so discovery actually closes:

  1. AUTO-APPLY  high-confidence, low-risk reclassify proposals (conf >= 0.85) — these
     only recategorize already-tracked channels. Sets status=approved then apply_proposal().
  2. EXPIRE      stale new_channel_discovery (> AGE_DAYS old). These are un-appliable
     (apply_proposal has no branch for them) and don't discriminate by confidence, so an
     unbounded backlog is pure noise; expiring is reversible (status flag) and they
     re-surface if still relevant.
  0. SUPERSEDE   duplicate pending proposals (same type, target and proposed state): the weekly scan
     re-created each finding every run (2026-10-09: 4,058 pending retire_channel rows were 32
     channels). The newest copy stays pending; older copies get status=superseded with a note naming
     the kept id. A status flag, never a delete, so it is reversible.
  3. REVIEW      add_channel / retire_channel stay pending — they change the source set,
     so a human approves them (via Telegram /approve_proposal as today).

Dry-run by default; pass --apply to write. Conservative thresholds are CLI-tunable.

    python3 scripts/iris_proposal_curator.py             # preview
    python3 scripts/iris_proposal_curator.py --apply
"""
import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [iris-curator] %(message)s")
log = logging.getLogger()



LANE_ID = "iris-proposal-curator"


def _receipt_lib():
    try:
        from scripts.lib import lane_last_receipt as lr
    except ImportError:
        from lib import lane_last_receipt as lr
    return lr

_DUPLICATES_CTE = """WITH ranked AS (
        SELECT id,
               first_value(id) OVER w AS keep_id,
               row_number() OVER w AS rn
        FROM iris_taxonomy_proposals
        WHERE status='pending'
        WINDOW w AS (PARTITION BY proposal_type, target, proposed_state ORDER BY created_at DESC, id DESC)
    )"""


def supersede_duplicates(cur, apply):
    """Count (and with apply, flag) pending proposals that duplicate a newer pending one. Returns the count."""
    cur.execute(_DUPLICATES_CTE + " SELECT COUNT(*) FROM ranked WHERE rn > 1")
    n = cur.fetchone()[0]
    if apply and n:
        cur.execute(_DUPLICATES_CTE + """
            UPDATE iris_taxonomy_proposals p
            SET status='superseded', reviewed_by='iris_curator', reviewed_at=NOW(),
                review_notes='superseded: duplicate of newer pending proposal #' || ranked.keep_id
            FROM ranked
            WHERE p.id = ranked.id AND ranked.rn > 1 AND p.status='pending'""")
        n = cur.rowcount
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--reclassify-conf", type=float, default=0.85, help="auto-apply reclassify >= this confidence")
    ap.add_argument("--discovery-age-days", type=int, default=14, help="expire new_channel_discovery older than this")
    ap.add_argument("--dry-run", action="store_true", help="offline plan; overrides --apply")
    args = ap.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN {LANE_ID}: would supersede duplicates, reclassify at "
              f"confidence>={args.reclassify_conf}, expire discovery after {args.discovery_age_days}d; "
              "add/retire channels remain pending human review")
        return 0
    lr = _receipt_lib()
    started = lr.now_iso()
    stats = {}
    try:
        rc = _run(args, stats)
    except BaseException as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="iris_proposal_curator.py", summary=stats, error=type(exc).__name__)
        raise
    lr.write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started,
                          script="iris_proposal_curator.py", summary=stats)
    return rc


def _run(args, stats):
    from db_adapter import get_connection
    conn = get_connection(); cur = conn.cursor()

    # 0. Supersede duplicate pending proposals (keep the newest of each)
    superseded = supersede_duplicates(cur, args.apply)
    if args.apply:
        conn.commit()

    # 1. Auto-apply high-confidence reclassify
    cur.execute("""SELECT id FROM iris_taxonomy_proposals
                   WHERE status='pending' AND proposal_type='reclassify' AND confidence >= %s
                   ORDER BY confidence DESC""", (args.reclassify_conf,))
    reclass_ids = [r[0] for r in cur.fetchall()]
    applied = 0
    if args.apply and reclass_ids:
        from iris_taxonomy_agent import apply_proposal
        for pid in reclass_ids:
            cur.execute("UPDATE iris_taxonomy_proposals SET status='approved', reviewed_by='iris_curator', reviewed_at=NOW() WHERE id=%s", (pid,))
            conn.commit()
            res = apply_proposal(pid)
            if res.get("ok") is not False:
                applied += 1
            else:
                log.warning("apply failed for #%s: %s", pid, res.get("error"))

    # 2. Expire stale un-appliable new_channel_discovery
    cur.execute("""SELECT COUNT(*) FROM iris_taxonomy_proposals
                   WHERE status='pending' AND proposal_type='new_channel_discovery'
                   AND created_at < NOW() - (%s || ' days')::interval""", (args.discovery_age_days,))
    expire_n = cur.fetchone()[0]
    if args.apply and expire_n:
        cur.execute("""UPDATE iris_taxonomy_proposals
                       SET status='expired', reviewed_by='iris_curator', reviewed_at=NOW(),
                           review_notes='auto-expired: stale un-appliable discovery (curator)'
                       WHERE status='pending' AND proposal_type='new_channel_discovery'
                       AND created_at < NOW() - (%s || ' days')::interval""", (args.discovery_age_days,))
        conn.commit()

    # 3. Report what's left for human review
    cur.execute("""SELECT proposal_type, COUNT(*) FROM iris_taxonomy_proposals
                   WHERE status='pending' AND proposal_type IN ('add_channel','retire_channel')
                   GROUP BY proposal_type ORDER BY 2 DESC""")
    review = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM iris_taxonomy_proposals WHERE status='pending'")
    still_pending = cur.fetchone()[0]
    conn.close()

    mode = "APPLIED" if args.apply else "DRY-RUN"
    log.info("[%s] duplicate pending proposals superseded: %d", mode, superseded)
    log.info("[%s] reclassify auto-apply: %d eligible%s", mode, len(reclass_ids),
             f", {applied} applied" if args.apply else "")
    log.info("[%s] stale discovery to expire (>%dd): %d", mode, args.discovery_age_days, expire_n)
    log.info("[%s] left for human review: %s", mode, ", ".join(f"{t}={n}" for t, n in review) or "none")
    log.info("[%s] pending after curation: %s", mode, still_pending if args.apply else "(unchanged in dry-run)")
    if not args.apply:
        log.info("Dry-run — re-run with --apply to write.")
    stats.update(superseded=superseded, eligible=len(reclass_ids), applied=applied,
                 stale_discovery=expire_n, pending=still_pending)
    return 1 if args.apply and applied < len(reclass_ids) else 0


if __name__ == "__main__":
    raise SystemExit(main())
