#!/usr/bin/env python3
"""Setup-Quality Prior + per-proposal advisory builder.

Distills the closed-trade entry grades (trade_backtest_results) and structured
LLM evaluations (trade_llm_reviews) into an aggregate "what kind of entry has
worked / not worked" prior, then attaches an ADVISORY (never a gate/block) to
proposals whose entry profile matches a historically weak setup.

Research/journaling-grade advisory. Advisory-only: this script never writes to
paper_trade_proposals and never affects execution or any safety gate. Every
output is labelled with sample size + confidence.

Rebuilds two summary tables each run (they are derived state, not historical):
  setup_quality_prior        — one row per RSI band
  proposal_setup_advisory    — one row per recent proposal that has an RSI
"""
import os
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s [setup-prior] %(message)s")
log = logging.getLogger("setup_quality_prior")

DB = dict(host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "5432")),
          dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
          password=os.getenv("DB_PASSWORD", ""))

DDL = """
CREATE TABLE IF NOT EXISTS setup_quality_prior (
  dimension text, band text, n int, win_rate numeric, avg_pnl numeric, avg_left numeric,
  grade_score numeric, llm_score numeric, dominant_verdict text, confidence text, note text,
  updated_at timestamptz DEFAULT now(), PRIMARY KEY (dimension, band)
);
CREATE TABLE IF NOT EXISTS proposal_setup_advisory (
  proposal_id bigint PRIMARY KEY, symbol text, status text, rsi numeric, band text,
  prior_score numeric, prior_win_rate numeric, prior_avg_left numeric, dominant_verdict text,
  confidence text, advisory_flag text, note text, updated_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS candidate_setup_advisory (
  entity_type text, symbol text, status text, rsi numeric, snapshot_date date, band text,
  prior_score numeric, prior_win_rate numeric, prior_avg_left numeric, dominant_verdict text,
  confidence text, advisory_flag text, note text, updated_at timestamptz DEFAULT now(),
  PRIMARY KEY (entity_type, symbol)
);
"""


def rsi_band(rsi):
    if rsi is None:
        return None
    rsi = float(rsi)
    return "<40" if rsi < 40 else "40-55" if rsi < 55 else "55-70" if rsi < 70 else ">70"


def conf(n):
    return "high" if n >= 15 else "medium" if n >= 8 else "low"


def build_prior(cur):
    # Structural stats per band from closed-trade grades
    cur.execute("""
        SELECT CASE WHEN entry_rsi<40 THEN '<40' WHEN entry_rsi<55 THEN '40-55'
                    WHEN entry_rsi<70 THEN '55-70' ELSE '>70' END AS band,
               COUNT(*) n,
               ROUND(100.0*SUM(CASE WHEN actual_pnl>0 THEN 1 ELSE 0 END)/COUNT(*),0) AS win_rate,
               ROUND(AVG(actual_pnl)::numeric,0) AS avg_pnl,
               ROUND(AVG(left_on_table_20d)::numeric,0) AS avg_left,
               ROUND(AVG(CASE entry_grade WHEN 'A' THEN 85 WHEN 'B' THEN 65 WHEN 'C' THEN 45 ELSE 25 END),0) AS grade_score
        FROM trade_backtest_results
        WHERE entry_rsi IS NOT NULL AND data_quality IN ('full','partial')
        GROUP BY 1
    """)
    struct = {r["band"]: r for r in cur.fetchall()}

    # Avg LLM overall score + dominant verdict per band (join evals to closed trades by symbol+date)
    cur.execute("""
        WITH ev AS (
          SELECT r.entry_rsi, v.eval_overall_score, v.eval_verdict
          FROM trade_llm_reviews v
          JOIN trade_backtest_results r
            ON r.symbol=v.symbol AND r.close_date = v.trade_close_date::date
          WHERE v.review_stage='structured_backtest_eval' AND v.eval_overall_score IS NOT NULL
        )
        SELECT CASE WHEN entry_rsi<40 THEN '<40' WHEN entry_rsi<55 THEN '40-55'
                    WHEN entry_rsi<70 THEN '55-70' ELSE '>70' END AS band,
               ROUND(AVG(eval_overall_score),0) AS llm_score,
               MODE() WITHIN GROUP (ORDER BY eval_verdict) AS dominant_verdict
        FROM ev GROUP BY 1
    """)
    llm = {r["band"]: r for r in cur.fetchall()}

    cur.execute("TRUNCATE setup_quality_prior")
    bands = ["<40", "40-55", "55-70", ">70"]
    for b in bands:
        s = struct.get(b)
        if not s:
            continue
        l = llm.get(b, {})
        n = s["n"]
        note = (f"Entries at RSI {b}: {s['win_rate']}% win, ${s['avg_left']} avg left on table "
                f"(n={n}, {conf(n)} confidence).")
        cur.execute("""
            INSERT INTO setup_quality_prior
              (dimension, band, n, win_rate, avg_pnl, avg_left, grade_score, llm_score, dominant_verdict, confidence, note, updated_at)
            VALUES ('rsi_band',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
        """, [b, n, s["win_rate"], s["avg_pnl"], s["avg_left"], s["grade_score"],
              l.get("llm_score"), l.get("dominant_verdict"), conf(n), note])
    log.info("prior rebuilt: %d band(s)", len([b for b in bands if b in struct]))
    return struct, llm


def build_advisories(cur, struct, llm):
    cur.execute("""
        SELECT id, symbol, status, rsi FROM paper_trade_proposals
        WHERE rsi IS NOT NULL AND created_at > now() - interval '90 days'
    """)
    props = cur.fetchall()
    cur.execute("TRUNCATE proposal_setup_advisory")
    written = 0
    for p in props:
        b = rsi_band(p["rsi"])
        s = struct.get(b)
        if not s:
            continue
        n = s["n"]
        score = (llm.get(b) or {}).get("llm_score")
        score = float(score) if score is not None else float(s["grade_score"])
        wr = float(s["win_rate"]); left = float(s["avg_left"])
        # Advisory flag (never a block): caution when the band historically underperforms.
        if score < 40 or (wr < 50 and left > 3000):
            flag = "caution"
        elif score >= 60 and wr >= 60:
            flag = "favorable"
        else:
            flag = "neutral"
        verdict = (llm.get(b) or {}).get("dominant_verdict")
        guide = ""
        if flag == "caution":
            guide = " Consider waiting for a pullback to a lower-RSI / fib entry." if b in (">70", "55-70") else " Historically weak band."
        note = (f"RSI {p['rsi']:.0f} → band {b}: {wr:.0f}% win, ${left:.0f} avg left on table, "
                f"prior score ~{score:.0f}/100 (n={n}, {conf(n)} conf)."
                + (f" Dominant verdict: {verdict}." if verdict else "") + guide)
        cur.execute("""
            INSERT INTO proposal_setup_advisory
              (proposal_id, symbol, status, rsi, band, prior_score, prior_win_rate, prior_avg_left,
               dominant_verdict, confidence, advisory_flag, note, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
        """, [p["id"], p["symbol"], p["status"], p["rsi"], b, round(score, 0), wr, left,
              verdict, conf(n), flag, note])
        written += 1
    log.info("advisories written: %d (of %d proposals with RSI)", written, len(props))


def build_candidate_advisories(cur, struct, llm):
    """Attach the same advisory to candidate symbols in the incubator + watchlist.
    Uses each symbol's latest RSI from ticker_snapshot_daily. Advisory-only — never
    changes incubator scoring/promotion or watchlist status."""
    cur.execute("TRUNCATE candidate_setup_advisory")
    sources = [
        ("incubator", "SELECT symbol, status FROM incubator_universe WHERE status='ACTIVE'"),
        ("watchlist", "SELECT symbol, status FROM watchlist_items WHERE status='active'"),
    ]
    total = 0
    for entity, q in sources:
        cur.execute(q)
        items = cur.fetchall()
        written = 0
        for it in items:
            cur.execute("""SELECT rsi, snapshot_date FROM ticker_snapshot_daily
                           WHERE symbol=%s AND rsi IS NOT NULL ORDER BY snapshot_date DESC LIMIT 1""", [it["symbol"]])
            snap = cur.fetchone()
            if not snap:
                continue
            b = rsi_band(snap["rsi"])
            s = struct.get(b)
            if not s:
                continue
            n = s["n"]
            score = (llm.get(b) or {}).get("llm_score")
            score = float(score) if score is not None else float(s["grade_score"])
            wr = float(s["win_rate"]); left = float(s["avg_left"])
            if score < 40 or (wr < 50 and left > 3000):
                flag = "caution"
            elif score >= 60 and wr >= 60:
                flag = "favorable"
            else:
                flag = "neutral"
            verdict = (llm.get(b) or {}).get("dominant_verdict")
            guide = (" Currently in a historically weak entry band — wait for a pullback / better setup."
                     if flag == "caution" else "")
            note = (f"Currently RSI {float(snap['rsi']):.0f} → band {b}: {wr:.0f}% win, ${left:.0f} avg left "
                    f"on table, prior score ~{score:.0f}/100 (n={n}, {conf(n)} conf)."
                    + (f" Dominant verdict: {verdict}." if verdict else "") + guide)
            cur.execute("""
                INSERT INTO candidate_setup_advisory
                  (entity_type, symbol, status, rsi, snapshot_date, band, prior_score, prior_win_rate,
                   prior_avg_left, dominant_verdict, confidence, advisory_flag, note, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (entity_type, symbol) DO NOTHING
            """, [entity, it["symbol"], it["status"], snap["rsi"], snap["snapshot_date"], b,
                  round(score, 0), wr, left, verdict, conf(n), flag, note])
            written += cur.rowcount
        log.info("%s advisories written: %d (of %d active)", entity, written, len(items))
        total += written
    return total


def main():
    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(DDL)
    struct, llm = build_prior(cur)
    build_advisories(cur, struct, llm)
    build_candidate_advisories(cur, struct, llm)
    conn.close()
    log.info("done (advisory-only; no proposal/incubator/watchlist mutation)")


if __name__ == "__main__":
    main()
