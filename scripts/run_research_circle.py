#!/usr/bin/env python3
"""Run one Research Escalation Circle lap on an operator question. Dry run by default.

    python scripts/run_research_circle.py --question "why is ELMT up today" --symbol ELMT
    python scripts/run_research_circle.py --question "..." --symbol HPE --analyzer deepseek   # model verdict
    python scripts/run_research_circle.py --question "..." --symbol HPE --apply                # write the ledger

Dry run: reads the free channels (Trade-AI house dossier, Yahoo Finance, SEC rows already ingested, SearXNG),
scores the lap, runs the Context Analyzer (deterministic unless --analyzer deepseek), prints the verdict and the
check-in it would schedule, and writes nothing. --apply appends the lifecycle and check-in rows.
Never sends a message. AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.lib import cio_goal_need_ledger as ngl  # noqa: E402
from scripts.lib import research_circle as rc  # noqa: E402

NO_CONSUMER_REASON = "operator/engineer entry point for the research circle; the desk wires it in Phase 2"


def _db_query(sql: str, params: tuple) -> list[dict]:
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    def setting(k, d=""):
        v = os.getenv(k, "")
        if v:
            return v
        try:
            for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{k}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
        return d
    conn = psycopg2.connect(host=setting("DB_HOST", "localhost"), dbname=setting("DB_NAME", "trade_ai"),
                            user=setting("DB_USER", "trade_ai"), password=setting("DB_PASSWORD"),
                            options="-c default_transaction_read_only=on", connect_timeout=5)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _house_channel(symbol: str, question: str):
    """Trade-AI stores through the desk's own gatherer (no model, no send)."""
    def _fn() -> list[rc.Evidence]:
        from scripts.lib import cio_operator_desk_loop as desk  # noqa: PLC0415

        intent = desk.analyze_operator_intent(question)
        intent.setdefault("text", question)
        ev = desk.gather_tradeai_evidence(intent)
        avail = ev.get("available") or {}
        out: list[rc.Evidence] = []
        text = avail.get("subject_dossier_text") or ""
        kind_of = {"Analysts": "analyst", "Earnings": "catalyst", "Catalysts": "catalyst", "News": "news",
                   "Research": "research", "Thesis": "thesis", "Company": "profile", "Sector": "profile",
                   "Industry": "profile", "Position": "profile"}
        for line in text.splitlines():
            for label, kind in kind_of.items():
                if f"· {label} (" in line or f" {label} (" in line:
                    # as_of is the date the line itself states; an undated line counts as stale, never as today.
                    out.append(rc.Evidence(kind, f"trade_ai:{label.lower()}", line.split(":", 1)[-1].strip()[:400],
                                           as_of=rc.stated_date(line), symbol=symbol, channel="house"))
                    break
        price = (avail.get("subject_price") or {}).get(symbol) or {}
        if price.get("close"):
            out.append(rc.Evidence("quote", "trade_ai:ticker_prices", f"{symbol} close ${float(price['close']):,.2f}",
                                   as_of=str(price.get("date") or price.get("as_of") or ""), symbol=symbol,
                                   value=float(price["close"]), channel="house"))
        lv = (avail.get("subject_levels") or {}).get(symbol) or {}
        if lv:
            out.append(rc.Evidence("levels", "trade_ai:reentry_desk", f"{symbol} levels {json.dumps(lv, default=str)[:300]}",
                                   as_of=str(avail.get("subject_levels_as_of") or ""), symbol=symbol, channel="house"))
        return out
    return _fn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--chat-id", default="dry_run")
    ap.add_argument("--message-id", default="dry_run")
    ap.add_argument("--analyzer", choices=("deterministic", "deepseek"), default="deterministic")
    ap.add_argument("--no-web", action="store_true", help="skip SearXNG (and so the targeted second lap)")
    ap.add_argument("--max-laps", type=int, default=2)
    ap.add_argument("--apply", action="store_true", help="append lifecycle and check-in rows")
    ap.add_argument("--goal-id", default="", help="project each lap onto this goal's need ledger (P5)")
    ap.add_argument("--predicate-version", default=ngl.DEFAULT_PREDICATE_VERSION)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sym = args.symbol.upper()
    channels = {
        "house": _house_channel(sym, args.question),
        "yahoo": lambda: rc.yahoo_channel(sym),
        "sec": lambda: rc.sec_channel(sym, _db_query),
    }
    if not args.no_web:
        channels["searxng"] = lambda: rc.searxng_channel(f"{sym} stock {args.question}"[:180], symbol=sym)
    ledger = rc.Ledger(apply=args.apply)
    targeted = None if args.no_web else (lambda q: rc.searxng_channel(q, symbol=sym, limit=4))
    laps = rc.run_circle(args.question, chat_id=args.chat_id, message_id=args.message_id, symbols=[sym],
                         subject_guids={}, channels=channels, ledger=ledger, targeted=targeted,
                         call_model=rc.deepseek_flash_caller() if args.analyzer == "deepseek" else None,
                         max_laps=args.max_laps)
    res = laps[-1]
    # P5: project what each lap still does not know onto the goal's need ledger.
    # Nothing is re-scored here -- score_lap already decided, and these rows carry
    # its numbers. Same --apply gate as the lifecycle ledger: a dry run writes nothing.
    need_rows: list[dict] = []
    if args.goal_id:
        need_ledger = ngl.NeedLedger(apply=args.apply)
        for lap in laps:
            need_rows.append(need_ledger.record(
                args.goal_id, lap.score, lap=lap.lap, predicate_version=args.predicate_version,
                decision=lap.verdict, question_guid=lap.question_guid, subject_guids={}))
    if args.json:
        print(json.dumps({"laps": [lap.to_dict() for lap in laps], "need_ledger": need_rows},
                         indent=2, default=str))
        return 0
    print(f"question_guid {res.question_guid} · needs {res.needs}")
    for lap in laps:
        by_channel: dict[str, int] = {}
        for e in lap.evidence:
            by_channel[e.channel] = by_channel.get(e.channel, 0) + 1
        v = lap.verdict
        print(f"── lap {lap.lap}: evidence {len(lap.evidence)} by channel {by_channel} · channel errors "
              f"{lap.channel_errors or 'none'}")
        print(f"   score {lap.score['overall']} · per need "
              + ", ".join(f"{k}={s['score']}" for k, s in lap.score['per_need'].items())
              + f" · contradictions {len(lap.score['contradictions'])}")
        print(f"   verdict [{v.get('analyzer')}] decision={v.get('decision')} next={v.get('next_channel')} "
              f"maturity={v.get('maturity')} score={v.get('sufficiency_score')} "
              f"note={v.get('analyzer_note') or v.get('analyzer_override') or ''}")
    v = res.verdict
    if v.get("answer_summary"):
        print("summary:", v["answer_summary"])
    if v.get("missing_facts"):
        print("missing:", v["missing_facts"])
    if res.checkin:
        print(f"check-in {res.checkin['due_at']} ({res.checkin['days']} d) — {res.checkin['reason']}")
    for row in need_rows:
        print(f"need ledger {row['key']} · open {row['open_needs'] or 'none'} · digest {row['need_digest']} "
              f"· corroborated {row['corroboration'].get('corroborated')} "
              f"· {'written' if args.apply else 'DRY RUN, not written'}")
    print("lifecycle:", " → ".join(r["state"] for r in ledger.rows), "·", "written" if args.apply else "dry run, nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
