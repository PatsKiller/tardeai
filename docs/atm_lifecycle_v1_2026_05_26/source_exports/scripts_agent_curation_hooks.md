# Source Export: scripts/agent_curation_hooks.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/agent_curation_hooks.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `a1126397a58a5c20039ae05a93f233c2da2c900190427c56e39ccbc1ad761f90` |
| **File Size** | 17282 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""agent_curation_hooks.py — Post-trade curation by Iris, Aegis, and outcome system.

Called when a paper trade closes. Non-blocking — if any hook fails,
the trade close still succeeds.

Functions:
    on_paper_trade_closed(conn, paper_trade_id) -> dict
    iris_record_trade_outcome(conn, paper_trade_id) -> dict
    aegis_write_post_trade_synthesis(conn, paper_trade_id) -> dict
    trigger_outcome_lessons(conn, paper_trade_id) -> dict
    check_pattern_confirmation(conn, paper_trade_id) -> dict
"""
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("agent_curation_hooks")


def _get_trade(conn, paper_trade_id):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, entry_price, exit_price, shares,
               pnl, pnl_pct, r_multiple, outcome_verdict, exit_reason,
               signal_grade, score_at_entry, catalyst_at_entry, catalyst_verified,
               rvol_at_entry, float_m_at_entry, hold_time_min,
               entry_time, exit_time, account, opened_via, automation_source,
               stop_loss, target_1, dollar_risk, risk_gate_result,
               proposal_id, closed_at
        FROM paper_trades WHERE id = %s
    """, [paper_trade_id])
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def _write_event(conn, trade_id, symbol, strategy_id, agent, event_type, summary, payload=None):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO agent_curation_events
            (paper_trade_id, symbol, strategy_id, agent_name, event_type, event_summary, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, [trade_id, symbol, strategy_id, agent, event_type, summary,
          json.dumps(payload) if payload else None])


def iris_record_trade_outcome(conn, paper_trade_id):
    """Iris records the trade outcome for intelligence memory."""
    trade = _get_trade(conn, paper_trade_id)
    if not trade:
        return {'success': False, 'reason': 'trade_not_found'}

    symbol = trade['symbol']
    verdict = trade['outcome_verdict'] or 'UNKNOWN'
    r_mult = trade.get('r_multiple')
    catalyst = trade.get('catalyst_at_entry', '')
    verified = trade.get('catalyst_verified', False)
    strategy = trade.get('strategy_id', '')

    r_str = f"{r_mult:+.1f}R" if r_mult is not None else "N/A"
    cat_str = f"{'verified' if verified else 'unverified'} catalyst"

    summary = (f"{symbol} closed {verdict} {r_str}; {cat_str}"
               f"{f' ({catalyst[:60]})' if catalyst else ''}")

    _write_event(conn, paper_trade_id, symbol, strategy, 'Iris',
                 'IRIS_OUTCOME_WRITEBACK', summary, {
                     'verdict': verdict,
                     'r_multiple': float(r_mult) if r_mult else None,
                     'pnl': float(trade['pnl']) if trade.get('pnl') else None,
                     'catalyst_verified': verified,
                     'strategy_id': strategy,
                     'signal_grade': trade.get('signal_grade'),
                 })

    # Write to agent_intelligence_rules (outcome_lessons)
    try:
        cur = conn.cursor()
        # Read current lessons
        cur.execute("""
            SELECT config FROM agent_intelligence_rules
            WHERE rule_type='outcome_lessons' AND rule_key='paper_trade_latest'
        """)
        row = cur.fetchone()
        existing = json.loads(row[0]) if row and row[0] else {'lessons': []}
        if isinstance(existing, str):
            existing = json.loads(existing)

        lessons_list = existing.get('lessons', [])
        lessons_list.insert(0, summary)
        lessons_list = lessons_list[:50]  # keep last 50

        from datetime import datetime, timezone
        new_config = json.dumps({
            'lessons': lessons_list,
            'text': '\n'.join(lessons_list[:10]),
            'evaluated_at': datetime.now(timezone.utc).isoformat(),
        })

        cur.execute("""
            INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
            VALUES ('outcome_lessons', 'paper_trade_latest', %s, 'iris_curation', NOW())
            ON CONFLICT (rule_type, rule_key) DO UPDATE SET
                config = %s, changed_by = 'iris_curation', updated_at = NOW()
        """, [new_config, new_config])
        log.info(f"[Iris] Wrote outcome lesson to agent_intelligence_rules")
    except Exception as e:
        log.warning(f"[Iris] agent_intelligence_rules write failed: {e}")

    # Mark trade as iris-curated
    cur = conn.cursor()
    cur.execute("UPDATE paper_trades SET iris_curated=true WHERE id=%s", [paper_trade_id])

    log.info(f"[Iris] {summary}")
    return {'success': True, 'summary': summary}


def aegis_write_post_trade_synthesis(conn, paper_trade_id):
    """Aegis writes a synthesis paragraph about the trade."""
    trade = _get_trade(conn, paper_trade_id)
    if not trade:
        return {'success': False, 'reason': 'trade_not_found'}

    symbol = trade['symbol']
    verdict = trade['outcome_verdict'] or 'UNKNOWN'
    r_mult = trade.get('r_multiple')
    strategy = trade.get('strategy_id', '')
    pnl = float(trade['pnl']) if trade.get('pnl') else 0
    hold_min = trade.get('hold_time_min') or 0
    catalyst = trade.get('catalyst_at_entry', '') or ''
    verified = trade.get('catalyst_verified', False)
    grade = trade.get('signal_grade', '')
    rvol = trade.get('rvol_at_entry')

    r_str = f"{r_mult:+.1f}R" if r_mult is not None else ""
    hold_str = f"{hold_min:.0f}min" if hold_min < 120 else f"{hold_min/60:.1f}h"

    # Build synthesis paragraph
    parts = [f"{symbol} paper trade closed {verdict} {r_str} (${pnl:+.2f})."]
    parts.append(f"{strategy.replace('_', ' ').title()} thesis {'held' if verdict == 'CORRECT' else 'failed'}.")

    if verified:
        parts.append(f"Verified catalyst{' strengthened' if verdict == 'CORRECT' else ' did not support price'}.")
    elif catalyst:
        parts.append(f"Unverified catalyst — consider verification for future {grade} setups.")

    if rvol and float(rvol) >= 8:
        parts.append(f"RVOL {float(rvol):.1f}x pattern {'strengthened' if verdict == 'CORRECT' else 'weakened'}.")

    parts.append(f"Hold time: {hold_str}.")

    if verdict == 'CORRECT':
        parts.append("Setup should remain eligible for future proposals.")
    else:
        parts.append("Review entry quality and stop placement for similar setups.")

    synthesis = " ".join(parts)

    _write_event(conn, paper_trade_id, symbol, strategy, 'Aegis',
                 'AEGIS_POST_TRADE_SYNTHESIS', synthesis, {
                     'verdict': verdict,
                     'pnl': pnl,
                     'r_multiple': float(r_mult) if r_mult else None,
                     'hold_minutes': hold_min,
                 })

    # Try writing to intelligence_whiteboard if it exists
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO intelligence_whiteboard
                (symbol, source_type, source_id, level, status, first_seen_at)
            VALUES (%s, 'aegis_synthesis', %s, 1, 'active', NOW())
            ON CONFLICT DO NOTHING
        """, [symbol, str(paper_trade_id)])
    except Exception:
        pass  # whiteboard schema may differ

    # Mark trade as aegis-summarized
    cur = conn.cursor()
    cur.execute("UPDATE paper_trades SET aegis_summarized=true WHERE id=%s", [paper_trade_id])

    log.info(f"[Aegis] {synthesis[:120]}")
    return {'success': True, 'synthesis': synthesis}


def trigger_outcome_lessons(conn, paper_trade_id):
    """Trigger existing outcome lesson capture if available."""
    trade = _get_trade(conn, paper_trade_id)
    if not trade:
        return {'success': False, 'reason': 'trade_not_found'}

    symbol = trade['symbol']
    strategy = trade.get('strategy_id', '')

    # Try calling existing evaluate_past_decisions if available
    try:
        from agent_outcome_scorer import evaluate_past_decisions
        evaluate_past_decisions(conn)
        _write_event(conn, paper_trade_id, symbol, strategy, 'system',
                     'OUTCOME_LESSON_CAPTURED',
                     f"Outcome lessons triggered for {symbol} close",
                     {'source': 'agent_outcome_scorer'})
        return {'success': True, 'source': 'agent_outcome_scorer'}
    except ImportError:
        pass
    except Exception as e:
        log.warning(f"evaluate_past_decisions failed: {e}")

    # Fallback: just record the event
    _write_event(conn, paper_trade_id, symbol, strategy, 'system',
                 'OUTCOME_LESSON_CAPTURED',
                 f"Trade {symbol} closed {trade.get('outcome_verdict')} — lesson captured",
                 {'verdict': trade.get('outcome_verdict'),
                  'pnl': float(trade['pnl']) if trade.get('pnl') else None})

    return {'success': True, 'source': 'fallback_event'}


def check_pattern_confirmation(conn, paper_trade_id):
    """Check if this trade confirms or weakens any known pattern."""
    trade = _get_trade(conn, paper_trade_id)
    if not trade:
        return {'success': False, 'reason': 'trade_not_found'}

    strategy = trade.get('strategy_id', '')
    verdict = trade.get('outcome_verdict', '')
    symbol = trade['symbol']

    cur = conn.cursor()
    cur.execute("""
        SELECT id, pattern_name, pattern_type, win_rate, trade_count
        FROM pattern_library
        WHERE strategy_id = %s
    """, [strategy])
    patterns = cur.fetchall()

    if not patterns:
        return {'success': True, 'patterns_checked': 0}

    checked = 0
    for pid, pname, ptype, wr, tc in patterns:
        checked += 1
        # Log pattern check event
        status = 'confirmed' if verdict == 'CORRECT' else 'weakened'
        _write_event(conn, paper_trade_id, symbol, strategy, 'Iris',
                     'PATTERN_CHECK',
                     f"Pattern '{pname}' {status} by {symbol} {verdict}",
                     {'pattern_id': pid, 'pattern_name': pname,
                      'pattern_type': ptype, 'verdict': verdict})

    return {'success': True, 'patterns_checked': checked}


def _index_trade_outcome_to_rag(conn, paper_trade_id):
    """Embed trade outcome into content_embeddings so agents learn from it via RAG."""
    trade = _get_trade(conn, paper_trade_id)
    if not trade:
        return {'success': False, 'reason': 'trade_not_found'}

    symbol = trade['symbol']
    verdict = trade.get('outcome_verdict') or 'UNKNOWN'
    strategy = trade.get('strategy_id', '')
    pnl = float(trade['pnl']) if trade.get('pnl') else 0
    r_mult = trade.get('r_multiple')
    catalyst = trade.get('catalyst_at_entry', '') or ''
    verified = trade.get('catalyst_verified', False)
    notes = trade.get('notes', '') or ''

    r_str = f"{r_mult:+.1f}R" if r_mult is not None else ""
    embed_text = (
        f"{symbol} paper trade {strategy} closed {verdict} {r_str} pnl=${pnl:+.2f}. "
        f"{'Verified' if verified else 'Unverified'} catalyst: {catalyst[:100]}. "
        f"{notes[:200]}"
    )
    title = f"{symbol} trade outcome: {verdict} {r_str} ({strategy})"

    try:
        from rag_retrieval import embed_text as _embed
        vec = _embed(embed_text[:2000])
        if vec is None:
            return {'success': False, 'reason': 'embedding_failed'}

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO content_embeddings (source_type, source_id, title, embedding, embedding_model, embedding_dim, created_at)
            VALUES ('trade_outcome', %s, %s, %s, 'nomic-embed-text', %s, NOW())
            ON CONFLICT (source_type, source_id) DO UPDATE SET
                title = EXCLUDED.title, embedding = EXCLUDED.embedding, created_at = NOW()
        """, [paper_trade_id, title[:300], json.dumps(vec), len(vec)])

        log.info(f"[RAG] Indexed trade outcome for {symbol} ({strategy} {verdict})")
        return {'success': True, 'symbol': symbol}
    except Exception as e:
        log.warning(f"[RAG] Index failed for {symbol}: {e}")
        return {'success': False, 'error': str(e)}


def _write_outcome_to_proposal(conn, trade):
    """Link trade result back to the originating proposal (Gap 3 provenance)."""
    proposal_id = trade.get('proposal_id')
    if not proposal_id:
        return {'success': False, 'reason': 'no_proposal_id'}

    pnl = trade.get('pnl')
    verdict = (
        'WIN'       if pnl and float(pnl) > 0 else
        'LOSS'      if pnl and float(pnl) < 0 else
        'BREAKEVEN'
    )

    hold_hours = None
    entry_time = trade.get('entry_time')
    closed_at = trade.get('closed_at') or trade.get('exit_time')
    if entry_time and closed_at:
        try:
            hold_hours = int((closed_at - entry_time).total_seconds() / 3600)
        except Exception:
            pass

    cur = conn.cursor()
    cur.execute("""
        UPDATE paper_trade_proposals SET
            outcome_trade_id         = %s,
            outcome_r_multiple       = %s,
            outcome_pnl              = %s,
            outcome_pnl_pct          = %s,
            outcome_verdict          = %s,
            outcome_thesis_confirmed = %s,
            outcome_closed_at        = %s,
            outcome_hold_hours       = %s
        WHERE id = %s AND outcome_trade_id IS NULL
    """, [trade['id'], trade.get('r_multiple'),
          trade.get('pnl'), trade.get('pnl_pct'),
          verdict,
          trade.get('outcome_verdict') == 'CORRECT' if trade.get('outcome_verdict') else None,
          closed_at, hold_hours, proposal_id])
    updated = cur.rowcount
    log.info(f"[provenance] Wrote outcome to proposal {proposal_id}: "
             f"verdict={verdict}, r={trade.get('r_multiple')}, "
             f"pnl=${trade.get('pnl')}, updated={updated}")
    return {'success': True, 'proposal_id': proposal_id, 'verdict': verdict, 'updated': updated}


def on_paper_trade_closed(conn, paper_trade_id):
    """Master hook called when any paper trade closes.

    Runs all curation hooks. Never blocks the close — errors are logged.
    """
    results = {}

    # Outcome provenance — write trade result back to originating proposal
    try:
        trade_data = _get_trade(conn, paper_trade_id)
        if trade_data:
            results['provenance'] = _write_outcome_to_proposal(conn, trade_data)
        else:
            results['provenance'] = {'success': False, 'reason': 'trade_not_found'}
    except Exception as e:
        log.error(f"Outcome provenance failed for trade {paper_trade_id}: {e}")
        results['provenance'] = {'success': False, 'error': str(e)}

    # Iris outcome writeback
    try:
        results['iris'] = iris_record_trade_outcome(conn, paper_trade_id)
    except Exception as e:
        log.error(f"Iris writeback failed for trade {paper_trade_id}: {e}")
        results['iris'] = {'success': False, 'error': str(e)}

    # Aegis synthesis
    try:
        results['aegis'] = aegis_write_post_trade_synthesis(conn, paper_trade_id)
    except Exception as e:
        log.error(f"Aegis synthesis failed for trade {paper_trade_id}: {e}")
        results['aegis'] = {'success': False, 'error': str(e)}

    # Outcome lessons
    try:
        results['lessons'] = trigger_outcome_lessons(conn, paper_trade_id)
    except Exception as e:
        log.error(f"Outcome lessons failed for trade {paper_trade_id}: {e}")
        results['lessons'] = {'success': False, 'error': str(e)}

    # Pattern confirmation
    try:
        results['patterns'] = check_pattern_confirmation(conn, paper_trade_id)
    except Exception as e:
        log.error(f"Pattern check failed for trade {paper_trade_id}: {e}")
        results['patterns'] = {'success': False, 'error': str(e)}

    # RAG indexing — embed trade outcome so agents learn from it
    try:
        results['rag'] = _index_trade_outcome_to_rag(conn, paper_trade_id)
    except Exception as e:
        log.error(f"RAG index failed for trade {paper_trade_id}: {e}")
        results['rag'] = {'success': False, 'error': str(e)}

    # Multi-tier realtime review (qwen3:14b — fast, runs on every close)
    try:
        from multi_tier_trade_reviewer import review_trade
        trade_row = _get_trade(conn, paper_trade_id)
        if trade_row and trade_row.get('status') == 'closed':
            results['realtime_review'] = review_trade(conn, trade_row, 'realtime')
    except Exception as e:
        log.error(f"Realtime review failed for trade {paper_trade_id}: {e}")
        results['realtime_review'] = {'success': False, 'error': str(e)}

    log.info(f"Curation complete for trade {paper_trade_id}: "
             f"provenance={results.get('provenance',{}).get('success')}, "
             f"iris={results.get('iris',{}).get('success')}, "
             f"aegis={results.get('aegis',{}).get('success')}, "
             f"lessons={results.get('lessons',{}).get('success')}, "
             f"patterns={results.get('patterns',{}).get('success')}, "
             f"rag={results.get('rag',{}).get('success')}, "
             f"realtime_review={results.get('realtime_review',{}).get('success')}")

    return results
```
