#!/usr/bin/env python3
"""hermes_external_feedback_loop.py — score the usefulness of external-researcher recommendations and feed
the signal back into the learning system (Phase 213 gap #2). ADVISORY-ONLY.

For each scored-eligible hermes_external_research row (status='sent', usefulness_score IS NULL), rate the
recommendation's usefulness 0.0–1.0 via the governed cloud bridge (intrinsic actionability/specificity/
grounding), enhanced by the symbol's realized outcome AFTER the research date when available. Writes
usefulness_score + a feedback note into evidence_json. NEVER touches broker/order/stop/proposal/scoring —
the per-lane usefulness aggregate is advisory input to lane routing only.

  python3 scripts/hermes_external_feedback_loop.py            # dry-run
  python3 scripts/hermes_external_feedback_loop.py --apply

Governed bridge, n8n path (2026-10-15, n8n llm lane batch 2): the cron line already rates through the bridge
(hermes_llm_failover.chat_json, caller advisory_desk / task usefulness_score -> process hermes_usefulness_score, a
DeepSeek-only routing row the cron line keeps). With TRADEAI_LLM_VIA_BRIDGE=1 (bound by the n8n run executor from the
allowlist ``llm_route`` of lane hermes-usefulness-backfill) each rating is ONE request through lib.llm_bridge_route as
its own process ``hermes_usefulness_score_n8n`` (routing row n8n_oauth_first: grok -> chatgpt -> DeepSeek, operator
D10), so the n8n route and caps never move the cron line's row. A refusal is terminal for the run (BRIDGE_ROUTE_REFUSED,
rows stay unscored and eligible). --dry-run makes no model call.
"""
import os, sys, json, argparse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KILL = ROOT / "data" / "runtime" / "HERMES_DISABLED"
sys.path.insert(0, str(ROOT / "scripts"))
_ENV_KEYS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
#: The n8n path's own process (advisory_desk / hermes_usefulness_score_n8n); the cron line keeps hermes_usefulness_score.
N8N_PROCESS_ID = "hermes_usefulness_score_n8n"
#: The flag the n8n run executor binds from the allowlist llm_route; read directly.
VIA_BRIDGE_ENV = "TRADEAI_LLM_VIA_BRIDGE"


def _via_bridge():
    return os.environ.get(VIA_BRIDGE_ENV, "off").strip().lower() in {"1", "on", "bridge"}


def _load_env():
    from lib.env_bootstrap import load_env
    return load_env(names=_ENV_KEYS)


def _db():
    import psycopg2
    return psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))


def _outcome(cur, symbol, after):
    """Realized pnl on the symbol for trades closed AFTER the research date (forward-looking outcome)."""
    if not symbol:
        return None
    try:
        cur.execute("""SELECT count(*), coalesce(sum(realized_pnl),0) FROM trade_instances
                       WHERE symbol=%s AND lower(coalesce(status,''))='closed'
                         AND close_date > %s""", (symbol, after))
        n, pnl = cur.fetchone()
        return {"closed_trades_after": int(n), "realized_pnl_after": float(pnl)} if n else None
    except Exception:
        cur.connection.rollback(); return None


def _rate(question, recommendation, dissent, outcome):
    """Governed cloud usefulness rating; fail closed when the provider is unavailable."""
    prompt = (f"Rate how USEFUL this external research recommendation is for a paper-trading research system. "
              f"Judge actionability, specificity, and grounding. This is advisory; do not suggest trading.\n"
              f"Question: {question}\nRecommendation: {recommendation}\nDissent: {dissent}\n"
              f"Realized outcome since (if any): {json.dumps(outcome)}\n"
              f'Return ONLY JSON: {{"usefulness": 0.0-1.0, "rationale": "one sentence"}}')
    if _via_bridge():
        from lib.llm_bridge_route import require_text_via_bridge
        from hermes_llm_failover import _extract_json_text

        content = _extract_json_text(require_text_via_bridge(N8N_PROCESS_ID, prompt, timeout_s=120))
        pack = {"content": content, "provider": "governed_bridge", "model": N8N_PROCESS_ID}
    else:
        from hermes_llm_failover import chat_json
        pack = chat_json(prompt, cloud_timeout_s=120, task_type="usefulness_score")
    data = json.loads(pack["content"])
    usefulness = max(0.0, min(1.0, float(data["usefulness"])))
    return usefulness, str(data.get("rationale", ""))[:240], pack


#: A governance refusal is not a provider fault, and retrying it cannot help.
#: The bridge reports these as non-retryable; match on both the machine code and
#: the HTTP status, because a client that only sees urllib's HTTPError string
#: never gets to read the response body carrying the code.
TERMINAL_MARKERS = (
    "COST_CAP_EXCEEDED",
    "COST_CONFIGURATION_INVALID",
    "POLICY_NOT_ALLOWED",
    "PROCESS_NOT_REGISTERED",
    "HTTP Error 429",
    "HTTP Error 403",
    # the n8n path (lib.llm_bridge_route): refused or unreachable -- stop, never another provider
    "BRIDGE_ROUTE_REFUSED",
)

#: Stop after this many consecutive provider failures. Defence in depth: on
#: 2026-09-06 the bridge reported a hard request-cap breach as HTTP 500, which
#: reads as transient, and this loop consumed all 46,106 remaining rows marking
#: them FAILED_PROVIDER in a few minutes. A queue that fails this many times in
#: a row is not going to recover within the same run.
MAX_CONSECUTIVE_FAILURES = 10


def _is_terminal(message: str) -> bool:
    """True when retrying is pointless because governance refused the request."""
    upper = message.upper()
    return any(m.upper() in upper for m in TERMINAL_MARKERS)


def main(argv=None):
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--dry-run", action="store_true", help="offline plan; takes precedence over --apply")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--max-rows", type=int, default=25)
    args = ap.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN hermes-usefulness-backfill: would score up to {args.max_rows} research rows through the existing governed process; no env load, DB, model or writes")
        return 0
    _load_env()
    if not args.apply:
        # Preserve the historical implicit model preview. Explicit --dry-run is offline.
        _run_feedback(args)
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        result = _run_feedback(args)
    except BaseException as exc:
        rc = int(exc.code) if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 1
        write_lane_receipt("hermes-usefulness-backfill", ok=False, exit_code=rc,
                           started_at=started, script="hermes_external_feedback_loop.py", error=type(exc).__name__)
        raise
    rc = 1 if result["failed"] or result["aborted"] else 0
    write_lane_receipt("hermes-usefulness-backfill", ok=rc == 0, exit_code=rc,
                       started_at=started, script="hermes_external_feedback_loop.py", summary=result)
    return rc


def _run_feedback(args):
    if KILL.exists():
        print("ABORT: kill-switch present"); sys.exit(2)
    c = _db(); cur = c.cursor()
    cur.execute("""SELECT id, lane, symbol, question, recommendation, dissent, created_at
                   FROM hermes_external_research
                   WHERE status='sent' AND usefulness_score IS NULL AND recommendation IS NOT NULL
                   ORDER BY id ASC LIMIT %s""", (args.max_rows,))
    rows = cur.fetchall()
    print(f"Hermes External Feedback Loop — eligible={len(rows)} apply={args.apply} model={args.model}")
    scored = 0
    failed = 0
    consecutive_failures = 0
    aborted = None
    for rid, lane, symbol, question, rec, dissent, created in rows:
        outcome = _outcome(cur, symbol, created)
        try:
            u, rationale, pack = _rate(question, rec, dissent, outcome)
        except Exception as exc:
            failed += 1
            message = str(exc)
            print(f"  id={rid} FAILED_PROVIDER {type(exc).__name__}: {message[:100]}")
            # Stop, rather than spending the rest of the queue on a refusal that
            # will not change. The rows are left unscored and stay eligible.
            if _is_terminal(message):
                aborted = f"governance refused the request: {message[:120]}"
                break
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                aborted = (f"{consecutive_failures} consecutive provider failures; "
                           f"last: {message[:120]}")
                break
            continue
        consecutive_failures = 0
        fb = {"usefulness_feedback": {"scored_by": f"{pack['provider']}:{pack['model']}", "scored_at": datetime.now().isoformat(),
              "outcome": outcome, "rationale": rationale}}
        print(f"  id={rid} lane={lane} sym={symbol or '-'} usefulness={u:.2f} outcome={outcome} :: {rationale[:80]}")
        if args.apply:
            note = (f"usefulness={u:.2f} ({rationale}); outcome={json.dumps(outcome)}; "
                    f"scored_by={pack['provider']}:{pack['model']}")
            cur.execute("""UPDATE hermes_external_research
                           SET usefulness_score=%s, learning_candidate=%s WHERE id=%s""",
                        (u, note[:500], rid))
            c.commit()   # commit per-row so one bad row can't drop the batch
            scored += 1
    if args.apply:
        c.commit()
    # per-lane learning signal (advisory)
    cur.execute("""SELECT lane, count(*), round(avg(usefulness_score)::numeric,3)
                   FROM hermes_external_research WHERE usefulness_score IS NOT NULL GROUP BY lane ORDER BY 3 DESC""")
    agg = [{"lane": r[0], "scored": int(r[1]), "avg_usefulness": float(r[2])} for r in cur.fetchall()]
    if aborted:
        print(f"ABORT: {aborted}")
        print(f"  stopped after {scored} scored; {len(rows) - scored} eligible rows left unscored "
              f"(still eligible — they were never written)")
    c.close()
    print("RESULT:", json.dumps({"scored_now": scored, "per_lane_usefulness": agg}))
    return {"selected": len(rows), "scored": scored, "failed": failed, "aborted": bool(aborted)}


if __name__ == "__main__":
    sys.exit(main())
