"""
agent_outcome_scorer.py — Weekly: score agent recommendations against closed trades.
Cron (crontab L275): Sunday 11:00, ``--apply``. (This docstring said "5:30 AM daily" until 2026-10-10.)
Feeds calibration data back to agents.

Loop: trade_close → score → calibration → agent prompt → adjusted confidence

CLI (n8n refactor wave 3, 2026-10-10). Until now the script parsed NO arguments: the cron's ``--apply``
was ignored and ``--dry-run`` (advertised as ``safe_dry_run_cmd`` in pipeline_stage_owner_map.py) ran a
LIVE scoring. Now:

* ``--dry-run`` (wins over ``--apply``): READ ONLY session, runs ``match_and_score`` (SELECT only) and
  read-only previews of the calibration / rules / source-performance stages, prints a ``DRY-RUN``
  report and returns BEFORE ``PipelineRun`` (pipeline telemetry) or any save/rebuild/write stage is
  reachable. It writes no receipt.
* ``--apply`` or no flag: the live run, unchanged (no flag stays live because
  pipeline_registry.py's remediation command runs it bare). Writes LaneRunReceipt@v1
  ``<state_root>/data/runtime/agent-outcome-scorer_last.json`` (``ok_at`` only on success).

Exit codes: 0 = ran (0 unscored pairs is a finding, still 0); 1 = the run failed (DB unavailable or a
stage raised; any outcome insert failed; any calibration rule write failed; or the source-performance
stage failed); 2 = usage error. One failed insert used to leave the transaction aborted and still
exit 0 when any earlier insert had been counted. Each row is its own savepoint, and any failure
exits 1.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from collections import defaultdict

import psycopg2
from psycopg2.extras import RealDictCursor

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

log = logging.getLogger(__name__)
LANE_ID = "agent-outcome-scorer"

_SOURCE_PERF_SQL = """
            SELECT t.screener_label, COUNT(*) as signals,
                   COUNT(CASE WHEN t.decision='GO' THEN 1 END) as go_signals,
                   COUNT(tc.id) as trades,
                   COUNT(CASE WHEN tc.pnl_pct > 0 THEN 1 END) as profitable,
                   AVG(tc.pnl_pct) as avg_pnl
            FROM trade_ai_scans t
            LEFT JOIN trade_closed tc ON tc.symbol=t.symbol
                AND tc.open_date >= t.run_date AND tc.open_date <= t.run_date + 5
            WHERE t.screener_label IS NOT NULL AND t.scanned_at > NOW() - INTERVAL '90 days'
            GROUP BY t.screener_label HAVING COUNT(*) >= 3
        """


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.agent_outcome_scorer
        from scripts.lib import lane_last_receipt as lr
    return lr


#: The names this connection reads. ``env_bootstrap.load_env`` honours the tmpfs render, the
#: hermetic ``TRADEAI_ENV_BOOTSTRAP_FILES`` override and the executor's per-lane bound; the ``PG*``
#: names are read only as a fallback after their ``DB_*`` twin, so a host that sets just
#: ``PGHOST=/var/run/postgresql`` still gets the socket.
_DB_ENV_KEYS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
                "PGHOST", "PGPORT", "PGDATABASE", "PGUSER")


def _first_env(*names: str):
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _get_conn():
    """Open the scorer's session from the environment — never by parsing a credential file.

    Until LQ-20261107-917 this function read ``PROJECT_ROOT/.env`` by hand for ``DB_PASSWORD`` and
    hardcoded host/port/db/user, so it failed outright where no checkout ``.env`` exists (a worktree)
    or where the password is withheld (the 2026-11-07 emulation recorded the lane
    ``CANNOT_EMULATE needs_credential``), and it could never connect over the peer socket. The
    sanction loader applies the usual order; the host defaults to the local socket and the password
    is passed only when configured, so peer auth / ``.pgpass`` can serve instead.
    """
    try:
        from scripts.lib.env_bootstrap import load_env
    except ImportError:  # imported as scripts.agent_outcome_scorer
        from lib.env_bootstrap import load_env
    load_env(names=_DB_ENV_KEYS)
    password = os.getenv("DB_PASSWORD") or None
    return psycopg2.connect(
        host=_first_env("DB_HOST", "PGHOST") or "/var/run/postgresql",
        port=_first_env("DB_PORT", "PGPORT") or None,
        dbname=_first_env("DB_NAME", "PGDATABASE") or "trade_ai",
        user=_first_env("DB_USER", "PGUSER") or None,
        password=password,
        # attribution in pg_stat_activity / idle-txn triage
        application_name=LANE_ID,
    )


# Candidate trades per recommendation. The pick is one_trade_per_recommendation (LQ-20261107-125).
# "Already scored" is keyed on the recommendation alone: trade_closed is reloaded with new ids, so a
# (war_id, trade_id) key queued every recommendation again after each reload. No row LIMIT here: it
# would cut one recommendation's candidates in half; the cap is on recommendations (MAX_RECOMMENDATIONS).
_CANDIDATES_SQL = """
    SELECT
        war.id as war_id,
        war.agent as agent_name,
        war.symbol,
        war.recommendation,
        war.confidence,
        war.created_at as recommendation_date,
        war.input_data_snapshot->'position'->>'account' as rec_account,
        tc.id as trade_id,
        tc.account as trade_account,
        tc.open_date as entry_date,
        tc.close_date as exit_date,
        tc.buy_price as entry_price,
        tc.sell_price as exit_price,
        tc.pnl as realized_pnl,
        tc.pnl_pct
    FROM watchlist_agent_results war
    JOIN trade_closed tc ON tc.symbol = war.symbol
    WHERE war.created_at::date <= tc.close_date
      AND war.created_at::date >= tc.open_date - INTERVAL '90 days'
      AND NOT EXISTS (
          SELECT 1 FROM agent_recommendation_outcomes aro
          WHERE aro.war_id = war.id
      )
"""
MAX_RECOMMENDATIONS = 1000


def _canon(raw) -> str:
    """One key per account: a recommendation says ``schwab_roth``, trade_closed says
    ``schwab_roth_ira``. Both go through config/account_display_names.json aliases."""
    try:
        from lib.account_display import canonical_key
    except ImportError:  # imported as scripts.agent_outcome_scorer
        from scripts.lib.account_display import canonical_key
    return canonical_key(raw)


def _as_date(v):
    return v.date() if isinstance(v, datetime) else v


def one_trade_per_recommendation(rows: list, stats: dict | None = None) -> list:
    """Reduce candidate (recommendation, trade) rows to at most one trade per recommendation.

    - A recommendation that names its account matches only that account's trades.
    - A trade open on the recommendation day beats one opened after it; the nearest one wins.
    - Account unknown and the best matches sit in more than one account: held back, not guessed.
    Each kept row carries ``match_note`` saying how it matched.
    """
    by_rec: dict = {}
    for r in rows:
        by_rec.setdefault(r['war_id'], []).append(r)
    held_back: dict = defaultdict(int)
    picked = []
    for cands in by_rec.values():
        rec_day = _as_date(cands[0]['recommendation_date'])
        account = _canon(cands[0].get('rec_account'))
        if account:
            cands = [c for c in cands if _canon(c.get('trade_account')) == account]
            if not cands:
                held_back['no_trade_in_named_account'] += 1
                continue
        ranked = []
        for c in cands:
            entry, exit_ = c['entry_date'], c['exit_date']
            if entry <= rec_day <= exit_:
                ranked.append(((0, -entry.toordinal()), c))  # held at the recommendation: latest entry
            elif rec_day < entry:
                ranked.append(((1, entry.toordinal()), c))   # entered after it: nearest entry
        if not ranked:
            held_back['outside_window'] += 1
            continue
        ranked.sort(key=lambda kc: (kc[0], kc[1]['trade_id']))
        best_key = ranked[0][0]
        best = [c for k, c in ranked if k == best_key]
        if not account and len({_canon(c.get('trade_account')) for c in best}) > 1:
            held_back['account_unknown_ambiguous'] += 1
            continue
        chosen = best[0]
        how = 'held_at_recommendation' if best_key[0] == 0 else 'entered_after_recommendation'
        chosen = {**chosen, 'match_note': f"match={how}; account={'named' if account else 'unknown'}; "
                                          f"candidates={len(cands)}"}
        picked.append(chosen)
    picked.sort(key=lambda r: (r['exit_date'], str(r['war_id'])), reverse=True)
    if stats is not None:
        stats['candidate_rows'] = len(rows)
        stats['recommendations'] = len(by_rec)
        stats['held_back'] = dict(held_back)
        stats['capped'] = max(0, len(picked) - MAX_RECOMMENDATIONS)
    return picked[:MAX_RECOMMENDATIONS]


def match_and_score(conn, stats: dict | None = None) -> list:
    """Match each unscored recommendation to one closed trade and score it.

    Respects re-entry classification: if a symbol has an active relist/market
    reconnection record (explicit_stop_out = false), do not score the
    recommendation as WRONG. Treat as RELIST_NEUTRAL instead.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(_CANDIDATES_SQL)
    pairs = one_trade_per_recommendation(cur.fetchall(), stats)

    # Build relist context: symbols with active relist/market reconnection records
    relist_symbols = set()
    try:
        cur.execute("""
            SELECT DISTINCT symbol FROM stopped_out_watch
            WHERE is_active = true
              AND explicit_stop_out = false
              AND (relisted_without_stop_out = true OR market_reconnection_event = true)
        """)
        relist_symbols = {r['symbol'] for r in cur.fetchall()}
    except Exception:
        pass  # table may not have new columns yet

    scored = []
    for p in pairs:
        rec = (str(p.get('recommendation') or '')).upper()
        pnl_pct = float(p.get('pnl_pct') or 0)
        sym = p.get('symbol', '')

        bullish = any(t in rec for t in ['BUY', 'ADD', 'BULL', 'STRONG_BUY', 'OVERWEIGHT'])
        bearish = any(t in rec for t in ['SELL', 'TRIM', 'AVOID', 'BEAR', 'REDUCE', 'EXIT'])

        # ── Check if this symbol is a relist (no true stop-out) ──
        is_relist = sym in relist_symbols

        if bullish:
            if pnl_pct >= 10: verdict, vscore = 'CORRECT', 1.0
            elif pnl_pct >= 3: verdict, vscore = 'CORRECT', 0.8
            elif pnl_pct >= 0: verdict, vscore = 'PARTIAL', 0.3
            elif pnl_pct >= -5:
                if is_relist:
                    # Relist: small loss is market noise, not a wrong recommendation
                    verdict, vscore = 'RELIST_NEUTRAL', 0.0
                else:
                    verdict, vscore = 'PARTIAL', -0.2
            else:
                if is_relist:
                    # Relist: don't penalize as WRONG — treat as neutral market event
                    verdict, vscore = 'RELIST_NEUTRAL', 0.0
                else:
                    verdict, vscore = 'WRONG', -1.0
        elif bearish:
            if pnl_pct <= -10: verdict, vscore = 'CORRECT', 1.0
            elif pnl_pct <= -3: verdict, vscore = 'CORRECT', 0.8
            elif pnl_pct <= 0: verdict, vscore = 'PARTIAL', 0.3
            elif pnl_pct <= 5:
                if is_relist:
                    verdict, vscore = 'RELIST_NEUTRAL', 0.0
                else:
                    verdict, vscore = 'PARTIAL', -0.2
            else:
                if is_relist:
                    verdict, vscore = 'RELIST_NEUTRAL', 0.0
                else:
                    verdict, vscore = 'WRONG', -1.0
        else:
            verdict, vscore = 'NEUTRAL', 0.0

        delta_days = None
        try:
            rd = p['recommendation_date']
            ed = p['exit_date']
            if hasattr(rd, 'date'): rd = rd.date()
            if hasattr(ed, 'date'): ed = ed.date()
            delta_days = (ed - rd).days
        except Exception:
            pass

        scored.append({**p, 'verdict': verdict, 'verdict_score': vscore,
                       'delta_days': delta_days, 'is_relist': is_relist})

    return scored


def save_outcomes(conn, scored: list, stats: dict | None = None) -> int:
    cur = conn.cursor()
    saved = 0
    failed = 0
    for p in scored:
        try:
            # One bad row must not abort the transaction (Postgres keeps the connection failed
            # until ROLLBACK). The savepoint lets the other rows commit, and the caller exits 1.
            cur.execute("SAVEPOINT aos_outcome")
            cur.execute("""
                INSERT INTO agent_recommendation_outcomes (
                    agent_name, symbol, recommendation, confidence,
                    recommendation_date, war_id, trade_id,
                    entry_date, exit_date, entry_price, exit_price,
                    realized_pnl, pnl_pct, verdict, verdict_score, delta_days, notes
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, [p.get('agent_name'), p.get('symbol'), p.get('recommendation'),
                  p.get('confidence'), p.get('recommendation_date'), p.get('war_id'),
                  p.get('trade_id'), p.get('entry_date'), p.get('exit_date'),
                  p.get('entry_price'), p.get('exit_price'), p.get('realized_pnl'),
                  p.get('pnl_pct'), p['verdict'], p['verdict_score'], p.get('delta_days'),
                  p.get('match_note')])
            cur.execute("RELEASE SAVEPOINT aos_outcome")
            saved += 1
        except Exception:
            failed += 1
            try:
                cur.execute("ROLLBACK TO SAVEPOINT aos_outcome")
            except Exception:
                conn.rollback()
                break
    conn.commit()
    if stats is not None:
        stats["save_failed"] = failed
    return saved


def rebuild_calibration(conn):
    """Recompute agent_calibration from scored outcomes.

    RELIST_NEUTRAL verdicts are excluded from accuracy calculations — they
    represent market reconnection events, not recommendation failures.
    """
    cur = conn.cursor()
    for window in [30, 90, 365]:
        cur.execute("""
            SELECT DISTINCT agent_name FROM agent_recommendation_outcomes
            WHERE scored_at > NOW() - %s * INTERVAL '1 day'
        """, [window])
        agents = [r[0] for r in cur.fetchall()]

        for agent in agents:
            # Overall (strategy_type=NULL) + per-strategy
            for strat in [None]:
                strat_clause = "" if not strat else "AND strategy_type = %s"
                strat_params = [] if not strat else [strat]
                # Exclude RELIST_NEUTRAL from accuracy denominator — they're
                # market events, not failed recommendations
                cur.execute("""
                    SELECT COUNT(*),
                           COUNT(CASE WHEN verdict='CORRECT' THEN 1 END),
                           COUNT(CASE WHEN verdict='WRONG' THEN 1 END),
                           COUNT(CASE WHEN verdict IN ('NEUTRAL', 'RELIST_NEUTRAL') THEN 1 END),
                           AVG(confidence), AVG(pnl_pct), SUM(realized_pnl)
                    FROM agent_recommendation_outcomes
                    WHERE agent_name=%s AND scored_at > NOW() - %s * INTERVAL '1 day'
                    """ + strat_clause + """
                """, [agent, window, *strat_params])
                row = cur.fetchone()
                if not row or not row[0]:
                    continue
                total, correct, wrong, neutral, avg_conf, avg_pnl, total_pnl = row
                denom = (correct or 0) + (wrong or 0)
                accuracy = (correct / denom * 100) if denom > 0 else None

                # Trending — exclude RELIST_NEUTRAL from trending calc
                cur.execute("""
                    SELECT AVG(CASE WHEN verdict='CORRECT' THEN 1.0 ELSE 0.0 END)
                    FROM agent_recommendation_outcomes
                    WHERE agent_name=%s AND verdict NOT IN ('NEUTRAL', 'RELIST_NEUTRAL')
                    AND scored_at > NOW() - INTERVAL '30 days'
                """, [agent])
                recent_30d = cur.fetchone()[0]
                recent_30d = float(recent_30d) * 100 if recent_30d else None

                trending = 'STABLE'
                if accuracy and recent_30d:
                    if recent_30d > accuracy + 5: trending = 'IMPROVING'
                    elif recent_30d < accuracy - 5: trending = 'DECLINING'

                cur.execute("""
                    INSERT INTO agent_calibration (
                        agent_name, strategy_type, window_days,
                        total_recommendations, correct_count, wrong_count, neutral_count,
                        accuracy_pct, avg_confidence, avg_pnl_pct, total_pnl,
                        recent_accuracy_30d, trending, computed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (agent_name, strategy_type, window_days) DO UPDATE SET
                        total_recommendations=EXCLUDED.total_recommendations,
                        correct_count=EXCLUDED.correct_count,
                        wrong_count=EXCLUDED.wrong_count,
                        accuracy_pct=EXCLUDED.accuracy_pct,
                        avg_confidence=EXCLUDED.avg_confidence,
                        avg_pnl_pct=EXCLUDED.avg_pnl_pct,
                        total_pnl=EXCLUDED.total_pnl,
                        recent_accuracy_30d=EXCLUDED.recent_accuracy_30d,
                        trending=EXCLUDED.trending, computed_at=NOW()
                """, [agent, strat, window, total, correct, wrong, neutral,
                      accuracy, avg_conf, avg_pnl, total_pnl, recent_30d, trending])
    conn.commit()


def write_calibration_to_rules(conn, stats: dict | None = None):
    """Write calibration to agent_intelligence_rules for prompt injection."""
    cur = conn.cursor()
    if stats is not None:
        stats.setdefault("rule_write_failed", 0)
    cur.execute("""
        SELECT agent_name, accuracy_pct, correct_count, wrong_count,
               total_recommendations, trending, avg_pnl_pct
        FROM agent_calibration
        WHERE window_days=90 AND strategy_type IS NULL AND total_recommendations>=3
        ORDER BY agent_name
    """)
    rows = cur.fetchall()
    if not rows:
        return

    for agent, acc, correct, wrong, total, trending, avg_pnl in rows:
        if acc is None:
            continue
        trend = {'IMPROVING': '↑', 'DECLINING': '↓', 'STABLE': '→'}.get(trending or '', '')
        text = (f"=== YOUR ACCURACY (90 days) ===\n"
                f"Overall: {acc:.0f}% ({correct}/{total} correct) {trend}\n"
                f"Avg P&L when followed: {avg_pnl:+.1f}%\n"
                f"Calibrate confidence to match. If <50%, be conservative.\n"
                f"{'=' * 40}")
        try:
            cur.execute("SAVEPOINT aos_rule")
            cur.execute("""
                INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                VALUES ('calibration_stats', %s, %s::jsonb, 'outcome_scorer', NOW())
                ON CONFLICT (rule_type, rule_key) DO UPDATE SET config=EXCLUDED.config, updated_at=NOW()
            """, [f"accuracy_{agent}", json.dumps({
                'agent': agent, 'accuracy_pct': float(acc), 'correct': correct,
                'wrong': wrong, 'total': total, 'trending': trending,
                'avg_pnl': float(avg_pnl) if avg_pnl else 0,
                'text': text, 'updated': datetime.now().isoformat(),
            })])
            cur.execute("RELEASE SAVEPOINT aos_rule")
        except Exception as e:
            if stats is not None:
                stats["rule_write_failed"] += 1
            log.error(f"Write calibration for {agent} failed: {e}")
            try:
                cur.execute("ROLLBACK TO SAVEPOINT aos_rule")
            except Exception:
                conn.rollback()
                break

    conn.commit()


def update_source_performance(conn) -> bool:
    """Track win rates per screener label. Returns False when the stage failed."""
    cur = conn.cursor()
    try:
        cur.execute(_SOURCE_PERF_SQL)
        for row in cur.fetchall():
            label, signals, go_sig, trades, profitable, avg_pnl = row
            if not label:
                continue
            win_rate = (profitable / trades * 100) if trades else None
            scar = max(0.5, 1.0 - ((trades - (profitable or 0)) * 0.1)) if trades else 1.0
            cur.execute("""
                INSERT INTO source_performance (source_type, source_id, total_signals, go_signals,
                    trades_matched, profitable_trades, win_rate, avg_pnl_pct, scar_factor, updated_at)
                VALUES ('screener', %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (source_type, source_id) DO UPDATE SET
                    total_signals=EXCLUDED.total_signals, go_signals=EXCLUDED.go_signals,
                    trades_matched=EXCLUDED.trades_matched, profitable_trades=EXCLUDED.profitable_trades,
                    win_rate=EXCLUDED.win_rate, avg_pnl_pct=EXCLUDED.avg_pnl_pct,
                    scar_factor=EXCLUDED.scar_factor, updated_at=NOW()
            """, [label, signals, go_sig, trades, profitable, win_rate, avg_pnl, scar])
        conn.commit()
        return True
    except Exception as e:
        log.error(f"Source performance update failed: {e}")
        return False


def dry_run() -> dict:
    """Read-only preview. PipelineRun, save_outcomes, rebuild_calibration, write_calibration_to_rules and
    update_source_performance are not reachable from here."""
    lr = _receipt_lib()
    conn = _get_conn()
    lr.enforce_readonly(conn)
    print("=== Agent Outcome Scorer (DRY-RUN) ===")
    match: dict = {}
    scored = match_and_score(conn, match)
    verdicts = defaultdict(int)
    for p in scored:
        verdicts[p['verdict']] += 1
    print(f"Unscored pairs found: {len(scored)}")
    cur = conn.cursor()
    cur.execute("""SELECT COUNT(DISTINCT agent_name) FROM agent_recommendation_outcomes
                   WHERE scored_at > NOW() - INTERVAL '365 days'""")
    calib_agents = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*) FROM agent_calibration
                   WHERE window_days=90 AND strategy_type IS NULL AND total_recommendations>=3
                     AND accuracy_pct IS NOT NULL""")
    rule_agents = cur.fetchone()[0]
    cur.execute(_SOURCE_PERF_SQL)
    source_labels = sum(1 for r in cur.fetchall() if r[0])
    conn.close()
    summary = {"unscored_pairs": len(scored), "candidate_rows": match["candidate_rows"],
               "recommendations": match["recommendations"], "held_back": match["held_back"],
               "capped": match["capped"], "verdicts": dict(verdicts),
               "would_save": len(scored), "calibration_agents_365d": calib_agents,
               "rule_agents_90d": rule_agents, "source_labels": source_labels}
    lr.dry_run_report(
        LANE_ID, summary,
        would_write=["agent_recommendation_outcomes (INSERT) x would_save",
                     "agent_calibration (UPSERT, windows 30/90/365) for scored agents (counts exclude this run's new rows)",
                     "agent_intelligence_rules calibration_stats (UPSERT) x rule_agents_90d",
                     "source_performance (UPSERT) x source_labels", "pipeline run telemetry (PipelineRun)"],
    )
    return summary


def run_scoring() -> dict:
    """The live run (unchanged stages). Returns counts for the receipt."""
    stats: dict = {}
    conn = _get_conn()

    print("=== Agent Outcome Scorer ===")
    match: dict = {}
    scored = match_and_score(conn, match)
    print(f"Unscored pairs found: {len(scored)}")

    saved = save_outcomes(conn, scored, stats)
    print(f"Outcomes saved: {saved}")

    rebuild_calibration(conn)
    print("Calibration rebuilt")

    write_calibration_to_rules(conn, stats)
    print("Calibration written to agent_intelligence_rules")

    source_ok = update_source_performance(conn)
    print("Source performance updated" if source_ok else "Source performance update FAILED")

    # Summary
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM agent_recommendation_outcomes")
    print(f"\nTotal scored outcomes: {cur.fetchone()[0]}")

    cur.execute("""
        SELECT agent_name, accuracy_pct, correct_count, wrong_count, trending
        FROM agent_calibration WHERE window_days=90 AND strategy_type IS NULL ORDER BY agent_name
    """)
    rows = cur.fetchall()
    if rows:
        print("Agent accuracy (90d):")
        for agent, acc, correct, wrong, trend in rows:
            print(f"  {agent}: {acc:.0f}% ({correct}✓/{wrong}✗) {trend or ''}" if acc else f"  {agent}: N/A")
    else:
        print("No calibration data yet — need 3+ closed trades per agent")

    conn.close()
    return {"unscored_pairs": len(scored), "candidate_rows": match["candidate_rows"],
            "held_back": match["held_back"], "saved": saved, "save_failed": stats["save_failed"],
            "rule_write_failed": stats.get("rule_write_failed", 0), "source_performance_ok": source_ok}


def _exit_code(summary: dict) -> int:
    """1 when any scored row failed to save, any calibration rule failed to write, or the
    source-performance stage failed. Zero unscored pairs is a finding, exit 0."""
    if summary.get("save_failed", 0) > 0:
        return 1
    if summary.get("rule_write_failed", 0) > 0:
        return 1
    if not summary["source_performance_ok"]:
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score agent recommendations against closed trades")
    ap.add_argument("--dry-run", action="store_true", help="read-only preview; wins over --apply")
    ap.add_argument("--apply", action="store_true", help="live run (also the no-flag default)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.dry_run:
        dry_run()
        return 0

    lr = _receipt_lib()
    started = datetime.now(timezone.utc).isoformat()
    summary: dict = {}
    try:
        with PipelineRun("agent_outcome_scorer") as _run:
            summary = run_scoring()
            _run.rows(summary["saved"])
            rc = _exit_code(summary)
            if rc:
                raise SystemExit(rc)  # PipelineRun records the failure
    except SystemExit as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=exc.code if isinstance(exc.code, int) else 1,
                              started_at=started, script="agent_outcome_scorer.py", summary=summary)
        raise
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="agent_outcome_scorer.py", summary=summary,
                              error=f"{type(exc).__name__}: {exc}",
                              output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                          script="agent_outcome_scorer.py", summary=summary, output=lane_output(summary))
    return 0


def lane_output(summary: dict) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: rows saved to agent_recommendation_outcomes).
    attempted = unscored (recommendation, closed trade) pairs; none = ``no_new_input``."""
    saved, pairs = int(summary.get("saved") or 0), int(summary.get("unscored_pairs") or 0)
    return {"produced_count": saved, "attempted_count": max(pairs, saved),
            "skipped_reasons": {"save_failed": int(summary.get("save_failed") or 0)},
            "empty_reason": "no_new_input" if saved == 0 else None}


if __name__ == '__main__':
    sys.exit(main())
