#!/usr/bin/env python3
"""Q2 — dry-run mint living symbol theses from EXISTING stores. No new LLM.

Sources: hermes_external_research + holdings role + Hermes rank + reentry desk.
Writes ONLY to data/cio/staging/ (not live cio_theses.jsonl).
Apply to live store after 8/27.

READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING_EVENTS = ROOT / "data/cio/staging/symbol_thesis_mint_dryrun.jsonl"
STAGING_PROJ = ROOT / "data/cio/staging/symbol_thesis_mint_dryrun_projection.json"


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    return t.strip()


def _summary_from_rec(sym: str, rec: str) -> str:
    t = _strip_fence(rec)
    t = " ".join(t.split())
    if len(t) > 700:
        t = t[:697].rstrip() + "…"
    if not t:
        return ""
    if not re.search(rf"\b{re.escape(sym)}\b", t, re.I):
        t = f"{sym}: {t}"
    return t


def _latest_research(conn, symbols: list[str]) -> dict[str, dict]:
    cur = conn.cursor()
    out = {}
    cur.execute(
        """SELECT DISTINCT ON (upper(symbol))
              upper(symbol), id, lane, recommendation, confidence, created_at
           FROM hermes_external_research
           WHERE upper(symbol) = ANY(%s)
             AND coalesce(recommendation,'')<>''
             AND recommendation NOT LIKE '[%%'
           ORDER BY upper(symbol), created_at DESC""",
        (symbols,),
    )
    for sym, rid, lane, rec, conf, ts in cur.fetchall():
        out[sym] = {
            "id": rid,
            "lane": lane,
            "recommendation": rec or "",
            "confidence": conf,
            "created_at": str(ts),
        }
    return out


def _hermes_rank(conn, symbols: list[str]) -> dict[str, int]:
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT DISTINCT ON (upper(symbol)) upper(symbol), rank
               FROM hermes_score_history
               WHERE upper(symbol) = ANY(%s) AND rank IS NOT NULL
               ORDER BY upper(symbol), as_of DESC NULLS LAST, created_at DESC NULLS LAST""",
            (symbols,),
        )
        return {r[0]: int(r[1]) for r in cur.fetchall()}
    except Exception:
        conn.rollback()
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-staging", action="store_true",
                    help="Write staging JSONL (still not live thesis store)")
    ap.add_argument("--out", default=str(ROOT / "data/cio/thesis_mint_dryrun_2026-08-22.json"))
    args = ap.parse_args()

    import os, sys
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    os.chdir(str(ROOT))
    CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
    from db_adapter import _get_conn
    from research_scheduler import load_universe, load_reentry_ready_near_symbols
    from scripts.lib.cio_held_thesis_coverage import build_held_coverage_report
    from scripts.lib.symbol_thesis_coverage import symbol_thesis_id
    from scripts.lib.portfolio_role import resolve_portfolio_role

    uni = load_universe(root=CURRENT)
    reentry = sorted(load_reentry_ready_near_symbols(root=CURRENT) or [])
    holdings = sorted(s for s, v in uni.items() if v.get("tier") == "T0-HOLD")
    live = build_held_coverage_report(root=CURRENT)
    live_state = {r["symbol"]: r for r in live.get("rows") or []}
    needs = set(live.get("needs_coverage") or [])

    symbols = sorted(set(holdings) | set(reentry))
    conn = _get_conn()
    research = _latest_research(conn, symbols)
    ranks = _hermes_rank(conn, symbols)

    cards = []
    mintable_holdings = []
    for sym in symbols:
        rec = research.get(sym) or {}
        text = rec.get("recommendation") or ""
        summary = _summary_from_rec(sym, text)
        role = resolve_portfolio_role(sym, universe_rec=uni.get(sym) or {}, root=CURRENT)
        would = bool(summary) and len(summary) >= 40
        live_row = live_state.get(sym) or {}
        card = {
            "symbol": sym,
            "bucket": "T0-HOLD" if sym in holdings else "reentry",
            "live_state": live_row.get("thesis_state") or ("reentry" if sym in reentry else "UNKNOWN"),
            "live_current": bool(live_row.get("has_current_symbol_thesis")),
            "research_id": rec.get("id"),
            "research_lane": rec.get("lane"),
            "research_chars": len(text),
            "hermes_rank": ranks.get(sym),
            "portfolio_role": (role or {}).get("portfolio_role"),
            "would_mint_current": would,
            "would_say": summary[:400],
            "blockers": [] if would else ["no_nonempty_external_research_or_summary_lt_40"],
        }
        cards.append(card)
        if sym in needs and would:
            mintable_holdings.append(sym)

    if args.apply_staging:
        from scripts.lib.cio_theses import CIOThesisStore
        if STAGING_EVENTS.exists():
            STAGING_EVENTS.unlink()
        if STAGING_PROJ.exists():
            STAGING_PROJ.unlink()
        store = CIOThesisStore(event_path=STAGING_EVENTS, projection_path=STAGING_PROJ)
        n_pub = 0
        for card in cards:
            if not card["would_mint_current"]:
                continue
            store.publish(
                card["would_say"],
                thesis_id=symbol_thesis_id(card["symbol"]),
                stance="hold" if card["bucket"] == "T0-HOLD" else "watch",
                owner_agent="system",
                actor_id="thesis_mint_dryrun",
                change_note="DRY_RUN mint from hermes_external_research — not live",
                extra={
                    "source_research_id": card["research_id"],
                    "source_lane": card["research_lane"],
                    "dry_run": True,
                },
                notify=False,
            )
            n_pub += 1
        staging_n = n_pub
    else:
        staging_n = 0

    report = {
        "schema": "ThesisMintDryRun@v1",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "live_held_current": f"{live.get('current_count')}/{live.get('held_count')} ({live.get('held_current_pct')}%)",
        "holdings_n": len(holdings),
        "reentry_n": len(reentry),
        "needs_coverage_n": len(needs),
        "mintable_of_19_required": len(mintable_holdings),
        "mintable_holdings": mintable_holdings,
        "would_mint_holdings": sum(1 for c in cards if c["bucket"] == "T0-HOLD" and c["would_mint_current"]),
        "would_mint_reentry": sum(1 for c in cards if c["bucket"] == "reentry" and c["would_mint_current"]),
        "staging_published": staging_n,
        "staging_path": str(STAGING_EVENTS) if args.apply_staging else None,
        "punchline": (
            "MOST of the RESEARCH_REQUIRED book can be minted from data already on disk"
            if len(mintable_holdings) >= 10
            else "Minting from existing research would NOT cover most of the 19"
        ),
        "apply_after": "2026-08-27",
        "cards": cards,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    slim = {k: report[k] for k in report if k != "cards"}
    print(json.dumps(slim, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
