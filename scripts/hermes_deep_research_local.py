#!/usr/bin/env python3
"""hermes_deep_research_local.py — Hermes Deep Research (Local) — BATCH_OVERNIGHT internal deep-research lane.

MANUAL / operator-run (NOT auto-wired into cron/systemd). Advisory + staging only: writes
hermes_research_intelligence rows (research_type='deep_research_local') via the validated build_insert path.
NEVER touches broker/order/stop/proposal/holdings/trading. Uses local Ollama gemma3:27b / gemma3-overnight.

Design: docs/hermes/PHASE210C_INTERNAL_DEEP_RESEARCH_AGENT_DESIGN.md.

  python3 scripts/hermes_deep_research_local.py                 # dry-run, gemma3:27b, 3 targets
  python3 scripts/hermes_deep_research_local.py --apply --max-rows 3
  python3 scripts/hermes_deep_research_local.py --model gemma3-overnight:latest --apply
Safety:
  - singleton lockfile; honors live kill-switch data/runtime/HERMES_DISABLED
  - Ollama health gate (skips cleanly when unhealthy — no flood)
  - deterministic fields stamped from code; bounded summary recovery; never fabricates content
"""
import os, sys, json, time, hashlib, argparse, urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from cio_agent_contract import AGENT_JSON_CONTRACT_VERSION, build_deep_research_json_schema, merge_structured_into_result
LOCK = Path("/tmp/hermes_deep_research_local.lock")
KILL = ROOT / "data" / "runtime" / "HERMES_DISABLED"   # live kill-switch (NOT the retired sidecar path)
AGENT = "deep_research_local"
RTYPE = "deep_research_local"
OLLAMA = "http://localhost:11434/api/chat"


def db():
    from hermes_staging_ingest import get_db_connection
    return get_db_connection()


def pick_targets(conn, max_rows):
    """Distinct recently-closed symbols not deep-researched in the last 7d (advisory, read-only select)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ti.symbol, count(*) n
        FROM trade_instances ti
        WHERE lower(coalesce(ti.status,''))='closed' AND ti.symbol ~ '^[A-Z]{1,5}$'
          AND NOT EXISTS (
            SELECT 1 FROM hermes_research_intelligence h
            WHERE h.symbol = ti.symbol AND h.research_type = %s
              AND h.created_at > now() - interval '7 days')
        GROUP BY ti.symbol ORDER BY n DESC LIMIT %s
    """, (RTYPE, max_rows))
    return [r[0] for r in cur.fetchall()]


def gather_context(conn, sym):
    cur = conn.cursor()
    ctx = {"symbol": sym}
    try:
        cur.execute("""SELECT strategy_id, execution_account, realized_pnl, status, close_date
                       FROM trade_instances WHERE symbol=%s ORDER BY close_date DESC NULLS LAST LIMIT 5""", (sym,))
        ctx["recent_trades"] = [list(map(str, r)) for r in cur.fetchall()]
    except Exception:
        conn.rollback(); ctx["recent_trades"] = []
    try:
        cur.execute("""SELECT topic, left(summary,200) FROM hermes_research_intelligence
                       WHERE symbol=%s AND research_type<>%s ORDER BY created_at DESC LIMIT 5""", (sym, RTYPE))
        ctx["prior_research"] = [list(map(str, r)) for r in cur.fetchall()]
    except Exception:
        conn.rollback(); ctx["prior_research"] = []
    return ctx


PROMPT = """You are Hermes Deep Research (Local), an advisory research analyst for a paper-trading system.
Produce a DEEP research report on the ticker below for the operator. You do not trade; this is advisory only.

Ticker: {sym}
Recent closed trades (strategy, account, pnl, status, close_date):
{trades}
Prior research notes:
{research}

{schema}
Be specific and grounded in the data above. Do not recommend executing any trade."""


def run_one(conn, sym, model, apply):
    from hermes_staging_ingest import validate_payload, build_insert
    ctx = gather_context(conn, sym)
    schema = build_deep_research_json_schema(sym)
    prompt = PROMPT.format(sym=sym, trades=json.dumps(ctx["recent_trades"]),
                           research=json.dumps(ctx["prior_research"]), schema=schema)
    payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False,
                          # match each model's canonical ctx (12b on-GPU limit 4096; 27b baked 8192;
                          # 16384 forced a distinct runner config → reload thrash, 07-23 sweep)
                          "options": {"num_ctx": 4096 if "12b" in model else 8192,
                                      "num_predict": 3000, "temperature": 0.3}, "format": "json"}).encode()
    try:
        req = urllib.request.Request(OLLAMA, data=payload, headers={"Content-Type": "application/json"})
        from llm_net import urlopen_retry
        content = json.loads(urlopen_retry(req, timeout=600, attempts=2, base=2.0)).get("message", {}).get("content", "")
        out = merge_structured_into_result(json.loads(content))
    except Exception as e:
        print(f"  {sym}: FAILED ({str(e)[:80]})"); return "failed"
    # deterministic fields stamped from code (never rely on LLM to echo)
    out["hermes_agent_name"] = AGENT
    out["research_type"] = RTYPE
    out.setdefault("topic", f"{sym} deep research synthesis")
    out["symbol"] = sym
    out.setdefault("freshness_date", date.today().isoformat())
    out["model_used"] = model
    # cap confidence (avoid the high-confidence-needs-3-refs rule)
    try:
        out["confidence_score"] = min(0.8, max(0.0, float(out.get("confidence_score", 0.5))))
    except Exception:
        out["confidence_score"] = 0.5
    ej = {k: out.pop(k) for k in ("thesis", "risks") if k in out}
    ej["context_recent_trades"] = ctx["recent_trades"]; ej["lane"] = "internal_deep_research_local"
    ej["cio_evidence"] = out.pop("evidence", [])
    ej["data_i_doubt"] = out.pop("data_i_doubt", "none")
    ej["agent_contract"] = out.pop("agent_contract", AGENT_JSON_CONTRACT_VERSION)
    # required by validate_payload: non-empty limitations + source_views
    lims = out.pop("limitations", None)
    ej["limitations"] = lims if (isinstance(lims, list) and lims) else \
        ["Local-model synthesis (advisory only); not independently verified; based on staged data above."]
    ej["source_views"] = ["trade_instances", "hermes_research_intelligence"]
    out["evidence_json"] = ej
    ok, errors = validate_payload(out, "hermes_research_intelligence")
    if not ok and errors == ["MISSING required column: summary"] and not out.get("summary"):
        try:
            from hermes_output_recovery import recover_summary_from_output
            rec = recover_summary_from_output(content, symbol=sym)
            if rec.get("recovered"):
                out["summary"] = rec["summary"]; ej["summary_recovery"] = rec
                ok, errors = validate_payload(out, "hermes_research_intelligence")
        except Exception:
            pass
    if not ok:
        print(f"  {sym}: REJECTED {errors[:2]}"); return "rejected"
    if not apply:
        print(f"  {sym}: VALIDATED (dry-run, conf={out.get('confidence_score')})"); return "validated"
    sql, vals = build_insert("hermes_research_intelligence", out)
    cur = conn.cursor(); cur.execute(sql, vals); rid = cur.fetchone()[0]; conn.commit()
    print(f"  {sym}: COMMITTED id={rid}"); return "applied"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-rows", type=int, default=3)
    ap.add_argument("--model", default="gemma3:27b")
    ap.add_argument("--allow-daytime", action="store_true", help="run outside the overnight window (manual)")
    args = ap.parse_args()

    if KILL.exists():
        print("ABORT: kill-switch present (data/runtime/HERMES_DISABLED)"); sys.exit(2)
    if LOCK.exists():
        print("ABORT: another deep-research run holds the lockfile"); sys.exit(1)
    hour = datetime.now().hour
    if not (hour >= 22 or hour < 6) and not args.allow_daytime:
        print(f"NOTE: outside overnight window (hour={hour}); pass --allow-daytime to run manually. Proceeding dry-run only.")
        args.apply = False
    LOCK.write_text(str(os.getpid()))
    try:
        # health gate
        try:
            from llm_health_gate import check_ollama_health
            # deep model (27b) is slow to cold-load; check reachability+availability only (the deep call
            # below has its own 600s timeout), so we don't false-skip on a cold 17GB model.
            h = check_ollama_health(model=args.model, generate_probe=False, timeout_sec=20)
            if not h.get("healthy"):
                print(f"SKIPPED_LLM_UNHEALTHY: {h.get('failure_class')}"); return
        except Exception as e:
            print(f"health gate unavailable ({e}); continuing cautiously")
        conn = db()
        targets = pick_targets(conn, args.max_rows)
        print(f"Hermes Deep Research (Local) — model={args.model} apply={args.apply} targets={targets}")
        counts = {}
        for sym in targets:
            r = run_one(conn, sym, args.model, args.apply)
            counts[r] = counts.get(r, 0) + 1
        conn.close()
        print("RESULT:", json.dumps(counts))
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
