#!/usr/bin/env python3
"""backfill_hermes_trade_links.py — Step-2 backfill of hermes_research_intelligence.related_trade_id /
related_proposal_id for TRADE-REFLECTION research types, only where the symbol maps unambiguously (1:1)
to a paper_trade / open proposal. Conservative: never fabricates, never overwrites a non-NULL link.

  python3 scripts/backfill_hermes_trade_links.py            # dry-run
  python3 scripts/backfill_hermes_trade_links.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras

REFLECTION_TYPES = ("ticker_thesis_challenge", "trade_reflection")


def _conn():
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])


def main():
    apply = "--apply" in sys.argv
    c = _conn(); cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("select count(*) c from hermes_research_intelligence"); total = cur.fetchone()["c"]
    cur.execute("select count(*) c from hermes_research_intelligence where related_trade_id is not null"); before_t = cur.fetchone()["c"]
    cur.execute("select count(*) c from hermes_research_intelligence where related_proposal_id is not null"); before_p = cur.fetchone()["c"]
    cur.execute("""select id, symbol, research_type from hermes_research_intelligence
                   where research_type = ANY(%s) and symbol is not null
                   and (related_trade_id is null or related_proposal_id is null)""", (list(REFLECTION_TYPES),))
    rows = cur.fetchall()
    set_t = set_p = ambig = nomatch = 0
    for r in rows:
        sym = r["symbol"]
        cur.execute("select id from paper_trades where symbol=%s order by id", (sym,))
        pts = [x["id"] for x in cur.fetchall()]
        cur.execute("""select id from paper_trade_proposals where symbol=%s
                       and status in ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST','MODIFIED') order by id""", (sym,))
        props = [x["id"] for x in cur.fetchall()]
        rtid = pts[0] if len(pts) == 1 else None
        rpid = props[0] if len(props) == 1 else None
        if rtid is None and rpid is None:
            if len(pts) > 1 or len(props) > 1:
                ambig += 1
            else:
                nomatch += 1
            continue
        if apply:
            cur.execute("""update hermes_research_intelligence
                           set related_trade_id=COALESCE(related_trade_id,%s),
                               related_proposal_id=COALESCE(related_proposal_id,%s), updated_at=now()
                           where id=%s""", (rtid, rpid, r["id"]))
        if rtid is not None:
            set_t += 1
        if rpid is not None:
            set_p += 1
    if apply:
        c.commit()
    cur.execute("select count(*) c from hermes_research_intelligence where related_trade_id is not null"); after_t = cur.fetchone()["c"]
    cur.execute("select count(*) c from hermes_research_intelligence where related_proposal_id is not null"); after_p = cur.fetchone()["c"]
    print(json.dumps({"mode": "apply" if apply else "dry-run", "total_rows": total,
                      "reflection_rows_considered": len(rows),
                      "related_trade_id": f"{before_t} -> {after_t} (+{set_t} unique 1:1)",
                      "related_proposal_id": f"{before_p} -> {after_p} (+{set_p} unique 1:1)",
                      "skipped_ambiguous": ambig, "skipped_no_match": nomatch}, indent=2))
    c.close()


if __name__ == "__main__":
    main()
