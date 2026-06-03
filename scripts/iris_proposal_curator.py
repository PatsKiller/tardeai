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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--reclassify-conf", type=float, default=0.85, help="auto-apply reclassify >= this confidence")
    ap.add_argument("--discovery-age-days", type=int, default=14, help="expire new_channel_discovery older than this")
    args = ap.parse_args()

    from db_adapter import get_connection
    conn = get_connection(); cur = conn.cursor()

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
    log.info("[%s] reclassify auto-apply: %d eligible%s", mode, len(reclass_ids),
             f", {applied} applied" if args.apply else "")
    log.info("[%s] stale discovery to expire (>%dd): %d", mode, args.discovery_age_days, expire_n)
    log.info("[%s] left for human review: %s", mode, ", ".join(f"{t}={n}" for t, n in review) or "none")
    log.info("[%s] pending after curation: %d", mode, still_pending if args.apply else "(unchanged in dry-run)")
    if not args.apply:
        log.info("Dry-run — re-run with --apply to write.")


if __name__ == "__main__":
    main()
