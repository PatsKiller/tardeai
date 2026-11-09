#!/usr/bin/env python3
"""Schwab off-hours market-data quotes for the Market Risk Engine: index futures, indices, extended-hours prices.

OFF BY DEFAULT (``schwab.enabled: false`` in config/market_risk_offhours_quotes.yaml) until the operator approves the
schedule in session (§25.10.2). Policy: AGENTS.md 28.2.0 (host lanes may read broker MARKET DATA), ratified by the
operator on PR #2407 (ratify commit f060c2e78). While off, every live invocation stops at ``disabled`` before any
Schwab or database module is imported.

What it reads: GET ``/marketdata/v1/quotes`` only (the host in ``schwab.marketdata_base_url``; any other URL is
refused), with the stored access token from the Schwab token manager's public read API (``health`` then
``get_access_token``, only while the access token is fresh: this lane never refreshes a token). A read that
lands while another caller is refreshing waits and re-reads ``health()``; it still does not refresh. It does not
import ``schwab_transport`` (the module that also carries the order surface), never touches an account, order, stop,
2FA or auth-flow endpoint, and never reads a credential file itself. ``config/schwab_access_mode.yaml`` must allow
reads. Rows go to ``market_quotes_extended`` (feed ``schwab``) through its single writer
(scripts/lib/writers/market_quotes_extended_writer.py), in #2384's contract -- NEVER ``market_quotes``, whose newest
row is the latest quote for stop checks, the repricer and watch alerts. ``--apply`` also refuses while the §7A domain
``quote_extended_session`` is still proposed.

    python3 scripts/market_quotes_offhours_schwab.py --probe                 # availability, no Schwab call
    python3 scripts/market_quotes_offhours_schwab.py --dry-run --fixture F   # parse a recorded payload; no DB, no net
    python3 scripts/market_quotes_offhours_schwab.py --apply                 # live (only when enabled)

A dry run is fixtures-only: without ``--fixture`` it refuses rather than call Schwab.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import offhours_quotes as oq  # noqa: E402

QUOTES_PATH = "quotes"
# health() is false for the last ACCESS_REFRESH_MARGIN_S (300s) of the ~30 min access token.
# Measured 2026-11-09 from the lane log and broker_oauth_token_audit (event/status/time only):
# all 14 no_token runs were 1500–1720s after the previous refresh_rotation, and the next
# refresh_rotation committed 0.5–3.9s later. Eight seconds covers that gap twice. The wait
# re-reads health(); it never calls get_access_token until access_fresh is true, so this lane
# still never refreshes and never loads the Schwab app credentials.
FRESH_WAIT_S = 8.0
FRESH_POLL_S = 0.5


def _wait_for_access_fresh(tm, key, *, sleep=None, monotonic=None, fresh_wait_s=None) -> bool:
    """True when health() says the stored access token is fresh, after a short re-read.

    ``sleep`` and ``monotonic`` are the real clock unless a test supplies its own. A sleep
    that does not advance the clock still stops: the step cap is the budget divided by the poll.
    """
    if not key:
        return False
    sleep_fn = time.sleep if sleep is None else sleep
    clock = time.monotonic if monotonic is None else monotonic
    budget = FRESH_WAIT_S if fresh_wait_s is None else float(fresh_wait_s)
    if tm.health(key).get("access_fresh"):
        return True
    if budget <= 0:
        return False
    deadline = clock() + budget
    steps = 0
    max_steps = int(budget / FRESH_POLL_S) + 2
    while steps < max_steps:
        steps += 1
        now = clock()
        if now >= deadline:
            return False
        sleep_fn(min(FRESH_POLL_S, deadline - now))
        if tm.health(key).get("access_fresh"):
            return True
    return False


def marketdata_url(cfg: dict) -> str:
    """The one URL this lane may GET. Refuses anything that is not the Schwab market-data host path."""
    base = str((cfg.get("schwab") or {}).get("marketdata_base_url") or "")
    if not base.startswith("https://api.schwabapi.com/marketdata/v1/"):
        raise ValueError(f"refused: {base!r} is not the Schwab market-data API")
    return base + QUOTES_PATH


def live_fetch(symbols: list[str], cfg: dict, *, sleep=None, monotonic=None, fresh_wait_s=None) -> dict:
    """Live Schwab quotes. Only reached with schwab.enabled true and --apply; never in a dry run or a test."""
    from lib import schwab_access_mode as sam

    if not sam.reads_allowed():
        sam.log_skip("market_quotes_offhours_schwab")
        return {"_status": sam.PAUSED_STATUS, "_detail": f"schwab_access_mode={sam.mode()}"}
    import requests
    import schwab_token_manager as tm  # public read API only: canonical_token_key, health, get_access_token

    url = marketdata_url(cfg)
    key = tm.canonical_token_key()
    # This lane never refreshes a token. get_access_token() refreshes a stale access token when the operator has
    # armed HTTP refresh, and that path loads the Schwab app credentials; so the lane reads the stored token only
    # while health() says it is fresh. A slot that overlaps another caller's refresh re-reads health() for
    # FRESH_WAIT_S and still does not call get_access_token until that read is fresh.
    if key and not _wait_for_access_fresh(tm, key, sleep=sleep, monotonic=monotonic, fresh_wait_s=fresh_wait_s):
        return {"_status": "no_token", "_detail": "access token not fresh; this lane never refreshes (fail closed)"}
    token = tm.get_access_token(key) if key else None
    if not token:
        return {"_status": "no_token", "_detail": "token manager returned no access token (fail closed)"}
    out: dict = {}
    provider_errors: list = []  # per-batch invalid-symbol reports: a later batch must never erase an earlier one
    size = int((cfg.get("schwab") or {}).get("batch_size", 100))
    batches, failed = 0, []
    for i in range(0, len(symbols), size):
        batches += 1
        r = requests.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                         params={"symbols": ",".join(symbols[i:i + size]), "fields": "quote,extended,regular",
                                 "indicative": "false"}, timeout=20)
        if r.status_code != 200:
            if tm.is_auth_failure(r.text):
                tm.record_auth_failure(r.text[:200], source="market_quotes_offhours_schwab")
            print(f"  [schwab-offhours] HTTP {r.status_code} on batch {i}")
            failed.append({"batch": i // size, "http_status": r.status_code})
            continue
        try:
            body = r.json()
        except ValueError:
            failed.append({"batch": i // size, "http_status": r.status_code, "error": "body is not JSON"})
            continue
        if not isinstance(body, dict):
            failed.append({"batch": i // size, "http_status": r.status_code, "error": "body is not an object"})
            continue
        errs = body.pop("errors", None) if "errors" in body else None
        out.update(body)
        if errs:
            provider_errors.append(errs)
    if provider_errors:  # the receipt reports the union, in batch order; one batch keeps the provider's own shape
        out["errors"] = provider_errors[0] if len(provider_errors) == 1 else provider_errors
    # review of #2416 F5: a run where every batch failed is an error, never "ok with 0 rows"
    if batches and len(failed) == batches:
        return {"_status": "http_error", "_detail": f"all {batches} Schwab quote batch(es) failed", "_failed": failed}
    if failed:
        out["_failed"] = failed  # partial: surfaced on the receipt as fetch.failed_batches
    return out


def probe(cfg: dict, *, db_query: Callable[[str], Any] | None = None) -> dict:
    """Availability without calling Schwab: switch, policy dependency, window, URL rail, modules present.

    The universe's SQL sources are read through ``db_query`` (default: the read-only reader below). It is a parameter
    so a caller can supply its own reader — a test supplies a stub instead of opening the live database.
    """
    now = datetime.now(timezone.utc)
    ok, why = oq.schwab_window(now, cfg)
    s = cfg.get("schwab") or {}
    try:
        url, url_ok = marketdata_url(cfg), True
    except ValueError as exc:
        url, url_ok = str(exc), False
    universe, prov = oq.resolve_universe(cfg, db_query=db_query or read_symbols)
    return {"schema": "OffHoursQuoteProbe@v2", "provider": "schwab", "store": oq.STORE, "enabled": bool(s.get("enabled")),
            "store_domain_granted": oq.mqe.domain_promoted(),
            "requires_policy": s.get("requires_policy"), "window_now": why, "in_window_now": ok,
            "marketdata_url": url, "url_rail_ok": url_ok,
            "token_manager_present": importlib.util.find_spec("schwab_token_manager") is not None,
            "symbols": oq.schwab_symbols(cfg, universe), "universe_missing_refs": prov["missing_refs"],
            "live_call_made": False}


def read_symbols(sql: str) -> list[str]:
    """Run one configured universe query READ-ONLY and return its single column.

    A separate connection is opened for this and ``readonly=True`` is set on it: the lane's write connection is
    thread-local and shared (``db_adapter._get_conn``), so making THAT session read-only would silently break the
    writer's insert later in the same run. Only the SELECTs declared in ``universe.sources`` reach here.
    """
    import os

    import psycopg2

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""), connect_timeout=10, application_name="market_quotes_offhours_schwab",
    )
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '20s'")
            cur.execute(sql)
            return [str(r[0]) for r in cur.fetchall() if r and r[0] is not None]
    finally:
        conn.close()


def _write(rows: list[dict]) -> dict:
    from db_adapter import _get_conn
    from lib.writers.market_quotes_extended_writer import write_extended_quotes

    conn = _get_conn()
    try:
        res = write_extended_quotes(conn.cursor(), rows)
        conn.commit()
        return res
    finally:
        conn.close()


def stored_reference(symbol: str, ref_date, cfg: dict | None = None) -> float | None:
    """The lane's OWN last stored settle for ``ref_date``, or None (design WU-1, ADDENDUM to LQ-20261107-939).

    Read from ``market_quotes_extended`` on this lane's feed: Friday's after-hours rows carry Friday's settle as their
    ``reference_close``, so a Sunday close the provider dates to Sunday is corroborated against the settle this lane
    itself recorded. It replaces the yfinance-named map (ES=F, NQ=F, ...) that read ``market_ohlcv_bars`` daily bars --
    zero rows, and a banned source in front of the Market Risk Engine (LQ-20261107-455). Being the same provider's
    earlier observation, it cannot catch an error shared by both prints (see the config comment). A missing source
    config, a missing row, a NULL reference, or a read error is "no reference": the row stays level-only.
    """
    s = (cfg or {}).get("schwab") or {}
    if str(s.get("settle_reference_source") or "") != "market_quotes_extended_own_feed":
        return None
    feed = str(s.get("settle_reference_feed") or "").strip()
    if not feed:
        return None
    from db_adapter import _get_conn

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT reference_close FROM market_quotes_extended "
            "WHERE symbol = %s AND feed = %s AND reference_date = %s AND reference_close IS NOT NULL "
            "ORDER BY bar_end DESC LIMIT 1",
            [str(symbol), feed, ref_date],
        )
        row = cur.fetchone()
        return float(row[0]) if row and row[0] is not None else None
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--fixture", help="recorded /marketdata/v1/quotes payload (dry run)")
    ap.add_argument("--now", help="ISO time with offset, pins the clock (dry run)")
    ap.add_argument("--force-window", action="store_true", help="ignore the ET window (dry run only)")
    ap.add_argument("--config", help="alternate config path")
    a = ap.parse_args(argv)
    cfg = oq.load_config(a.config)
    if a.probe:
        print(json.dumps(probe(cfg), indent=1))
        return 0
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    if a.dry_run:
        if not a.fixture:
            print(json.dumps({"status": "refused", "detail": "dry run is fixtures-only: pass --fixture"}))
            return 2
        doc = json.loads(Path(a.fixture).read_text(encoding="utf-8"))
        dry_cfg = {**cfg, "schwab": {**cfg["schwab"], "enabled": True}}  # parse path only; no Schwab, no DB
        r = oq.run(cfg=dry_cfg, now=now, fetch=lambda _s: doc.get("quotes", doc), write=None,
                   dry_run=True, force_window=a.force_window, db_query=read_symbols)
        r["config_enabled"] = bool(cfg["schwab"].get("enabled"))
        print(json.dumps(r, default=str, indent=1))
        return 0
    r = oq.run(cfg=cfg, now=now, fetch=lambda syms: live_fetch(syms, cfg), write=_write, dry_run=False,
               db_query=read_symbols,
               reference_lookup=lambda sym, d: stored_reference(sym, d, cfg))
    print(json.dumps(r, default=str, indent=1))
    return 0 if r.get("status") in ("ok", "partial", "disabled", "outside_window", "schwab_paused", "refused_domain_proposed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
