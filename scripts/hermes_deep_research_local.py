#!/usr/bin/env python3
"""hermes_deep_research_local.py — governed Hermes deep research lane.

Advisory + staging only: writes hermes_research_intelligence rows
(research_type='deep_research_local') via the validated build_insert path. The
historical filename and research type remain for lineage; local generation does not.
NEVER touches broker/order/stop/proposal/holdings/trading.

US overnight (22:00–06:00 ET): ChatGPT OAuth (:8646). Otherwise the governed
DeepSeek bridge is used subject to its bulk window.

  python3 scripts/hermes_deep_research_local.py                 # dry-run
  python3 scripts/hermes_deep_research_local.py --apply --max-rows 3
Safety:
  - singleton lockfile; honors live kill-switch data/runtime/HERMES_DISABLED
  - no local generative provider or fallback
  - deterministic fields stamped from code; bounded summary recovery; never fabricates content
"""
import os, sys, json, argparse
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from cio_agent_contract import AGENT_JSON_CONTRACT_VERSION, build_deep_research_json_schema, merge_structured_into_result
LOCK = Path("/tmp/hermes_deep_research_local.lock")
KILL = ROOT / "data" / "runtime" / "HERMES_DISABLED"   # live kill-switch (NOT the retired sidecar path)
AGENT = "deep_research_local"
RTYPE = "deep_research_local"


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


PROMPT = """You are Hermes Deep Research, an advisory research analyst for a paper-trading system.
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
    try:
        if str(model).startswith("chatgpt"):
            from hermes_external_researcher import call_codex_cli
            content = call_codex_cli("gpt-5.4", prompt)
            if not content:
                print(f"  {sym}: FAILED chatgpt oauth empty"); return "failed"
            pack = {"content": content, "model": "chatgpt-oauth", "provider": "chatgpt_oauth"}
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = {"summary": content[:2000]}
            out = merge_structured_into_result(parsed if isinstance(parsed, dict) else {"summary": str(parsed)})
            model = "chatgpt-oauth"
            out["llm_provider"] = "chatgpt_oauth"
            print(f"  {sym}: LLM chatgpt_oauth")
        elif model == "deepseek-v4-flash":
            from hermes_llm_failover import chat_json
            pack = chat_json(prompt, cloud_timeout_s=180)
            content = pack["content"]
            out = merge_structured_into_result(json.loads(pack["content"]))
            model = pack.get("model") or model
            out["llm_provider"] = pack.get("provider")
            if pack.get("failover"):
                print(f"  {sym}: BACKUP {pack.get('model')} ({pack.get('reason')})")
                out["llm_failover_reason"] = pack.get("reason")
            else:
                print(f"  {sym}: LLM {pack.get('provider')} {pack.get('model')}")
        else:
            print(f"  {sym}: FAILED forbidden_model={model}")
            return "failed"
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
    ej["context_recent_trades"] = ctx["recent_trades"]
    ej["lane"] = "governed_deep_research"
    ej["cio_evidence"] = out.pop("evidence", [])
    ej["data_i_doubt"] = out.pop("data_i_doubt", "none")
    ej["agent_contract"] = out.pop("agent_contract", AGENT_JSON_CONTRACT_VERSION)
    # required by validate_payload: non-empty limitations + source_views
    lims = out.pop("limitations", None)
    ej["limitations"] = lims if (isinstance(lims, list) and lims) else \
        ["Advisory synthesis; not independently verified; based on staged data above."]
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
    # Long LLM calls leave the SSL session dead. Fresh write connection;
    # do not close the caller's conn in a way that leaves them holding a dead handle.
    wconn = db()
    try:
        cur = wconn.cursor(); cur.execute(sql, vals); rid = cur.fetchone()[0]; wconn.commit()
    finally:
        try:
            wconn.close()
        except Exception:
            pass
    print(f"  {sym}: COMMITTED id={rid}")
    try:
        _cur = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"
        if _cur.is_dir() and str(_cur) not in sys.path:
            sys.path.insert(0, str(_cur))
        from cio_product_reassessment import notify_from_flash_row
    except Exception:
        try:
            from scripts.lib.cio_product_reassessment import notify_from_flash_row
        except Exception:
            notify_from_flash_row = None
    if notify_from_flash_row:
        try:
            notify_from_flash_row(
                symbol=sym, row_id=rid,
                summary=str((out or {}).get("summary") or "")[:240],
                model=str((out or {}).get("model_used") or ""),
                research_type="deep_research_local",
            )
        except Exception:
            pass
    return "applied"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-rows", type=int, default=3)
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--allow-daytime", action="store_true", help="run outside the overnight window (manual)")
    ap.add_argument(
        "--allow-peak",
        action="store_true",
        help="allow DeepSeek Flash apply during official peak (01-04 and 06-10 UTC)",
    )
    args = ap.parse_args()

    if KILL.exists():
        print("ABORT: kill-switch present (data/runtime/HERMES_DISABLED)"); sys.exit(2)
    if LOCK.exists():
        print("ABORT: another deep-research run holds the lockfile"); sys.exit(1)
    try:
        from hermes_llm_failover import (
            allow_deepseek_peak,
            deepseek_window_label,
            is_deepseek_offpeak,
            primary_provider,
        )
        flash = primary_provider() == "bridge_flash"
    except Exception:
        flash = False
        is_deepseek_offpeak = None  # type: ignore
    hour = datetime.now().hour
    try:
        from lib.overnight_llm_policy import (
            LANE_CHATGPT,
            LANE_NONE,
            is_us_overnight,
            overnight_llm_lane,
        )
    except Exception:
        from scripts.lib.overnight_llm_policy import (  # type: ignore
            LANE_CHATGPT,
            LANE_NONE,
            is_us_overnight,
            overnight_llm_lane,
        )
    if is_us_overnight():
        lane = overnight_llm_lane()
        if lane == LANE_CHATGPT:
            args.model = "chatgpt"
        elif lane == LANE_NONE:
            print("US_OVERNIGHT: skipping judgmental LLM (US_OVERNIGHT_LLM=off)")
            return
    # The DeepSeek peak guard must key on the EFFECTIVE model, not on the
    # configured provider. `flash` is computed above from primary_provider()
    # BEFORE the overnight branch may rewrite args.model to "chatgpt", so during
    # the overnight window it still reads True while the run costs nothing.
    #
    # This timer runs OnCalendar 22:00-05:35 ET. The guard permits 10:00-21:00
    # ET. Those windows never overlap, so every single invocation logged
    #
    #   SKIPPED_DEEPSEEK_PEAK: window=as-needed-only bulk Flash/Pro is
    #   10:00-21:00 America/New_York; outside that is as-needed only.
    #
    # and exited 0. The lane has therefore never run: attempts_24h=0 with
    # Result=success on every timer fire. A cost control was refusing a free
    # lane, and the schedule and the guard were mutually exclusive by
    # construction.
    #
    # The guard is UNCHANGED for real DeepSeek runs — that spend ceiling is the
    # point of it. It simply no longer fires when nothing DeepSeek is invoked.
    uses_deepseek = str(args.model or "").startswith("deepseek")
    if flash and uses_deepseek and is_deepseek_offpeak is not None:
        if (
            args.apply
            and not is_deepseek_offpeak()
            and not (args.allow_peak or args.allow_daytime or allow_deepseek_peak())
        ):
            print(
                f"SKIPPED_DEEPSEEK_PEAK: window={deepseek_window_label()} "
                "bulk Flash/Pro is 10:00-21:00 America/New_York; outside that is as-needed only. "
                "Pass --allow-peak to override."
            )
            return
    elif not (hour >= 22 or hour < 6) and not args.allow_daytime:
        print(f"NOTE: outside overnight window (hour={hour}); pass --allow-daytime to run manually. Proceeding dry-run only.")
        args.apply = False
    LOCK.write_text(str(os.getpid()))
    try:
        if not (str(args.model).startswith("chatgpt") or args.model == "deepseek-v4-flash"):
            print(f"REFUSED_LOCAL_GENERATIVE_MODEL: {args.model}")
            return
        conn = db()
        targets = pick_targets(conn, args.max_rows)
        print(f"Hermes Deep Research — model={args.model} apply={args.apply} targets={targets}")
        counts = {}
        for sym in targets:
            try:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = db()
                r = run_one(conn, sym, args.model, args.apply)
            except Exception as exc:
                print(f"  {sym}: FAILED_RETRYABLE {type(exc).__name__}: {exc}")
                r = "failed_retryable"
                try:
                    conn.close()
                except Exception:
                    pass
                conn = db()
            counts[r] = counts.get(r, 0) + 1
        try:
            conn.close()
        except Exception:
            pass
        print("RESULT:", json.dumps(counts))
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
