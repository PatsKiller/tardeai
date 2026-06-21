#!/usr/bin/env python3
"""reclassify_knowledge_directives.py — one-time cleanup for the watch-directive clutter (operator 2026-06-21).

Knowledge/planning trend directives (Roth/Medicare/MAPT/income-planning research themes) were created as
ticker-discovery watch_directives by the old `add-topic` path, then sat at "0 hits · 0 staged" forever —
flooding the Watchlist's Watch Directives section and making the ticker-discovery cron chase tickers for
"Roth conversion ladder". The API now routes these to the research pipeline only (api_v2._watch_directive_create);
this backfills the EXISTING ones: mirror each into topic_monitor (the knowledge-research path, idempotent),
then archive the directive so it leaves the active watchlist set.

Only touches: kind='trend', status='active', 0 hits, 0 staged, theme matches the planning regex. Anything
with a hit/stage, any ticker/sector directive, and any genuine ticker-discovery trend are left untouched.

  python3 scripts/reclassify_knowledge_directives.py            # dry-run (default) — prints what it WOULD do
  python3 scripts/reclassify_knowledge_directives.py --apply    # mirror to topic_monitor + archive
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

# Same classifier the API uses (api_v2._watch_directive_create) — keep them in lock-step.
PLANNING_RX = re.compile(r"roth|irmaa|medicaid|medicare|ssdi|estate|trust|mapt|retire|tax|"
                         r"conversion|dividend|covered call|income|cef|pty|nav|annuit", re.I)
CTX = ("Operator age 58 (59 Aug 2026), SSDI, NY, Medicare ~Dec 2026, Golden-Window Roth, MAPT "
       "asset protection, ~$1.2M portfolio.")


def _theme_of(label, spec):
    theme = re.sub(r"^trend\s+", "", label or "", flags=re.I).strip()
    kws = [k for k in ((spec or {}).get("keywords") or []) if k]
    return theme, kws


def run(apply=False):
    conn = _get_conn()
    cur = conn.cursor()
    # active trend directives with NO hits (hits live in watch_directive_hits, joined by directive_id;
    # staged is a subset of hits, so "no hits" ⇒ "0 hits · 0 staged"). Genuine ticker-discovery trends
    # ("AI datacenter", "Defense") have hits and are excluded here.
    cur.execute("""
        SELECT d.id, d.label, d.spec
        FROM watch_directives d
        WHERE d.kind='trend' AND d.status='active'
          AND NOT EXISTS (SELECT 1 FROM watch_directive_hits h WHERE h.directive_id = d.id)
        ORDER BY d.id""")
    rows = [(r[0], r[1], r[2], 0, 0) for r in cur.fetchall()]

    existing_topics = set()
    try:
        cur.execute("SELECT topic_id FROM topic_monitor")
        existing_topics = {r[0] for r in cur.fetchall()}
    except Exception:
        pass

    targets = []
    for did, label, spec, hits, staged in rows:
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except Exception:
                spec = {}
        theme, kws = _theme_of(label, spec or {})
        if not PLANNING_RX.search(theme + " " + " ".join(kws)):
            continue
        tid = "k_" + re.sub(r"[^a-z0-9]+", "_", theme.lower()).strip("_")[:46]
        targets.append({"id": did, "theme": theme[:70], "kws": kws[:8], "tid": tid,
                        "already_topic": tid in existing_topics})

    print(f"{'APPLY' if apply else 'DRY-RUN'} · {len(rows)} active 0-activity trend directives scanned · "
          f"{len(targets)} knowledge/planning themes to reclassify")
    for t in targets:
        print(f"  d{t['id']:>4}  {'(topic exists)' if t['already_topic'] else '→ new topic '}  "
              f"{t['tid'][:40]:<40}  {t['theme']}")

    if not apply:
        print("\n(dry-run — re-run with --apply to mirror to topic_monitor + archive these directives)")
        return 0

    mirrored, archived = 0, 0
    for t in targets:
        try:
            if not t["already_topic"]:
                cur.execute("""INSERT INTO topic_monitor (topic_id, display_name, search_queries, priority,
                                 agent_owner, owner, enabled, max_age_days, min_articles, personal_context)
                               VALUES (%s,%s,%s::jsonb,2,'Steph','shared',true,30,3,%s)
                               ON CONFLICT (topic_id) DO NOTHING""",
                            (t["tid"], t["theme"][:80], json.dumps(t["kws"] or [t["theme"]]), CTX))
                mirrored += 1
            cur.execute("UPDATE watch_directives SET status='archived', updated_at=now() WHERE id=%s", (t["id"],))
            archived += 1
        except Exception as e:
            print(f"  ! d{t['id']} failed: {str(e)[:120]}")
            conn.rollback()
            continue
    conn.commit()
    print(f"\n✓ mirrored {mirrored} new research topic(s) → topic_monitor · archived {archived} directive(s)")
    return 0


if __name__ == "__main__":
    sys.exit(run(apply="--apply" in sys.argv))
