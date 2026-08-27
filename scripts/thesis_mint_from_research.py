#!/usr/bin/env python3
"""Q2 — mint living symbol theses from EXISTING stores. No new LLM.

Sources: hermes_external_research + holdings role + Hermes rank + reentry desk.
Default write is staging: data/cio/staging/ (not live cio_theses.jsonl).
--apply-live is opt-in and writes CIOThesisStore default paths
(data/cio/cio_theses.jsonl) after a huge warning. Do not pass it by accident.

Mint grade is JOINED rec+dissent+evidence (g_mint). Report JSON still
publishes both rec-only and joined splits.

READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING_EVENTS = ROOT / "data/cio/staging/symbol_thesis_mint_dryrun.jsonl"
STAGING_PROJ = ROOT / "data/cio/staging/symbol_thesis_mint_dryrun_projection.json"
# Live store is the shared CURRENT/rebuild jsonl (inode 3064869), not the worktree.
LIVE_ROOT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
LIVE_EVENTS = LIVE_ROOT / "data/cio/cio_theses.jsonl"
LIVE_PROJ = LIVE_ROOT / "data/cio/cio_theses_projection.json"

LIVE_APPLY_WARNING = """
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
WARNING: --apply-live WRITES TO THE LIVE CIO THESIS STORE
  CURRENT/data/cio/cio_theses.jsonl
  CURRENT/data/cio/cio_theses_projection.json
(shared inode with rebuild). This is append-only, operator-visible,
and NOT the default. Default remains staging (--apply-staging).
Do not use this flag unless you intend to mint living symbol theses
into the live store.
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
"""


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    return t.strip()


def _summary_from_rec(sym: str, rec: str, *, cap: int = 2000) -> str:
    t = _strip_fence(rec)
    t = " ".join(t.split())
    if len(t) > cap:
        t = t[: cap - 1].rstrip() + "…"
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
              upper(symbol), id, lane, recommendation, dissent, evidence_json,
              confidence, created_at
           FROM hermes_external_research
           WHERE upper(symbol) = ANY(%s)
             AND coalesce(recommendation,'')<>''
             AND recommendation NOT LIKE '[%%'
           ORDER BY upper(symbol), created_at DESC""",
        (symbols,),
    )
    for sym, rid, lane, rec, dissent, evidence, conf, ts in cur.fetchall():
        out[sym] = {
            "id": rid,
            "lane": lane,
            "recommendation": rec or "",
            "dissent": dissent or "",
            "evidence": evidence,
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


def _mint_extra(card: dict, *, dry_run: bool, apply_live: bool) -> dict:
    return {
        "source_research_id": card["research_id"],
        "source_lane": card["research_lane"],
        "dry_run": dry_run,
        "apply_live": apply_live,
        "substantiveness": "PASS" if card["would_mint_state"] == "CURRENT" else "THIN",
        "substantiveness_grade": (
            card.get("grade_mint") or card["grade_joined"] or card["grade_rec_only"]
        ),
        "grade_rec_only": card["grade_rec_only"],
        "grade_joined": card["grade_joined"],
        "mint_state": card["would_mint_state"],
        "mint_grade_source": card.get("mint_grade_source"),
    }


def _kind_for_card(card: dict) -> str:
    live = (card.get("live_regrade") or card.get("live_state") or "").upper()
    nxt = (card.get("would_mint_state") or "").upper()
    if live in ("", "UNKNOWN", "RESEARCH_REQUIRED", "REENTRY"):
        return "minted"
    if live == "THIN" and nxt == "CURRENT":
        return "upgraded"
    if live == "CURRENT" and nxt == "THIN":
        return "downgraded"
    if nxt == "SKIP":
        return "invalidated"
    return "revised"


def _publish_mint_cards(
    cards: list,
    store,
    *,
    notify: bool,
    dry_run: bool,
    apply_live: bool,
    actor_id: str,
    change_note: str,
    emit_desk_card: bool = False,
) -> int:
    from scripts.lib.symbol_thesis_coverage import symbol_thesis_id
    from scripts.lib.cio_held_thesis_coverage import write_thesis_change_card

    n_pub = 0
    for card in cards:
        if not card["would_mint"]:
            continue
        tid = symbol_thesis_id(card["symbol"])
        rec = store.publish(
            card["would_say"],
            thesis_id=tid,
            stance="hold" if card["bucket"] == "T0-HOLD" else "watch",
            owner_agent="system",
            actor_id=actor_id,
            change_note=change_note,
            extra=_mint_extra(card, dry_run=dry_run, apply_live=apply_live),
            notify=notify,
        )
        if emit_desk_card:
            write_thesis_change_card(
                symbol=card["symbol"],
                thesis_id=tid,
                version=int((rec or {}).get("version") or 1),
                kind=_kind_for_card(card),
                summary=card["would_say"],
                mint_state=card.get("would_mint_state"),
                grade=card.get("grade_mint"),
            )
        n_pub += 1
    return n_pub


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-staging", action="store_true",
                    help="Write staging JSONL (still not live thesis store)")
    ap.add_argument(
        "--apply-live",
        action="store_true",
        help=(
            "DANGER: write to live CURRENT/data/cio/cio_theses.jsonl "
            "(data/cio/cio_theses.jsonl). Default remains staging. "
            "Prints a huge warning. Opt-in only. Do not use during freeze."
        ),
    )
    ap.add_argument("--out", default=str(ROOT / "data/cio/thesis_mint_dryrun_2026-08-22.json"))
    args = ap.parse_args()

    if args.apply_live:
        print(LIVE_APPLY_WARNING, file=sys.stderr)
        print(LIVE_APPLY_WARNING)

    import os
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    os.chdir(str(ROOT))
    CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
    from db_adapter import _get_conn
    from research_scheduler import load_universe, load_reentry_ready_near_symbols
    from scripts.lib.cio_held_thesis_coverage import build_held_coverage_report
    from scripts.lib.portfolio_role import resolve_portfolio_role
    from scripts.lib.thesis_substantiveness import grade_text, join_research_text, mint_state_for

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
        rec_only = rec.get("recommendation") or ""
        joined = join_research_text(
            rec_only, rec.get("dissent"), rec.get("evidence"),
        )
        summary_rec = _summary_from_rec(sym, rec_only)
        summary_joined = _summary_from_rec(sym, joined)
        g_rec = grade_text(sym, summary_rec)
        g_joined = grade_text(sym, summary_joined)
        mint_body = summary_joined or summary_rec
        # P2: grade JOINED rec+dissent+evidence for would_mint_state / extra.
        # Rec-only and joined splits stay in the report JSON.
        g_mint = g_joined if summary_joined else g_rec
        mint_state = mint_state_for(g_mint)
        would = mint_state in ("CURRENT", "THIN")
        role = resolve_portfolio_role(sym, universe_rec=uni.get(sym) or {}, root=CURRENT)
        live_row = live_state.get(sym) or {}
        live_summary = (live_row.get("thesis_summary") or "")
        live_grade = grade_text(sym, live_summary) if live_summary else None
        card = {
            "symbol": sym,
            "bucket": "T0-HOLD" if sym in holdings else "reentry",
            "live_state": live_row.get("thesis_state") or ("reentry" if sym in reentry else "UNKNOWN"),
            "live_current": bool(live_row.get("has_current_symbol_thesis")),
            "live_regrade": (live_grade or {}).get("coverage_state") if live_grade else None,
            "live_grade": (live_grade or {}).get("grade") if live_grade else None,
            "research_id": rec.get("id"),
            "research_lane": rec.get("lane"),
            "research_chars": len(rec_only),
            "joined_chars": len(joined),
            "hermes_rank": ranks.get(sym),
            "portfolio_role": (role or {}).get("portfolio_role"),
            "grade_rec_only": g_rec.get("grade"),
            "state_rec_only": g_rec.get("coverage_state"),
            "grade_joined": g_joined.get("grade"),
            "state_joined": g_joined.get("coverage_state"),
            "grade_mint": g_mint.get("grade"),
            "mint_grade_source": "joined" if summary_joined else "rec_only",
            "would_mint_state": mint_state if would else "SKIP",
            "would_mint_current": mint_state == "CURRENT",
            "would_mint_thin": mint_state == "THIN",
            "would_mint": would,
            "would_say": mint_body,
            "would_say_preview": mint_body[:400],
            "blockers": [] if would else ["no_nonempty_external_research_or_summary_lt_40"],
            "grade_reasons": g_mint.get("reasons") or [],
        }
        cards.append(card)
        if sym in needs and would:
            mintable_holdings.append(sym)

    staging_n = 0
    live_n = 0
    if args.apply_staging:
        from scripts.lib.cio_theses import CIOThesisStore
        if STAGING_EVENTS.exists():
            STAGING_EVENTS.unlink()
        if STAGING_PROJ.exists():
            STAGING_PROJ.unlink()
        staging_store = CIOThesisStore(event_path=STAGING_EVENTS, projection_path=STAGING_PROJ)
        # P4: staging stays silent. notify=False
        staging_n = _publish_mint_cards(
            cards,
            staging_store,
            notify=False,
            dry_run=True,
            apply_live=False,
            actor_id="thesis_mint_dryrun",
            change_note="DRY_RUN mint from hermes_external_research — not live",
        )
    if args.apply_live:
        from scripts.lib.cio_theses import CIOThesisStore
        # Never unlink live jsonl — append-only. Default CIOThesisStore paths.
        live_store = CIOThesisStore(event_path=LIVE_EVENTS, projection_path=LIVE_PROJ)
        # P4: live apply uses CIOThesisStore.publish notify=True + desk card
        live_n = _publish_mint_cards(
            cards,
            live_store,
            notify=True,
            dry_run=False,
            apply_live=True,
            actor_id="thesis_mint_from_research",
            change_note="LIVE mint from hermes_external_research (joined rec+dissent+evidence)",
            emit_desk_card=True,
        )

    req_cards = [c for c in cards if c["symbol"] in needs]
    live_current_cards = [
        c for c in cards
        if c["bucket"] == "T0-HOLD" and c.get("live_grade")
    ]
    split_rec = {
        "CURRENT": sum(1 for c in req_cards if c["state_rec_only"] == "CURRENT"),
        "THIN": sum(1 for c in req_cards if c["state_rec_only"] == "THIN"),
        "SKIP": sum(1 for c in req_cards if c["state_rec_only"] not in ("CURRENT", "THIN")),
    }
    split_joined = {
        "CURRENT": sum(1 for c in req_cards if c["state_joined"] == "CURRENT"),
        "THIN": sum(1 for c in req_cards if c["state_joined"] == "THIN"),
        "SKIP": sum(1 for c in req_cards if c["state_joined"] not in ("CURRENT", "THIN")),
    }
    live_regrade = {
        "PASS": sum(1 for c in live_current_cards if c.get("live_regrade") == "CURRENT"),
        "THIN": sum(1 for c in live_current_cards if c.get("live_regrade") == "THIN"),
        "n": len(live_current_cards),
    }
    report = {
        "schema": "ThesisMintDryRun@v2",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "live_held_current": (
            f"{live.get('current_count')}/{live.get('held_count')} "
            f"coverage={live.get('coverage_pct')}% substantive={live.get('substantive_pct')}%"
        ),
        "holdings_n": len(holdings),
        "reentry_n": len(reentry),
        "needs_coverage_n": len(needs),
        "mintable_of_19_required": len(mintable_holdings),
        "mintable_holdings": mintable_holdings,
        "projected_split_of_19": {
            "n": len(req_cards),
            "rec_only": split_rec,
            "joined": split_joined,
            "honest_line": (
                f"rec-only {split_rec['CURRENT']}/{len(req_cards)} CURRENT, "
                f"{split_rec['THIN']} THIN; joined {split_joined['CURRENT']}/{len(req_cards)} CURRENT, "
                f"{split_joined['THIN']} THIN. 19/19 is coverage, not quality."
            ),
        },
        "existing_current_regrade": live_regrade,
        "would_mint_holdings": sum(1 for c in cards if c["bucket"] == "T0-HOLD" and c["would_mint"]),
        "would_mint_holdings_current": sum(
            1 for c in cards if c["bucket"] == "T0-HOLD" and c["would_mint_state"] == "CURRENT"
        ),
        "would_mint_holdings_thin": sum(
            1 for c in cards if c["bucket"] == "T0-HOLD" and c["would_mint_state"] == "THIN"
        ),
        "would_mint_reentry": sum(1 for c in cards if c["bucket"] == "reentry" and c["would_mint"]),
        "staging_published": staging_n,
        "staging_path": str(STAGING_EVENTS) if args.apply_staging else None,
        "apply_live": bool(args.apply_live),
        "live_published": live_n,
        "live_path": str(LIVE_EVENTS) if args.apply_live else None,
        "notify": bool(args.apply_live),
        "punchline": (
            f"Join gap still {len(mintable_holdings)}/{len(needs)} mintable; "
            f"quality split joined CURRENT={split_joined['CURRENT']} THIN={split_joined['THIN']}. "
            "Do not treat 19/19 as a green coverage dashboard."
        ),
        "apply_after": "2026-08-22",
        "freeze_lifted": True,
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
