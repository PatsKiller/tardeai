#!/usr/bin/env python3
"""Hermes news bridge (2026-06-04) — Prompt #2.

Bridges Hermes's discovered, ticker-level news (hermes_research_intelligence) into the
TradeAI catalyst path by inserting into news_articles with source='hermes'. The already-
repaired chain then takes over: news_to_catalyst.py classifies these into catalyst_events,
and signal_fusion.py consumes them. No Docker crossing — both ends are the shared Postgres.

HERMES WALL: this job is READ-ONLY on hermes_* tables. It writes ONLY news_articles (the
TradeAI catalyst feed). It never writes back to Hermes-controlled tables or any trading table.

Dedup is tracked on the TradeAI side: each bridged row carries raw_payload.hermes_research_id,
and we skip Hermes rows already bridged. Downstream, catalyst_events(symbol,headline) is unique,
so a Hermes article duplicating an existing one cannot create a duplicate catalyst.

Usage:
  python3 scripts/hermes_news_bridge.py [--limit 200] [--lookback-hours 48] [--json] [--dry-run]

--dry-run runs the same candidate SELECT and scoring on a READ ONLY session and returns BEFORE
write_news_articles / commit are reachable, listing what it would bridge (the writer's own dedupe
is not evaluated, so "would_bridge" is an upper bound). A real run writes
data/runtime/hermes_news_bridge_last.json (LaneRunReceipt@v1; ok_at only on success) under the
persistent state root and exits 1 when the run failed or every insert attempt errored.

2026-11-07 (LQ-20261107-112): the lane reported ``no_new_input``/OK on every run from 2026-10-29 to
2026-11-07 while writing nothing at all — its upstream (research_type='momentum_catalyst' rows from
catalyst_momentum_engine, whose SearXNG news engines were unresponsive) had died, and a per-run zero
is a legitimate, allowed empty. The contract already declares the answer — N8nExpectedOutput
``per_window``, min_produced 1, window_h 48 — so the run now also reads its own window from the
output store (``hermes_rows_in_window``) and fails with ``no_input_in_window`` (plus a fatal
``dependency_unavailable`` skip) when nothing at all has been produced inside it. Per-run zeros stay
``no_new_input``; a 48 h zero becomes RUN_FAILED ``empty_output`` at the executor.

2026-11-08 (LQ-20261107-1330): ``no_new_input`` was still a lie in the one case that reads as it: run
d:hermes-news-bridge:live:20261108T1840 read 2 candidates, the writer skipped both as clean duplicates
(``skipped_reasons = {duplicate: 2, insert_error: 0}``), and the receipt said ``no_new_input`` — the lane
had input and said it had none. A zero whose every attempted row was a duplicate now says
``all_duplicate``: a reviewed idle token (config/run_quality_idle_reasons.json) and an allowed empty
reason in the lane's contract, so the truthful reason does not turn the run red. A zero with no
candidate at all stays ``no_new_input``.
"""
import os, sys, json
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from lib.writers.news_articles_writer import write_news_articles  # noqa: E402  (the store's one write path)
# Ticker-level Hermes research worth treating as catalyst news. research_backlog is
# topic-level (no symbol) and excluded; thesis_challenge/youtube can be added later.
BRIDGE_TYPES = ("momentum_catalyst",)
RECEIPT_NAME = "hermes_news_bridge"
LANE_ID = "hermes-news-bridge"
# The lane's N8nExpectedOutput window (config/n8n_health_contracts.json: rule per_window, min_produced 1,
# window_h 48). Per run a zero is legitimate and allowed as ``no_new_input``; across the window it is not.
WINDOW_HOURS = 48
WINDOW_EMPTY_REASON = "no_input_in_window"
WINDOW_UNKNOWN_REASON = "window_unreadable"
# LQ-20261107-1330: the run read candidates and every one was already bridged — input existed, so
# ``no_new_input`` is false. Reviewed idle token AND allowed empty reason in the lane's contract.
ALL_DUPLICATE_REASON = "all_duplicate"


# Names this bridge reads. The env file also holds broker credentials; those are not copied.
_ENV_KEYS = frozenset({"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"})


def load_env():
    p = os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    for line in open(p):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k in _ENV_KEYS:
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def _first_url(source_urls_json):
    try:
        v = source_urls_json
        if isinstance(v, str):
            v = json.loads(v)
        if isinstance(v, list) and v:
            return str(v[0])[:1000]
        if isinstance(v, dict) and v:
            return str(next(iter(v.values())))[:1000]
    except Exception:
        pass
    return None


def _strategy_type(strategy_tags):
    try:
        v = strategy_tags
        if isinstance(v, str):
            v = json.loads(v)
        if isinstance(v, list) and v:
            return str(v[0])[:60]
    except Exception:
        pass
    return None


def hermes_rows_in_window(cur, hours=WINDOW_HOURS):
    """Rows this lane really produced inside its contract window, read from the store (source='hermes').

    The per-run counters below cannot see a feed that has been dead for days: with no candidates every run
    reports ``no_new_input``, which the contract allows, so the lane looks green while producing nothing
    (2026-10-29 -> 2026-11-07: 0 rows for 9 days, every run DONE in 0.2 s). The window is the rule the
    contract already declares; this reads it from the output store instead of trusting this run's zero.

    Returns the count and never a default: ``count(*)`` cannot be NULL, so an empty or NULL reply means the
    read itself is broken. "Unknown" must not arrive at the caller as 0 — that would report a dead feed as
    the answer instead of a broken query.
    """
    cur.execute("SELECT count(*) FROM news_articles "
                "WHERE source = 'hermes' AND created_at > now() - interval '%s hours'", (int(hours),))
    row = cur.fetchone()
    if not row or row[0] is None:
        raise RuntimeError("news_articles source='hermes' window count returned no value")
    return int(row[0])


def run(limit=200, lookback_hours=48, as_json=False, dry_run=False):
    load_env()
    conn = db()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)
    cur = conn.cursor()
    types = ",".join("%s" for _ in BRIDGE_TYPES)
    # READ-ONLY on hermes_*; only ticker-level rows not already bridged into news_articles.
    cur.execute(  # nosemgrep: tq-py-sql-fstring -- types is only '%s' placeholders; values are params
        f"""
        SELECT h.id, h.symbol, h.topic, h.summary, h.source_urls_json,
               h.confidence_score, h.freshness_date, h.created_at, h.research_type, h.strategy_tags
        FROM hermes_research_intelligence h
        WHERE h.symbol IS NOT NULL AND h.symbol <> ''
          AND h.topic IS NOT NULL AND h.topic <> ''
          AND h.research_type IN ({types})
          AND h.created_at > now() - %s * interval '1 hour'
          AND NOT EXISTS (
              SELECT 1 FROM news_articles n
              WHERE n.source = 'hermes'
                AND (n.raw_payload->>'hermes_research_id') = h.id::text
          )
        ORDER BY h.created_at DESC
        LIMIT %s
    """, list(BRIDGE_TYPES) + [lookback_hours, limit])
    rows = cur.fetchall()

    bridged, skipped_dup, insert_errors = [], 0, 0
    would = []
    for hid, symbol, topic, summary, urls, conf, fresh, created, rtype, stags in rows:
        title = str(topic)[:500]
        # Dedupe is the write module's rule (same symbol + same source_url or title);
        # a duplicate writes nothing and is counted from the receipt below.
        # Rating alignment (2026-06-04): score Hermes-ingested articles with the SAME framework
        # TradeAI's news_ingestion uses (content_scoring.score_content) so all news_articles share
        # one relevance/quality scale, regardless of which engine ingested them. Hermes's own
        # confidence is kept in raw_payload for provenance, not used as the relevance score.
        try:
            from content_scoring import score_content
            scored = score_content(title, str(summary or ""), source="hermes", symbols=[symbol] if symbol else None)
        except Exception:
            scored = {"relevance_score": (float(conf) if conf is not None else 0.5),
                      "quality_score": None, "validation_status": "unscored"}
        payload = {"hermes_research_id": hid, "research_type": rtype,
                   "bridged_by": "hermes_news_bridge.py",
                   "bridged_at": datetime.now(timezone.utc).isoformat(),
                   "hermes_confidence": (round(float(conf), 3) if conf is not None else None),
                   "quality_score": scored.get("quality_score"),
                   "validation_status": scored.get("validation_status")}
        if dry_run:
            would.append({"hermes_id": hid, "symbol": symbol, "title": title[:50], "type": rtype,
                          "relevance_score": round(float(scored.get("relevance_score") or 0.0), 3)})
            continue
        try:
            receipt = write_news_articles(cur, [{
                "symbol": symbol, "strategy_type": _strategy_type(stags), "title": title,
                "summary": (str(summary)[:1000] if summary else None), "source": "hermes",
                "source_url": _first_url(urls), "published_at": (fresh or created),
                "relevance_score": round(float(scored.get("relevance_score") or 0.0), 3),
                "raw_payload": json.dumps(payload),
            }], source="hermes")
            if not receipt.rows_written:
                skipped_dup += 1
                continue
            new_id = receipt.ids[0]
            bridged.append({"news_id": new_id, "hermes_id": hid, "symbol": symbol,
                            "title": title[:50], "type": rtype})
        except Exception as e:
            conn.rollback()
            insert_errors += 1
            print(f"  [bridge] {symbol}: insert error — {str(e)[:90]}")
            continue
    if dry_run:
        conn.close()
        report = {"run_at": datetime.now(timezone.utc).isoformat(), "dry_run": True,
                  "candidates": len(rows), "would_bridge": len(would), "rows": would[:20]}
        if as_json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"[hermes-bridge] DRY RUN: {len(rows)} candidates, would attempt {len(would)} "
                  f"news_articles inserts (writer dedupe not evaluated); nothing written")
            for w in would[:15]:
                print(f"  {w['symbol']:>8} | {w['type']:<18} | would bridge hermes#{w['hermes_id']}")
        return report
    conn.commit()
    # Read AFTER the commit so this run's own inserts count; read-only, and it is the only number that can
    # see a feed that has been dead for longer than one run.
    window_rows = hermes_rows_in_window(cur)
    report = {"run_at": datetime.now(timezone.utc).isoformat(),
              "candidates": len(rows), "bridged": len(bridged),
              "skipped_dup": skipped_dup, "insert_errors": insert_errors,
              "window_hours": WINDOW_HOURS, "window_rows": window_rows, "rows": bridged[:20]}
    conn.close()
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"[hermes-bridge] {len(bridged)} bridged, {skipped_dup} dup-skipped, "
              f"{len(rows)} candidates; source=hermes rows in the last {WINDOW_HOURS} h: {window_rows}")
        for b in bridged[:15]:
            print(f"  {b['symbol']:>8} | {b['type']:<18} | news#{b['news_id']} <- hermes#{b['hermes_id']}")
    return report


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 200
    lookback = int(a[a.index("--lookback-hours") + 1]) if "--lookback-hours" in a else 48
    if "--dry-run" in a:
        run(limit=limit, lookback_hours=lookback, as_json="--json" in a, dry_run=True)
        return 0
    from lib.lane_last_receipt import now_iso, receipt_path, write_lane_receipt

    # The receipt keeps its established path (data/runtime/hermes_news_bridge_last.json); its lane id is the n8n
    # lane's, so the per-attempt copy lands where the executor reads it (lane_attempts/hermes-news-bridge/<run_id>).
    def write_receipt(_name, **kw):
        return write_lane_receipt(LANE_ID, path=receipt_path(RECEIPT_NAME), script=RECEIPT_NAME, **kw)

    started = now_iso()
    try:
        rep = run(limit=limit, lookback_hours=lookback, as_json="--json" in a)
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started,
                      output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        print(f"[hermes-bridge] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    summary = {k: rep[k] for k in ("candidates", "bridged", "skipped_dup", "insert_errors")}
    # Unknown is not zero: if the window count did not come back, the contract's per_window rule was not
    # verified, so the run fails with that sentence instead of claiming either outcome.
    window_rows = rep.get("window_rows")
    window_unknown = window_rows is None
    # Every attempted insert errored (none bridged, none a clean dup-skip): the run did not work.
    inserts_failed = rep["insert_errors"] > 0 and rep["bridged"] == 0 and rep["skipped_dup"] == 0
    # The contract's window rule (per_window 48 h, min_produced 1): zero output across the whole window is a
    # failure even though zero output in one run is allowed as no_new_input. This is the 2026-10-29..11-07 hole.
    window_empty = (not window_unknown) and int(window_rows) == 0
    failed = inserts_failed or window_empty or window_unknown
    if window_unknown:
        error = (f"the source=hermes window count could not be read, so the contract's per_window rule "
                 f"({WINDOW_HOURS} h, min_produced=1) is unverified for this run")
    elif window_empty:
        error = (f"no source=hermes rows in the last {WINDOW_HOURS} h (contract per_window min_produced=1): "
                 f"the bridge runs but its input feed produces nothing; {rep['candidates']} candidates this run")
    elif inserts_failed:
        error = "every news_articles insert errored"
    else:
        error = None
    outcome, reason = receipt_outcome(summary, failed=failed, window_unknown=window_unknown, window_empty=window_empty,
                                      inserts_failed=inserts_failed)
    write_receipt(RECEIPT_NAME, ok=not failed, summary=summary, started_at=started, error=error,
                  output=lane_output(summary, window_rows=window_rows), outcome=outcome, outcome_reason=reason)
    if failed:
        print(f"[hermes-bridge] FAILED: {error}", file=sys.stderr)
    return 1 if failed else 0


def _all_duplicate(summary: dict) -> bool:
    """The run read at least one candidate and every one was a clean duplicate skip (LQ-20261107-1330).

    ``candidates`` is how many rows the SELECT returned — each then ends bridged, dup-skipped or errored —
    so "every skip is a duplicate" is ``skipped_dup == attempted``, with nothing bridged. An insert error
    is not a duplicate and keeps the run on the old reason: a mixed zero is not "nothing new".
    """
    bridged = int(summary["bridged"])
    attempted = max(int(summary["candidates"]), bridged)
    return (bridged == 0 and attempted > 0 and int(summary["skipped_dup"]) == attempted
            and int(summary["insert_errors"]) == 0)


def receipt_outcome(summary: dict, *, failed: bool, window_unknown: bool, window_empty: bool,
                    inserts_failed: bool) -> tuple[str, str]:
    """ok | empty | error (LQ-192). An unreadable window, a dead feed window or all-failed inserts are ERRORS;
    nothing new to bridge is a true empty."""
    if window_unknown:
        return "error", "window_count_unreadable"
    if window_empty:
        return "error", "no_source_rows_in_window"
    if inserts_failed:
        return "error", "every_insert_errored"
    if failed:
        return "error", "run_failed"
    if int(summary["bridged"]) != 0:
        return "ok", "bridged"
    # LQ-20261107-1330: the top-level outcome reason must agree with output.empty_reason — one receipt
    # stating two different reasons for the same zero is how "no_new_input" survived on a run that read two.
    return "empty", (ALL_DUPLICATE_REASON if _all_duplicate(summary) else "no_new_input")


def lane_output(summary: dict, window_rows=None) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: news_articles rows inserted, source=hermes).
    attempted = unbridged Hermes research rows read; no candidate at all = ``no_new_input``, which the
    contract allows PER RUN. A run that read candidates and skipped every one as a duplicate is
    ``all_duplicate`` (LQ-20261107-1330): it had input, so ``no_new_input`` was false. ``window_rows == 0``
    is the different, failing case: nothing at all has been produced across the contract window, so the
    empty reason is ``no_input_in_window`` (not allowed) and the upstream dependency is recorded as a fatal
    skip. ``window_rows is None`` (unreadable) is its own reason, never folded into zero."""
    bridged = int(summary["bridged"])
    empty = bridged == 0
    window_unknown = window_rows is None
    window_empty = (not window_unknown) and int(window_rows) == 0
    skipped = {"duplicate": int(summary["skipped_dup"]),
               "insert_error": int(summary["insert_errors"])}
    if window_empty or window_unknown:
        skipped["dependency_unavailable"] = 1
    if window_empty:
        empty_reason = WINDOW_EMPTY_REASON
    elif window_unknown:
        empty_reason = WINDOW_UNKNOWN_REASON
    elif _all_duplicate(summary):
        empty_reason = ALL_DUPLICATE_REASON
    else:
        empty_reason = "no_new_input"
    return {"produced_count": bridged, "attempted_count": max(int(summary["candidates"]), bridged),
            "skipped_reasons": skipped,
            "empty_reason": empty_reason if empty else None}


if __name__ == "__main__":
    sys.exit(main())
