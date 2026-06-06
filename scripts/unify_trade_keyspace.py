#!/usr/bin/env python3
"""unify_trade_keyspace.py — Step 3: unify the journal/backtest keyspace with the paper loop.

Adds (additive, idempotent):
  - paper_trades.trade_key  TEXT   = SYMBOL:account:entry_date  (the universal trade key)
  - journal_trade_reviews.paper_trade_id   BIGINT
  - trade_backtest_results.paper_trade_id  BIGINT
Backfills paper_trades.trade_key for all rows, and journal/backtest.paper_trade_id ONLY where the
trade_key maps 1:1 to a paper_trade (never fuzzy, never overwrites). Reports coverage.

  python3 scripts/unify_trade_keyspace.py            # dry-run (no writes)
  python3 scripts/unify_trade_keyspace.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras


def _conn():
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])


def main():
    apply = "--apply" in sys.argv
    c = _conn(); cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if apply:
        cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS trade_key TEXT")
        cur.execute("ALTER TABLE journal_trade_reviews ADD COLUMN IF NOT EXISTS paper_trade_id BIGINT")
        cur.execute("ALTER TABLE trade_backtest_results ADD COLUMN IF NOT EXISTS paper_trade_id BIGINT")
        # backfill the universal key on paper_trades — convention matches journal/backtest:
        # symbol:account:CLOSE_date (fall back to entry date for still-open trades).
        cur.execute("""UPDATE paper_trades
                       SET trade_key = symbol || ':' || COALESCE(account,'') || ':' ||
                                       COALESCE(exit_time::date::text, entry_time::date::text, '')
                       WHERE symbol IS NOT NULL
                         AND (trade_key IS NULL
                              OR trade_key <> symbol || ':' || COALESCE(account,'') || ':' ||
                                 COALESCE(exit_time::date::text, entry_time::date::text, ''))""")
        c.commit()

    # build paper_trade key map (only if column exists)
    cur.execute("select column_name from information_schema.columns where table_name='paper_trades' and column_name='trade_key'")
    has_pt_key = bool(cur.fetchone())
    keymap = {}
    if has_pt_key:
        cur.execute("select trade_key, array_agg(id) ids from paper_trades where trade_key is not null group by trade_key")
        keymap = {r["trade_key"]: r["ids"] for r in cur.fetchall()}

    stats = {"mode": "apply" if apply else "dry-run"}
    for tbl in ("journal_trade_reviews", "trade_backtest_results"):
        cur.execute(f"select id, trade_key from {tbl} where trade_key is not null")
        rows = cur.fetchall()
        match = ambig = nomatch = 0
        for r in rows:
            ids = keymap.get(r["trade_key"])
            if not ids:
                nomatch += 1
            elif len(ids) == 1:
                match += 1
                if apply:
                    cur.execute(f"update {tbl} set paper_trade_id=%s where id=%s and paper_trade_id is null", (ids[0], r["id"]))
            else:
                ambig += 1
        stats[tbl] = {"rows": len(rows), "linked_1to1": match, "ambiguous": ambig, "no_paper_trade": nomatch}
    if apply:
        c.commit()
        cur.execute("select count(*) c from paper_trades where trade_key is not null"); stats["paper_trades_with_trade_key"] = cur.fetchone()["c"]
    print(json.dumps(stats, indent=2))
    c.close()


if __name__ == "__main__":
    main()
