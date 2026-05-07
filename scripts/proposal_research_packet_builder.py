#!/usr/bin/env python3
"""proposal_research_packet_builder.py — Orchestrator that builds complete research packets.

Coordinates technical snapshot, backtest engine, agent review, LLM review,
and decision gate into a single research packet per proposal.

Usage:
    .venv/bin/python scripts/proposal_research_packet_builder.py --proposal-id 2 --refresh
    .venv/bin/python scripts/proposal_research_packet_builder.py --all-pending --refresh-stale
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

log = logging.getLogger("research_packet")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _safe_import(module_name, func_name):
    """Safely import a function, return None if unavailable."""
    try:
        mod = __import__(module_name)
        return getattr(mod, func_name, None)
    except Exception:
        return None


def _compute_research_score(packet):
    """Score out of 100 based on completeness."""
    score = 0

    # Source lineage known: 10
    sl = packet.get('source_lineage', {})
    if sl and sl.get('source'):
        score += 10

    # Current data fresh: 10
    tech = packet.get('technical_snapshot', {})
    if tech and tech.get('scan_timestamp'):
        try:
            scan_ts = datetime.fromisoformat(str(tech['scan_timestamp']).replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - scan_ts).total_seconds() / 3600
            if age_hours < 2:
                score += 10
            elif age_hours < 4:
                score += 5
        except Exception:
            pass

    # Technical snapshot complete: 20
    if tech:
        tech_fields = ['atr', 'rsi', 'vwap_state', 'rvol', 'gap_pct']
        populated = sum(1 for f in tech_fields if tech.get(f) is not None)
        score += int(20 * populated / max(len(tech_fields), 1))

    # Catalyst/news quality known: 15
    catalyst = packet.get('catalyst_packet', {})
    if catalyst.get('catalyst'):
        score += 8
        if catalyst.get('catalyst_verified'):
            score += 7
        elif catalyst.get('catalyst_confidence') and float(catalyst['catalyst_confidence']) > 0.7:
            score += 4

    # Agent reviews complete: 15
    agent_status = packet.get('agent_review_status', {})
    if agent_status.get('status') == 'complete':
        score += 15
    elif agent_status.get('status') == 'partial':
        score += 8

    # Local LLM or fallback review: 10
    llm = packet.get('local_llm_review', {})
    if llm.get('narrative_source') == 'local_llm':
        score += 10
    elif llm.get('narrative_source') == 'deterministic_fallback':
        score += 6

    # Backtest snapshot complete: 10
    bt = packet.get('backtest_snapshot', {})
    if bt.get('backtest_quality') in ('SUFFICIENT', 'LIMITED'):
        score += 10
    elif bt.get('backtest_quality') == 'INSUFFICIENT':
        score += 5
    elif bt.get('sample_size', 0) > 0:
        score += 3

    # Risk/reward complete: 10
    rr = packet.get('risk_reward', {})
    if rr.get('proposed_rr') and rr.get('dollar_risk') is not None:
        score += 10

    return min(100, score)


def _compute_confidence_score(packet):
    """Score out of 100 based on actual trade quality signals."""
    score = 50  # base

    catalyst = packet.get('catalyst_packet', {})
    tech = packet.get('technical_snapshot', {})
    bt = packet.get('backtest_snapshot', {})
    rr = packet.get('risk_reward', {})
    agent = packet.get('agent_votes', {})

    # Verified catalyst: +15
    if catalyst.get('catalyst_verified'):
        score += 15

    # Favorable technicals
    rsi_state = tech.get('rsi_state', '')
    if rsi_state in ('bullish momentum', 'neutral'):
        score += 5
    elif 'overbought' in str(rsi_state):
        score -= 10

    vwap_state = tech.get('vwap_state', '')
    if 'above' in str(vwap_state) and 'extended' not in str(vwap_state):
        score += 5

    # R:R >= 1.5
    proposed_rr = float(rr.get('proposed_rr') or 0)
    if proposed_rr >= 2.0:
        score += 10
    elif proposed_rr >= 1.5:
        score += 5
    elif proposed_rr < 1.2:
        score -= 10

    # Sector not severely underperforming
    vs_sector = float(packet.get('sector_packet', {}).get('vs_sector_pct') or 0)
    if vs_sector < -10:
        score -= 15
    elif vs_sector < -5:
        score -= 5

    # Critic not blocking
    critic = catalyst.get('critic_verdict', '')
    if critic == 'BLOCK':
        score -= 25
    elif critic == 'DOWNGRADE':
        score -= 10

    # Agent votes positive
    positive_votes = sum(1 for v in agent.values()
                        if isinstance(v, dict) and v.get('vote') in ('APPROVE_TEST', 'CAUTIOUS_TEST'))
    negative_votes = sum(1 for v in agent.values()
                        if isinstance(v, dict) and v.get('vote') in ('REJECT', 'BLOCK'))
    score += positive_votes * 3
    score -= negative_votes * 8

    # Backtest quality
    bt_quality = bt.get('backtest_quality', 'NO_DATA')
    if bt_quality == 'SUFFICIENT':
        bt_wr = bt.get('win_rate')
        if bt_wr and float(bt_wr) > 0.5:
            score += 10
    elif bt_quality == 'LIMITED':
        score += 3

    return max(0, min(100, score))


def build_research_packet(conn, proposal_id, refresh=False):
    """Build complete research packet for a proposal."""
    cur = conn.cursor()

    # Load proposal
    cur.execute("""
        SELECT * FROM paper_trade_proposals WHERE id = %s
    """, [proposal_id])
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if not row:
        return {"error": f"Proposal {proposal_id} not found"}
    prop = dict(zip(cols, row))
    symbol = prop['symbol']
    strategy_id = prop.get('strategy_id') or ''

    log.info(f"Building research packet for {symbol} (#{proposal_id})...")

    def _safe_rollback():
        try: conn.rollback()
        except: pass

    # ── 1. Technical Snapshot ──────────────────────────────────────────
    technical = {}
    try:
        from proposal_technical_snapshot import generate_snapshot
        technical = generate_snapshot(conn, proposal_id=proposal_id)
        log.info(f"  Technical snapshot: ATR={technical.get('atr')} RSI={technical.get('rsi')}")
    except Exception as e:
        log.warning(f"  Technical snapshot failed: {e}")
        _safe_rollback()
        technical = {"error": str(e)}

    # ── 2. Backtest ────────────────────────────────────────────────────
    backtest = {}
    try:
        _safe_rollback()
        from proposal_backtest_engine import backtest_proposal
        backtest = backtest_proposal(conn, proposal_id)
        log.info(f"  Backtest: quality={backtest.get('backtest_quality')} samples={backtest.get('sample_size')}")
    except Exception as e:
        log.warning(f"  Backtest failed: {e}")
        _safe_rollback()
        backtest = {"error": str(e)}

    # ── 3. Agent Review ────────────────────────────────────────────────
    agent_result = {}
    try:
        _safe_rollback()
        from proposal_agent_review import review_proposal
        agent_result = review_proposal(conn, proposal_id)
        log.info(f"  Agent review: status={agent_result.get('agent_review_status')}")
    except Exception as e:
        log.warning(f"  Agent review failed: {e}")
        _safe_rollback()
        agent_result = {"error": str(e)}

    # ── 4. LLM Review ─────────────────────────────────────────────────
    llm_result = {}
    try:
        _safe_rollback()
        from proposal_llm_reviewer import review_proposal as llm_review
        llm_result = llm_review(conn, proposal_id)
        log.info(f"  LLM review: source={llm_result.get('narrative_source')}")
    except Exception as e:
        log.warning(f"  LLM review failed: {e}")
        _safe_rollback()
        llm_result = {"error": str(e)}

    # ── 5. Source lineage ──────────────────────────────────────────────
    _safe_rollback()
    cur.execute("""
        SELECT source, screener_label, run_label, scanned_at, score, decision, grade,
               ticker_perf_1m, sector_perf_1m, vs_sector_pct,
               sector, industry
        FROM trade_ai_scans WHERE symbol = %s
        ORDER BY scanned_at DESC LIMIT 1
    """, [symbol])
    scan_cols = [d[0] for d in cur.description]
    scan_row = cur.fetchone()
    source_lineage = dict(zip(scan_cols, scan_row)) if scan_row else {}

    # ── 6. Risk gate ──────────────────────────────────────────────────
    _safe_rollback()
    risk_gate = {}
    try:
        from risk_gate import RiskGate
        rg = RiskGate(conn)
        entry = float(prop.get('proposed_entry') or 0)
        stop = float(prop.get('proposed_stop') or 0)
        dollar_size = entry * int(prop.get('proposed_shares') or 0)
        decision = rg.check(
            symbol=symbol, strategy_id=strategy_id,
            trade_plan={'stop_loss': stop, 'dollar_size': dollar_size},
            account=prop.get('proposed_account', 'TOS_PAPER'),
            mode='paper', action_context='paper_trade',
            extra={'sector': prop.get('sector'), 'intel_readiness': prop.get('intel_readiness')}
        )
        risk_gate = {
            "approved": decision.approved,
            "result": decision.result,
            "reason_codes": decision.reason_codes,
            "reason_text": decision.reason_text,
        }
    except Exception as e:
        risk_gate = {"approved": False, "result": "RISK_GATE_ERROR", "reason_codes": [str(e)]}

    # ── 7. Decision gate ──────────────────────────────────────────────
    decision_gate = {}
    try:
        from proposal_decision_gate import compute_decision_state
        decision_gate = compute_decision_state(
            prop, technical, backtest,
            agent_result.get('reviews', {}),
            agent_result.get('agent_votes', {}),
            llm_result.get('review', {}),
            risk_gate
        )
    except Exception as e:
        log.warning(f"  Decision gate failed: {e}")
        decision_gate = {"decision_state": "RESEARCH_INCOMPLETE", "reasons": [str(e)]}

    # ── Build packet ──────────────────────────────────────────────────
    # Catalyst packet
    catalyst_packet = {
        "catalyst": prop.get('catalyst'),
        "catalyst_verified": prop.get('catalyst_verified'),
        "catalyst_confidence": float(prop.get('catalyst_confidence') or 0),
        "critic_verdict": prop.get('critic_verdict'),
        "critic_confidence": float(prop.get('critic_confidence') or 0),
        "critic_reasoning": prop.get('critic_reasoning'),
    }

    # Sector packet (vs_sector_pct comes from scan, not proposal table)
    sector_packet = {
        "sector": prop.get('sector'),
        "industry": prop.get('industry'),
        "ticker_perf_1m": source_lineage.get('ticker_perf_1m'),
        "sector_perf_1m": source_lineage.get('sector_perf_1m'),
        "vs_sector_pct": source_lineage.get('vs_sector_pct'),
    }

    # Risk/reward
    entry = float(prop.get('proposed_entry') or 0)
    stop = float(prop.get('proposed_stop') or 0)
    t1 = float(prop.get('proposed_target1') or 0)
    shares = int(prop.get('proposed_shares') or 0)
    dollar_risk = abs(entry - stop) * shares
    dollar_reward = (t1 - entry) * shares
    risk_reward = {
        "proposed_entry": entry, "proposed_stop": stop, "proposed_target1": t1,
        "proposed_shares": shares,
        "dollar_risk": round(dollar_risk, 2),
        "dollar_reward": round(dollar_reward, 2),
        "proposed_rr": float(prop.get('proposed_rr') or 0),
        "risk_pct_portfolio": float(prop.get('risk_pct_portfolio') or 0),
    }

    # Stock history from backtest
    stock_history = backtest.get('symbol_history', {})

    # News packet
    news_packet = []
    try:
        cur.execute("""
            SELECT title, source, published_at, sentiment
            FROM news_articles WHERE symbol = %s
            AND published_at > NOW() - INTERVAL '3 days'
            ORDER BY published_at DESC LIMIT 5
        """, [symbol])
        for title, source, pub, sent in cur.fetchall():
            news_packet.append({"title": title, "source": source, "published_at": str(pub), "sentiment": sent})
    except Exception:
        pass

    # Missing data
    missing = []
    if not technical.get('atr'):
        missing.append("ATR missing — indicator engine has not populated this symbol")
    if technical.get('rsi') is None:
        missing.append("RSI missing — indicator engine pending")
    if not technical.get('vwap_distance_pct') and technical.get('vwap_distance_pct') != 0:
        missing.append("VWAP missing — no intraday VWAP data")
    fib = technical.get('fib_context', {})
    if isinstance(fib, dict) and not fib.get('available', True):
        missing.append(fib.get('summary', 'Fib unavailable'))
    if not news_packet:
        missing.append("No recent news articles found")
    if backtest.get('backtest_quality') == 'NO_DATA':
        missing.append("Backtest insufficient — no local samples")
    elif backtest.get('backtest_quality') == 'INSUFFICIENT':
        missing.append(f"Backtest insufficient — only {backtest.get('sample_size', 0)} local samples")
    agent_status = agent_result.get('agent_review_status', '')
    if agent_status not in ('complete', 'BLOCKED', 'REJECTED'):
        missing.append("Agent review incomplete — click Run AI Review")
    llm_src = llm_result.get('narrative_source', '')
    if llm_src == 'deterministic_fallback':
        missing.append("LLM review unavailable — using deterministic fallback")

    # Approval blockers
    blockers = []
    if not risk_gate.get('approved'):
        blockers.append(f"Risk gate: {risk_gate.get('result')} — {', '.join(risk_gate.get('reason_codes', []))}")
    agent_votes = agent_result.get('agent_votes', {})
    for name, v in agent_votes.items():
        if isinstance(v, dict) and v.get('vote') == 'BLOCK':
            blockers.append(f"{name} BLOCKED")
    if catalyst_packet.get('critic_verdict') == 'BLOCK':
        blockers.append("Critic BLOCKED")

    # Agent votes for packet
    agent_votes_packet = agent_result.get('agent_votes', {})

    # Timeframe
    timeframe_map = {
        'momentum_scalp': 'intraday_scalp',
        'gap_and_go': 'intraday_scalp',
        'swing_breakout': 'multi_day_swing',
        'sector_rotation': 'multi_week_position',
        'income_add': 'long_term_income',
        'earnings_catalyst': 'event_driven',
    }
    timeframe = timeframe_map.get(strategy_id, 'unknown')

    # Final summary
    ds = decision_gate.get('decision_state', 'RESEARCH_INCOMPLETE')
    conf = _compute_confidence_score({
        'catalyst_packet': catalyst_packet,
        'technical_snapshot': technical,
        'backtest_snapshot': backtest,
        'risk_reward': risk_reward,
        'sector_packet': sector_packet,
        'agent_votes': agent_votes_packet,
    })
    research = _compute_research_score({
        'source_lineage': source_lineage,
        'technical_snapshot': technical,
        'catalyst_packet': catalyst_packet,
        'agent_review_status': {'status': agent_result.get('agent_review_status', 'pending')},
        'local_llm_review': llm_result,
        'backtest_snapshot': backtest,
        'risk_reward': risk_reward,
    })
    live_readiness = 0  # always 0 — paper only

    final_summary = {
        "decision_state": ds,
        "research_score": research,
        "confidence_score": conf,
        "live_readiness_score": live_readiness,
        "approval_allowed": ds in ('APPROVE_READY_PAPER_TEST', 'CAUTIOUS_PAPER_TEST', 'BACKTEST_INSUFFICIENT'),
        "approval_blocked_reason": "; ".join(blockers) if blockers else None,
        "missing_data_count": len(missing),
        "blocker_count": len(blockers),
    }

    packet = {
        "proposal_id": proposal_id,
        "symbol": symbol,
        "strategy_id": strategy_id,
        "timeframe": timeframe,
        "source_lineage": {k: str(v) for k, v in source_lineage.items()} if source_lineage else {},
        "agent_review_status": {
            "status": agent_result.get('agent_review_status', 'pending'),
            "required": agent_result.get('agents', []),
            "completed": list(agent_result.get('reviews', {}).keys()),
        },
        "agent_votes": agent_votes_packet,
        "local_llm_review": {
            "narrative_source": llm_result.get('narrative_source', 'unavailable'),
            "model": llm_result.get('model', 'none'),
            "decision": llm_result.get('review', {}).get('decision'),
            "confidence_score": llm_result.get('review', {}).get('confidence_score'),
            "review": llm_result.get('review', {}),
        },
        "technical_snapshot": technical,
        "catalyst_packet": catalyst_packet,
        "news_packet": news_packet,
        "sector_packet": sector_packet,
        "stock_history": stock_history,
        "backtest_snapshot": backtest,
        "risk_reward": risk_reward,
        "risk_gate": risk_gate,
        "decision_gate": decision_gate,
        "missing_data": missing,
        "approval_blockers": blockers,
        "final_summary": final_summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── Persist ───────────────────────────────────────────────────────
    try:
        cur.execute("""
            INSERT INTO proposal_research_packets
                (proposal_id, symbol, strategy_id, packet_status,
                 research_score, confidence_score, live_readiness_score,
                 agent_review_complete, local_llm_review_complete,
                 technical_review_complete, backtest_complete,
                 risk_gate_snapshot, packet)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (proposal_id) DO UPDATE SET
                packet_status = EXCLUDED.packet_status,
                research_score = EXCLUDED.research_score,
                confidence_score = EXCLUDED.confidence_score,
                live_readiness_score = EXCLUDED.live_readiness_score,
                agent_review_complete = EXCLUDED.agent_review_complete,
                local_llm_review_complete = EXCLUDED.local_llm_review_complete,
                technical_review_complete = EXCLUDED.technical_review_complete,
                backtest_complete = EXCLUDED.backtest_complete,
                risk_gate_snapshot = EXCLUDED.risk_gate_snapshot,
                packet = EXCLUDED.packet,
                updated_at = NOW()
            RETURNING id
        """, [
            proposal_id, symbol, strategy_id, ds,
            research, conf, live_readiness,
            agent_result.get('agent_review_status') == 'complete',
            llm_result.get('narrative_source') not in ('', 'unavailable', None),
            bool(technical.get('rsi') or technical.get('atr')),
            backtest.get('backtest_quality') not in ('NO_DATA', None),
            json.dumps(risk_gate, default=str),
            json.dumps(packet, default=str),
        ])
        packet_id = cur.fetchone()[0]

        # Update proposal row
        cur.execute("""
            UPDATE paper_trade_proposals
            SET research_packet_id = %s,
                research_score = %s,
                confidence_score = %s,
                live_readiness_score = %s,
                approval_allowed = %s,
                approval_blocked_reason = %s,
                updated_at = NOW()
            WHERE id = %s
        """, [
            packet_id, research, conf, live_readiness,
            final_summary['approval_allowed'],
            final_summary['approval_blocked_reason'],
            proposal_id,
        ])
        conn.commit()
        log.info(f"  Packet #{packet_id}: research={research} confidence={conf} decision={ds}")
    except Exception as e:
        log.error(f"  Failed to persist packet: {e}")
        conn.rollback()

    return packet


def main():
    parser = argparse.ArgumentParser(description="Research packet builder")
    parser.add_argument("--proposal-id", type=int)
    parser.add_argument("--all-pending", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--refresh-stale", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.all_pending:
            cur = conn.cursor()
            if args.refresh_stale:
                # Only refresh packets older than 15 minutes
                cur.execute("""
                    SELECT ptp.id FROM paper_trade_proposals ptp
                    LEFT JOIN proposal_research_packets prp ON prp.proposal_id = ptp.id
                    WHERE ptp.status = 'PENDING'
                    AND (prp.id IS NULL OR prp.updated_at < NOW() - INTERVAL '15 minutes')
                    ORDER BY ptp.created_at DESC
                """)
            else:
                cur.execute("SELECT id FROM paper_trade_proposals WHERE status='PENDING' ORDER BY created_at DESC")
            for (pid,) in cur.fetchall():
                build_research_packet(conn, pid, refresh=True)
        elif args.proposal_id:
            packet = build_research_packet(conn, args.proposal_id, refresh=args.refresh)
            print(json.dumps(packet, indent=2, default=str))
        else:
            print("Usage: --proposal-id N [--refresh] or --all-pending [--refresh-stale]")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
