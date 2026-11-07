#!/usr/bin/env python3
"""finviz_proactive_research.py — use Finviz for PROACTIVE research beyond screeners.

The screener runner discovers tickers; finviz_news.py can pull per-ticker headlines but was only ever
reactive (per-symbol on demand). This runs Finviz's Elite news_export proactively across the whole watch
universe (held + active watchlist + research-discovery candidates), persisting fresh headlines into
news_articles (source='finviz_news') so Finviz is a standing catalyst/research source — not just a screen.

Uses the same FINVIZ_API_TOKEN as the screeners (no extra creds). Deduped by source_url. Advisory.

The cap and the lookback default to ``config/finviz_proactive_research.json`` — a reviewed value rather
than a constant in this file — and ``--max`` / ``--lookback-hours`` still win for an operator one-off.

  python3 scripts/finviz_proactive_research.py [--max N] [--lookback-hours N] [--dry-run]
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LANE_ID = "finviz-proactive-research"
CONFIG_PATH = ROOT / "config" / "finviz_proactive_research.json"
UNIVERSE_STATE_REL = "data/runtime/finviz_proactive_research_universe.json"
#: The provider's own rows in news_articles: the only evidence that a symbol once produced a headline.
COVERAGE_SOURCE = "finviz_news"
#: The only selection this lane implements. Named in config so a config that asks for something else is a
#: refusal rather than a silent fall back to this behaviour.
SELECTION = "staleness_first"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ENV_KEYS = frozenset({"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "FINVIZ_API_TOKEN"})
#: A symbol Finviz can carry news for. The DB holdings document also lists identifiers a feed never tags
#: (CUSIPs such as 543354104, fund ids), and counting those as "held coverage" would overstate the book.
_RESEARCH_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}(?:\.[A-Z]{1,2})?$")


class ConfigUnavailable(RuntimeError):
    """The lane's own selection config is missing or unreadable.

    Falling back to a constant here would recreate the defect this selection replaces: an unreviewed default
    silently deciding how much of the watchlist a scheduled run looks at. An unknown cap is not a cap.
    """


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


def load_config(path=None) -> dict:
    """The lane's selection config, or :class:`ConfigUnavailable` naming what is wrong with it."""
    p = Path(path) if path is not None else CONFIG_PATH
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigUnavailable(f"config unreadable ({type(exc).__name__}): {p}") from exc
    except ValueError as exc:
        raise ConfigUnavailable(f"config is not JSON ({type(exc).__name__}): {p}") from exc
    if not isinstance(cfg, dict):
        raise ConfigUnavailable(f"config is not a JSON object: {p}")
    for key, default in (("max_symbols", None), ("lookback_hours", 12)):
        value = cfg.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigUnavailable(f"config {key} must be a positive integer, got {value!r}: {p}")
    selection = cfg.get("selection", SELECTION)
    if selection != SELECTION:
        raise ConfigUnavailable(f"config selection {selection!r} is not one this lane implements "
                                f"({SELECTION!r}): {p}")
    return cfg


def resolve_window(cli_max, cli_lookback) -> tuple[int, int, str, str]:
    """``(max_n, lookback_hours, max_source, lookback_source)`` — the config is the default, a flag wins."""
    cfg = load_config()
    max_n = int(cli_max) if cli_max is not None else int(cfg["max_symbols"])
    lookback = int(cli_lookback) if cli_lookback is not None else int(cfg["lookback_hours"])
    return (max_n, lookback, "cli" if cli_max is not None else "config",
            "cli" if cli_lookback is not None else "config")


def _as_utc(value):
    """A timezone-aware UTC datetime, or None for "no evidence" (never flattened into a 1970 timestamp)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _last_asked(symbol, covered_at, attempts):
    """When this lane last asked the provider about ``symbol``: the newest of its row and its attempt.

    The attempt record is what makes the sweep advance. Finviz tags a handful of names a day, so 5,538 of the
    5,679 active watchlist symbols have never produced a row (measured 2026-11-07); ordering on coverage alone
    would hand the same first window to every run for ever.
    """
    known = [d for d in (covered_at, attempts.get(symbol)) if d is not None]
    return max(known) if known else _EPOCH


def _attempts_path() -> Path:
    """Beside the lane's own receipts, so the state root is resolved exactly once, the same way."""
    from lib.lane_last_receipt import runtime_dir
    return Path(runtime_dir()) / "finviz_proactive_research_universe.json"


def load_attempts(path=None) -> tuple[dict, str]:
    """``({symbol: last_asked_at}, source)``; source is ``ok`` / ``absent`` / ``malformed`` / ``unreadable:*``.

    A store this lane cannot read must not read as "never asked anybody": that would silently re-run the oldest
    alphabet and, worse, hide the fact. The caller reports the source instead of relying on the empty dict.
    """
    p = Path(path) if path is not None else _attempts_path()
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "absent"
    except (OSError, ValueError) as exc:
        return {}, f"unreadable:{type(exc).__name__}"
    raw = payload.get("attempts") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {}, "malformed"
    out = {}
    for symbol, stamp in raw.items():
        when = _as_utc(stamp)
        if when is not None:
            out[str(symbol)] = when
    return out, "ok"


def record_attempts(symbols, *, previous=None, path=None, now=None) -> tuple[str, str]:
    """Mark the symbols this run asked the provider about. Returns ``(status, detail)`` and never raises.

    A run whose news rows are already committed must not fail on its own bookkeeping; the caller reports the
    status, so a store that cannot be written says so instead of quietly re-covering the same window.
    """
    p = Path(path) if path is not None else _attempts_path()
    stamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    merged = {str(sym): when.isoformat() for sym, when in (previous or {}).items()}
    merged.update({str(sym): stamp for sym in symbols})
    payload = {"schema": "FinvizProactiveUniverse@v1", "lane_id": LANE_ID, "as_of": stamp,
               "attempts": dict(sorted(merged.items()))}
    try:
        from lib.atomic_json_store import atomic_write_json
        atomic_write_json(p, payload)
    except Exception as exc:  # noqa: BLE001 -- bookkeeping must not fail a run whose product is committed
        return "unwritten", f"{type(exc).__name__}: {exc}"
    return "ok", str(p)


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


def _universe(cur, max_n, *, attempts=None):
    """Held + active watchlist, and the coverage facts of the slice.

    Held names come first and are never truncated: the book always gets proactive coverage, however large the
    watchlist. The rest of the cap is filled STALENESS-FIRST — the symbols this lane has gone longest without
    asking the provider about, never-asked first — so a 5,679-symbol watchlist against a 400 cap is swept
    window by window instead of re-reading whichever 400 sort first. Three defects died here:

    * ``watchlist_items ORDER BY symbol`` + ``out[:400]``: nothing after "ALPX" was ever covered (LQ-52);
    * hour rotation, which advanced the window by ONE symbol per hour — a full sweep took ~1,419 days at four
      runs a weekday, which is rotation in name only (LQ-211);
    * a cap that lived in two hard-coded argv lists rather than in a reviewed config value (LQ-211).
    """
    held, held_source = _holdings_symbols()
    researchable = [s for s in held if _RESEARCH_SYMBOL_RE.match(s)]
    unresearchable = [s for s in held if not _RESEARCH_SYMBOL_RE.match(s)]
    cur.execute("""SELECT w.symbol, c.last_at
                     FROM (SELECT DISTINCT symbol FROM watchlist_items
                            WHERE status <> 'removed' AND symbol ~ '^[A-Z]{1,5}$') w
                     LEFT JOIN (SELECT symbol, max(created_at) AS last_at
                                  FROM news_articles WHERE source = %s GROUP BY symbol) c
                       ON c.symbol = w.symbol
                     ORDER BY w.symbol""", (COVERAGE_SOURCE,))
    covered: dict = {}
    for row in cur.fetchall() or []:
        covered[str(row[0])] = _as_utc(row[1] if len(row) > 1 else None)
    seen, out = set(), []
    for s in researchable:
        if s and s not in seen:
            seen.add(s); out.append(s)
    holdings_n = len(out)
    attempted = attempts or {}
    watch = [(sym, when) for sym, when in covered.items() if sym not in seen]
    watch.sort(key=lambda item: (_last_asked(item[0], item[1], attempted), item[0]))
    stats = {"holdings": holdings_n, "holdings_used": min(holdings_n, max_n),
             "holdings_source": held_source, "watchlist_available": len(watch),
             "watchlist_used": 0, "truncated": len(watch), "selection": SELECTION,
             "never_covered": sum(1 for _s, when in watch if when is None),
             "never_attempted": sum(1 for sym, _w in watch if sym not in attempted),
             "window_asked_at": None, "next_in_line": None,
             "held_without_ticker": len(unresearchable),
             "held_without_ticker_sample": unresearchable[:5]}
    if holdings_n >= max_n:
        stats["holdings_used"] = max_n
        return out[:max_n], stats
    room = max_n - holdings_n
    window = watch[:room]
    out.extend(sym for sym, _w in window)
    stats["watchlist_used"] = len(window)
    stats["truncated"] = max(0, len(watch) - len(window))
    if window:
        asked = _last_asked(*window[-1], attempted)
        stats["window_asked_at"] = None if asked == _EPOCH else asked.isoformat()
    if len(watch) > len(window):
        stats["next_in_line"] = watch[len(window)][0]
    return out, stats


def run(max_n, lookback_hours, dry_run=False, summary=None):
    try:
        from finviz_news import fetch_finviz_stock_news_all
        from content_scoring import score_content, tag_content
    except Exception as e:
        print(f"ABORT: deps unavailable ({e})"); return 1
    conn = _get_conn(); cur = conn.cursor()
    attempts, attempts_source = load_attempts()
    universe_list, ustat = _universe(cur, max_n, attempts=attempts)
    universe = set(universe_list)
    # ONE request for all ticker-tagged Stock news, then distribute to the universe (a headline can tag
    # several tickers, e.g. "CVX,NOC,LMT" → saved once per universe ticker it mentions).
    allnews = fetch_finviz_stock_news_all(lookback_hours=lookback_hours)
    print(f"finviz proactive research: {len(allnews)} stock-news items vs {len(universe)}-symbol universe "
          f"({ustat['holdings_used']} held from {ustat['holdings_source']}, "
          f"{ustat['watchlist_used']} of {ustat['watchlist_available']} watchlist, "
          f"{ustat['truncated']} not covered this run, staleness-first up to "
          f"{ustat['window_asked_at'] or 'never-asked'}, next {ustat['next_in_line'] or '-'}) "
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
        # The sweep cursor: every symbol this run asked the provider about, whether or not it produced a row.
        state, detail = record_attempts(universe_list, previous=attempts)
        if summary is not None:
            summary["universe_state"] = state
        if state != "ok":
            print(f"WARN {LANE_ID}: universe state not recorded ({detail}) — the next run re-covers the same "
                  f"{len(universe_list)} symbols first", file=sys.stderr)
    print(json.dumps({"news_items": len(allnews), "universe": len(universe),
                      "symbols_covered": len(covered), "saved": saved, "skipped_dup": skipped,
                      "universe_coverage": ustat, "universe_state_source": attempts_source,
                      "mode": "DRY" if dry_run else "LIVE"}, indent=2))
    if summary is not None:
        summary.update(news_items=len(allnews), universe=len(universe), symbols_covered=len(covered),
                       saved=saved, skipped_dup=skipped, failed_writes=failed_writes,
                       universe_coverage=ustat, universe_state_source=attempts_source)
    return 0


def _universe_preview(max_n):
    """The universe the next live run would use, with its coverage facts — read-only, no provider call."""
    attempts, attempts_source = load_attempts()
    conn = _get_conn(); cur = conn.cursor()
    try:
        symbols, stats = _universe(cur, max_n, attempts=attempts)
    finally:
        conn.close()
    stats["attempts_source"] = attempts_source
    stats["attempts_known"] = len(attempts)
    return symbols, stats


def main(argv=None):
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--max", type=int, default=None,
                    help="cap on the research universe (default: config/finviz_proactive_research.json "
                         "max_symbols)")
    ap.add_argument("--lookback-hours", type=int, default=None,
                    help="provider lookback window (default: the lane config's lookback_hours)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preview-universe", action="store_true",
                    help="print the universe the next live run would use (read-only DB read; dry run is static)")
    args = ap.parse_args(argv)
    try:
        max_n, lookback, max_source, lookback_source = resolve_window(args.max, args.lookback_hours)
        config_error = None
    except ConfigUnavailable as exc:
        # A flag can still supply the value the config could not; the run only fails if one is missing.
        config_error = str(exc)
        max_n, lookback = args.max, args.lookback_hours
        max_source = "cli" if args.max is not None else "unavailable"
        lookback_source = "cli" if args.lookback_hours is not None else "unavailable"
    if args.preview_universe and not args.dry_run:
        # The evidence path: read the universe (holdings from the DB document + the watchlist window), no
        # provider call, no write. Kept separate from --dry-run because the preview must stay offline-only
        # (tests/test_refactor_shard_04_20261011.py: a preview that opens a socket or .env is a defect).
        if max_n is None:
            print(f"PREVIEW {LANE_ID}: universe unavailable (config): {config_error}")
            return 1
        print(f"PREVIEW {LANE_ID}: universe the next live run would use (max {max_n} from {max_source}, "
              f"no fetch, no write)")
        try:
            symbols, stats = _universe_preview(max_n)
        except Exception as exc:  # noqa: BLE001 -- a preview that cannot read the universe must say so
            print(f"PREVIEW {LANE_ID}: universe unavailable ({type(exc).__name__}: {exc})")
            return 1
        print(json.dumps({"lane": LANE_ID, "mode": "PREVIEW", "max": max_n, "max_source": max_source,
                          "universe_size": len(symbols), "coverage": stats,
                          "held_in_universe": symbols[:stats["holdings_used"]],
                          "writes": "none"}, indent=2))
        return 0
    if args.dry_run:
        # Offline dry run: states what the live arm would do, touching no DB, no .env and no provider.
        print(f"DRY-RUN {LANE_ID}: would ingest Finviz headlines for up to "
              f"{max_n if max_n is not None else 'an unresolvable number of'} research symbols")
        if config_error:
            print(f"DRY-RUN {LANE_ID}: config unavailable ({config_error}) — a live run would refuse, not "
                  f"fall back to a default cap")
        print(json.dumps({
            "lane": LANE_ID, "mode": "DRY",
            "max": max_n if max_n is not None else "unavailable", "max_source": max_source,
            "lookback_hours": lookback if lookback is not None else "unavailable",
            "lookback_source": lookback_source,
            "universe": "held symbols first (DB holdings document, holdings.json fallback) + watchlist symbols "
                        "this lane asked about least recently, never-asked first, to fill --max; held names "
                        "are never truncated",
            "would_fetch": f"one Finviz stock-news request, lookback {lookback if lookback is not None else '?'}h",
            "would_write": "news_articles rows for universe tickers the provider tags (no strategy_type), then "
                           "the sweep cursor in data/runtime/finviz_proactive_research_universe.json",
            "writes": "none", "reads": "none (use --preview-universe for the universe facts)"}, indent=2))
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    summary = {}
    if max_n is None or lookback is None:
        print(f"CONFIG UNAVAILABLE {LANE_ID}: {config_error}", file=sys.stderr)
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                           script="finviz_proactive_research.py",
                           error=f"ConfigUnavailable: {config_error}",
                           output={"produced_count": 0, "attempted_count": 0,
                                   "skipped_reasons": {"dependency_unavailable": 1}})
        return 1
    try:
        _load_env()
        rc = run(max_n=max_n, lookback_hours=lookback, dry_run=False, summary=summary)
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
