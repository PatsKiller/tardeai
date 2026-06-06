#!/usr/bin/env python3
"""persist_shadow_scores.py — Step 5: DB-persist shadow scores (keyed to candidate) + close the
loop-closure flag (proposal_outcome_chain.outcome_fed_back) when learning is derived for a trade.

- candidate_shadow_scores: one row per (symbol, strategy, run_timestamp); loaded from the file-based
  shadow scorer output and written by the scorer going forward (persist(output)).
- outcome_fed_back: set TRUE for an outcome chain when its paper_trade has a derived lesson,
  edge-comparison, or Hermes trade-reflection (i.e. the outcome actually fed learning).

Read-only w.r.t. trading. No GO/WAIT/strategy/order changes.
  python3 scripts/persist_shadow_scores.py            # dry-run
  python3 scripts/persist_shadow_scores.py --apply
"""
import os, sys, json, glob, psycopg2, psycopg2.extras

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADOW_DIR = os.path.join(ROOT, "data", "learning", "shadow_scores")

DDL = """
CREATE TABLE IF NOT EXISTS candidate_shadow_scores (
  id SERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  strategy TEXT,
  original_score NUMERIC,
  shadow_score NUMERIC,
  delta NUMERIC,
  decision TEXT,
  adjustment_count INTEGER,
  learning_adjustments JSONB,
  run_timestamp TIMESTAMPTZ,
  scored_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (symbol, strategy, run_timestamp)
);
CREATE INDEX IF NOT EXISTS idx_css_symbol ON candidate_shadow_scores(symbol);
"""


def _conn():
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])


def persist(output, conn=None):
    """Persist a shadow_score() output dict into candidate_shadow_scores. Returns rows written."""
    own = conn is None
    conn = conn or _conn()
    cur = conn.cursor()
    cur.execute(DDL)
    ts = output.get("timestamp")
    n = 0
    for r in output.get("results", []):
        cur.execute("""
            INSERT INTO candidate_shadow_scores
              (symbol, strategy, original_score, shadow_score, delta, decision, adjustment_count,
               learning_adjustments, run_timestamp)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (symbol, strategy, run_timestamp) DO UPDATE SET
              original_score=EXCLUDED.original_score, shadow_score=EXCLUDED.shadow_score,
              delta=EXCLUDED.delta, decision=EXCLUDED.decision, adjustment_count=EXCLUDED.adjustment_count,
              learning_adjustments=EXCLUDED.learning_adjustments
        """, (r.get("symbol"), r.get("strategy"), r.get("original_score"), r.get("shadow_score"),
              r.get("delta"), r.get("decision"), r.get("adjustment_count"),
              json.dumps(r.get("learning_adjustments") or []), ts))
        n += 1
    conn.commit()
    if own:
        conn.close()
    return n


def main():
    apply = "--apply" in sys.argv
    c = _conn(); cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # ── A. load file-based shadow scores into DB ──
    files = sorted(glob.glob(os.path.join(SHADOW_DIR, "*shadow_scores.json")))
    loaded = 0
    if apply:
        cur.execute(DDL); c.commit()
        for f in files:
            try:
                out = json.load(open(f))
                loaded += persist(out, c)
            except Exception as e:
                print(f"  skip {os.path.basename(f)}: {e}")
    cur.execute("select count(*) c from information_schema.tables where table_name='candidate_shadow_scores'")
    has_tbl = cur.fetchone()["c"] > 0
    css_rows = 0
    if has_tbl:
        cur.execute("select count(*) c from candidate_shadow_scores"); css_rows = cur.fetchone()["c"]
    # ── B. close outcome_fed_back where learning was derived ──
    cur.execute("select count(*) c, count(*) filter(where outcome_fed_back) fed from proposal_outcome_chain")
    b = cur.fetchone(); before_fed = b["fed"]
    sql_set = """
        UPDATE proposal_outcome_chain oc
        SET outcome_fed_back = TRUE, feedback_at = COALESCE(feedback_at, now()), updated_at = now()
        WHERE oc.outcome_fed_back IS NOT TRUE AND oc.paper_trade_id IS NOT NULL
          AND (EXISTS (SELECT 1 FROM trade_lesson_memory l WHERE l.trade_id = oc.paper_trade_id)
            OR EXISTS (SELECT 1 FROM paper_trade_edge_comparison e WHERE e.paper_trade_id = oc.paper_trade_id)
            OR EXISTS (SELECT 1 FROM hermes_research_intelligence h WHERE h.related_trade_id = oc.paper_trade_id))
    """
    cur.execute("select count(*) c from proposal_outcome_chain oc where oc.outcome_fed_back is not true and oc.paper_trade_id is not null and ("
                "exists(select 1 from trade_lesson_memory l where l.trade_id=oc.paper_trade_id)"
                " or exists(select 1 from paper_trade_edge_comparison e where e.paper_trade_id=oc.paper_trade_id)"
                " or exists(select 1 from hermes_research_intelligence h where h.related_trade_id=oc.paper_trade_id))")
    would_set = cur.fetchone()["c"]
    if apply:
        cur.execute(sql_set); c.commit()
    cur.execute("select count(*) c, count(*) filter(where outcome_fed_back) fed from proposal_outcome_chain")
    a = cur.fetchone()
    print(json.dumps({"mode": "apply" if apply else "dry-run",
                      "shadow_files": [os.path.basename(f) for f in files], "shadow_rows_loaded": loaded,
                      "candidate_shadow_scores_total": css_rows,
                      "outcome_fed_back": f"{before_fed} -> {a['fed']} (of {a['c']})", "would_set_fed_back": would_set}, indent=2))
    c.close()


if __name__ == "__main__":
    main()
