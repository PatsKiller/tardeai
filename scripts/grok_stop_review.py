#!/usr/bin/env python3
"""Grok Stop Review (Stage 2c) — an EXTERNAL-LLM curation layer for protective stops, on top of the
technical rules (swing-low/ATR) and the Hermes advisory.

Operator: "have grok review hermes and [be] well curated for stops also besides technicals." For each live
stop (Schwab + Alpaca, from the lifecycle scan) Grok reviews the WHOLE picture — position, P&L, the placed
stop vs the advised level, proximity, lifecycle health, and the latest Hermes thesis — and returns a
curated R:R judgement: is the stop well-placed? too tight / too loose? should it trail? what to do. The
verdict is persisted to stop_grok_reviews and written into the Hermes research stream
(research_type='stop_curation') so it shows on the Open Trades card's 'reviewed by GROK' + the Hermes hub.

ADVISORY ONLY — never places/moves/cancels an order. Run on a modest cadence (Grok is external/rate-limited):
  python3 scripts/grok_stop_review.py --apply [--lane grok] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from cio_agent_contract import build_stop_review_json_schema, extract_json_object, merge_structured_into_result

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PROMPT_VERSION = "stop_grok_v1"


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _ensure_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS stop_grok_reviews (
                     id SERIAL PRIMARY KEY, account TEXT, symbol TEXT, order_id TEXT, lane TEXT,
                     grade TEXT, rr_assessment TEXT, recommendation TEXT, suggested_action TEXT,
                     should_trail BOOLEAN, confidence REAL, raw JSONB,
                     reviewed_at TIMESTAMPTZ DEFAULT NOW())""")


def _latest_thesis(cur, symbol: str) -> str | None:
    try:
        cur.execute("""SELECT summary FROM hermes_research_intelligence
                       WHERE symbol=%s AND research_type<>'stop_curation' AND research_type<>'stop_health'
                       ORDER BY created_at DESC LIMIT 1""", (symbol,))
        r = cur.fetchone()
        return (r[0] if r else None)
    except Exception:
        return None


def _build_prompt(stop: dict, thesis: str | None) -> str:
    sp = stop.get("stop_price")
    lvl = f"${sp}" if sp is not None else f"trailing {stop.get('trail_offset')}{'%' if stop.get('trail_link')=='PERCENT' else ''}"
    return (
        "You are a risk manager curating a PROTECTIVE STOP on a real holding. Judge the stop on RISK:REWARD "
        "and protection quality — go BEYOND the technical rule that set it. Be concise and decisive.\n\n"
        f"Symbol: {stop.get('symbol')}  Account: {stop.get('account')} ({stop.get('broker')})\n"
        f"Shares held: {stop.get('held_qty')}  Current price: ${stop.get('current_price')}\n"
        f"Live stop: {stop.get('order_type')} at {lvl}  (qty {stop.get('qty')})\n"
        f"Distance to stop: {stop.get('proximity_pct')}%  Lifecycle: {stop.get('lifecycle')}  Coverage: {stop.get('coverage')}\n"
        f"Latest Hermes thesis: {thesis or 'n/a'}\n\n"
        + build_stop_review_json_schema()
    )


def _parse(text: str) -> dict | None:
    parsed = extract_json_object(text)
    return merge_structured_into_result(parsed) if parsed else None


def _hermes_finding(cur, stop: dict, parsed: dict) -> None:
    """Surface Grok's curated take in the Hermes stream → 'reviewed by GROK' on the card + Hermes hub."""
    try:
        line = f"Grok stop curation [{parsed.get('grade')}]: {parsed.get('recommendation')} — {parsed.get('rr_assessment')}"
        cur.execute("""INSERT INTO hermes_research_intelligence
            (source, hermes_agent_name, research_type, symbol, topic, summary, thesis, thesis_type,
             evidence_json, confidence_score, model_used, status, category_lifecycle, freshness_date, created_at)
            VALUES ('hermes','Grok','stop_curation',%s,'Grok stop R:R review',%s,%s,'neutral',%s::jsonb,%s,
                    'grok','staged','stop', CURRENT_DATE, NOW())""",
            (stop.get("symbol"), line[:480], (parsed.get("suggested_action") or "")[:480],
             json.dumps(parsed), float(parsed.get("confidence") or 0.7)))
    except Exception:
        pass


def run(apply: bool = False, lane: str = "grok", limit: int | None = None) -> dict:
    import llm_lane
    import stop_lifecycle_monitor as slm
    stops = slm.scan(persist=False)["stops"]
    # curate stops that are actually held (skip orphans — those are a health issue, not an R:R question)
    stops = [s for s in stops if s.get("held_qty")]
    if limit:
        stops = stops[:int(limit)]
    conn = _conn(); cur = conn.cursor()
    _ensure_table(cur); conn.commit()
    out = {"mode": "APPLIED" if apply else "DRY-RUN", "lane": lane, "reviewed": [], "errors": 0}
    for s in stops:
        thesis = _latest_thesis(cur, s.get("symbol"))
        try:
            text = llm_lane.generate(_build_prompt(s, thesis), lane=lane, timeout=90)
        except Exception as e:
            out["errors"] += 1
            out["reviewed"].append({"symbol": s.get("symbol"), "status": f"error: {str(e)[:60]}"})
            continue
        parsed = _parse(text)
        if not parsed:
            out["reviewed"].append({"symbol": s.get("symbol"), "status": "parse_failed"})
            continue
        if apply:
            cur.execute("""INSERT INTO stop_grok_reviews
                (account,symbol,order_id,lane,grade,rr_assessment,recommendation,suggested_action,
                 should_trail,confidence,raw)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (s.get("account"), s.get("symbol"), s.get("order_id"), lane, parsed.get("grade"),
                 parsed.get("rr_assessment"), parsed.get("recommendation"), parsed.get("suggested_action"),
                 bool(parsed.get("should_trail")), float(parsed.get("confidence") or 0.7), json.dumps(parsed)))
            _hermes_finding(cur, s, parsed)
            conn.commit()
        out["reviewed"].append({"symbol": s.get("symbol"), "account": s.get("account"),
                                "grade": parsed.get("grade"), "rec": parsed.get("recommendation"),
                                "should_trail": parsed.get("should_trail")})
    return out


def main():
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="grok")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(apply=a.apply, lane=a.lane, limit=a.limit), indent=2, default=str))


if __name__ == "__main__":
    main()
