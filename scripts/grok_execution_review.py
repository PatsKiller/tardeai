#!/usr/bin/env python3
"""grok_execution_review.py — Grok coaching on COMPUTED execution metrics (advisory; read-only).

Feeds the deterministic metrics from trade_execution_quality to Grok (free OAuth lane) and stores a strict
JSON coaching record in trade_execution_grok_reviews — SEPARATE from the computed numbers. Grok explains and
classifies; it does NOT produce the numeric scores (those are already computed). Parse-strict: a bad response
is stored as review_status='parse_failed', never fabricated.

  python3 scripts/grok_execution_review.py --limit 10 --apply
  python3 scripts/grok_execution_review.py --trade-key srt:279 --apply
"""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PROMPT_VERSION = "exec_review_v1"


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


PROMPT = """You are a disciplined trading-execution coach. Below are ALREADY-COMPUTED, factual metrics for one
closed trade. Do NOT invent or change any numbers — only interpret them. A profitable trade can still be poorly
executed. Be specific and trade-specific (no generic 'tighten stops' filler).

Trade: {symbol} [{strategy}] {outcome}/{execution}
Entry {entry_price} @ {entry_time}  ->  Exit {exit_price} @ {exit_time}  | realized P&L ${pnl}
Entry RVOL {rvol} (volume confirmed: {vol_conf}) | above VWAP: {above_vwap} ({vwap_dist}%) | RSI {rsi} | MACD {macd}
Capture ratio {capture} | MFE after entry {mfe} | MAE after entry {mae}
Post-exit move {missed_pct}% (10-day {missed_10d}%) | missed-opportunity: {missed_grade}
Entry timing: {entry_timing} | Exit timing: {exit_timing} | flags: {flags} | rule violations: {viol}
Computed summary: {summary}

Return STRICT JSON ONLY (no prose, no markdown), exactly these keys:
{{"execution_label": "...", "primary_mistake": "...", "secondary_mistake": "...", "what_happened": "...",
"what_should_have_happened": "...", "rule_to_test": "...", "backtest_hypotheses": ["...","..."],
"normalized_tags": ["..."], "confidence": 0.0}}"""


def _build(row):
    flags = [k for k in ("no_volume_entry_flag", "early_entry_flag", "late_entry_flag", "premature_exit_flag") if row.get(k)]
    return PROMPT.format(
        symbol=row["symbol"], strategy=row.get("strategy_id") or "unknown",
        outcome=row.get("outcome_grade"), execution=row.get("execution_grade"),
        entry_price=row.get("entry_price"), exit_price=row.get("exit_price"),
        entry_time=str(row.get("entry_time"))[:19], exit_time=str(row.get("exit_time"))[:19],
        pnl=row.get("realized_pnl"), rvol=row.get("entry_volume_ratio"), vol_conf=row.get("entry_volume_confirmed"),
        above_vwap=row.get("entry_above_vwap"), vwap_dist=row.get("entry_vwap_distance_pct"),
        rsi=row.get("entry_rsi"), macd=row.get("entry_macd_state"), capture=row.get("capture_ratio"),
        mfe=row.get("mfe_after_entry"), mae=row.get("mae_after_entry"), missed_pct=row.get("mfe_after_exit_pct"),
        missed_10d=row.get("missed_profit_pct"), missed_grade=row.get("missed_opportunity_grade"),
        entry_timing=row.get("entry_timing_grade"), exit_timing=row.get("exit_timing_grade"),
        flags=", ".join(flags) or "none", viol=row.get("strategy_rule_violations"), summary=row.get("computed_summary"))


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    req = {"execution_label", "primary_mistake", "what_happened", "what_should_have_happened",
           "rule_to_test", "backtest_hypotheses", "normalized_tags", "confidence"}
    return d if req.issubset(d.keys()) else None


def run(limit=10, trade_key=None, apply=False, lane="deepseek-flash"):
    import llm_lane
    conn = _conn(); cur = conn.cursor()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q = """SELECT q.* FROM trade_execution_quality q
           LEFT JOIN trade_execution_grok_reviews r ON r.trade_key=q.trade_key AND r.source=q.source
           WHERE q.path_status='OK' AND r.id IS NULL"""
    if trade_key:
        q = q.replace("AND r.id IS NULL", "") + f" AND q.trade_key='{trade_key}'"
    q += f" ORDER BY q.exit_time DESC LIMIT {int(limit)}"
    cur.execute(q)
    rows = cur.fetchall()
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "lane": lane, "reviewed": [], "parse_failed": 0}
    for row in rows:
        prompt = _build(row)
        snap = {k: (float(v) if hasattr(v, "is_integer") or isinstance(v, (int, float)) else v)
                for k, v in row.items() if k in ("entry_volume_ratio", "capture_ratio", "mfe_after_exit_pct",
                "outcome_grade", "execution_grade", "entry_timing_grade", "exit_timing_grade")}
        try:
            text = llm_lane.generate(prompt, lane=lane, timeout=90)
        except Exception as e:
            report["reviewed"].append({"trade_key": row["trade_key"], "status": "error", "err": str(e)[:80]})
            continue
        parsed = _parse(text)
        status = "ok" if parsed else "parse_failed"
        if not parsed:
            report["parse_failed"] += 1
        if apply:
            cur.execute("""INSERT INTO trade_execution_grok_reviews
                (trade_key,source,model_lane,prompt_version,computed_metrics_snapshot,grok_execution_label,
                 grok_summary,grok_mistakes,grok_what_to_do_next_time,grok_strategy_backtest_hypotheses,
                 normalized_tags,confidence,review_status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (trade_key, source) DO UPDATE SET grok_execution_label=EXCLUDED.grok_execution_label,
                 grok_summary=EXCLUDED.grok_summary, review_status=EXCLUDED.review_status,
                 computed_metrics_snapshot=EXCLUDED.computed_metrics_snapshot, created_at=NOW()""",
                (row["trade_key"], row["source"], lane, PROMPT_VERSION, json.dumps(snap, default=str),
                 (parsed or {}).get("execution_label"), (parsed or {}).get("what_happened"),
                 json.dumps([(parsed or {}).get("primary_mistake"), (parsed or {}).get("secondary_mistake")]),
                 (parsed or {}).get("what_should_have_happened"),
                 json.dumps((parsed or {}).get("backtest_hypotheses", [])),
                 json.dumps((parsed or {}).get("normalized_tags", [])),
                 (parsed or {}).get("confidence"), status))
            conn.commit()
        report["reviewed"].append({"trade_key": row["trade_key"], "symbol": row["symbol"], "status": status,
                                   "label": (parsed or {}).get("execution_label"),
                                   "primary_mistake": (parsed or {}).get("primary_mistake")})
    print(json.dumps(report, indent=2, default=str))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--trade-key")
    ap.add_argument("--lane", default="grok")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    run(a.limit, a.trade_key, a.apply, a.lane)


if __name__ == "__main__":
    main()
