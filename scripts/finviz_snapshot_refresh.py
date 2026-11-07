#!/usr/bin/env python3
"""finviz_snapshot_refresh.py — refresh ``ticker_snapshot_daily`` and ``fundamental_data`` for one session close.

Why this exists (LQ-20261107-336, WP0a of the Market Event Re-entry spec).

``ticker_snapshot_daily`` stopped at 2026-11-03 because it has exactly one writer: stage 11 of
``portfolio_orchestrator.py``, which sits *behind* stage 1. Stage 1 died on 2026-11-04, 11-05 and 11-06 with

    AttributeError: 'NoneType' object has no attribute 'upper'   (portfolio_analyzer._get_sector)

— the Schwab sync writes ``asset_type: null`` and the analyzer called ``.upper()`` on it (FU-007, fixed in
``c072bb634``). The fix is on the integration line and serving, but the weekday 07:15 cron is the only thing
that ever calls the writer, so the three missing sessions are still missing: a code fix is not a backfill.

``fundamental_data`` is not broken at all: its only writer is ``external_market_data_ingest.py --fundamentals``
on ``0 8 * * 1`` — Mondays. On a Saturday it is a week old by design.

So this lane refreshes both for a named session close over an explicit universe — holdings, the active
watchlist, and the members of screener screens that have actually run recently. Finviz only: every value comes
from ``finviz_enrichment`` (the single Finviz writer) and the fundamentals are read back from the stored cache
through the data broker, so the fundamentals leg spends zero provider calls.

    python3 scripts/finviz_snapshot_refresh.py --dry-run [--snapshot-date 2026-11-06]
    python3 scripts/finviz_snapshot_refresh.py --apply   [--snapshot-date 2026-11-06]

A dry run reads, plans and writes nothing (AGENTS.md §6). ``--apply`` writes ``ticker_snapshot_daily`` rows,
``fundamental_data`` rows and one LaneRunReceipt@v2.

Two honesty rules this file is built around:

* ``db_adapter.save_ticker_snapshot_daily`` **swallows its own errors** (prints, rolls back, returns None), so a
  sent row count is not evidence. ``produced_count`` here is a READ-BACK: the rows that exist in the table for
  this snapshot_date and this run's symbols after the write.
* a cache record the run did not actually refresh (Finviz refused, or the symbol came back empty) is NOT dated
  as this close — it is counted under ``not_refreshed`` with a reason, never written as if fresh.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

LANE_ID = "finviz-snapshot-refresh"
SCRIPT = "finviz_snapshot_refresh.py"
#: Active-watchlist cap: matches finviz_enrichment.DEFAULT_UNIVERSE_CAP (the number the enrichment lane already
#: spends safely against Finviz's ~100 req/hour, 20 tickers per export).
WATCHLIST_CAP = 200
#: A screener whose last completed run is older than this is not a current screen: its members are not added.
SCREEN_MAX_AGE_DAYS = 14
#: A cache record fetched before the run started by more than this is not this run's data.
REFRESH_GRACE_S = 900
#: fundamental_data row cap for one run (external_market_data_ingest.FINVIZ_FUNDAMENTALS_LIMIT).
FUNDAMENTALS_LIMIT = 200


def _receipt():
    """The shared receipt module (``scripts/lib/lane_last_receipt.py``)."""
    from lib import lane_last_receipt as r

    return r


def last_session_close(today: date | None = None) -> str:
    """The most recent US equity session on or before ``today`` — the close the rows will carry.

    A Saturday run captures Friday's close, so the row is dated Friday, not Saturday: dating it "today" would
    tell every ``MAX(snapshot_date)`` consumer the snapshot is a weekend quote it never was.
    """
    from lib.cio_market_calendar import is_us_trading_day

    d = today or date.today()
    for _ in range(10):
        if is_us_trading_day(d):
            return d.isoformat()
        d -= timedelta(days=1)
    raise RuntimeError("no US session in the last 10 days — refusing to guess a snapshot date")


def _connect(readonly: bool):
    """One DB connection. A dry run is READ ONLY at the server, not merely by convention."""
    from db_adapter import _get_conn

    conn = _get_conn()
    if readonly:
        _receipt().enforce_readonly(conn)
    return conn


def holdings_symbols(root: Path) -> list:
    """Every held symbol that is not cash and not a loan, in file order."""
    path = root / "data" / "portfolios" / "state" / "holdings.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        print(f"  [snapshot-refresh] holdings unreadable ({type(exc).__name__}): {exc}", file=sys.stderr)
        return []
    out = []
    for h in doc.get("holdings") or []:
        sym = str((h or {}).get("symbol") or "").strip().upper()
        if not sym or h.get("is_cash") or h.get("is_loan"):
            continue
        out.append(sym)
    return out


def watchlist_symbols(conn, *, cap: int = WATCHLIST_CAP) -> list:
    """Active watchlist, stalest-enriched first, capped — the same order the enrichment lane uses."""
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol FROM watchlist_items
            WHERE status = 'active' AND symbol IS NOT NULL
            ORDER BY last_enriched_at ASC NULLS FIRST
            LIMIT %s""",
        (cap,),
    )
    return [str(r[0]).strip().upper() for r in cur.fetchall() if r[0]]


def screener_members(conn, *, max_age_days: int = SCREEN_MAX_AGE_DAYS) -> tuple[list, dict]:
    """Members of screener screens that have run recently, and a count of the screens that have not.

    A screen last executed in August is not a current screen: its members would be stale *names*, not data,
    so they are reported (``stale_screens``) and left out rather than silently widening the universe.
    """
    cur = conn.cursor()
    cur.execute(
        """SELECT m.symbol
             FROM screener_symbol_membership m
             JOIN finviz_screeners s ON s.screener_id = m.screener_id
            WHERE s.active
              AND m.membership_status = 'present'
              AND m.last_seen_in_screener_at >= now() - make_interval(days => %s)""",
        (int(max_age_days),),
    )
    members = sorted({str(r[0]).strip().upper() for r in cur.fetchall() if r[0]})
    cur.execute(
        """SELECT count(*) FROM finviz_screeners
            WHERE active AND (last_run IS NULL OR last_run < now() - make_interval(days => %s))""",
        (int(max_age_days),),
    )
    row = cur.fetchone()
    if not row or row[0] is None:  # a count we did not read is unknown, never 0 screens stale
        raise RuntimeError("finviz_screeners count returned no row")
    return members, {"stale_screens": int(row[0]), "max_age_days": int(max_age_days)}


def build_universe(root: Path, conn, *, cap: int = WATCHLIST_CAP, screen_max_age_days: int = SCREEN_MAX_AGE_DAYS,
                   extra: list | None = None) -> dict:
    """Union of holdings, active watchlist, recent screener members and explicitly supplied symbols.

    Ordered holdings → watchlist → screens → extra, de-duplicated, so the report can say where each symbol
    came from without the caller re-deriving it.
    """
    held = holdings_symbols(root)
    watch = watchlist_symbols(conn, cap=cap)
    members, screens = screener_members(conn, max_age_days=screen_max_age_days)
    ordered: list = []
    seen: set = set()
    for group in (held, watch, members, [str(s).strip().upper() for s in (extra or [])]):
        for sym in group:
            if sym and sym not in seen:
                seen.add(sym)
                ordered.append(sym)
    return {
        "symbols": ordered,
        "sources": {
            "holdings": len(held),
            "watchlist": len(watch),
            "screener_members": len(members),
            "explicit": len([s for s in (extra or []) if str(s).strip()]),
            "overlap_deduped": (len(held) + len(watch) + len(members) + len(extra or [])) - len(ordered),
        },
        "screens": screens,
    }


def _aware(dt: datetime) -> datetime:
    """Attach the local zone to the cache's naive ``cached_at`` (it is written naive-local by finviz_enrichment)."""
    return dt.astimezone() if dt.tzinfo is None else dt


def _fresh_after(record: dict, started: datetime) -> bool:
    """True when this record was fetched by THIS run (not a cache survivor dressed as this close)."""
    cached_at = (record or {}).get("cached_at")
    if not cached_at:
        return False
    try:
        return _aware(datetime.fromisoformat(str(cached_at))) >= _aware(started) - timedelta(seconds=REFRESH_GRACE_S)
    except ValueError:
        return False


def count_snapshot_rows(conn, snapshot_date: str, symbols: list) -> int:
    """Read the write back. ``save_ticker_snapshot_daily`` returns None whatever happens, so this is the proof."""
    if not symbols:
        return 0
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FROM ticker_snapshot_daily WHERE snapshot_date = %s AND symbol = ANY(%s)",
        (snapshot_date, list(symbols)),
    )
    row = cur.fetchone()
    conn.rollback()  # a read must never leave a transaction open on a shared thread-local connection
    if not row or row[0] is None:  # an unread count is unknown: reporting 0 would claim "wrote nothing"
        raise RuntimeError(f"snapshot row count unreadable for {snapshot_date}")
    return int(row[0])


def plan(root: Path, *, snapshot_date: str, cap: int, screen_max_age_days: int, extra: list | None,
         force_refresh: bool) -> dict:
    """What an ``--apply`` of this same state would spend and write. Reads only; writes nothing."""
    from finviz_enrichment import BATCH_SIZE, _default_views, _read_cache_readonly, _split_equities

    conn = _connect(readonly=True)
    uni = build_universe(root, conn, cap=cap, screen_max_age_days=screen_max_age_days, extra=extra)
    cache = _read_cache_readonly(root)
    equities, rejected = _split_equities(list(uni["symbols"]))
    if force_refresh:
        to_fetch = list(equities)
    else:
        from finviz_enrichment import _stale_symbols

        to_fetch = _stale_symbols(equities, cache)
    views = _default_views()
    batches = -(-len(to_fetch) // BATCH_SIZE)
    return {
        "snapshot_date": snapshot_date,
        "universe": uni["symbols"],
        "sources": uni["sources"],
        "screens": uni["screens"],
        "equities": len(equities),
        "rejected_non_ticker": [r.get("symbol") for r in rejected],
        "cached_now": len(equities) - len(to_fetch),
        "to_fetch": len(to_fetch),
        "to_fetch_first": to_fetch[:10],
        "views": views,
        "finviz_export_requests": batches * len(views),
        "would_write_snapshot_rows": len(equities),
        "would_write_fundamental_symbols": min(len(equities), FUNDAMENTALS_LIMIT),
        "force_refresh": bool(force_refresh),
        "cache_tickers": len(cache),
    }


def lane_output(*, produced: int, attempted: int, skipped: dict, snapshot_date: str, extra: dict | None = None) -> dict:
    """LaneRunReceipt@v2 output fields. ``skipped_reasons`` partitions ``attempted``: produced + skipped == attempted."""
    out = {
        "produced_count": int(produced),
        "attempted_count": int(attempted),
        "skipped_reasons": {k: int(v) for k, v in (skipped or {}).items() if v},
        "empty_reason": None if produced else "no_refreshed_records",
        "output_evidence": [{"kind": "store_rows", "ref": "ticker_snapshot_daily", "snapshot_date": snapshot_date,
                             "rows_verified": int(produced)}],
    }
    if extra:
        out["output_evidence"].append(extra)
    return out


def apply(root: Path, *, snapshot_date: str, cap: int, screen_max_age_days: int, extra: list | None,
          force_refresh: bool, fundamentals_limit: int) -> dict:
    """Fetch from Finviz, write the snapshot rows and the fundamentals, verify, and return the receipt body."""
    from db_adapter import save_ticker_snapshot_daily
    from external_market_data_ingest import ingest_finviz_fundamentals
    from finviz_enrichment import _split_equities, enrich_tickers

    started = datetime.now(timezone.utc)
    conn = _connect(readonly=False)
    uni = build_universe(root, conn, cap=cap, screen_max_age_days=screen_max_age_days, extra=extra)
    equities, rejected = _split_equities(list(uni["symbols"]))
    results = enrich_tickers(equities, project_root=str(root), force_refresh=force_refresh)

    fresh = {s: r for s, r in (results or {}).items()
             if isinstance(r, dict) and not r.get("rejected_non_ticker") and _fresh_after(r, started)}
    stale_by_run = [s for s in equities if s not in fresh]
    save_ticker_snapshot_daily(snapshot_date, fresh)  # returns None on failure — never trusted, never counted
    verified = count_snapshot_rows(conn, snapshot_date, list(fresh))

    fund = {"rows": None, "fetched": None}  # None until the ingest reports: unknown, not zero
    try:
        fund = ingest_finviz_fundamentals(list(fresh), limit=min(len(fresh), fundamentals_limit)) or fund
    except Exception as exc:  # noqa: BLE001 -- the snapshot is this lane's declared output; report the rest
        print(f"  [snapshot-refresh] fundamentals leg failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    skipped = {}
    if rejected:
        skipped["rejected_non_ticker"] = len(rejected)
    if stale_by_run:
        skipped["not_refreshed"] = len(stale_by_run)
    attempted = len(uni["symbols"])
    produced = verified
    # A symbol can be missing from the table for a reason other than the two buckets above (e.g. the writer
    # rolled back): account for it rather than let produced + skipped fall short of attempted.
    gap = attempted - produced - sum(skipped.values())
    if gap > 0:
        skipped["write_unverified"] = gap
    return {
        "snapshot_date": snapshot_date,
        "sources": uni["sources"],
        "screens": uni["screens"],
        "symbols": attempted,
        "refreshed": len(fresh),
        "not_refreshed": len(stale_by_run),
        "rejected_non_ticker": len(rejected),
        "snapshot_rows_verified": verified,
        "fundamentals_rows": fund.get("rows"),
        "fundamentals_symbols": fund.get("fetched"),
        "skipped": skipped,
    }


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="plan only: no fetch, no write (wins over --apply)")
    mode.add_argument("--apply", action="store_true", help="fetch from Finviz and write the two stores")
    ap.add_argument("--snapshot-date", default=None,
                    help="session close the rows carry (YYYY-MM-DD); default: the last US session ≤ today")
    ap.add_argument("--project-root", default=".",
                    help="tree whose data/ holds holdings.json and the enrichment cache (default: this checkout)")
    ap.add_argument("--symbols", default="", help="extra symbols, comma-separated (e.g. sector peers)")
    ap.add_argument("--symbols-file", default="", help="file of extra symbols, one per line")
    ap.add_argument("--cap", type=int, default=WATCHLIST_CAP, help=f"active-watchlist cap (default {WATCHLIST_CAP})")
    ap.add_argument("--screen-max-age-days", type=int, default=SCREEN_MAX_AGE_DAYS)
    ap.add_argument("--no-force-refresh", action="store_true",
                    help="refresh only records past the cache TTL instead of every symbol in the universe")
    ap.add_argument("--fundamentals-limit", type=int, default=FUNDAMENTALS_LIMIT)
    ap.add_argument("--json", action="store_true", help="print the result document only")
    a = ap.parse_args(argv)

    root = Path(a.project_root).resolve()
    snapshot_date = a.snapshot_date or last_session_close()
    try:
        datetime.strptime(snapshot_date, "%Y-%m-%d")
    except ValueError:
        print(f"--snapshot-date must be YYYY-MM-DD, got {snapshot_date!r}", file=sys.stderr)
        return 2

    extra = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    if a.symbols_file:
        try:
            extra += [ln.strip().upper() for ln in Path(a.symbols_file).read_text().splitlines()
                      if ln.strip() and not ln.startswith("#")]
        except OSError as exc:
            print(f"--symbols-file unreadable: {exc}", file=sys.stderr)
            return 2

    force = not a.no_force_refresh
    if a.dry_run or not a.apply:
        p = plan(root, snapshot_date=snapshot_date, cap=a.cap, screen_max_age_days=a.screen_max_age_days,
                 extra=extra, force_refresh=force)
        _receipt().dry_run_report(
            LANE_ID,
            {k: v for k, v in p.items() if k != "universe"},
            would_write=[
                f"ticker_snapshot_daily: <= {p['would_write_snapshot_rows']} rows at snapshot_date {snapshot_date}",
                f"fundamental_data: <= {p['would_write_fundamental_symbols']} symbols (source=finviz, "
                f"zero provider calls — read from the stored cache)",
                "finviz_enrichment cache: "
                + (f"{p['to_fetch']} tickers refreshed" if p["to_fetch"] else "no fetch (cache fresh)"),
                f"LaneRunReceipt@v2 for {LANE_ID}",
            ],
        )
        if a.json:
            print(json.dumps({"dry_run": True, **p}, default=str))
        return 0

    started_iso = datetime.now(timezone.utc).astimezone().isoformat()
    try:
        result = apply(root, snapshot_date=snapshot_date, cap=a.cap, screen_max_age_days=a.screen_max_age_days,
                       extra=extra, force_refresh=force, fundamentals_limit=a.fundamentals_limit)
    except Exception as exc:
        _receipt().write_lane_receipt(
            LANE_ID, ok=False, exit_code=1, started_at=started_iso, script=SCRIPT,
            error=f"{type(exc).__name__}: {exc}",
            produced_count=0, attempted_count=0, skipped_reasons={"dependency_unavailable": 1},
        )
        raise

    out = lane_output(produced=result["snapshot_rows_verified"], attempted=result["symbols"],
                      skipped=result["skipped"], snapshot_date=snapshot_date,
                      extra={"kind": "store_rows", "ref": "fundamental_data", "source": "finviz",
                             "rows_written": result["fundamentals_rows"]})
    ok = result["snapshot_rows_verified"] > 0
    _receipt().write_lane_receipt(
        LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=started_iso, script=SCRIPT,
        summary={k: v for k, v in result.items() if k != "symbols"},
        produced_count=out["produced_count"], attempted_count=out["attempted_count"],
        skipped_reasons=out["skipped_reasons"], empty_reason=out["empty_reason"],
        output_evidence=out["output_evidence"],
    )
    if a.json:
        print(json.dumps({"apply": True, **result, "receipt_output": out}, default=str))
    else:
        print(f"  [snapshot-refresh] {snapshot_date}: {result['snapshot_rows_verified']}/{result['symbols']} symbols "
              f"verified in ticker_snapshot_daily · fundamentals {result['fundamentals_rows']} rows "
              f"({result['fundamentals_symbols']} symbols)"
              + (f" · skipped {result['skipped']}" if result["skipped"] else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
