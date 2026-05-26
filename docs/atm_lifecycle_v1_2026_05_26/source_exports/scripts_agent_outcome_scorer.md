# Source Export: scripts/agent_outcome_scorer.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/agent_outcome_scorer.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `74755212fafcf0fdf22ca88c1aaf33556089f96bad87bc58236c6ec42fe1f8e6` |
| **File Size** | 15638 bytes |

## Full Source

```py
"""
agent_outcome_scorer.py — Nightly: score agent recommendations against closed trades.
Cron: 5:30 AM daily. Feeds calibration data back to agents.

Loop: trade_close → score → calibration → agent prompt → adjusted confidence
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

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
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_conn():
    pw = ''
    for line in (PROJECT_ROOT / '.env').read_text().splitlines():
        if line.startswith('DB_PASSWORD='): pw = line.split('=', 1)[1].strip()
    return psycopg2.connect(host='127.0.0.1', port=5432, dbname='trade_ai', user='trade_ai', password=pw)


def match_and_score(conn) -> list:
    """Join trade_closed to watchlist_agent_results, score each pair.

    Respects re-entry classification: if a symbol has an active relist/market
    reconnection record (explicit_stop_out = false), do not score the
    recommendation as WRONG. Treat as RELIST_NEUTRAL instead.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT
            war.id as war_id,
            war.agent as agent_name,
            war.symbol,
            war.recommendation,
            war.confidence,
            war.created_at as recommendation_date,
            tc.id as trade_id,
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
              WHERE aro.war_id = war.id AND aro.trade_id = tc.id
          )
        ORDER BY tc.close_date DESC
        LIMIT 1000
    """)
    pairs = cur.fetchall()

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


def save_outcomes(conn, scored: list) -> int:
    cur = conn.cursor()
    saved = 0
    for p in scored:
        try:
            cur.execute("""
                INSERT INTO agent_recommendation_outcomes (
                    agent_name, symbol, recommendation, confidence,
                    recommendation_date, war_id, trade_id,
                    entry_date, exit_date, entry_price, exit_price,
                    realized_pnl, pnl_pct, verdict, verdict_score, delta_days
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, [p.get('agent_name'), p.get('symbol'), p.get('recommendation'),
                  p.get('confidence'), p.get('recommendation_date'), p.get('war_id'),
                  p.get('trade_id'), p.get('entry_date'), p.get('exit_date'),
                  p.get('entry_price'), p.get('exit_price'), p.get('realized_pnl'),
                  p.get('pnl_pct'), p['verdict'], p['verdict_score'], p.get('delta_days')])
            saved += 1
        except Exception:
            pass
    conn.commit()
    return saved


def rebuild_calibration(conn):
    """Recompute agent_calibration from scored outcomes.

    RELIST_NEUTRAL verdicts are excluded from accuracy calculations — they
    represent market reconnection events, not recommendation failures.
    """
    cur = conn.cursor()
    for window in [30, 90, 365]:
        cur.execute(f"""
            SELECT DISTINCT agent_name FROM agent_recommendation_outcomes
            WHERE scored_at > NOW() - INTERVAL '{window} days'
        """)
        agents = [r[0] for r in cur.fetchall()]

        for agent in agents:
            # Overall (strategy_type=NULL) + per-strategy
            for strat in [None]:
                strat_clause = "" if not strat else f"AND strategy_type = '{strat}'"
                # Exclude RELIST_NEUTRAL from accuracy denominator — they're
                # market events, not failed recommendations
                cur.execute(f"""
                    SELECT COUNT(*),
                           COUNT(CASE WHEN verdict='CORRECT' THEN 1 END),
                           COUNT(CASE WHEN verdict='WRONG' THEN 1 END),
                           COUNT(CASE WHEN verdict IN ('NEUTRAL', 'RELIST_NEUTRAL') THEN 1 END),
                           AVG(confidence), AVG(pnl_pct), SUM(realized_pnl)
                    FROM agent_recommendation_outcomes
                    WHERE agent_name=%s AND scored_at > NOW() - INTERVAL '{window} days'
                    {strat_clause}
                """, [agent])
                row = cur.fetchone()
                if not row or not row[0]:
                    continue
                total, correct, wrong, neutral, avg_conf, avg_pnl, total_pnl = row
                denom = (correct or 0) + (wrong or 0)
                accuracy = (correct / denom * 100) if denom > 0 else None

                # Trending — exclude RELIST_NEUTRAL from trending calc
                cur.execute(f"""
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


def write_calibration_to_rules(conn):
    """Write calibration to agent_intelligence_rules for prompt injection."""
    cur = conn.cursor()
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
        except Exception as e:
            log.error(f"Write calibration for {agent} failed: {e}")

    conn.commit()


def update_source_performance(conn):
    """Track win rates per screener label."""
    cur = conn.cursor()
    try:
        cur.execute("""
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
        """)
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
    except Exception as e:
        log.error(f"Source performance update failed: {e}")


if __name__ == '__main__':
    with PipelineRun("agent_outcome_scorer") as _run:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        conn = _get_conn()

        print("=== Agent Outcome Scorer ===")
        scored = match_and_score(conn)
        print(f"Unscored pairs found: {len(scored)}")

        saved = save_outcomes(conn, scored)
        print(f"Outcomes saved: {saved}")

        rebuild_calibration(conn)
        print("Calibration rebuilt")

        write_calibration_to_rules(conn)
        print("Calibration written to agent_intelligence_rules")

        update_source_performance(conn)
        print("Source performance updated")

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
```
