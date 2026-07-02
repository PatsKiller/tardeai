#!/usr/bin/env python3
"""hermes_scalp_post_trade_review.py — Post-Trade Review Agent (Phase 3).

Generates structured stop-quality critiques for closed momentum scalps (deterministic dry-run
mode; optional LLM via journal_ai_critique when --llm). Syncs validation_tracker.json from
scalp_stop_validation_tracker.py.

  python3 scripts/hermes_scalp_post_trade_review.py [--once] [--interval 300] [--llm]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.momentum_scalp_swarm_state import now_iso, read_json, write_json, append_audit  # noqa: E402

SCALP_LLM_PROMPT = """You are a momentum-scalp stop-discipline coach. Use ONLY the facts below.

Trade: {symbol} momentum_scalp | entry ${entry} → exit ${exit_} | P&L ${pnl}
Regime: {regime} | setup: {setup}
Deterministic stop review (already computed — do not contradict):
- Q1 initial stop vs MAE: {q1}
- Q2 trail activation: {q2}
- Q3 R left on table: {q3}
- Q4 recommended params: {q4}
- Breakeven timing: {be_timing}
- Realized R: {realized_r}

Layer 3 trailing is config-OFF (backtest net-negative). Do NOT recommend enabling trailing execution.

Return STRICT JSON only:
{{"summary": "2-3 sentences",
"strengths": ["..."],
"improvements": ["..."],
"takeaways": ["..."],
"stop_critique": {{
  "initial_stop_vs_mae": "...",
  "breakeven_timing": "...",
  "r_left_on_table": "...",
  "recommended_params_setup_regime": "..."
}}}}"""

OAUTH_LANES = ("grok", "chatgpt", "local")


def _r_multiple(entry, exit_, stop) -> float | None:
    try:
        e, x, s = float(entry), float(exit_), float(stop)
        risk = e - s
        if risk <= 0:
            return None
        return round((x - e) / risk, 3)
    except (TypeError, ValueError):
        return None


def _stop_quality_score(critique: dict) -> int:
    """Heuristic 1–5 from deterministic answers."""
    score = 3
    mae_text = str(critique.get("initial_stop_vs_mae") or "").lower()
    if "optimal" in mae_text:
        score += 1
    elif "too tight" in mae_text or "too loose" in mae_text:
        score -= 1
    be = str(critique.get("breakeven_timing") or "").lower()
    if "correct" in be or "secured" in be:
        score += 1
    elif "missed" in be or "late" in be:
        score -= 1
    r_left = critique.get("r_left_on_table")
    if r_left is not None and float(r_left) > 1.5:
        score -= 1
    return max(1, min(5, score))


def _critique_trade(row: dict) -> dict:
    """Answer the four §5 stop quality questions deterministically."""
    sym = row.get("symbol")
    entry = row.get("entry_price")
    exit_ = row.get("exit_price")
    stop = row.get("planned_stop") or row.get("stop_loss_price")
    mae = row.get("max_adverse_excursion")
    mfe = row.get("max_favorable_excursion")
    be_r = row.get("breakeven_trigger_r")
    trail_active = row.get("trailing_active")
    regime = row.get("market_regime") or "unknown"
    init_atr = row.get("initial_stop_atr")
    final_r_stop = row.get("final_r_vs_planned_stop")

    realized_r = _r_multiple(entry, exit_, stop)
    # paper_trades.max_adverse_excursion / max_favorable_excursion are % from entry (see trade_execution_analyzer)
    mae_r = mfe_r = None
    risk_pct = None
    if entry and stop:
        try:
            e, s = float(entry), float(stop)
            if e > 0 and e > s:
                risk_pct = (e - s) / e * 100.0
        except (TypeError, ValueError):
            pass
    if mae is not None and risk_pct and risk_pct > 0:
        mae_r = round(abs(float(mae)) / risk_pct, 2)
    if mfe is not None and risk_pct and risk_pct > 0:
        mfe_r = round(abs(float(mfe)) / risk_pct, 2)

    # Q1: initial stop vs MAE
    if mae_r is None:
        q1 = "unknown — MAE not tagged"
    elif mae_r < 0.5:
        q1 = f"too tight — MAE only {mae_r}R (stopped on noise risk)"
    elif mae_r > 1.0:
        q1 = f"too loose — MAE {mae_r}R exceeded 1R planned risk"
    else:
        q1 = f"optimal — MAE {mae_r}R within planned 1R envelope"

    # Q2: trail activation (L3 advisory — config OFF)
    if trail_active:
        q2 = "trail was active — verify activation was after BE +1.5R (L3 advisory only)"
    else:
        q2 = "trail not active (expected — Layer 3 config-OFF per §2.1 backtest gate)"

    # Q3: R left on table (MFE in R minus realized R)
    r_left = None
    if mfe_r is not None and realized_r is not None:
        r_left = round(max(0, mfe_r - realized_r), 2)
    q3 = f"{r_left}R left on table (MFE-R minus realized)" if r_left is not None else "insufficient MFE/replay data"

    # Q4: recommended params
    setup = row.get("setup_type") or row.get("signal_grade") or "momentum_scalp"
    q4 = {
        "setup": setup,
        "regime": regime,
        "initial_stop_atr_mult": init_atr or "1.0-1.5",
        "breakeven_trigger_r": be_r or 1.2,
        "trail_mult": "advisory-only — do not enable L3 execution",
        "note": "Layer 3 trailing stays config-OFF until §6 paper validation overturns backtest",
    }

    be_timing = "unknown"
    if be_r is not None and realized_r is not None:
        if float(be_r) <= abs(realized_r) and realized_r > 0:
            be_timing = f"breakeven trigger {be_r}R — trade closed +{realized_r}R (BE rule relevant if still open at trigger)"
        else:
            be_timing = f"breakeven at {be_r}R — closed at {realized_r}R before/at trigger"

    critique = {
        "trade_id": row.get("id"),
        "symbol": sym,
        "closed_at": str(row.get("closed_at") or row.get("exit_time") or ""),
        "realized_r": realized_r,
        "initial_stop_vs_mae": q1,
        "trail_activation_correct": q2,
        "r_left_on_table": r_left,
        "r_left_on_table_narrative": q3,
        "recommended_params": q4,
        "breakeven_timing": be_timing,
        "final_r_vs_planned_stop": final_r_stop,
        "policy_sections_reviewed": ["§3 L1", "§3 L2", "§3 L3 (advisory)", "§3 L4", "§5", "§6"],
        "mode": "deterministic",
    }
    critique["stop_quality_score"] = _stop_quality_score(critique)
    return critique


def _parse_scalp_llm(text: str) -> dict | None:
    import re
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    if not {"summary", "stop_critique"}.issubset(d.keys()):
        return None
    return d


def _pick_oauth_lane(preferred: str = "grok") -> str | None:
    import llm_lane
    order = [preferred] + [l for l in OAUTH_LANES if l != preferred]
    for lane in order:
        if lane == "local" or llm_lane.available(lane):
            return lane
    return None


def _enrich_with_llm(crit: dict, row: dict, *, lane: str = "grok") -> dict:
    """OAuth LLM enrichment via llm_lane (Grok :8645, ChatGPT :8646, local fallback)."""
    chosen = _pick_oauth_lane(lane)
    if not chosen:
        return {**crit, "llm_enhanced": False, "llm_error": "no LLM lane available (oauth proxies down?)"}

    import llm_lane
    q4 = crit.get("recommended_params") or {}
    prompt = SCALP_LLM_PROMPT.format(
        symbol=crit.get("symbol"),
        entry=row.get("entry_price"),
        exit_=row.get("exit_price"),
        pnl=row.get("pnl"),
        regime=row.get("market_regime") or "unknown",
        setup=row.get("setup_type") or row.get("signal_grade") or "momentum_scalp",
        q1=crit.get("initial_stop_vs_mae"),
        q2=crit.get("trail_activation_correct"),
        q3=crit.get("r_left_on_table_narrative"),
        q4=json.dumps(q4, default=str),
        be_timing=crit.get("breakeven_timing"),
        realized_r=crit.get("realized_r"),
    )
    try:
        raw = llm_lane.generate(prompt, lane=chosen, timeout=90)
        parsed = _parse_scalp_llm(raw)
        if not parsed:
            return {**crit, "llm_enhanced": False, "llm_lane": chosen, "llm_error": "unparseable response", "llm_raw_preview": (raw or "")[:400]}
        sc = parsed.get("stop_critique") or {}
        merged = {
            **crit,
            "mode": "deterministic+oauth",
            "llm_enhanced": True,
            "llm_lane": chosen,
            "llm_summary": parsed.get("summary"),
            "llm_strengths": parsed.get("strengths") or [],
            "llm_improvements": parsed.get("improvements") or [],
            "llm_takeaways": parsed.get("takeaways") or [],
            "initial_stop_vs_mae": sc.get("initial_stop_vs_mae") or crit.get("initial_stop_vs_mae"),
            "breakeven_timing": sc.get("breakeven_timing") or crit.get("breakeven_timing"),
            "r_left_on_table_narrative": sc.get("r_left_on_table") or crit.get("r_left_on_table_narrative"),
            "recommended_params": {
                **q4,
                "llm_note": sc.get("recommended_params_setup_regime"),
            },
        }
        merged["stop_quality_score"] = _stop_quality_score(merged)
        return merged
    except Exception as e:
        return {**crit, "llm_enhanced": False, "llm_lane": chosen, "llm_error": str(e)[:200]}


def _fetch_unreviewed(reviewed_ids: set) -> list[dict]:
    from db_adapter import _execute
    rows = _execute(
        """SELECT id, symbol, entry_price, exit_price, planned_stop, stop_loss_price,
                  exit_reason, market_regime, max_adverse_excursion, max_favorable_excursion,
                  breakeven_trigger_r, trailing_active, initial_stop_atr, final_r_vs_planned_stop,
                  setup_type, signal_grade, closed_at, exit_time, pnl
           FROM paper_trades
           WHERE strategy_id='momentum_scalp'
             AND (lifecycle_state='closed' OR status='closed')
             AND exit_price IS NOT NULL
             AND exit_reason NOT IN ('duplicate_of_22','dedup_removed','cancelled')
           ORDER BY COALESCE(closed_at, exit_time, updated_at) DESC NULLS LAST
           LIMIT 50""",
        fetch="all",
    ) or []
    out = []
    for r in rows:
        d = dict(r)
        if d.get("id") not in reviewed_ids:
            out.append(d)
    return out


def _sync_validation_tracker() -> dict:
    from scalp_stop_validation_tracker import run as tracker_run
    report = tracker_run("momentum_scalp")
    m = report.get("metrics") or {}
    payload = {
        "schema_version": "1.0",
        "updated_at": now_iso(),
        "gate": "4.4_to_4.5",
        "closed_trades": m.get("closed_trades", 0),
        "social_route_trades": 0,  # enriched when social tagging wired
        "metrics": m,
        "gate_verdicts": report.get("gate_verdicts"),
        "overall": report.get("overall"),
        "trailing_note": report.get("trailing_note"),
        "policy_ref": "MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md §6",
        "source": "scalp_stop_validation_tracker.py",
    }
    write_json("validation_tracker.json", payload)
    return payload


def _rows_needing_llm(reviews: list[dict], *, force: bool) -> list[dict]:
    if force:
        return list(reviews)
    return [r for r in reviews if not r.get("llm_enhanced")]


def tick(*, use_llm: bool = False, llm_lane: str = "grok", force_llm: bool = False) -> dict:
    store = read_json("post_trade_reviews.json", {"reviews": []}) or {"reviews": []}
    reviewed_ids = {r.get("trade_id") for r in (store.get("reviews") or []) if r.get("trade_id") is not None}
    new_rows = _fetch_unreviewed(reviewed_ids)

    new_critiques = []
    llm_enriched = 0
    for row in new_rows[:10]:
        crit = _critique_trade(row)
        if use_llm:
            crit = _enrich_with_llm(crit, row, lane=llm_lane)
            if crit.get("llm_enhanced"):
                llm_enriched += 1
        new_critiques.append(crit)
        append_audit({
            "agent": "post_trade_review",
            "action": "critique",
            "trade_id": crit.get("trade_id"),
            "symbol": crit.get("symbol"),
            "stop_quality_score": crit.get("stop_quality_score"),
        })

    all_reviews = (store.get("reviews") or []) + new_critiques

    # Backfill LLM on existing reviews when no new closed trades
    if use_llm and not new_rows:
        refreshed = []
        for rev in all_reviews:
            if not force_llm and rev.get("llm_enhanced"):
                refreshed.append(rev)
                continue
            row = _fetch_trade_by_id(rev.get("trade_id"))
            if not row:
                refreshed.append(rev)
                continue
            enriched = _enrich_with_llm(rev, row, lane=llm_lane)
            if enriched.get("llm_enhanced"):
                llm_enriched += 1
            refreshed.append(enriched)
        all_reviews = refreshed

    write_json("post_trade_reviews.json", {
        "schema_version": "1.0",
        "updated_at": now_iso(),
        "reviews": all_reviews[-100:],
        "total_reviewed": len(all_reviews),
    })

    tracker = _sync_validation_tracker()

    return {
        "new_critiques": len(new_critiques),
        "llm_enriched": llm_enriched,
        "total_reviewed": len(all_reviews),
        "validation_closed_trades": tracker.get("closed_trades"),
        "validation_overall": tracker.get("overall"),
        "critiques": new_critiques,
        "oauth_lane": llm_lane if use_llm else None,
    }


def _fetch_trade_by_id(trade_id: int) -> dict | None:
    from db_adapter import _execute
    r = _execute(
        """SELECT id, symbol, entry_price, exit_price, planned_stop, stop_loss_price,
                  exit_reason, market_regime, max_adverse_excursion, max_favorable_excursion,
                  breakeven_trigger_r, trailing_active, initial_stop_atr, final_r_vs_planned_stop,
                  setup_type, signal_grade, closed_at, exit_time, pnl
           FROM paper_trades WHERE id=%s AND strategy_id='momentum_scalp'""",
        [trade_id],
        fetch="one",
    )
    return dict(r) if r else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--llm", action="store_true", help="OAuth LLM enrichment (grok/chatgpt via llm_lane)")
    ap.add_argument("--lane", default="grok", choices=["grok", "chatgpt", "local"], help="preferred OAuth lane")
    ap.add_argument("--force-llm", action="store_true", help="re-run LLM on reviews that already have llm_enhanced")
    args = ap.parse_args()
    if args.once:
        print(json.dumps(tick(use_llm=args.llm, llm_lane=args.lane, force_llm=args.force_llm), indent=2, default=str))
        return
    lane_msg = f" llm={args.lane}" if args.llm else ""
    print(f"[post_trade_review] starting loop{lane_msg}", flush=True)
    while True:
        try:
            out = tick(use_llm=args.llm, llm_lane=args.lane, force_llm=args.force_llm)
            print(f"[post_trade_review] {now_iso()} new={out['new_critiques']} llm={out.get('llm_enriched', 0)} total={out['total_reviewed']}", flush=True)
        except Exception as e:
            print(f"[post_trade_review] error: {e}", flush=True)
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    main()