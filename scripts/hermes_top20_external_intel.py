#!/usr/bin/env python3
"""hermes_top20_external_intel.py — curate the top-N Hermes-ranked watchlist names into a well-formatted
context and send each to the FREE external LLM lanes (ChatGPT via openai-codex OAuth + Grok via xAI) for
enhanced intelligence. Reuses hermes_external_researcher.py (auth, capability cache, storage to
hermes_external_research). ADVISORY — never trades.

Skips a (symbol, lane) pair already researched in the last FRESH_HOURS. Cadence via cron.

  python3 scripts/hermes_top20_external_intel.py [--top 20] [--lanes chatgpt,grok] [--apply] [--dry-run]

--dry-run (wins over --apply) runs the same candidate SELECTs and budget-guard decisions on a READ
ONLY session and returns each decision WITHOUT appending research-call accounting events, writing the
skip ledger or starting hermes_external_researcher (the no-flag form still appends DRY_RUN accounting
events, as before). A real --apply run writes data/runtime/hermes_top20_external_intel_last.json
(LaneRunReceipt@v1; ok_at only on success) under the persistent state root and exits 1 when the run
failed or every researcher call it started failed.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# G2: scripts-only + lib — never also put scripts/lib or root on path
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from lib.cio_agent_contract import contract_header
from lib.research_call_accounting import append_event as append_call_event, call_id_for, new_run_id
FRESH_HOURS = 12
RECEIPT_NAME = "hermes_top20_external_intel"


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _named(conn, symbols):
    """Explicit symbol list (operator runs, e.g. 'all buy/strong_buy watchlist items' 2026-06-12)."""
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, hermes_rank, hermes_composite_score,
                     hermes_score_components, rsi, trend
                   FROM watchlist_items WHERE symbol = ANY(%s)
                   ORDER BY symbol, hermes_composite_score DESC""", (sorted({s.upper() for s in symbols}),))
    return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]


def _top(conn, n):
    """Top-N by Hermes rank PLUS every operator-directive symbol regardless of rank (2026-06-12:
    CIFR #326 / DLR #1172 / AXTI #1627 never made the top-20 cut — operator standing instructions
    outrank scores)."""
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, hermes_rank, hermes_composite_score,
                     hermes_score_components, rsi, trend
                   FROM watchlist_items
                   WHERE (hermes_rank IS NOT NULL AND hermes_rank <= %s)
                      OR (in_directive_watch=true AND status<>'removed')
                   ORDER BY symbol, hermes_composite_score DESC""", (n,))
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    rows.sort(key=lambda r: (r["hermes_rank"] is None, r["hermes_rank"] or 0))
    return rows


def _question(r):
    c = r.get("hermes_score_components") or {}
    facs = "; ".join(f"{k}={v.get('score')}({v.get('detail')})" for k, v in c.items() if not k.startswith("_"))
    return (
        f"You are an elite equity analyst. {r['symbol']} ranks #{r['hermes_rank']} on our watchlist "
        f"(internal composite {r['hermes_composite_score']}/100, confidence {c.get('_confidence')}). "
        f"RSI {r.get('rsi')}, trend {r.get('trend')}. Factor reads — {facs}. "
        "Give ENHANCED intelligence, concise and specific (no boilerplate): "
        "(1) your conviction high/medium/low + a one-line thesis; "
        "(2) the 2-3 most important catalysts or risks we may be missing; "
        "(3) is the current trade setup valid — better entry / invalidation level; "
        "(4) any competitive or sector dynamic that changes the picture. "
        "End with a single line: VERDICT: <bullish|neutral|bearish> | CONVICTION: <high|med|low>. "
        f"{contract_header()} External researcher will parse tagged evidence + data_i_doubt from your analysis."
    )


def _recent(conn, symbol, lane):
    cur = conn.cursor()
    cur.execute("""SELECT 1 FROM hermes_external_research WHERE symbol=%s AND lane=%s
                   AND created_at > now() - interval '%s hours'
                   AND status IN ('sent','ok','complete','success') LIMIT 1""",
                (symbol, lane, FRESH_HOURS))
    return cur.fetchone() is not None


# Symbols actually held / proposed / under an active directive. Cached once per run so the budget
# guard can tier each candidate without a per-symbol round-trip.
def _trigger_context(conn):
    cur = conn.cursor()
    ctx = {"holdings": set(), "proposals": set(), "directive": set()}
    # held-symbol set from canonical holdings.json — the latest_holdings VIEW was retired
    # 2026-07-03 (it read the dead `holdings` table, frozen at 2026-04-19, so budget tiering
    # treated current positions as not-held for months).
    try:
        _hp = _holdings_path()
        d = json.loads(_hp.read_text()) if _hp.exists() else {}
        items = d if isinstance(d, list) else (d.get("holdings") or d.get("positions") or [])
        for it in items:
            if isinstance(it, dict) and not it.get("is_cash"):
                s = (it.get("symbol") or it.get("ticker") or "").upper().strip()
                if s and s not in ("CASH", "USD"):
                    ctx["holdings"].add(s)
    except Exception:
        pass
    for key, sql in [
        ("proposals", "SELECT DISTINCT symbol FROM paper_trade_proposals WHERE status IN ('pending','approved','open','active','proposed')"),
        ("directive", "SELECT DISTINCT symbol FROM watch_directive_hits"),
    ]:
        try:
            cur.execute(sql)
            for r in cur.fetchall():
                if r[0]:
                    ctx[key].add(str(r[0]).upper().strip())
        except Exception:
            pass
    return ctx


def _holdings_path() -> Path:
    """Served holdings.json: the persistent-state portfolio dir (AGENTS.md §9.4), not the code checkout."""
    try:
        from lib.persistent_state_root import resolve_durable_dir

        return resolve_durable_dir("data/portfolios/state", PROJECT_ROOT) / "holdings.json"
    except Exception:  # noqa: BLE001 -- helper unavailable: the checkout path (release symlinks it)
        return PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"


def _trigger_for(r, ctx):
    """Map a candidate row to (trigger_source, has_active_trigger) for the budget guard.
    Strongest trigger wins: held > proposed > directive > high-rank > broad."""
    sym = (r.get("symbol") or "").upper().strip()
    if sym in ctx["holdings"]:
        return "holdings", True
    if sym in ctx["proposals"]:
        return "open_proposal", True
    if sym in ctx["directive"]:
        return "active_directive", True
    score = r.get("hermes_composite_score") or 0
    rank = r.get("hermes_rank")
    if (score and score >= 70) or (rank is not None and rank <= 20):
        return "high_rank_watchlist", True
    # Everything else is broad-universe curation — metadata only, the guard will not call an LLM.
    return "top20_curation", False


def run(top=20, lanes=("chatgpt", "grok"), apply=False, symbols=None, *, run_id=None, dry_run=False):
    if dry_run:
        apply = False  # --dry-run wins over --apply
    producer = "hermes_top20_external_intel"
    family = "B"
    accounting_run_id = run_id or new_run_id(producer)

    def account(event, *, symbol, lane, call_id, reason=None, metadata=None):
        if dry_run:
            return  # a dry run appends nothing to the research-call accounting ledger
        try:
            append_call_event(
                event, producer=producer, family=family, run_id=accounting_run_id,
                call_id=call_id, symbol=symbol, lane=lane, trigger="top20_external_intel",
                reason=reason, apply=apply, metadata=metadata,
            )
        except Exception as exc:
            print(f"[top20] accounting_error={type(exc).__name__}:{exc}")

    conn = _conn()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)
    rows = _named(conn, symbols) if symbols else _top(conn, top)
    report = {"top": len(rows), "lanes": list(lanes), "called": 0, "skipped": 0,
              "metadata_only": 0, "deferred": 0, "blocked": 0, "would_call": 0, "call_errors": 0,
              "detail": []}
    # Budget guard: broad-universe names get METADATA_ONLY (no cloud LLM); only held / proposed /
    # directive / high-rank names reach a free-OAuth lane. Eliminates the broad-universe LLM fan-out.
    try:
        from hermes_research_budget_guard import decide as _budget_decide, _load_policy as _load_bpol
        _bpol = _load_bpol()
        _tier_of = _bpol.get("trigger_source_tier", {})
    except Exception:
        _budget_decide = None
        _bpol, _tier_of = None, {}
    ctx = _trigger_context(conn)
    tier_count = {}            # per-tier symbols already ALLOWed this run -> enforces per-run caps
    for r in rows:
        q = _question(r)
        trig, has_trig = _trigger_for(r, ctx)
        tier = _tier_of.get(trig, "T3")
        for lane in lanes:
            call_id = call_id_for(accounting_run_id, r["symbol"], lane)
            account(
                "SCHEDULED", symbol=r["symbol"], lane=lane, call_id=call_id,
                metadata={"tier": tier, "trigger_source": trig},
            )
            recent = _recent(conn, r["symbol"], lane)
            decision = "ALLOW"
            if _budget_decide is not None:
                gd = _budget_decide(symbol=r["symbol"], trigger_source=trig,
                                    research_type="enhanced_intel", lane="cloud_" + lane,
                                    urgency="normal", has_active_trigger=has_trig, dedup_fresh=recent,
                                    symbols_this_run=tier_count.get(tier, 0))
                decision = gd["decision"]
                if decision == "ALLOW":
                    tier_count[tier] = tier_count.get(tier, 0) + 1
            elif recent:
                decision = "DEFER"
            if decision != "ALLOW":
                if recent and not dry_run:
                    try:
                        from lib.research_skip_ledger import log_mapped_reason
                        log_mapped_reason("FRESH_HOURS", symbol=r["symbol"], lane=lane)
                    except Exception:
                        pass
                report[{"METADATA_ONLY": "metadata_only", "DEFER": "deferred",
                        "BLOCK": "blocked"}.get(decision, "skipped")] += 1
                report["detail"].append({"symbol": r["symbol"], "lane": lane, "trigger_source": trig,
                                         "budget_decision": decision})
                event = "DEDUPED" if recent else "SKIP_GATED"
                account(
                    event, symbol=r["symbol"], lane=lane, call_id=call_id,
                    reason="FRESH_HOURS" if recent else f"BUDGET_GUARD_{decision}",
                    metadata={"tier": tier, "trigger_source": trig},
                )
                continue
            if dry_run:
                report["would_call"] += 1
                report["detail"].append({"symbol": r["symbol"], "lane": lane,
                                         "trigger_source": trig, "budget_decision": "ALLOW",
                                         "action": "would_call_external_researcher"})
                continue
            if not apply:
                report["detail"].append({"symbol": r["symbol"], "lane": lane,
                                         "trigger_source": trig, "budget_decision": "ALLOW",
                                         "action": "dry-run"})
                account("DRY_RUN", symbol=r["symbol"], lane=lane, call_id=call_id,
                        reason="provider_not_called", metadata={"trigger_source": trig})
                continue
            try:
                cp = subprocess.run(
                    [_child_python(), str(PROJECT_ROOT / "scripts" / "hermes_external_researcher.py"),
                     "--lane", lane, "--symbol", r["symbol"], "--question", q,
                     "--trigger", trig, "--priority", "P2", "--apply",
                     "--run-id", accounting_run_id, "--call-id", call_id,
                     "--producer", producer, "--family", family],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=180)
                ok = cp.returncode == 0
                report["called"] += 1 if ok else 0
                report["detail"].append({"symbol": r["symbol"], "lane": lane, "ok": ok})
                if not ok:
                    report["call_errors"] += 1
                    account("ERROR", symbol=r["symbol"], lane=lane, call_id=call_id,
                            reason=f"subprocess_exit_{cp.returncode}")
            except Exception as e:
                report["call_errors"] += 1
                report["detail"].append({"symbol": r["symbol"], "lane": lane, "error": str(e)[:80]})
                account("ERROR", symbol=r["symbol"], lane=lane, call_id=call_id,
                        reason=f"subprocess_error:{type(e).__name__}")
    keys = ("top", "lanes", "called", "skipped", "metadata_only", "deferred", "blocked")
    if dry_run:
        keys = keys + ("would_call",)
    elif apply:
        keys = keys + ("call_errors",)
    print(json.dumps({**{k: report[k] for k in keys}, **({"dry_run": True} if dry_run else {})}, indent=2))
    return report


def _child_python() -> str:
    try:
        from lib.live_project_root import venv_python

        return venv_python(PROJECT_ROOT)
    except Exception:  # noqa: BLE001 -- helper unavailable: the running interpreter (old behaviour)
        return sys.executable


def main(argv=None) -> int:
    # G2: after imports settle — refuse dual lib.X / scripts.lib.X identity
    from lib import assert_single_import_identity
    assert_single_import_identity()
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--lanes", default="chatgpt,grok")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--symbols", help="explicit comma-separated symbol list (overrides --top)")
    ap.add_argument("--dry-run", action="store_true",
                    help="read-only preview of the budget decisions; wins over --apply; writes nothing")
    a = ap.parse_args(argv)
    kw = dict(top=a.top, lanes=tuple(x.strip() for x in a.lanes.split(",") if x.strip()),
              symbols=a.symbols.split(",") if a.symbols else None)
    if a.dry_run or not a.apply:
        # no-flag form unchanged (it still appends DRY_RUN accounting events); no receipt either way
        run(apply=False, dry_run=a.dry_run, **kw)
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    try:
        rep = run(apply=True, **kw)
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        print(f"[top20] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    summary = {k: rep[k] for k in ("top", "called", "call_errors", "skipped", "metadata_only",
                                   "deferred", "blocked")}
    # Calls were started and none succeeded: the lane's work did not happen. Deferrals are findings.
    failed = rep["call_errors"] > 0 and rep["called"] == 0
    write_receipt(RECEIPT_NAME, ok=not failed, summary=summary, started_at=started,
                  error="every hermes_external_researcher call failed" if failed else None)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
