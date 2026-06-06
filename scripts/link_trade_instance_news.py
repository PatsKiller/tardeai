#!/usr/bin/env python3
"""link_trade_instance_news.py — structured news linkage for the canonical all-trades model.

Builds `trade_instance_news` (structured FK: trade_instance_id ↔ news_article_id, classified by trade
lifecycle window) and summary counts on trade_instances. Broker/account-neutral — matches any
trade_instance (paper or imported) to ticker news by symbol + published_at window. Read-only w.r.t.
trading; additive/idempotent analysis. Honest limitation: the news corpus is recent (~6 weeks), so older
imported trades will have no matches — never fabricated.

Windows (relative to entry_time / exit_time):
  pre_entry    [entry-3d, entry-1d)      — catalyst lead-up
  entry_window [entry-1d, entry+1d]      — news at entry
  hold_window  (entry+1d, coalesce(exit,now)-1d) — news during the hold
  exit_window  [exit-1d, exit+1d]        — news at exit (closed trades only)

  python3 scripts/link_trade_instance_news.py            # dry-run (counts only)
  python3 scripts/link_trade_instance_news.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras

DDL = """
CREATE TABLE IF NOT EXISTS trade_instance_news (
  id BIGSERIAL PRIMARY KEY,
  trade_instance_id BIGINT NOT NULL REFERENCES trade_instances(id),
  news_article_id BIGINT NOT NULL,
  symbol TEXT,
  relation TEXT NOT NULL,           -- pre_entry | entry_window | hold_window | exit_window
  published_at TIMESTAMPTZ,
  sentiment TEXT,
  relevance_score NUMERIC,
  is_attention_spike BOOLEAN,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (trade_instance_id, news_article_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_tin_ti ON trade_instance_news(trade_instance_id);
CREATE INDEX IF NOT EXISTS idx_tin_news ON trade_instance_news(news_article_id);
"""

ALTER = """
ALTER TABLE trade_instances
  ADD COLUMN IF NOT EXISTS news_pre_entry_count INTEGER,
  ADD COLUMN IF NOT EXISTS news_entry_count INTEGER,
  ADD COLUMN IF NOT EXISTS news_hold_count INTEGER,
  ADD COLUMN IF NOT EXISTS news_exit_count INTEGER;
"""

# Classify each (trade_instance, news) pair by window. Real tickers only on both sides.
LINK_INSERT = """
INSERT INTO trade_instance_news
  (trade_instance_id, news_article_id, symbol, relation, published_at, sentiment, relevance_score, is_attention_spike)
SELECT ti.id, n.id, ti.symbol,
  CASE
    WHEN n.published_at >= ti.entry_time - interval '1 day' AND n.published_at <= ti.entry_time + interval '1 day' THEN 'entry_window'
    WHEN ti.exit_time IS NOT NULL AND n.published_at >= ti.exit_time - interval '1 day' AND n.published_at <= ti.exit_time + interval '1 day' THEN 'exit_window'
    WHEN n.published_at > ti.entry_time + interval '1 day' AND n.published_at < COALESCE(ti.exit_time, now()) - interval '1 day' THEN 'hold_window'
    WHEN n.published_at >= ti.entry_time - interval '3 days' AND n.published_at < ti.entry_time - interval '1 day' THEN 'pre_entry'
  END AS relation,
  n.published_at, n.sentiment, n.relevance_score, n.is_attention_spike
FROM trade_instances ti
JOIN news_articles n
  ON n.symbol = ti.symbol
 AND n.symbol ~ '^[A-Z]{1,5}$'
 AND n.published_at IS NOT NULL
 AND ti.entry_time IS NOT NULL
 AND n.published_at >= ti.entry_time - interval '3 days'
 -- closed trades: full lifecycle (to exit+1d). OPEN trades: cap at entry+1d (entry/pre_entry only) so
 -- long-held open positions do NOT vacuum the whole recent-news corpus into a meaningless hold_window.
 AND n.published_at <= COALESCE(ti.exit_time + interval '1 day', ti.entry_time + interval '1 day')
WHERE CASE
    WHEN n.published_at >= ti.entry_time - interval '1 day' AND n.published_at <= ti.entry_time + interval '1 day' THEN 'entry_window'
    WHEN ti.exit_time IS NOT NULL AND n.published_at >= ti.exit_time - interval '1 day' AND n.published_at <= ti.exit_time + interval '1 day' THEN 'exit_window'
    WHEN n.published_at > ti.entry_time + interval '1 day' AND n.published_at < COALESCE(ti.exit_time, now()) - interval '1 day' THEN 'hold_window'
    WHEN n.published_at >= ti.entry_time - interval '3 days' AND n.published_at < ti.entry_time - interval '1 day' THEN 'pre_entry'
  END IS NOT NULL
ON CONFLICT (trade_instance_id, news_article_id, relation) DO NOTHING;
"""

SUMMARY = """
UPDATE trade_instances ti SET
  news_pre_entry_count = s.pre, news_entry_count = s.ent,
  news_hold_count = s.hold, news_exit_count = s.ex
FROM (
  SELECT base.id,
    count(tin.id) FILTER (WHERE relation='pre_entry') pre,
    count(tin.id) FILTER (WHERE relation='entry_window') ent,
    count(tin.id) FILTER (WHERE relation='hold_window') hold,
    count(tin.id) FILTER (WHERE relation='exit_window') ex
  FROM trade_instances base
  LEFT JOIN trade_instance_news tin ON tin.trade_instance_id = base.id
  GROUP BY base.id
) s WHERE s.id = ti.id;
"""


def main():
    apply = "--apply" in sys.argv
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if apply:
        cur.execute(DDL); cur.execute(ALTER); c.commit()
        cur.execute("DELETE FROM trade_instance_news")  # derived table — rebuild cleanly each run
        cur.execute(LINK_INSERT); cur.execute(SUMMARY); c.commit()

    def one(s):
        cur.execute(s); return cur.fetchone()["c"]
    rep = {"mode": "apply" if apply else "dry-run"}
    if one("select count(*) c from information_schema.tables where table_name='trade_instance_news'"):
        rep["news_links_total"] = one("select count(*) c from trade_instance_news")
        cur.execute("select relation, count(*) n from trade_instance_news group by 1 order by 2 desc")
        rep["by_relation"] = {r["relation"]: r["n"] for r in cur.fetchall()}
        cur.execute("""select ti.source_system, count(*) n from trade_instance_news tin
                       join trade_instances ti on ti.id=tin.trade_instance_id group by 1 order by 2 desc""")
        rep["by_source_system"] = {r["source_system"]: r["n"] for r in cur.fetchall()}
        rep["trade_instances_with_any_news"] = one("select count(distinct trade_instance_id) c from trade_instance_news")
        rep["with_entry_news"] = one("select count(*) c from trade_instances where coalesce(news_entry_count,0)>0")
        rep["with_hold_news"] = one("select count(*) c from trade_instances where coalesce(news_hold_count,0)>0")
        rep["with_exit_news"] = one("select count(*) c from trade_instances where coalesce(news_exit_count,0)>0")
        rep["total_trade_instances"] = one("select count(*) c from trade_instances")
    print(json.dumps(rep, indent=2, default=str))
    if "--json" in sys.argv:
        json.dump(rep, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=2, default=str)
    c.close()


if __name__ == "__main__":
    main()
