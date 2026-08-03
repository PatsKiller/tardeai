#!/usr/bin/env python3
"""options_lifecycle_oversight.py — v1.1 Phase 7: OPTIONAL free-lane oversight.

Deterministic policy stays canonical. Free LLM seats (llm_lane chatgpt/grok —
the same infrastructure as Defense oversight) review ONLY configured exception
cases and return a strongest objection. Advisory, period: nothing here can
change a recommendation, urgency, price, TIF, ticket, hash, DATA_BLOCKED state,
2FA, or outcome P&L — the module has no write path into any of those tables.

Paid lanes are DISABLED by default (policy oversight.paid_enabled=false); the
gate conditions are encoded but inert until the operator flips the config.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from options_lifecycle_engine import policy

VERDICTS = ("CONCUR", "QUALIFY", "OBJECT", "UNAVAILABLE")
PROMPT_VERSION = "olc-oversight-1.0"


def ensure_oversight_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS options_oversight_runs (
        run_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        snapshot_id int,
        decision_id int,
        policy_version text,
        ticket_hash text,
        trigger_reason text NOT NULL,
        lane text NOT NULL,
        model text,
        prompt_version text NOT NULL,
        verdict text,
        strongest_objection text,
        missing_data text,
        alternative text,
        raw text,
        tokens_est int,
        cost_est numeric DEFAULT 0,
        created_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_oversight_run_key
        ON options_oversight_runs (strategy_position_id, snapshot_id, lane, trigger_reason)""")
    conn.commit()


def _ocfg() -> dict:
    return policy().get("oversight", {
        "free_enabled": True, "paid_enabled": False,
        "close_vs_roll_diff_dollars": 500, "roll_material_debit_dollars": 250,
        "notional_threshold_dollars": 25000, "flip_window_minutes": 30})


def triggers(cur, s: dict, eco: dict, d: dict, ticket: dict | None = None,
             operator_requested: bool = False) -> list[str]:
    """The configured exception cases — everything else runs deterministic-only."""
    c = _ocfg()
    out = []
    if operator_requested:
        out.append("operator_requested")
    if d["recommendation"] == "DATA_BLOCKED" and operator_requested:
        out.append("data_blocked_override_request")
    subs = {x.get("recommendation") for x in (d.get("subordinate") or [])}
    if d["recommendation"] in ("ASSIGNMENT_CRITICAL", "DEFEND") and \
            subs & {"HARVEST_FULL", "HARVEST_PARTIAL"}:
        out.append("assignment_vs_harvest_conflict")
    if ticket and ticket.get("kind") == "roll":
        alt = (ticket.get("alternate_close_only") or {}).get("net")
        if alt is not None and abs(ticket["net_debit_credit"] - alt) >= c["close_vs_roll_diff_dollars"]:
            out.append("close_vs_roll_material_difference")
        if ticket["net_debit_credit"] < -c["roll_material_debit_dollars"]:
            out.append("roll_adds_material_debit")
    cur.execute("""SELECT count(*) FROM options_lifecycle_decisions
                   WHERE strategy_position_id=%s
                     AND created_at > now() - make_interval(mins => %s)""",
                (s["strategy_position_id"], c["flip_window_minutes"]))
    if (cur.fetchone() or [0])[0] >= 2:
        out.append("recommendation_flapping")
    if s["strategy_type"] == "unknown_multi_leg":
        out.append("unknown_structure")
    notional = (eco.get("underlying_price") or 0) * sum(
        float(l["contracts"]) * int(l["multiplier"]) for l in s["legs"] if l["status"] == "open")
    if notional >= c["notional_threshold_dollars"]:
        out.append("notional_above_threshold")
    if s["strategy_type"] == "protective_put" and d["recommendation"] in ("CLOSE", "HARVEST_FULL"):
        out.append("protective_hedge_closure")
    return out


def _brief(s: dict, eco: dict, d: dict, trigger: str) -> str:
    legs = "; ".join(f"{l['side']} {float(l['contracts']):g}× {l['occ_symbol'].strip()}"
                     for l in s["legs"] if l["status"] == "open")
    return (f"OPTIONS LIFECYCLE EXCEPTION REVIEW (trigger: {trigger})\n"
            f"Position #{s['strategy_position_id']} {s['account_key']}: {s['underlying']} "
            f"{s['strategy_type'].replace('_', ' ')} — {legs}\n"
            f"Economics: P&L {eco.get('unrealized_pnl')} · {eco.get('pct_max_profit_captured')}% of max "
            f"captured · DTE {eco.get('dte_nearest')} · short Δ {eco.get('short_delta')} · "
            f"giveback {eco.get('giveback')}\n"
            f"DETERMINISTIC PRIMARY: {d['recommendation']} ({d['urgency']}) — {d['rationale']}\n"
            f"Subordinate: {json.dumps(d.get('subordinate') or [])[:400]}\n\n"
            "You are an independent reviewer. The deterministic decision is CANONICAL — you may not "
            "change it; you may only concur, qualify, or object with your strongest objection.\n"
            "Reply STRICT JSON: {\"verdict\": \"CONCUR|QUALIFY|OBJECT\", "
            "\"strongest_objection\": \"...\", \"missing_data\": \"...\", \"alternative\": \"...\"}")


def run_free_review(cur, conn, s: dict, eco: dict, d: dict, trigger: str,
                    snapshot_id=None, decision_id=None, ticket_hash=None) -> list[dict]:
    """Both free seats, keyed + cached per (position, snapshot, lane, trigger)."""
    ensure_oversight_tables(cur, conn)
    if not _ocfg().get("free_enabled", True):
        return []
    from llm_lane import available, generate
    results = []
    prompt = _brief(s, eco, d, trigger)
    for lane in ("deepseek-flash", "chatgpt", "grok"):
        cur.execute("""SELECT run_id, verdict FROM options_oversight_runs
                       WHERE strategy_position_id=%s AND snapshot_id IS NOT DISTINCT FROM %s
                         AND lane=%s AND trigger_reason=%s""",
                    (s["strategy_position_id"], snapshot_id, lane, trigger))
        if cur.fetchone():
            continue  # cached — keyed runs never re-bill/re-ask
        verdict, obj, missing, alt, raw = "UNAVAILABLE", None, None, None, None
        if available(lane):
            try:
                t0 = time.time()
                raw = generate(prompt, lane=lane, timeout=120)
                raw = raw if isinstance(raw, str) else json.dumps(raw)
                p = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
                if p.get("verdict") in VERDICTS:
                    verdict = p["verdict"]
                    obj, missing, alt = p.get("strongest_objection"), p.get("missing_data"), p.get("alternative")
            except Exception as e:
                raw = f"__error__ {str(e)[:200]}"
        cur.execute("""INSERT INTO options_oversight_runs
            (strategy_position_id, snapshot_id, decision_id, policy_version, ticket_hash,
             trigger_reason, lane, model, prompt_version, verdict, strongest_objection,
             missing_data, alternative, raw, tokens_est, cost_est)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)
            ON CONFLICT DO NOTHING""",
            (s["strategy_position_id"], snapshot_id, decision_id,
             policy()["policy_version"], ticket_hash, trigger, lane, f"free:{lane}",
             PROMPT_VERSION, verdict, obj, missing, alt, (raw or "")[:6000],
             len(prompt) // 4))
        conn.commit()
        results.append({"lane": lane, "verdict": verdict, "strongest_objection": obj})
    return results


def strongest_objection(cur, spid: int) -> dict | None:
    """The card-face line: latest OBJECT/QUALIFY across lanes for this position."""
    cur.execute("""SELECT lane, verdict, strongest_objection, trigger_reason, created_at
                   FROM options_oversight_runs
                   WHERE strategy_position_id=%s AND verdict IN ('OBJECT','QUALIFY')
                   ORDER BY run_id DESC LIMIT 1""", (spid,))
    r = cur.fetchone()
    if not r:
        return None
    return {"lane": r[0], "verdict": r[1], "objection": r[2], "trigger": r[3],
            "at": str(r[4])}


def paid_gate(cur, s: dict, free_results: list[dict], operator_requested: bool) -> dict:
    """Paid lane conditions — encoded but DISABLED by default. Returns the gate
    verdict; running paid is a separate explicit call that checks this."""
    c = _ocfg()
    if not c.get("paid_enabled", False):
        return {"allowed": False, "reason": "paid oversight DISABLED by default (policy)"}
    verdicts = {r["lane"]: r["verdict"] for r in free_results}
    disagree = len({v for v in verdicts.values() if v in ("CONCUR", "OBJECT")}) > 1
    if not (disagree or operator_requested):
        return {"allowed": False, "reason": "no free-lane disagreement and no operator request"}
    return {"allowed": True, "reason": "gated conditions met — still requires explicit invocation"}


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    ensure_oversight_tables(cur, conn)
    print("oversight tables ensured; free_enabled:", _ocfg().get("free_enabled"),
          "| paid_enabled:", _ocfg().get("paid_enabled", False))
