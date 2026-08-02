#!/usr/bin/env python3
"""decision_qa.py — Decision quality assessment, contradiction detection, and gating.

Prevents weak, conflicting, partial, or data-quality-compromised analysis
from appearing as actionable. Every symbol gets a decision_quality_status.

Usage:
    python3 scripts/decision_qa.py [--symbols SCHD RTX] [--all] [--json]

    from decision_qa import assess_symbol, assess_all
"""
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# Recommendation groups for conflict detection
_BUY_GROUP = {"BUY", "ADD", "ADD_ON_PULLBACK", "STRONG_BUY"}
_SELL_GROUP = {"SELL", "TRIM", "AVOID", "REBALANCE_TRIM"}
_HOLD_GROUP = {"HOLD", "NEUTRAL", "IGNORE"}
_UNCERTAIN_GROUP = {"RESEARCH_MORE"}


def _get_conn():
    import psycopg2
    pw = os.environ.get("DB_PASSWORD", "")
    if not pw:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _rec_group(rec: str) -> str:
    r = (rec or "").upper().replace(" ", "_")
    if r in _BUY_GROUP: return "BUY"
    if r in _SELL_GROUP: return "SELL"
    if r in _HOLD_GROUP: return "HOLD"
    if r in _UNCERTAIN_GROUP: return "UNCERTAIN"
    return "UNKNOWN"


def assess_symbol(symbol: str) -> dict:
    """Run full decision QA for a single symbol. Returns assessment dict."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sym = symbol.upper()

    # ── Gather all data ──────────────────────────────────────────

    # Maturity
    cur.execute("SELECT * FROM watchlist_analysis_maturity WHERE symbol=%s", (sym,))
    maturity = cur.fetchone()

    # Agent results
    cur.execute("""
        SELECT DISTINCT ON (agent) agent, recommendation, confidence, created_at
        FROM watchlist_agent_results WHERE symbol=%s AND status='completed'
        ORDER BY agent, created_at DESC
    """, (sym,))
    agent_results = {r["agent"]: dict(r) for r in cur.fetchall()}

    # Synthesis
    cur.execute("SELECT * FROM watchlist_final_synthesis WHERE symbol=%s", (sym,))
    synthesis = cur.fetchone()

    # Strategy card
    cur.execute("SELECT strategy_type FROM watchlist_strategy_cards WHERE symbol=%s", (sym,))
    sc = cur.fetchone()
    strategy_type = sc["strategy_type"] if sc else None

    # Escalation policy (required agents)
    cur.execute("SELECT required_agents FROM watchlist_escalation_policies WHERE strategy_type=%s", (strategy_type or "core_holding",))
    policy = cur.fetchone()
    required_agents = list(policy["required_agents"]) if policy else ["steph", "risk"]

    # Data quality issues (last 7 days)
    cur.execute("""
        SELECT COUNT(*) as cnt FROM alert_events
        WHERE symbol=%s AND data_quality_status NOT IN ('valid', 'unknown')
        AND created_at > NOW() - INTERVAL '7 days'
    """, (sym,))
    dq_issue_count = cur.fetchone()["cnt"]

    # Recent stop triggered
    cur.execute("""
        SELECT COUNT(*) as cnt FROM alert_events
        WHERE symbol=%s AND alert_type='stop_triggered'
        AND created_at > NOW() - INTERVAL '7 days'
    """, (sym,))
    recent_stop_triggered = cur.fetchone()["cnt"] > 0

    # Portfolio weight
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    acct_summaries = holdings.get("account_summaries", {})
    total_portfolio = sum(info.get("total_value", 0) for info in acct_summaries.values())
    sym_mv = sum(float(h.get("market_value", 0) or 0)
                 for h in holdings.get("holdings", []) if h.get("symbol") == sym)
    weight = round(sym_mv / total_portfolio * 100, 2) if total_portfolio > 0 else 0

    cur.close()
    conn.close()

    # ── Detect issues ────────────────────────────────────────────

    conflicts = []
    gating_reasons = []
    status = "actionable"
    actionable = True
    human_review = False

    # 0. CLASSIFICATION REQUIRED — must have active ticker_strategy_classifications row
    try:
        conn_c0 = _get_conn()
        cur_c0 = conn_c0.cursor()
        cur_c0.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE", (sym,))
        c0_row = cur_c0.fetchone()
        cur_c0.close()
        conn_c0.close()
        if not c0_row:
            gating_reasons.append("No active classification in ticker_strategy_classifications — classify before evaluation")
            status = "classification_required"
            actionable = False
            human_review = True
    except Exception:
        pass

    # 1. Missing required agents
    completed_agents = []
    if maturity:
        completed_agents = maturity.get("completed_agents") or []
    # Normalize: risk_agent → risk for comparison
    norm_completed = set()
    for a in completed_agents:
        norm_completed.add(a.replace("_agent", ""))
    norm_required = set(a.replace("_agent", "") for a in required_agents)

    missing = norm_required - norm_completed
    if missing:
        gating_reasons.append(f"Missing required agent(s): {', '.join(sorted(missing))}")
        status = "missing_required_agent"
        actionable = False

    # 2. Contradiction detection between agents
    agent_groups = {}
    for agent, result in agent_results.items():
        rec = result.get("recommendation", "")
        group = _rec_group(rec)
        agent_groups[agent] = {"rec": rec, "group": group, "confidence": result.get("confidence", 0)}

    groups_seen = set(v["group"] for v in agent_groups.values() if v["group"] != "UNKNOWN")

    if "BUY" in groups_seen and "SELL" in groups_seen:
        buy_agents = [a for a, v in agent_groups.items() if v["group"] == "BUY"]
        sell_agents = [a for a, v in agent_groups.items() if v["group"] == "SELL"]
        conflicts.append({
            "type": "buy_vs_sell",
            "description": f"{', '.join(buy_agents)} say BUY-family vs {', '.join(sell_agents)} say SELL-family",
            "agents": {a: v["rec"] for a, v in agent_groups.items()},
        })
        if not missing:
            status = "conflicting_agents"
        human_review = True

    if "HOLD" in groups_seen and recent_stop_triggered:
        hold_agents = [a for a, v in agent_groups.items() if v["group"] == "HOLD"]
        conflicts.append({
            "type": "hold_vs_stop_triggered",
            "description": f"{', '.join(hold_agents)} say HOLD but stop was triggered",
        })
        human_review = True

    if "UNCERTAIN" in groups_seen and synthesis:
        # Only flag as conflict if the uncertain agent had >40% confidence
        # RESEARCH_MORE at <40% confidence = data gap, not a disagreement
        uncertain_high_conf = [a for a, v in agent_groups.items()
                               if v["group"] == "UNCERTAIN" and float(v.get("confidence", 0)) >= 0.4]
        uncertain_low_conf = [a for a, v in agent_groups.items()
                              if v["group"] == "UNCERTAIN" and float(v.get("confidence", 0)) < 0.4]
        if uncertain_high_conf:
            conflicts.append({
                "type": "uncertain_agent_with_synthesis",
                "description": f"{', '.join(uncertain_high_conf)} say RESEARCH_MORE (>40% conf) but synthesis produced final recommendation — genuine uncertainty",
            })
        # Low-confidence RESEARCH_MORE is just a data gap — log but don't flag as conflict
        if uncertain_low_conf and not uncertain_high_conf:
            # Not a conflict — just note for audit
            gating_reasons.append(f"{', '.join(uncertain_low_conf)} returned RESEARCH_MORE due to insufficient data (not a conflict)")

    # 3. Data quality
    if dq_issue_count > 0:
        gating_reasons.append(f"{dq_issue_count} data quality issue(s) in last 7 days")
        if status == "actionable":
            status = "data_quality_warning"
        # Don't hard-block unless multiple critical
        if dq_issue_count >= 3:
            status = "data_quality_blocked"
            actionable = False

    # 4. Tiny position
    if weight < 0.5 and weight > 0:
        gating_reasons.append(f"Position weight {weight:.2f}% < 0.5% — low priority")
        if status == "actionable" and not recent_stop_triggered:
            status = "tiny_position_low_priority"
        # Only actionable if alert is severe
        if not recent_stop_triggered and status == "tiny_position_low_priority":
            actionable = False

    # 5. Stale analysis (synthesis older than 7 days)
    if synthesis and synthesis.get("updated_at"):
        synth_age = datetime.now(synthesis["updated_at"].tzinfo) - synthesis["updated_at"]
        if synth_age.days > 7:
            gating_reasons.append(f"Synthesis is {synth_age.days} days old")
            if status == "actionable":
                status = "stale_analysis"
            actionable = False

    # 6. No synthesis at all
    if not synthesis and maturity and maturity.get("analysis_stage") not in ("raw_data_only", "strategy_card_ready"):
        gating_reasons.append("No final synthesis exists despite agent reviews")
        status = "partial_review"
        actionable = False

    # 7. Conflicts override actionable if unresolved
    if conflicts and not (synthesis and synthesis.get("conflicts")):
        # Synthesis didn't explicitly resolve conflicts
        if actionable:
            status = "needs_human_review"
            human_review = True
            actionable = False

    # 8. Strategy-specific checks
    if strategy_type == "income" and synthesis:
        synth_rec = (synthesis.get("recommendation") or "").upper()
        synth_reasons = synthesis.get("reason_codes") or []
        # Check if TRIM/SELL recommendation is driven solely by technicals
        if synth_rec in ("TRIM", "SELL"):
            tech_only_reasons = {"overbought", "rsi_high", "technical_overbought"}
            if set(r.lower() for r in synth_reasons) <= tech_only_reasons:
                conflicts.append({
                    "type": "income_etf_technical_trim",
                    "description": f"Income ETF with TRIM recommendation driven only by technical signals: {synth_reasons}",
                })
                gating_reasons.append("Income ETF should not TRIM solely on technical signals")
                human_review = True
                if status == "actionable":
                    status = "needs_human_review"
                    actionable = False

    # 9. No target allocation exists — cannot recommend exact trim quantity
    if synthesis and synthesis.get("recommendation") in ("TRIM", "REBALANCE_TRIM"):
        gating_reasons.append("No target allocation database — exact trim quantity is estimated")

    # 9b. Portfolio gating — layer allocation check
    try:
        conn_qa = _get_conn()
        import psycopg2.extras as _pxe2
        cur_qa = conn_qa.cursor(cursor_factory=_pxe2.RealDictCursor)
        cur_qa.execute("""
            SELECT pl.layer_id, pl.target_min_pct, pl.target_max_pct
            FROM portfolio_layers pl
        """)
        layer_targets = {r["layer_id"]: (float(r["target_min_pct"]), float(r["target_max_pct"])) for r in cur_qa.fetchall()}
        cur_qa.close()
        conn_qa.close()

        # Check if income_generators is underweight
        # We already computed this in the income engine — get from DB
        # Approximate: if income layer is <25% and we're recommending ADD for a core_compounder, flag
        if synthesis and layer_targets:
            synth_rec = (synthesis.get("recommendation") or "").upper()
            # If recommending ADD on a core_compounder while income layer is underweight
            cur_qa2 = _get_conn().cursor(cursor_factory=_pxe2.RealDictCursor)
            cur_qa2.execute("SELECT layer_id FROM income_asset_profiles WHERE symbol=%s", (sym,))
            sym_layer_row = cur_qa2.fetchone()
            sym_layer = sym_layer_row["layer_id"] if sym_layer_row else "core_compounders"
            cur_qa2.close()

            if synth_rec in ("ADD", "BUY") and sym_layer == "core_compounders":
                # Check if core is already overweight
                gating_reasons.append("Note: core_compounders layer is overweight (86.9% vs 40-60% target) — prioritize income_generators additions")
    except Exception:
        pass

    # 10. Income-specific QA checks
    cur2 = _get_conn().cursor()
    import psycopg2.extras as _pxe
    cur2 = _get_conn().cursor(cursor_factory=_pxe.RealDictCursor)
    cur2.execute("SELECT * FROM income_asset_profiles WHERE symbol=%s", (sym,))
    income_profile = cur2.fetchone()
    cur2.close()

    if income_profile:
        ip_layer = income_profile.get("layer_id", "")
        ip_income = float(income_profile.get("annual_income", 0) or 0)
        ip_payout = income_profile.get("payout_safety", "unknown")
        ip_yield = float(income_profile.get("dividend_yield_pct", 0) or 0)

        # 10a. Income generator being trimmed — verify payout risk
        if ip_layer == "income_generators" and synthesis:
            synth_rec = (synthesis.get("recommendation") or "").upper()
            if synth_rec in ("TRIM", "SELL", "AVOID") and ip_payout in ("safe", "moderate"):
                conflicts.append({
                    "type": "income_generator_trim_safe_payout",
                    "description": f"Income generator with {ip_payout} payout being recommended for {synth_rec} — verify income impact",
                })
                gating_reasons.append(f"Reducing {sym} removes ${ip_income:,.0f}/yr income (payout: {ip_payout})")
                human_review = True

        # 10b. High yield position missing income context in synthesis
        if ip_yield > 4 and synthesis and not synthesis.get("reason_codes"):
            gating_reasons.append(f"High yield ({ip_yield:.1f}%) position — synthesis should reference income impact")

        # 10d. Past performance used as sole forward rationale
        if synthesis:
            synth_reasons = synthesis.get("reason_codes") or []
            synth_narr = (synthesis.get("synthesis_narrative") or "").lower()
            past_perf_only = {"past_performance", "historical_return", "backtest_score"}
            if set(r.lower() for r in synth_reasons) <= past_perf_only and synth_reasons:
                conflicts.append({
                    "type": "past_performance_as_prediction",
                    "description": "Recommendation uses historical return as sole forward rationale — past performance is not a guarantee",
                })
                human_review = True
                if status == "actionable":
                    status = "needs_human_review"
                    actionable = False

        # 10c. Concentration risk in income — single position > 40% of portfolio income
        ip_income_pct = float(income_profile.get("portfolio_income_pct", 0) or 0)
        if ip_income_pct > 40:
            gating_reasons.append(f"Income concentration risk: {sym} provides {ip_income_pct:.0f}% of total portfolio income")
    else:
        # No income profile at all for a held position
        if weight > 0:
            gating_reasons.append(f"Income data missing — run materialize_income_engine.py")

    # 11. Check synthesis safety — overrides QA if unsafe
    if synthesis and synthesis.get("decision_safety") in ("unsafe", "blocked"):
        ds = synthesis["decision_safety"]
        if actionable:
            status = ds
            actionable = False
        gating_reasons.append(f"Synthesis safety: {ds}")
        safety_reasons = synthesis.get("safety_reasons") or []
        for sr in safety_reasons:
            if isinstance(sr, dict):
                gating_reasons.append(f"  Safety: {sr.get('rule', '?')}")
        if synthesis.get("human_review_required"):
            human_review = True

    out = {
        "symbol": sym,
        "decision_quality_status": status,
        "actionable": actionable,
        "human_review_required": human_review,
        "conflicts_detected": conflicts,
        "gating_reasons": gating_reasons,
        "agent_results": {a: {"rec": v["rec"], "group": v["group"], "confidence": v["confidence"]}
                          for a, v in agent_groups.items()},
        "required_agents": list(norm_required),
        "completed_agents": list(norm_completed),
        "missing_agents": list(missing),
        "strategy_type": strategy_type,
        "portfolio_weight": weight,
        "dq_issue_count": dq_issue_count,
        "has_synthesis": synthesis is not None,
        "synthesis_rec": synthesis.get("recommendation") if synthesis else None,
    }
    # CIO TRUST HIGH|DEGRADED — buy-side fail-closes when dual/street/narrative weak
    try:
        from lib.cio_trust_bundle import apply_trust_to_qa, compute_cio_trust_bundle
        dual = {}
        if synthesis:
            raw_dual = synthesis.get("dual_consensus_json") or synthesis.get("dual_consensus") or {}
            if isinstance(raw_dual, str):
                try:
                    dual = json.loads(raw_dual)
                except Exception:
                    dual = {}
            elif isinstance(raw_dual, dict):
                dual = raw_dual
        trust = compute_cio_trust_bundle(
            recommendation=synthesis.get("recommendation") if synthesis else None,
            synthesis_updated_at=synthesis.get("updated_at") if synthesis else None,
            models_agree=synthesis.get("models_agree") if synthesis else None,
            dual_consensus=dual,
            model_used=synthesis.get("model_used") if synthesis else None,
            decision_quality_status=status,
            decision_safety=synthesis.get("decision_safety") if synthesis else None,
            actionable=actionable,
            synthesis_narrative=synthesis.get("synthesis_narrative") if synthesis else None,
            evidence=dual.get("structured_evidence") if isinstance(dual, dict) else None,
            on_main=False,
        )
        patched = apply_trust_to_qa(out, trust)
        out = patched
        out["decision_quality_status"] = patched.get("status") or patched.get("decision_quality_status") or status
        if "status" in patched and patched["status"] != status:
            out["decision_quality_status"] = patched["status"]
        out["actionable"] = patched.get("actionable", actionable)
        out["human_review_required"] = patched.get("needs_human_review") or patched.get("human_review_required") or human_review
        out["gating_reasons"] = patched.get("gating_reasons") or gating_reasons
        out["cio_trust"] = patched.get("cio_trust") or trust
    except Exception:
        pass
    return out


def assess_all() -> list:
    """Run decision QA for all symbols with maturity records."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT symbol FROM watchlist_analysis_maturity")
    symbols = [r["symbol"] for r in cur.fetchall()]
    conn.close()

    results = []
    for sym in symbols:
        try:
            r = assess_symbol(sym)
            results.append(r)
            _persist_qa(sym, r)
        except Exception as e:
            print(f"  [qa] {sym}: error — {e}")
    return results


def _persist_qa(symbol: str, qa: dict):
    """Write QA results back to DB."""
    conn = _get_conn()
    cur = conn.cursor()

    status = qa["decision_quality_status"]
    actionable = qa["actionable"]
    human_review = qa["human_review_required"]
    conflicts = json.dumps(qa["conflicts_detected"], default=str)
    gating = json.dumps(qa["gating_reasons"], default=str)

    # Update synthesis if it exists
    cur.execute("""
        UPDATE watchlist_final_synthesis
        SET decision_quality_status = %s, actionable = %s,
            human_review_required = %s, conflicts_detected = %s,
            gating_reasons = %s, updated_at = now()
        WHERE symbol = %s
    """, (status, actionable, human_review, conflicts, gating, symbol))

    # Always update maturity
    cur.execute("""
        UPDATE watchlist_analysis_maturity
        SET decision_quality_status = %s, actionable = %s, updated_at = now()
        WHERE symbol = %s
    """, (status, actionable, symbol))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    symbols = None
    if "--symbols" in sys.argv:
        idx = sys.argv.index("--symbols")
        symbols = [s.upper() for s in sys.argv[idx + 1:] if not s.startswith("-")]
    elif "--all" in sys.argv:
        symbols = None

    if symbols:
        results = []
        for sym in symbols:
            r = assess_symbol(sym)
            _persist_qa(sym, r)
            results.append(r)
    else:
        results = assess_all()

    for r in results:
        icon = "\u2713" if r["actionable"] else "\u2717"
        flags = []
        if r["missing_agents"]: flags.append(f"missing:{','.join(r['missing_agents'])}")
        if r["conflicts_detected"]: flags.append(f"conflicts:{len(r['conflicts_detected'])}")
        if r["dq_issue_count"]: flags.append(f"dq:{r['dq_issue_count']}")
        if r["human_review_required"]: flags.append("human_review")
        flag_str = f" [{' | '.join(flags)}]" if flags else ""
        print(f"  {icon} {r['symbol']:>6} {r['decision_quality_status']:>28} weight={r['portfolio_weight']:>6.2f}% synth={r.get('synthesis_rec') or '—':>16}{flag_str}")

    if "--json" in sys.argv:
        print(json.dumps(results, indent=2, default=str))
