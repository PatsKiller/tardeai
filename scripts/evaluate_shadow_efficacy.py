#!/usr/bin/env python3
"""evaluate_shadow_efficacy.py — Step 6: lessons → scoring, SHADOW-FIRST evidence layer.

Measures whether the lesson-adjusted shadow scores (candidate_shadow_scores) would have improved
decisions, using realized paper-trade outcomes. Produces evidence ONLY — it never changes production
GO/WAIT or strategy scoring. Grafting lessons into production is an explicit, operator-gated decision
that requires this evidence to clear a sample-size + hit-rate bar first.

Classification (per shadow-scored candidate that became a closed paper trade):
  - shadow MORE cautious (delta<0): "correct" if outcome was non-WIN (LOSS/BREAKEVEN/PHANTOM) — the
    penalty would have de-prioritized a non-winner; "wrong" if outcome was WIN (would have missed it).
  - shadow MORE bullish (delta>0): "correct" if WIN; "wrong" if non-WIN.
  - delta==0: neutral.

  python3 scripts/evaluate_shadow_efficacy.py            # dry-run
  python3 scripts/evaluate_shadow_efficacy.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras

MIN_SAMPLES = 20   # do-not-graft below this; statistical floor
MIN_HITRATE = 0.60

DDL = """
CREATE TABLE IF NOT EXISTS candidate_shadow_efficacy (
  id SERIAL PRIMARY KEY,
  symbol TEXT, strategy TEXT, paper_trade_id BIGINT,
  original_score NUMERIC, shadow_score NUMERIC, delta NUMERIC,
  realized_verdict TEXT, realized_r NUMERIC,
  shadow_assessment TEXT,          -- correct | wrong | neutral
  evaluated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (symbol, strategy, paper_trade_id)
);
"""


def _conn():
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])


def main():
    apply = "--apply" in sys.argv
    c = _conn(); cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if apply:
        cur.execute(DDL); c.commit()
    # latest shadow score per symbol+strategy joined to its closed paper trade
    cur.execute("""
        SELECT DISTINCT ON (css.symbol, css.strategy)
               css.symbol, css.strategy, css.original_score, css.shadow_score, css.delta,
               p.id AS paper_trade_id, p.outcome_verdict, p.r_multiple
        FROM candidate_shadow_scores css
        JOIN paper_trades p
          ON p.symbol = css.symbol
         AND (lower(coalesce(p.status,''))='closed' OR p.exit_time IS NOT NULL)
        ORDER BY css.symbol, css.strategy, css.run_timestamp DESC NULLS LAST, p.id DESC
    """)
    rows = cur.fetchall()
    correct = wrong = neutral = 0
    samples = []
    for r in rows:
        verdict = (r["outcome_verdict"] or "").upper()
        delta = float(r["delta"]) if r["delta"] is not None else 0.0
        if verdict == "PHANTOM" or verdict == "":
            # no real outcome → treat as non-winner for "cautious correct", but flag separately
            won = False
        else:
            won = verdict == "WIN"
        if delta < 0:
            assess = "correct" if not won else "wrong"
        elif delta > 0:
            assess = "correct" if won else "wrong"
        else:
            assess = "neutral"
        correct += assess == "correct"; wrong += assess == "wrong"; neutral += assess == "neutral"
        samples.append({"symbol": r["symbol"], "strategy": r["strategy"], "delta": delta,
                        "verdict": verdict or "NONE", "assessment": assess})
        if apply:
            cur.execute("""INSERT INTO candidate_shadow_efficacy
                (symbol,strategy,paper_trade_id,original_score,shadow_score,delta,realized_verdict,realized_r,shadow_assessment)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (symbol,strategy,paper_trade_id) DO UPDATE SET
                  shadow_assessment=EXCLUDED.shadow_assessment, delta=EXCLUDED.delta, realized_verdict=EXCLUDED.realized_verdict,
                  realized_r=EXCLUDED.realized_r, evaluated_at=now()""",
                (r["symbol"], r["strategy"], r["paper_trade_id"], r["original_score"], r["shadow_score"],
                 r["delta"], verdict or None, r["r_multiple"], assess))
    if apply:
        c.commit()
    decisive = correct + wrong
    hit_rate = (correct / decisive) if decisive else None
    n = len(rows)
    if n < MIN_SAMPLES:
        verdict = "INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT"
    elif hit_rate is not None and hit_rate >= MIN_HITRATE:
        verdict = "EVIDENCE_SUPPORTS_GRAFT_PENDING_OPERATOR_APPROVAL"
    else:
        verdict = "EVIDENCE_INSUFFICIENT_OR_NEGATIVE_DO_NOT_GRAFT"
    print(json.dumps({"mode": "apply" if apply else "dry-run", "evaluable_candidates": n,
                      "correct": correct, "wrong": wrong, "neutral": neutral,
                      "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
                      "min_samples_required": MIN_SAMPLES, "min_hitrate_required": MIN_HITRATE,
                      "graft_verdict": verdict, "samples": samples}, indent=2))
    c.close()


if __name__ == "__main__":
    main()
