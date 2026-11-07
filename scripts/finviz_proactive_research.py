#!/usr/bin/env python3
"""finviz_proactive_research.py — use Finviz for PROACTIVE research beyond screeners.

The screener runner discovers tickers; finviz_news.py can pull per-ticker headlines but was only ever
reactive (per-symbol on demand). This runs Finviz's Elite news_export proactively across the whole watch
universe (held + active watchlist + research-discovery candidates), persisting fresh headlines into
news_articles (source='finviz_news') so Finviz is a standing catalyst/research source — not just a screen.

Uses the same FINVIZ_API_TOKEN as the screeners (no extra creds). Deduped by source_url. Advisory.

  python3 scripts/finviz_proactive_research.py [--max 150] [--lookback-hours 72] [--dry-run]
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LANE_ID = "finviz-proactive-research"
_ENV_KEYS = frozenset({"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "FINVIZ_API_TOKEN"})
#: A symbol Finviz can carry news for. The DB holdings document also lists identifiers a feed never tags
#: (CUSIPs such as 543354104, fund ids), and counting those as "held coverage" would overstate the book.
_RESEARCH_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}(?:\.[A-Z]{1,2})?$")


def _load_env():
    from dotenv import dotenv_values
    for name, value in dotenv_values(ROOT / ".env").items():
        if name in _ENV_KEYS and value is not None:
            os.environ.setdefault(name, value)


def _get_conn():
    from db_adapter import _get_conn as connect
    return connect()


def is_duplicate(*args, **kwargs):
    from lib.writers.news_articles_writer import is_duplicate as check
    return check(*args, **kwargs)


def write_news_articles(*args, **kwargs):
    from lib.writers.news_articles_writer import write_news_articles as write
    return write(*args, **kwargs)


def _holdings_symbols() -> tuple[list[str], str]:
    """Held symbols, DB first.

    The database is the holdings system of record (operator 2026-11-03); ``holdings.json`` is the
    documented fallback and its use is REPORTED, never silent. The old reader opened the file inside a bare
    ``except Exception: pass``, so a missing or unreadable file silently dropped every holding from the
    universe — the names most worth proactive coverage.
    """
    try:
        from lib.holdings_document import load_document
        doc = load_document()
        rows = doc.get("holdings") or []
        syms = [str(h.get("symbol", "")).upper() for h in rows
                if isinstance(h, dict) and h.get("symbol") and not h.get("is_cash")]
        return syms, str(doc.get("document_source") or "unknown")
    except Exception as exc:  # noqa: BLE001 -- the file below IS the documented fallback; the reason is reported
        reason = f"holdings_json_fallback:{type(exc).__name__}"
    try:
        hj = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        return ([str(h.get("symbol", "")).upper() for h in hj.get("holdings", [])
                 if h.get("symbol") and not h.get("is_cash")], reason)
    except Exception as exc:  # noqa: BLE001 -- reported as unavailable, not flattened to an empty book
        return [], f"holdings_unavailable:{type(exc).__name__}"


def _universe(cur, max_n, *, rotation=None):
    """Held + active watchlist + research-discovery candidates, and the coverage facts of the slice.

    Held names are never truncated: the book always gets proactive coverage, however large the watchlist.
    The rest of the cap is a ROTATING window over the alphabetically ordered watchlist (stable within a
    UTC hour, so a rerun in the same hour is reproducible), because a plain ``out[:max_n]`` permanently
    starved everything after "ALPX": 5,678 watchlist symbols against a 400 cap meant only the first 400
    ever saw a headline.
    """
    held, held_source = _holdings_symbols()
    researchable = [s for s in held if _RESEARCH_SYMBOL_RE.match(s)]
    unresearchable = [s for s in held if not _RESEARCH_SYMBOL_RE.match(s)]
    cur.execute("""SELECT DISTINCT symbol FROM watchlist_items
                   WHERE status <> 'removed' AND symbol ~ '^[A-Z]{1,5}$'
                   ORDER BY symbol""")
    watch = [r[0] for r in cur.fetchall()]
    seen, out = set(), []
    for s in researchable:
        if s and s not in seen:
            seen.add(s); out.append(s)
    holdings_n = len(out)
    stats = {"holdings": holdings_n, "holdings_used": min(holdings_n, max_n),
             "holdings_source": held_source, "watchlist_available": len(watch),
             "watchlist_used": 0, "truncated": len(watch), "rotation": 0,
             "held_without_ticker": len(unresearchable),
             "held_without_ticker_sample": unresearchable[:5]}
    if holdings_n >= max_n:
        return out[:max_n], stats
    watch = [w for w in watch if w not in seen]
    room = max_n - holdings_n
    if watch and room:
        k = (rotation if rotation is not None else int(time.time() // 3600)) % len(watch)
        watch = watch[k:] + watch[:k]
        stats["rotation"] = k
    out.extend(watch[:room])
    stats["watchlist_used"] = min(len(watch), room)
    stats["truncated"] = max(0, len(watch) - room)
    return out, stats


def run(max_n=150, lookback_hours=72, dry_run=False, summary=None):
    try:
        from finviz_news import fetch_finviz_stock_news_all
        from content_scoring import score_content, tag_content
    except Exception as e:
        print(f"ABORT: deps unavailable ({e})"); return 1
    conn = _get_conn(); cur = conn.cursor()
    universe_list, ustat = _universe(cur, max_n)
    universe = set(universe_list)
    # ONE request for all ticker-tagged Stock news, then distribute to the universe (a headline can tag
    # several tickers, e.g. "CVX,NOC,LMT" → saved once per universe ticker it mentions).
    allnews = fetch_finviz_stock_news_all(lookback_hours=lookback_hours)
    print(f"finviz proactive research: {len(allnews)} stock-news items vs {len(universe)}-symbol universe "
          f"({ustat['holdings_used']} held from {ustat['holdings_source']}, "
          f"{ustat['watchlist_used']} of {ustat['watchlist_available']} watchlist, "
          f"{ustat['truncated']} not covered this run, rotation {ustat['rotation']}) "
          f"({'DRY' if dry_run else 'LIVE'})")
    saved, skipped, covered = 0, 0, set()
    failed_writes = 0
    for it in allnews:
        head = (it.get("headline") or "")[:500]
        url = (it.get("url") or "")[:500]
        if not head or not url:
            continue
        hits = [t for t in it.get("tickers", []) if t in universe]
        for sym in hits:
            if is_duplicate(cur, sym, url, head):
                skipped += 1; continue
            covered.add(sym)
            if dry_run:
                saved += 1; continue
            try:
                from hermes_source_policy import should_ingest
                ok, _why = should_ingest("finviz_news")
                if not ok:
                    skipped += 1
                    continue
                sc = score_content(title=head, text="", source="finviz_news", symbols=[sym])
                tg = tag_content(text="", title=head)
                pub = datetime.fromtimestamp(int(it["datetime"]), tz=timezone.utc) if it.get("datetime") else None
                receipt = write_news_articles(cur, [{
                    # strategy_type is a STRATEGY classification (topic_curator, iris taxonomy,
                    # rag_retrieval all key on it). Writing the ticker here polluted 440 news rows and
                    # the catalyst rows built from them; left absent so the classifier owns its value.
                    "symbol": sym, "title": head, "summary": "",
                    "source": "finviz_news", "source_url": url, "published_at": pub,
                    "relevance_score": sc.get("relevance_score", 0.5),
                    "strategy_tags": json.dumps(tg.get("strategy_tags", [])),
                    "agent_tags": json.dumps(tg.get("agent_tags", [])),
                }], source="finviz_news")
                if not receipt.rows_written:
                    skipped += 1
                    continue
                saved += 1
            except Exception as e:
                failed_writes += 1
                conn.rollback(); print(f"  {sym}: save error {str(e)[:50]}"); continue
    if not dry_run:
        conn.commit()
    print(json.dumps({"news_items": len(allnews), "universe": len(universe),
                      "symbols_covered": len(covered), "saved": saved, "skipped_dup": skipped,
                      "universe_coverage": ustat,
                      "mode": "DRY" if dry_run else "LIVE"}, indent=2))
    if summary is not None:
        summary.update(news_items=len(allnews), universe=len(universe), symbols_covered=len(covered),
                       saved=saved, skipped_dup=skipped, failed_writes=failed_writes,
                       universe_coverage=ustat)
    return 0


def _universe_preview(max_n):
    """The universe the next live run would use, with its coverage facts — read-only, no provider call."""
    conn = _get_conn(); cur = conn.cursor()
    try:
        symbols, stats = _universe(cur, max_n)
    finally:
        conn.close()
    return symbols, stats


def main(argv=None):
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--max", type=int, default=150)
    ap.add_argument("--lookback-hours", type=int, default=72)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preview-universe", action="store_true",
                    help="print the universe the next live run would use (read-only DB read; dry run is static)")
    args = ap.parse_args(argv)
    if args.preview_universe and not args.dry_run:
        # The evidence path: read the universe (holdings from the DB document + the watchlist window), no
        # provider call, no write. Kept separate from --dry-run because the preview must stay offline-only
        # (tests/test_refactor_shard_04_20261011.py: a preview that opens a socket or .env is a defect).
        print(f"PREVIEW {LANE_ID}: universe the next live run would use (max {args.max}, no fetch, no write)")
        try:
            symbols, stats = _universe_preview(args.max)
        except Exception as exc:  # noqa: BLE001 -- a preview that cannot read the universe must say so
            print(f"PREVIEW {LANE_ID}: universe unavailable ({type(exc).__name__}: {exc})")
            return 1
        print(json.dumps({"lane": LANE_ID, "mode": "PREVIEW", "max": args.max,
                          "universe_size": len(symbols), "coverage": stats,
                          "held_in_universe": symbols[:stats["holdings_used"]],
                          "writes": "none"}, indent=2))
        return 0
    if args.dry_run:
        # Offline dry run: states what the live arm would do, touching no DB, no .env and no provider.
        print(f"DRY-RUN {LANE_ID}: would ingest Finviz headlines for up to {args.max} research symbols")
        print(json.dumps({
            "lane": LANE_ID, "mode": "DRY", "max": args.max,
            "lookback_hours": args.lookback_hours,
            "universe": "held symbols first (DB holdings document, holdings.json fallback) + a rotating "
                        "watchlist window to fill --max; held names are never truncated",
            "would_fetch": f"one Finviz stock-news request, lookback {args.lookback_hours}h",
            "would_write": "news_articles rows for universe tickers the provider tags (no strategy_type)",
            "writes": "none", "reads": "none (use --preview-universe for the universe facts)"}, indent=2))
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    summary = {}
    try:
        _load_env()
        rc = run(max_n=args.max, lookback_hours=args.lookback_hours, dry_run=False, summary=summary)
    except Exception as exc:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                           script="finviz_proactive_research.py", error=f"{type(exc).__name__}: {exc}",
                           output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    # Keep the established soft-error exit behavior, but do not advance output proof after failed writes.
    failed = rc != 0 or bool(summary.get("failed_writes"))
    write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                       script="finviz_proactive_research.py", summary=summary,
                       error="write_failed" if summary.get("failed_writes") else ("run_failed" if rc else None),
                       output=lane_output(summary, rc))
    return rc


def lane_output(summary: dict, rc: int) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: news_articles rows saved for universe tickers).
    attempted = universe-ticker hits considered (saved + duplicate/policy skips + failed writes); no new headline =
    ``no_new_input``; run() returning 1 (news/scoring modules unavailable) = ``dependency_unavailable``."""
    saved, dup, failed = (int(summary.get(k) or 0) for k in ("saved", "skipped_dup", "failed_writes"))
    skipped = {"duplicate_or_policy": dup, "write_failed": failed}
    if rc:
        skipped["dependency_unavailable"] = 1
    return {"produced_count": saved, "attempted_count": saved + dup + failed, "skipped_reasons": skipped,
            "empty_reason": "no_new_input" if saved == 0 and not rc else None}


if __name__ == "__main__":
    raise SystemExit(main())
