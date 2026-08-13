#!/usr/bin/env python3
"""hermes_outcome_grader.py — the Outcome Spine (Phase 2, docs/design/HERMES_MATURITY_5_DESIGN.md §2).

One canonical join from every Hermes claim to money, in hermes_outcome_ledger:

  promotion     every non-dry hermes_promotion_audit row with a symbol — graded +5/+20
                sessions excess return vs SPY
  external_rec  every sent hermes_external_research recommendation — direction parsed
                (long/short/neutral), graded direction-adjusted vs SPY
  research_row  symbol-linked hermes_research_intelligence — graded on ACTION (did a
                proposal / trade / directive hit follow?); also fills
                hermes_research_intelligence.downstream_outcome (was 100% NULL)
  trade         closed trade_instances — realized_r attached; claim records whether
                Hermes research existed at entry

Everything in Phases 3-5 (calibration, promotion gates, source curation, lane routing) reads
ONLY this ledger. Pure SQL + the daily-close cache — zero LLM. Advisory-only; honors
data/runtime/HERMES_DISABLED.

  python3 scripts/hermes_outcome_grader.py                 # dry-run summary
  python3 scripts/hermes_outcome_grader.py --apply         # seed + grade (nightly cron)
  python3 scripts/hermes_outcome_grader.py --apply --backfill-closes  # one-time full close backfill
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

KILL_SWITCH = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
CFG_FILE = PROJECT_ROOT / "config" / "hermes_outcome_grader.yaml"

_SHORT_PAT = re.compile(r"\b(sell|short|avoid|bearish|reduce|trim|exit|underweight)\b", re.I)
_LONG_PAT = re.compile(r"\b(buy|long|bullish|accumulate|add|overweight|strong)\b", re.I)


def _cfg():
    import yaml
    return yaml.safe_load(CFG_FILE.read_text())


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def rec_direction(text: str | None) -> str:
    t = (text or "")[:400]
    is_long, is_short = bool(_LONG_PAT.search(t)), bool(_SHORT_PAT.search(t))
    if is_long and not is_short:
        return "long"
    if is_short and not is_long:
        return "short"
    return "neutral"


# ── daily-close cache ─────────────────────────────────────────────────────────
def refresh_close_cache(cur, cfg, backfill=False):
    """Upsert daily closes from market_quotes (last quote per symbol per day); SPY additionally
    from price_cache. Nightly touches only the last few days; --backfill-closes does history."""
    window = "" if backfill else f"WHERE fetched_at >= NOW() - make_interval(days => {int(cfg['close_cache_refresh_days'])})"
    cur.execute(f"""INSERT INTO daily_close_cache (symbol, price_date, close_price, source)
                    SELECT DISTINCT ON (UPPER(symbol), fetched_at::date)
                           UPPER(symbol), fetched_at::date, price, 'market_quotes'
                    FROM market_quotes
                    {window}
                    {"AND" if window else "WHERE"} price IS NOT NULL AND price > 0
                    ORDER BY UPPER(symbol), fetched_at::date, fetched_at DESC
                    ON CONFLICT (symbol, price_date) DO UPDATE SET
                      close_price = EXCLUDED.close_price, source = EXCLUDED.source""")
    n_mq = cur.rowcount
    cur.execute("""INSERT INTO daily_close_cache (symbol, price_date, close_price, source)
                   SELECT UPPER(symbol), price_date, close_price, 'price_cache'
                   FROM price_cache WHERE close_price IS NOT NULL AND close_price > 0
                   ON CONFLICT (symbol, price_date) DO NOTHING""")
    return n_mq + cur.rowcount


def _sessions(cur, benchmark):
    cur.execute("SELECT price_date FROM daily_close_cache WHERE symbol=%s ORDER BY price_date",
                (benchmark.upper(),))
    return [r[0] for r in cur.fetchall()]


# ── seeding (idempotent) ─────────────────────────────────────────────────────
def seed(cur, cfg) -> dict:
    counts = {}
    # promotions (symbol via target research row)
    cur.execute("""INSERT INTO hermes_outcome_ledger (subject_type, subject_id, symbol, emitted_at, claim, direction)
                   SELECT 'promotion', pa.id, UPPER(hri.symbol), pa.promoted_at,
                          'promotion:' || COALESCE(pa.promotion_type,'unknown'), 'long'
                   FROM hermes_promotion_audit pa
                   JOIN hermes_research_intelligence hri
                     ON pa.target_table='hermes_research_intelligence' AND hri.id = pa.target_id
                   WHERE NOT pa.dry_run AND hri.symbol IS NOT NULL
                   ON CONFLICT (subject_type, subject_id) DO NOTHING""")
    counts["promotion"] = cur.rowcount
    # external recs (direction parsed in python — small batches of new rows only)
    cur.execute("""SELECT er.id, UPPER(er.symbol), er.created_at, LEFT(er.recommendation, 300), er.lane
                   FROM hermes_external_research er
                   LEFT JOIN hermes_outcome_ledger l
                     ON l.subject_type='external_rec' AND l.subject_id = er.id
                   WHERE er.status='sent' AND er.symbol IS NOT NULL AND er.recommendation IS NOT NULL
                     AND l.id IS NULL""")
    rows = cur.fetchall()
    for rid, sym, at, rec, lane in rows:
        cur.execute("""INSERT INTO hermes_outcome_ledger (subject_type, subject_id, symbol, emitted_at, claim, direction)
                       VALUES ('external_rec', %s, %s, %s, %s, %s)
                       ON CONFLICT (subject_type, subject_id) DO NOTHING""",
                    (rid, sym, at, f"rec:{lane}", rec_direction(rec)))
    counts["external_rec"] = len(rows)
    # research rows (action-graded)
    cur.execute("""INSERT INTO hermes_outcome_ledger (subject_type, subject_id, symbol, emitted_at, claim, direction)
                   SELECT 'research_row', hri.id, UPPER(hri.symbol), hri.created_at,
                          'research:' || COALESCE(hri.research_type,'unknown'), 'neutral'
                   FROM hermes_research_intelligence hri
                   LEFT JOIN hermes_outcome_ledger l
                     ON l.subject_type='research_row' AND l.subject_id = hri.id
                   WHERE hri.symbol IS NOT NULL AND l.id IS NULL
                   ON CONFLICT (subject_type, subject_id) DO NOTHING""")
    counts["research_row"] = cur.rowcount
    # trades (realized R + hermes-context flag)
    cur.execute("""INSERT INTO hermes_outcome_ledger (subject_type, subject_id, symbol, emitted_at, claim,
                                                      direction, trade_instance_id, realized_r)
                   SELECT 'trade', ti.id, UPPER(ti.symbol), ti.entry_time,
                          'trade:' || CASE WHEN EXISTS (
                              SELECT 1 FROM hermes_research_intelligence h
                              WHERE UPPER(h.symbol)=UPPER(ti.symbol)
                                AND h.created_at BETWEEN ti.entry_time - make_interval(days => %s)
                                                     AND ti.entry_time)
                            THEN 'with_hermes_context' ELSE 'no_hermes_context' END,
                          CASE WHEN LOWER(COALESCE(ti.side,'buy')) IN ('sell','short') THEN 'short' ELSE 'long' END,
                          ti.id, ti.r_multiple
                   FROM trade_instances ti
                   LEFT JOIN hermes_outcome_ledger l ON l.subject_type='trade' AND l.subject_id = ti.id
                   WHERE ti.exit_time IS NOT NULL AND ti.entry_time IS NOT NULL
                     AND ti.symbol IS NOT NULL AND l.id IS NULL
                   ON CONFLICT (subject_type, subject_id) DO NOTHING""",
                (cfg["trade_context_lookback_days"],))
    counts["trade"] = cur.rowcount
    return counts


# ── grading ──────────────────────────────────────────────────────────────────
def grade(cur, cfg, max_rows=None) -> dict:
    bench = cfg["benchmark"].upper()
    h5, h20 = int(cfg["horizons"]["short_sessions"]), int(cfg["horizons"]["long_sessions"])
    hit_pct, miss_pct = float(cfg["verdict"]["hit_pct"]), float(cfg["verdict"]["miss_pct"])
    sessions = _sessions(cur, bench)
    if len(sessions) < h20 + 1:
        return {"error": f"benchmark calendar too short ({len(sessions)} sessions)"}
    first_s, last_s = sessions[0], sessions[-1]

    import bisect
    def base_idx(d):
        i = bisect.bisect_right(sessions, d) - 1
        return i if i >= 0 else None

    # pending verdicts + verdict-holding rows whose 20d context prices haven't filled yet
    cur.execute(f"""SELECT id, subject_type, symbol, emitted_at::date, direction
                    FROM hermes_outcome_ledger
                    WHERE verdict='pending' OR (price_20d IS NULL AND verdict IN ('hit','miss','neutral'))
                    ORDER BY emitted_at LIMIT %s""", (max_rows or int(cfg["max_rows_per_run"]),))
    pending = cur.fetchall()
    if not pending:
        return {"graded": 0, "still_pending": 0}

    # bulk price lookup: every (symbol|SPY, session-date) we might need
    need_syms = sorted({p[2] for p in pending} | {bench})
    cur.execute("""SELECT symbol, price_date, close_price FROM daily_close_cache
                   WHERE symbol = ANY(%s) AND price_date BETWEEN %s AND %s""",
                (need_syms, first_s, last_s))
    px: dict[tuple, float] = {(r[0], r[1]): float(r[2]) for r in cur.fetchall()}

    def close_on(sym, i):
        """close at session index i, tolerating up to 2 missing days forward."""
        for j in (i, i + 1, i + 2):
            if 0 <= j < len(sessions):
                v = px.get((sym, sessions[j]))
                if v:
                    return v
        return None

    graded = still = ungradeable = 0
    now = datetime.now(timezone.utc)
    for lid, stype, sym, edate, direction in pending:
        # Price sets the VERDICT only for price-claims; research_row is action-graded and
        # trade is R/P&L-graded — for those, price columns are context and never a verdict.
        price_verdict = stype in ("promotion", "external_rec")
        bi = base_idx(edate)
        if bi is None:
            if price_verdict:
                cur.execute("UPDATE hermes_outcome_ledger SET verdict='ungradeable', graded_at=NOW() WHERE id=%s", (lid,))
                ungradeable += 1
            continue
        long_ready = bi + h20 < len(sessions)
        base = close_on(sym, bi); b_spy = close_on(bench, bi)
        if base is None or b_spy is None:
            # no price series for this symbol (delisted/OTC/fund)
            if long_ready and price_verdict:
                cur.execute("UPDATE hermes_outcome_ledger SET verdict='ungradeable', graded_at=NOW() WHERE id=%s", (lid,))
                ungradeable += 1
            else:
                still += 1
            continue

        def excess(h):
            p = close_on(sym, bi + h); s = close_on(bench, bi + h)
            if p is None or s is None:
                return None, None
            e = ((p / base) - (s / b_spy)) * 100.0
            return p, (e if direction != "short" else -e)

        p5, e5 = excess(h5) if bi + h5 < len(sessions) else (None, None)
        p20, e20 = excess(h20) if long_ready else (None, None)
        if not long_ready or e20 is None:
            if p5 is not None:
                cur.execute("""UPDATE hermes_outcome_ledger SET base_price=%s, price_5d=%s, outcome_ret_5d=%s
                               WHERE id=%s""", (base, p5, round(e5, 3) if e5 is not None else None, lid))
            still += 1
            continue
        if price_verdict:
            verdict = "hit" if e20 >= hit_pct else ("miss" if e20 <= miss_pct else "neutral")
            cur.execute("""UPDATE hermes_outcome_ledger
                           SET base_price=%s, price_5d=%s, price_20d=%s, outcome_ret_5d=%s, outcome_ret_20d=%s,
                               verdict=%s, graded_at=%s
                           WHERE id=%s""",
                        (base, p5, p20, round(e5, 3) if e5 is not None else None, round(e20, 3),
                         verdict, now, lid))
        else:
            cur.execute("""UPDATE hermes_outcome_ledger
                           SET base_price=%s, price_5d=%s, price_20d=%s, outcome_ret_5d=%s, outcome_ret_20d=%s
                           WHERE id=%s""",
                        (base, p5, p20, round(e5, 3) if e5 is not None else None, round(e20, 3), lid))
        graded += 1
    return {"graded": graded, "still_pending": still, "ungradeable": ungradeable,
            "sessions": len(sessions)}


def grade_research_actions(cur, cfg) -> dict:
    """Research rows: verdict = was it ACTIONED (proposal/trade/directive hit) within the window?
    Also fills hermes_research_intelligence.downstream_outcome (only where NULL)."""
    win = int(cfg["research_action_window_days"])
    cur.execute("""
        WITH r AS (
          SELECT l.id AS lid, l.subject_id AS hid, l.symbol, l.emitted_at
          FROM hermes_outcome_ledger l
          WHERE l.subject_type='research_row' AND l.actioned IS NULL
            AND l.emitted_at < NOW() - make_interval(days => %s)
        ), j AS (
          SELECT r.lid, r.hid,
            CASE
              WHEN EXISTS (SELECT 1 FROM trade_instances t WHERE UPPER(t.symbol)=r.symbol
                           AND t.entry_time BETWEEN r.emitted_at AND r.emitted_at + make_interval(days => %s)) THEN 'trade'
              WHEN EXISTS (SELECT 1 FROM paper_trade_proposals p WHERE UPPER(p.symbol)=r.symbol
                           AND p.created_at BETWEEN r.emitted_at AND r.emitted_at + make_interval(days => %s)) THEN 'proposal'
              WHEN EXISTS (SELECT 1 FROM watch_directive_hits h WHERE UPPER(h.symbol)=r.symbol
                           AND h.surfaced_at BETWEEN r.emitted_at AND r.emitted_at + make_interval(days => %s)) THEN 'directive_hit'
              ELSE 'none' END AS act
          FROM r
        )
        UPDATE hermes_outcome_ledger l SET actioned = j.act,
               verdict = CASE WHEN l.verdict='pending' AND j.act <> 'none' THEN 'hit'
                              WHEN l.verdict='pending' THEN 'neutral' ELSE l.verdict END,
               graded_at = COALESCE(l.graded_at, NOW())
        FROM j WHERE l.id = j.lid""", (win, win, win, win))
    n = cur.rowcount
    cur.execute("""UPDATE hermes_research_intelligence hri
                   SET downstream_outcome = l.actioned
                   FROM hermes_outcome_ledger l
                   WHERE l.subject_type='research_row' AND l.subject_id = hri.id
                     AND l.actioned IS NOT NULL AND hri.downstream_outcome IS NULL""")
    return {"research_actioned": n, "downstream_outcome_filled": cur.rowcount}


def grade_trades(cur) -> dict:
    """Trades grade on realized R / P&L, not price drift."""
    cur.execute("""UPDATE hermes_outcome_ledger l
                   SET realized_r = COALESCE(l.realized_r, ti.r_multiple),
                       verdict = CASE
                         WHEN COALESCE(ti.r_multiple, ti.pnl) IS NULL THEN 'ungradeable'
                         WHEN COALESCE(ti.r_multiple, 0) > 0 OR (ti.r_multiple IS NULL AND ti.pnl > 0) THEN 'hit'
                         WHEN COALESCE(ti.r_multiple, 0) < 0 OR (ti.r_multiple IS NULL AND ti.pnl < 0) THEN 'miss'
                         ELSE 'neutral' END,
                       graded_at = NOW()
                   FROM trade_instances ti
                   WHERE l.subject_type='trade' AND l.verdict='pending' AND ti.id = l.subject_id""")
    return {"trades_graded": cur.rowcount}


def writeback_trade_outcomes(cur) -> dict:
    """P2 reverse edge: fold graded trade outcomes back into the watchlist conviction ledger.

    Routes through lib.two_way_curation.write_realized_outcome so audit + overwrite
    semantics stay single-sourced. Advisory only.
    """
    from lib.two_way_curation import outcome_verdict_to_ledger, write_realized_outcome

    def _ex(sql, params=None, fetch=None):
        cur.execute(sql, params or ())
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        return True

    cur.execute("""SELECT UPPER(l.symbol) AS symbol, l.verdict
                   FROM hermes_outcome_ledger l
                   WHERE l.subject_type='trade' AND l.verdict IN ('hit','miss','neutral')
                     AND l.symbol IS NOT NULL""")
    rows = cur.fetchall()
    written = 0
    for row in rows:
        symbol = row["symbol"] if isinstance(row, dict) else row[0]
        verdict = row["verdict"] if isinstance(row, dict) else row[1]
        realized, thesis = outcome_verdict_to_ledger(verdict)
        if realized is None:
            continue
        res = write_realized_outcome(symbol, realized, thesis, executor=_ex, overwrite=True)
        if res.get("ok"):
            written += 1
    return {"outcomes_written": written}


def writeback_hermes_research(cur) -> dict:
    """P1 reverse edge: fold graded Hermes research action-outcomes into watchlist conviction.

    Routes through lib.two_way_curation.write_hermes_research (audit + single writer).
    """
    from lib.two_way_curation import hermes_research_score_from_action, write_hermes_research

    def _ex(sql, params=None, fetch=None):
        cur.execute(sql, params or ())
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        return True

    cur.execute("""SELECT UPPER(l.symbol) AS symbol, l.actioned
                   FROM hermes_outcome_ledger l
                   WHERE l.subject_type='research_row' AND l.actioned IS NOT NULL
                     AND l.symbol IS NOT NULL""")
    rows = cur.fetchall()
    written = 0
    for row in rows:
        symbol = row["symbol"] if isinstance(row, dict) else row[0]
        action = row["actioned"] if isinstance(row, dict) else row[1]
        score = hermes_research_score_from_action(action)
        if score is None:
            continue
        res = write_hermes_research(
            symbol, score,
            detail={"actioned": action, "source": "hermes_outcome_ledger"},
            executor=_ex,
        )
        if res.get("ok"):
            written += 1
    return {"hermes_research_written": written}


def run(apply=False, backfill_closes=False, max_rows=None) -> dict:
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — grader idle"}
        print(json.dumps(out))
        return out
    cfg = _cfg()
    conn = _conn(); cur = conn.cursor()
    out = {"ok": True, "apply": apply}
    if not apply:
        cur.execute("SELECT verdict, count(*) FROM hermes_outcome_ledger GROUP BY 1")
        out["ledger_now"] = {r[0]: r[1] for r in cur.fetchall()}
        out["note"] = "dry-run: no seed/grade performed (use --apply)"
        print(json.dumps(out, indent=2)); return out

    out["closes_upserted"] = refresh_close_cache(cur, cfg, backfill=backfill_closes)
    conn.commit()
    out["seeded"] = seed(cur, cfg); conn.commit()
    # Freeze factor components into the ledger at seed time — score-history retention (21d)
    # would otherwise eat the snapshots the outcome calibrator (Phase 3) needs.
    cur.execute("""UPDATE hermes_outcome_ledger l SET components = sub.components
                   FROM (SELECT l2.id AS lid, h.components
                         FROM hermes_outcome_ledger l2
                         JOIN LATERAL (SELECT components FROM hermes_score_history h
                                       WHERE h.symbol = l2.symbol AND h.scored_at <= l2.emitted_at
                                       ORDER BY h.scored_at DESC LIMIT 1) h ON true
                         WHERE l2.components IS NULL AND l2.created_at > NOW() - interval '3 days'
                           AND l2.subject_type IN ('promotion','external_rec','trade')) sub
                   WHERE l.id = sub.lid""")
    out["components_frozen"] = cur.rowcount
    conn.commit()
    out["priced"] = grade(cur, cfg, max_rows=max_rows); conn.commit()
    out["research"] = grade_research_actions(cur, cfg); conn.commit()
    out["trades"] = grade_trades(cur); conn.commit()
    out["outcome_writeback"] = writeback_trade_outcomes(cur); conn.commit()
    out["research_writeback"] = writeback_hermes_research(cur); conn.commit()
    cur.execute("SELECT subject_type, verdict, count(*) FROM hermes_outcome_ledger GROUP BY 1,2 ORDER BY 1,2")
    out["ledger"] = [f"{r[0]}/{r[1]}={r[2]}" for r in cur.fetchall()]
    out["ts"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backfill-closes", action="store_true",
                    help="one-time: build daily_close_cache from full market_quotes history")
    ap.add_argument("--max-rows", type=int, default=None)
    args = ap.parse_args()
    run(apply=args.apply, backfill_closes=args.backfill_closes, max_rows=args.max_rows)


if __name__ == "__main__":
    main()
