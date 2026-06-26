#!/usr/bin/env python3
"""options_research_bridge.py — Stage options desk intelligence into Hermes + TradeAI surfaces.

After each options monitor pass:
  • Publishes data/runtime/options_desk_latest.json (TradeAI /api/v2/trade-ai enrichment)
  • Stages hermes_research_intelligence rows (research_type=options_desk) for RAG + coordinator

Usage:
  .venv/bin/python scripts/options_research_bridge.py --apply
  .venv/bin/python scripts/options_research_bridge.py --apply --symbol NOC
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timezone, datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

import options_engine as oe


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def stage_hermes_research(summary: dict, *, apply: bool = False, symbol: str = "") -> dict:
    """Insert desk + per-symbol options research rows for Hermes coordinator."""
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "no db"}
    staged = 0
    skipped = 0
    cur = conn.cursor()

    top_bits = [
        f"{p['symbol']} {p['strategy']} edge {p.get('edge_score')}"
        for p in (summary.get("top_proposals") or [])[:5]
    ]
    desk_line = (
        f"Options desk: {summary.get('proposal_count', 0)} proposals — "
        f"{json.dumps(summary.get('strategy_counts') or {})}. "
        f"Top: {', '.join(top_bits)}"
    )
    rows_to_stage = [{"symbol": None, "topic": "Options Desk Summary", "summary": desk_line, "thesis": desk_line}]

    by_sym = summary.get("by_symbol") or {}
    sym_filter = (symbol or "").upper()
    for sym, ideas in by_sym.items():
        if sym_filter and sym != sym_filter:
            continue
        if not ideas:
            continue
        best = ideas[0]
        rows_to_stage.append({
            "symbol": sym,
            "topic": f"Options: {best.get('strategy', '').replace('_', ' ')}",
            "summary": (
                f"{sym} {best.get('recommended_action') or best.get('strategy')}: "
                f"${best.get('strike')} {best.get('expiration')} · edge {best.get('edge_score')} · "
                f"POP {best.get('pop_pct')}% · IV rank {best.get('iv_rank')}%"
            ),
            "thesis": (
                f"Options desk flags {sym} for {best.get('strategy')} "
                f"({best.get('option_type')} {best.get('side')}) — review chain before routing."
            ),
        })

    for row in rows_to_stage:
        sym = row.get("symbol")
        if sym:
            cur.execute(
                """SELECT 1 FROM hermes_research_intelligence
                   WHERE research_type='options_desk' AND symbol=%s AND status IN ('staged','promoted')
                     AND created_at > NOW() - INTERVAL '6 hours' LIMIT 1""",
                (sym,),
            )
        else:
            cur.execute(
                """SELECT 1 FROM hermes_research_intelligence
                   WHERE research_type='options_desk' AND symbol IS NULL AND status IN ('staged','promoted')
                     AND created_at > NOW() - INTERVAL '3 hours' LIMIT 1""",
            )
        if cur.fetchone():
            skipped += 1
            continue
        if not apply:
            staged += 1
            continue
        evidence = {
            "source": "options_research_bridge",
            "desk_generated_at": summary.get("generated_at"),
            "strategy_slots": summary.get("strategy_slots"),
            "raw_pool": summary.get("raw_pool"),
        }
        cur.execute(
            """INSERT INTO hermes_research_intelligence
               (source, hermes_agent_name, research_type, symbol, topic, summary, thesis,
                thesis_type, evidence_json, confidence_score, freshness_date, model_used, status)
               VALUES ('hermes','options_research_bridge','options_desk', %s, %s, %s, %s,
                       'neutral', %s::jsonb, %s, %s, 'options_engine', 'staged')""",
            (
                sym,
                row["topic"],
                row["summary"][:500],
                row["thesis"][:500],
                json.dumps(evidence),
                min(0.95, 0.5 + _f(best_edge(summary, sym)) / 100.0) if sym else 0.7,
                date.today().isoformat(),
            ),
        )
        staged += 1
    if apply:
        conn.commit()
    return {"ok": True, "staged": staged, "skipped": skipped, "dry_run": not apply}


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def best_edge(summary: dict, sym: str) -> float:
    ideas = (summary.get("by_symbol") or {}).get(sym) or []
    return _f(ideas[0].get("edge_score")) if ideas else 0.0


def run(*, apply: bool = False, symbol: str = "", force: bool = False) -> dict:
    props = oe.generate_proposals(force=force)
    summary = oe.publish_options_desk_runtime(oe.build_options_desk_summary(props))
    hermes = stage_hermes_research(summary, apply=apply, symbol=symbol)
    return {
        "ok": True,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "desk": {
            "proposal_count": summary.get("proposal_count"),
            "strategy_counts": summary.get("strategy_counts"),
            "top": summary.get("top_proposals", [])[:5],
        },
        "hermes": hermes,
        "runtime_path": str(oe.OPTIONS_DESK_RUNTIME),
    }


def main():
    p = argparse.ArgumentParser(description="Options desk → Hermes + TradeAI runtime bridge")
    p.add_argument("--apply", action="store_true", help="Write Hermes staged rows (default dry-run)")
    p.add_argument("--force", action="store_true", help="Force-regenerate proposals before publish")
    p.add_argument("--symbol", default="", help="Stage only one symbol")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    rep = run(apply=args.apply, symbol=args.symbol, force=args.force)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(json.dumps(rep, indent=2, default=str))


if __name__ == "__main__":
    main()