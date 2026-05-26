# Source Export: scripts/paper_trade_analyzer.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/paper_trade_analyzer.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `c624dc01beb3edd18ff36c977ff55044a3b3b8bf95da6fd3adba36ec9b4a1ac5` |
| **File Size** | 11601 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""paper_trade_analyzer.py — Overnight local LLM analysis of closed paper trades.

Uses local_llm.py (Ollama LOCAL_LLM_MODEL with cloud fallback) to analyze
closed paper trades and expired/rejected proposals.

If local LLM is unavailable, all deterministic operations still run.

Usage:
    .venv/bin/python scripts/paper_trade_analyzer.py --dry-run
    .venv/bin/python scripts/paper_trade_analyzer.py --limit 5
    .venv/bin/python scripts/paper_trade_analyzer.py --proposal-analysis
"""
import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

log = logging.getLogger("paper_trade_analyzer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _get_local_llm():
    """Get local_llm.generate function if available."""
    try:
        from local_llm import generate, model_used, OLLAMA_MODEL
        return generate, OLLAMA_MODEL
    except ImportError:
        log.warning("local_llm.py not importable — LLM analysis unavailable")
        return None, None


def _check_ollama_available():
    """Quick check if Ollama is reachable."""
    try:
        import urllib.request
        from local_llm_config import get_local_llm_base_url
        _base = get_local_llm_base_url().rstrip("/")
        req = urllib.request.Request(f"{_base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m.get('name', '') for m in data.get('models', [])]
            return True, models
    except Exception:
        return False, []


def get_unanalyzed_trades(conn, limit=25):
    """Get closed paper trades not yet analyzed by LLM."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, setup_type, signal_grade,
               score_at_entry, entry_price, exit_price, shares,
               stop_loss, target_1, pnl, pnl_pct, r_multiple,
               outcome_verdict, exit_reason, catalyst_at_entry,
               catalyst_verified, rvol_at_entry, float_m_at_entry,
               hold_time_min, opened_via, automation_source,
               risk_gate_result, account, entry_time, exit_time
        FROM paper_trades
        WHERE status = 'closed'
        AND (post_trade_analyzed IS NOT TRUE)
        ORDER BY closed_at DESC
        LIMIT %s
    """, [limit])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_alerts_for_trade(conn, trade_id):
    """Get alerts generated during trade lifecycle."""
    cur = conn.cursor()
    cur.execute("""
        SELECT alert_type, severity, title, created_at
        FROM open_trade_alerts
        WHERE paper_trade_id = %s
        ORDER BY created_at
    """, [trade_id])
    return [{'type': r[0], 'severity': r[1], 'title': r[2]} for r in cur.fetchall()]


def build_analysis_prompt(trade, alerts):
    """Build the analysis prompt for local LLM."""
    t = trade
    entry = float(t.get('entry_price') or 0)
    exit_p = float(t.get('exit_price') or 0)
    stop = float(t.get('stop_loss') or 0)
    target = float(t.get('target_1') or 0)
    pnl = float(t.get('pnl') or 0)
    r_mult = t.get('r_multiple')
    hold = t.get('hold_time_min') or 0

    alert_str = ""
    if alerts:
        alert_str = "\n".join(f"  - {a['type']}: {a['title']}" for a in alerts[:5])
    else:
        alert_str = "  None"

    prompt = f"""Analyze this paper trade as a prop desk reviewer. Be concise (under 300 words).

Symbol: {t.get('symbol')}
Strategy: {t.get('strategy_id')}
Setup type: {t.get('setup_type', 'N/A')}
Signal grade: {t.get('signal_grade', 'N/A')}
Score: {t.get('score_at_entry', 'N/A')}
Entry: ${entry:.2f}
Stop: ${stop:.2f}
Target: ${target:.2f}
Exit: ${exit_p:.2f}
P&L: ${pnl:+.2f}
R multiple: {f'{r_mult:.2f}' if r_mult else 'N/A'}
Catalyst: {(t.get('catalyst_at_entry') or 'None')[:100]}
Catalyst verified: {t.get('catalyst_verified', False)}
RVOL at entry: {t.get('rvol_at_entry', 'N/A')}
Opened via: {t.get('opened_via', 'N/A')}
Automation source: {t.get('automation_source', 'N/A')}
Trade age: {f'{hold:.0f} minutes' if hold else 'N/A'}
Risk gate: {t.get('risk_gate_result', 'N/A')}
Known alerts:
{alert_str}
Outcome: {t.get('outcome_verdict', 'N/A')}

Answer these questions concisely:
1. Why did this trade work or fail?
2. Was the catalyst classification accurate?
3. Was entry quality good?
4. Was stop placement reasonable?
5. Was target realistic?
6. Did the trade match the strategy playbook?
7. What should be changed for future similar proposals?
8. Should this strengthen or weaken any known pattern?

Return a JSON object with keys: summary, worked_reasons (list), failed_reasons (list), lessons (list), suggested_changes (list), confidence (0-1).
If the trade was profitable, focus worked_reasons. If not, focus failed_reasons."""

    return prompt


def analyze_trade(conn, trade, generate_fn, dry_run=False):
    """Analyze a single closed trade with local LLM."""
    trade_id = trade['id']
    symbol = trade['symbol']

    alerts = get_alerts_for_trade(conn, trade_id)
    prompt = build_analysis_prompt(trade, alerts)
    prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:16]

    if dry_run:
        log.info(f"[dry-run] Would analyze {symbol} (trade #{trade_id})")
        return {'success': True, 'dry_run': True, 'symbol': symbol}

    # Call LLM
    log.info(f"Analyzing {symbol} (trade #{trade_id})...")
    try:
        raw = generate_fn(prompt, timeout=120, fallback=True, fast=False)
    except Exception as e:
        log.error(f"LLM call failed for {symbol}: {e}")
        return {'success': False, 'error': str(e)}

    if not raw:
        log.warning(f"LLM returned empty for {symbol}")
        return {'success': False, 'error': 'empty_response'}

    # Try to parse JSON from response
    parsed = None
    try:
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
    except Exception:
        pass

    # Get model used
    try:
        from local_llm import model_used
        model = model_used
    except Exception:
        model = 'unknown'

    # Write analysis
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO paper_trade_analysis
            (paper_trade_id, symbol, strategy_id, model_used, analysis_type,
             prompt_hash, summary, worked_reasons, failed_reasons,
             lessons, suggested_rule_changes, confidence, created_by)
        VALUES (%s, %s, %s, %s, 'post_trade', %s, %s, %s, %s, %s, %s, %s, 'local_llm')
        ON CONFLICT (paper_trade_id, analysis_type) DO UPDATE SET
            summary=EXCLUDED.summary, worked_reasons=EXCLUDED.worked_reasons,
            failed_reasons=EXCLUDED.failed_reasons, lessons=EXCLUDED.lessons,
            suggested_rule_changes=EXCLUDED.suggested_rule_changes,
            model_used=EXCLUDED.model_used, confidence=EXCLUDED.confidence,
            created_at=NOW()
    """, [
        trade_id, symbol, trade.get('strategy_id'), model, prompt_hash,
        parsed.get('summary', raw[:500]) if parsed else raw[:500],
        json.dumps(parsed.get('worked_reasons', [])) if parsed else None,
        json.dumps(parsed.get('failed_reasons', [])) if parsed else None,
        json.dumps(parsed.get('lessons', [])) if parsed else None,
        json.dumps(parsed.get('suggested_changes', [])) if parsed else None,
        parsed.get('confidence') if parsed else None,
    ])

    # Mark trade as analyzed
    cur.execute("UPDATE paper_trades SET post_trade_analyzed=true WHERE id=%s", [trade_id])

    # Write curation event
    cur.execute("""
        INSERT INTO agent_curation_events
            (paper_trade_id, symbol, strategy_id, agent_name, event_type, event_summary, payload)
        VALUES (%s, %s, %s, 'local_llm', 'LOCAL_LLM_ANALYSIS', %s, %s)
    """, [trade_id, symbol, trade.get('strategy_id'),
          f"LLM analysis complete for {symbol} ({trade.get('outcome_verdict')})",
          json.dumps({'model': model, 'parsed': parsed is not None})])

    log.info(f"Analysis saved for {symbol} (model: {model})")
    return {'success': True, 'symbol': symbol, 'model': model, 'parsed': parsed is not None}


def run_analyzer(limit=25, dry_run=False, proposal_analysis=False):
    """Run the full analyzer."""
    generate_fn, default_model = _get_local_llm()
    ollama_available, ollama_models = _check_ollama_available()

    log.info(f"Ollama available: {ollama_available}, models: {ollama_models}")

    if not generate_fn:
        log.warning("No LLM available — skipping analysis")
        return {
            'available': False,
            'reason': 'local_llm not importable',
            'trades_processed': 0,
        }

    conn = get_conn()
    started = datetime.now(timezone.utc)

    # Record run start
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO local_llm_runs (model_name, status, run_type, started_at)
        VALUES (%s, 'running', 'post_trade', NOW()) RETURNING id
    """, [default_model])
    run_id = cur.fetchone()[0]
    conn.commit()

    try:
        trades = get_unanalyzed_trades(conn, limit)
        log.info(f"Found {len(trades)} unanalyzed trades")

        processed = 0
        failed = 0

        for trade in trades:
            try:
                result = analyze_trade(conn, trade, generate_fn, dry_run)
                if result.get('success'):
                    processed += 1
                else:
                    failed += 1
            except Exception as e:
                log.error(f"Error analyzing trade {trade['id']}: {e}")
                failed += 1

            if not dry_run:
                conn.commit()

        duration = (datetime.now(timezone.utc) - started).total_seconds()

        # Update run record
        cur.execute("""
            UPDATE local_llm_runs SET
                status='completed', finished_at=NOW(),
                duration_sec=%s, items_processed=%s, items_failed=%s
            WHERE id=%s
        """, [round(duration, 1), processed, failed, run_id])
        conn.commit()

        log.info(f"Analyzer complete: {processed} processed, {failed} failed, {duration:.1f}s")

        return {
            'available': True,
            'ollama_available': ollama_available,
            'model': default_model,
            'trades_processed': processed,
            'trades_failed': failed,
            'duration_sec': round(duration, 1),
            'dry_run': dry_run,
        }
    except Exception as e:
        cur.execute("""
            UPDATE local_llm_runs SET status='failed', finished_at=NOW(), last_error=%s
            WHERE id=%s
        """, [str(e)[:500], run_id])
        conn.commit()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper trade LLM analyzer")
    parser.add_argument("--dry-run", action="store_true", help="Don't call LLM or write results")
    parser.add_argument("--limit", type=int, default=25, help="Max trades to analyze")
    parser.add_argument("--proposal-analysis", action="store_true", help="Also analyze rejected/expired proposals")
    args = parser.parse_args()

    result = run_analyzer(limit=args.limit, dry_run=args.dry_run, proposal_analysis=args.proposal_analysis)
    print(json.dumps(result, indent=2))
```
