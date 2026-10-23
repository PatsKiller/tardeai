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
  python3 scripts/grok_stop_review.py --plan            # dry run: no model call, no write; stops + budget decision
  python3 scripts/grok_stop_review.py                   # calls Grok, writes nothing
  python3 scripts/grok_stop_review.py --apply [--limit N]

Spend gate (2026-10-22): every call passes process_id=grok_stop_review, so it goes through
lib.llm_consumption.gate_and_generate (registration, grok-only lane, mode, dollar cap, consumption log). The registry row
caps it at max_stops_per_run 12 and daily_soft_cap 30 calls/day; the daily count is checked before each call
(DAILY_CALL_CAP). A budget refusal ends the run; any other failure is an error on that stop. There is no fallback model.
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
# Spend gate (2026-10-22, incident SPCX resume): every Grok call names this registered process
# (config/llm_process_registry.json grok_stop_review), so lib.llm_consumption.gate_and_generate checks
# registration, allowed lanes (grok only), mode and caps, and logs the call. resume-operator.sh greps the served
# release for this line before it resumes the cron line.
PROCESS_ID = "grok_stop_review"
# Fallback when the registry row has no max_stops_per_run. Grok is external (AGENTS.md §2A): bound what leaves.
MAX_STOPS_PER_RUN = 12


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
        # One write module per store (SoT Phase 9): SQL lives in lib.writers.hermes_research_writer.
        from lib.writers.hermes_research_writer import write_research_rows
        write_research_rows(cur, [{
            "source": "hermes", "hermes_agent_name": "Grok", "research_type": "stop_curation",
            "symbol": stop.get("symbol"), "topic": "Grok stop R:R review", "summary": line[:480],
            "thesis": (parsed.get("suggested_action") or "")[:480], "thesis_type": "neutral",
            "evidence_json": json.dumps(parsed), "confidence_score": float(parsed.get("confidence") or 0.7),
            "model_used": "grok", "status": "staged", "category_lifecycle": "stop",
        }], producer="Grok")
    except Exception:
        pass


class BudgetRefused(RuntimeError):
    """The spend gate (or this lane's daily call cap) refused the call before anything was sent."""


# Spend-gate refusals that end the run: nothing after them can be allowed today. Matched on the gate's typed codes.
_BUDGET_CODES = ("DAILY_CALL_CAP", "COST_CAP_EXCEEDED", "BUDGET_UNAVAILABLE", "PROCESS_NOT_REGISTERED",
                 "POLICY_NOT_ALLOWED", "manual_mode", "BRIDGE_ROUTE_REFUSED")


def _per_run_cap() -> int:
    """max_stops_per_run from the registry row; MAX_STOPS_PER_RUN when the row or field is missing."""
    try:
        from lib.llm_consumption import _registry_process
        row = _registry_process(PROCESS_ID) or {}
        return max(1, int(row.get("max_stops_per_run") or MAX_STOPS_PER_RUN))
    except Exception:  # noqa: BLE001 — a missing registry never widens the cap
        return MAX_STOPS_PER_RUN


def budget_state() -> dict:
    """Read-only budget view for --plan and the per-call pre-check. Calls no model."""
    from lib import llm_consumption as lc
    cfg = lc.get_process_config(PROCESS_ID)
    used = lc.calls_today(PROCESS_ID)
    cap = cfg.get("daily_soft_cap")
    return {"process_id": PROCESS_ID, "registered": bool(cfg.get("registered")),
            "allowed_lanes": list(cfg.get("allowed_lanes") or []), "mode": cfg.get("mode"),
            "calls_today": used, "daily_call_cap": cap, "per_run_cap": _per_run_cap(),
            "daily_cost_cap_usd": cfg.get("daily_cost_cap_usd")}


def _gated_generate(prompt: str, *, lane: str, symbol: str | None) -> str:
    """One Grok call through lib.llm_consumption.gate_and_generate (via llm_lane.generate with a process_id).

    Refuses with BudgetRefused before sending anything when today's logged calls for this process have reached the
    registry daily_soft_cap (the gate itself checks registration, allowed lanes, mode and the dollar cap). There is no
    fallback lane: any failure propagates to the caller, which records it as an error on that stop.
    """
    from lib import llm_consumption as lc
    if lc.over_daily_cap(PROCESS_ID):
        raise BudgetRefused(f"DAILY_CALL_CAP: {PROCESS_ID} reached its daily_soft_cap; nothing sent")
    import llm_lane
    try:
        return llm_lane.generate(prompt, lane=lane, timeout=90, process_id=PROCESS_ID,
                                 task_summary=f"grok stop review {symbol or '?'}")
    except Exception as e:  # noqa: BLE001 — classified, never swallowed
        msg = str(e)
        if type(e).__name__ == "ManualRequired" or any(code in msg for code in _BUDGET_CODES):
            raise BudgetRefused(msg[:200]) from e
        raise


def _held_stops() -> list[dict]:
    import stop_lifecycle_monitor as slm
    stops = slm.scan(persist=False)["stops"]
    # curate stops that are actually held (skip orphans — those are a health issue, not an R:R question)
    return [s for s in stops if s.get("held_qty")]


def plan(limit: int | None = None) -> dict:
    """The script's own dry run for the resume packet: which stops a run would send, and the budget decision.

    Calls no model and writes nothing (it reads the stop lifecycle scan with persist=False and the consumption log).
    """
    cap = _per_run_cap()
    n = min(int(limit), cap) if limit else cap
    stops = _held_stops()
    b = budget_state()
    remaining = None
    if b.get("daily_call_cap") is not None:
        remaining = max(0, int(b["daily_call_cap"]) - int(b["calls_today"] or 0))
    would = stops[:n] if remaining is None else stops[:min(n, remaining)]
    return {"mode": "PLAN", "process_id": PROCESS_ID, "budget": b, "held_stops": len(stops),
            "would_review": [s.get("symbol") for s in would], "would_send_calls": len(would),
            "refused": None if b["registered"] else "PROCESS_NOT_REGISTERED"}


def run(apply: bool = False, lane: str = "grok", limit: int | None = None) -> dict:
    cap = _per_run_cap()
    n = min(int(limit), cap) if limit else cap
    stops = _held_stops()
    skipped_over_cap = max(0, len(stops) - n)
    stops = stops[:n]
    conn = _conn(); cur = conn.cursor()
    _ensure_table(cur); conn.commit()
    out = {"mode": "APPLIED" if apply else "DRY-RUN", "lane": lane, "process_id": PROCESS_ID,
           "per_run_cap": cap, "skipped_over_per_run_cap": skipped_over_cap,
           "reviewed": [], "errors": 0, "refused": None}
    for s in stops:
        thesis = _latest_thesis(cur, s.get("symbol"))
        try:
            text = _gated_generate(_build_prompt(s, thesis), lane=lane, symbol=s.get("symbol"))
        except BudgetRefused as e:
            # The gate said no: stop the run. Nothing is sent on any other lane.
            out["refused"] = str(e)[:200]
            print(f"grok_stop_review: refused by spend gate: {str(e)[:200]}", file=sys.stderr)
            break
        except Exception as e:  # noqa: BLE001 — logged as an error on this stop; no fallback model
            out["errors"] += 1
            out["reviewed"].append({"symbol": s.get("symbol"), "status": f"error: {str(e)[:60]}"})
            print(f"grok_stop_review: {s.get('symbol')}: grok call failed, no fallback: {str(e)[:120]}",
                  file=sys.stderr)
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
    ap.add_argument("--lane", default="grok", help="grok only: the registry row allows no other lane")
    ap.add_argument("--limit", type=int, default=None, help=f"clamped to max_stops_per_run ({MAX_STOPS_PER_RUN})")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--plan", action="store_true",
                    help="dry run with no model call: list the stops a run would send and the budget decision")
    a = ap.parse_args()
    if a.plan:
        print(json.dumps(plan(limit=a.limit), indent=2, default=str))
        return
    print(json.dumps(run(apply=a.apply, lane=a.lane, limit=a.limit), indent=2, default=str))


if __name__ == "__main__":
    main()
