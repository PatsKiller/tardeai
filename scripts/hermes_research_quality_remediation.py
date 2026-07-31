#!/usr/bin/env python3
"""Hermes research quality remediation — closes maturity gates external_error_rate,
proposals_with_prior_research, and s0_research_freshness via research_scheduler lanes.

Runs on a timer (systemd). Does NOT fabricate agent review artifacts — scheduled research only.

Usage:
  python scripts/hermes_research_quality_remediation.py --dry-run
  python scripts/hermes_research_quality_remediation.py --run
  python scripts/hermes_research_quality_remediation.py --summary
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

DEFAULT_BUDGET = 25
EXTERNAL_LANES = ("grok", "chatgpt")


def _db():
    from db_adapter import _execute, USE_DB
    if not USE_DB:
        raise RuntimeError("DB unavailable")
    return _execute


def _ensure_columns(ex):
    ex("""
        ALTER TABLE intelligence_remediation_runs
          ADD COLUMN IF NOT EXISTS external_retries INT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS proposal_backfills INT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS s0_refreshes INT NOT NULL DEFAULT 0
    """, fetch="none")


def failed_external_symbols(ex) -> list[str]:
    rows = ex("""
        SELECT DISTINCT UPPER(symbol) AS symbol
        FROM hermes_external_research
        WHERE status = 'error'
          AND created_at > NOW() - INTERVAL '24 hours'
          AND symbol IS NOT NULL
        ORDER BY 1
    """, fetch="all") or []
    return [dict(r)["symbol"] for r in rows if dict(r).get("symbol")]


def proposals_missing_prior_research(ex) -> list[str]:
    rows = ex("""
        SELECT DISTINCT UPPER(p.symbol) AS symbol
        FROM paper_trade_proposals p
        WHERE p.created_at > NOW() - INTERVAL '30 days'
          AND NOT EXISTS (
            SELECT 1 FROM hermes_research_intelligence h
            WHERE UPPER(h.symbol) = UPPER(p.symbol)
              AND h.created_at < p.created_at
              AND h.created_at > p.created_at - INTERVAL '30 days'
          )
        ORDER BY 1
    """, fetch="all") or []
    return [dict(r)["symbol"] for r in rows if dict(r).get("symbol")]


def stale_s0_symbols(ex) -> list[str]:
    rows = ex("""
        SELECT DISTINCT UPPER(wi.symbol) AS symbol
        FROM watchlist_items wi
        WHERE wi.scope_tier = 'S0'
          AND wi.status IN ('active', 'researched')
          AND NOT EXISTS (
            SELECT 1 FROM hermes_research_intelligence h
            WHERE UPPER(h.symbol) = UPPER(wi.symbol)
              AND h.created_at > NOW() - INTERVAL '7 days'
          )
        ORDER BY 1
    """, fetch="all") or []
    return [dict(r)["symbol"] for r in rows if dict(r).get("symbol")]


def _dispatch_symbol(sym: str, tier: str, apply: bool, *, local: bool = True, external: bool = True) -> dict:
    from research_scheduler import dispatch, _enqueue_local
    out = {"symbol": sym, "tier": tier, "local": None, "external": []}
    if local:
        out["local"] = _enqueue_local(sym, tier, deep=False) if apply else {"ok": True, "tail": "would enqueue local-gemma"}
    if external:
        for lane in EXTERNAL_LANES:
            res = dispatch(sym, lane, tier, apply)
            out["external"].append({"lane": lane, **res})
            if apply:
                time.sleep(1)
    return out


def remediate(*, dry_run: bool = True, budget: int = DEFAULT_BUDGET) -> dict:
    ex = _db()
    _ensure_columns(ex)
    apply = not dry_run

    ext_syms = failed_external_symbols(ex)
    prop_syms = proposals_missing_prior_research(ex)
    s0_syms = stale_s0_symbols(ex)

    external_retries = 0
    proposal_backfills = 0
    s0_refreshes = 0
    details: list[dict] = []

    ext_budget = max(1, budget // 2)
    prop_budget = max(1, budget // 3)
    s0_budget = max(1, budget - ext_budget - prop_budget)

    # 1) Retry failed external lanes (one external call per symbol, budgeted)
    from research_scheduler import dispatch
    for sym in ext_syms:
        if external_retries >= ext_budget:
            break
        if dry_run:
            external_retries += 1
            details.append({"kind": "external_retry", "symbol": sym, "dry_run": True})
            continue
        lane = EXTERNAL_LANES[external_retries % len(EXTERNAL_LANES)]
        res = dispatch(sym, lane, "T1-WATCH", apply)
        details.append({"kind": "external_retry", "symbol": sym, "lane": lane, **res})
        external_retries += 1
        if apply:
            time.sleep(1)

    # 2) Backfill research for proposals missing prior intelligence
    for sym in prop_syms:
        if proposal_backfills >= prop_budget:
            break
        if dry_run:
            proposal_backfills += 1
            details.append({"kind": "proposal_backfill", "symbol": sym, "dry_run": True})
            continue
        _dispatch_symbol(sym, "T0-PROP", apply, local=True, external=proposal_backfills < prop_budget)
        proposal_backfills += 1

    # 3) Refresh stale S0 holdings research (local always; one external if budget remains)
    for sym in s0_syms:
        if s0_refreshes >= s0_budget:
            break
        if dry_run:
            s0_refreshes += 1
            details.append({"kind": "s0_refresh", "symbol": sym, "dry_run": True})
            continue
        use_ext = s0_refreshes < s0_budget // 2
        _dispatch_symbol(sym, "T0-HOLD", apply, local=True, external=use_ext)
        s0_refreshes += 1

    out = {
        "dry_run": dry_run,
        "external_retries": external_retries,
        "proposal_backfills": proposal_backfills,
        "s0_refreshes": s0_refreshes,
        "candidates": {
            "failed_external": len(ext_syms),
            "proposals_missing_prior": len(prop_syms),
            "stale_s0": len(s0_syms),
        },
        "at": datetime.now(timezone.utc).isoformat(),
        "details": details[:40],
    }
    if apply:
        ex("""
            INSERT INTO intelligence_remediation_runs
            (gaps_enqueued, items_archived, ensemble_queued, watch_critics,
             external_retries, proposal_backfills, s0_refreshes, note)
            VALUES (0, 0, 0, 0, %s, %s, %s, 'hermes_research_quality')
        """, (external_retries, proposal_backfills, s0_refreshes), fetch="none")
    return out


def remediation_summary(ex) -> dict:
    _ensure_columns(ex)
    last = ex("""
        SELECT * FROM intelligence_remediation_runs
        WHERE note = 'hermes_research_quality'
        ORDER BY run_at DESC LIMIT 1
    """, fetch="one")
    totals = ex("""
        SELECT
          COALESCE(SUM(external_retries), 0) AS external_retries,
          COALESCE(SUM(proposal_backfills), 0) AS proposal_backfills,
          COALESCE(SUM(s0_refreshes), 0) AS s0_refreshes,
          COUNT(*) AS run_count
        FROM intelligence_remediation_runs
        WHERE note = 'hermes_research_quality'
          AND run_at > NOW() - INTERVAL '7 days'
    """, fetch="one") or {}
    gates = {}
    try:
        from hermes_maturity_gates import _gates_research
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        gates = _gates_research(cur)
    except Exception:
        pass
    return {
        "last_run": last,
        "totals_7d": totals,
        "candidates": {
            "failed_external": len(failed_external_symbols(ex)),
            "proposals_missing_prior": len(proposals_missing_prior_research(ex)),
            "stale_s0": len(stale_s0_symbols(ex)),
        },
        "research_gates": gates,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    args = parser.parse_args()
    if args.summary:
        print(json.dumps(remediation_summary(_db()), indent=2, default=str))
        return
    result = remediate(dry_run=not args.run, budget=args.budget)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
