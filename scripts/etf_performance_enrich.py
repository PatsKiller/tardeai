#!/usr/bin/env python3
"""etf_performance_enrich.py — YTD price performance + dividend yield for ETFs/funds (and any instrument),
from the shared Finviz enrichment cache. Fills the gap the operator flagged: "I want actual ETF YTD
performance ... yield and dividends." Stores on symbol_profiles so the watchlist API → skill → agent can
report it.

SOURCE (2026-11-07, LQ-20261107-184): ``data/state/ticker_enrichment_cache.json`` — the cache the
``finviz-enrichment`` lane fills with Finviz Elite views 141 (``perf_ytd_pct``) and 161
(``div_yield_pct``). yfinance was the source before and is now forbidden by the operator price rule, so
this lane reads the cache and never calls the network. A symbol with no cache record, or one older than
``CACHE_MAX_AGE_DAYS``, yields nothing this run rather than a number from somewhere else.

PLAUSIBILITY (same item): the lane wrote and served YTD 1424.59% (CRED) and yields up to 95.02% (UNWPX) —
split and adjustment artefacts, reproducible from two sources, and not returns a reader can use. A value
outside ``PERF_BOUNDS`` is never written; a value already stored outside its bound is cleared to NULL when
no plausible replacement arrives, because "unknown" is honest and +1424% is not. A plausible stored value is
never cleared merely because today's source has nothing for it.

Read-only re: trading. ``--symbols X,Y`` to target; default = all etf/fund/inverse_etf on symbol_profiles.
Cron weekly alongside classify_instruments/etf_analyst. ``SYMBOL_CAP`` is a runaway guard, not a politeness
bound: the old 300 existed because each symbol cost a 0.8 s network call, and it left 139 of 439 rows
refreshed only every other week.

Lane ``etf-performance-enrich`` (cron L520). ``--dry-run`` and the older ``--no-fetch``
now print an offline plan before any DB, credential loader, DDL, provider or profile writer.
Unknown/abbreviated flags exit 2. preview() remains the older explicit READ ONLY SELECT preview
for library callers. The dispatch CLI does not open the live DB to prove a plan. Own env loading
is name-bounded and delayed until a real run; the db_adapter shared loader remains separate.

A real run writes ``<state_root>/data/runtime/etf-performance-enrich_last.json`` (LaneRunReceipt@v1;
``ok_at`` only on success). Exit codes: 0 = ran (some symbols without data, or zero target symbols, are
findings); 1 = the run failed: crash / DB unavailable (failed receipt, exception re-raised), or symbols
were attempted and every one raised or came back with no YTD, yield or dividend value (nothing could be
fetched when work existed); 2 = usage error.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
if not __import__("os").getenv("DB_PASSWORD") and (ROOT / ".env").exists():
    # DB_* only (AGENTS.md §23.18): load_dotenv copied the whole env file, broker credentials included, into
    # os.environ. With DB_PASSWORD set here, db_adapter also skips env_bootstrap's whole-render load.
    for _line in (ROOT / ".env").read_text().splitlines():
        _k, _sep, _v = _line.strip().partition("=")
        if _sep and _k.strip().startswith("DB_") and not _line.strip().startswith("#"):
            __import__("os").environ.setdefault(_k.strip(), _v.strip().strip("'\""))



def finite_or_none(v):
    """Return ``v`` when it is a finite number, else None (NaN/inf are unknown)."""
    import math as _math
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return v if _math.isfinite(f) else None

def _arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--symbols")
    return parser.parse_args(argv)


def _get_conn():
    """db_adapter is imported here, after the DB_*-only loader above, so a dry run or usage error never loads it."""
    from db_adapter import _get_conn as connect
    return connect()


def upsert_profile(*args, **kwargs):
    from lib.writers.symbol_profiles_writer import upsert_profile as write
    return write(*args, **kwargs)


_ENV_KEYS = frozenset({"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"})


def _load_env():
    if not os.getenv("DB_PASSWORD"):
        try:
            from dotenv import dotenv_values
            for key, value in dotenv_values(ROOT / ".env").items():
                if key in _ENV_KEYS and value is not None:
                    os.environ.setdefault(key, value)
        except Exception:
            pass

LANE_ID = "etf-performance-enrich"
#: A runaway guard, not a politeness bound. The cap was 300 while each symbol cost a 0.8 s yfinance call;
#: the source is now a local cache, and 439 ETF/fund targets must all be visited every run (LQ-20261107-184).
SYMBOL_CAP = 5000
#: How old a Finviz cache record may be and still describe "YTD". The cache is filled by another lane over
#: the watchlist universe; a record older than this is reported as stale and not used.
CACHE_MAX_AGE_DAYS = 30
#: A percentage a reader can act on. Outside these, the number is an artefact (reverse split, adjusted close,
#: partial-distribution history), not a return: measured live 2026-11-07, 4 rows had |YTD| > 150% (CRED 1424.59,
#: DVIN 1649.37, DVAL 894.82, DLLL 542.77) and 10 had yield > 25% (UNWPX 95.02, MTYY 89.13, ...).
PERF_BOUNDS = {"ytd_return_pct": 150.0, "dividend_yield_pct": 25.0}
#: cache record key -> symbol_profiles column
_PERF_SOURCES = (("ytd_return_pct", "perf_ytd_pct"), ("dividend_yield_pct", "div_yield_pct"))
_PERF_COLS = (("ytd_return_pct", "numeric"), ("dividend_yield_pct", "numeric"),
              ("ttm_dividend", "numeric"), ("perf_updated_at", "timestamptz"))
# Stalest first (2026-10-20). ``ORDER BY 1`` + SYMBOL_CAP=300 over 434 targets meant the alphabetical tail was never
# refreshed: 11 rows (L..N, e.g. NBIZ/NVD/NLR) kept the NaN ytd_return_pct this lane wrote on 2026-08-29 before the
# 2026-09-13 writer finite check, because nothing ever revisited them (symbol_profiles finite contract, BLOCK).
_TARGET_SQL = ("SELECT upper(symbol) FROM symbol_profiles WHERE instrument_type IN ('etf','fund','inverse_etf') "
               "ORDER BY perf_updated_at ASC NULLS FIRST, 1")


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.etf_performance_enrich
        from scripts.lib import lane_last_receipt as lr
    return lr


def _flag(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _bound_reason(column, value):
    """None when ``value`` is usable for ``column``; else why not. NaN/inf are unknown, not implausible."""
    v = finite_or_none(value)
    if v is None:
        return None
    limit = PERF_BOUNDS.get(column)
    if limit is not None and abs(float(v)) > limit:
        return f"{column}={float(v)} outside +/-{limit:g}%"
    return None


def finviz_cache(root=None):
    """The shared Finviz enrichment cache (``data/state/ticker_enrichment_cache.json``), read, never written.

    Resolved the way the other lanes resolve runtime state: ``TRADEAI_STATE_ROOT`` (default
    ``~/trade-ai-releases/persistent-state``) first, then this checkout's own ``data/`` — a served release
    symlinks ``data/state`` into the state root, a bare worktree has neither and gets an empty cache, which
    the caller reports as ``no_source_value`` rather than falling back to another provider.
    """
    try:
        from finviz_enrichment import load_cache
    except ImportError:  # imported as scripts.etf_performance_enrich
        from scripts.finviz_enrichment import load_cache
    if root is not None:
        candidates = [Path(root)]
    else:
        try:
            from lib.n8n_pilot_observations import state_root
        except ImportError:  # imported as scripts.etf_performance_enrich
            from scripts.lib.n8n_pilot_observations import state_root
        candidates = [state_root(), ROOT]
    for candidate in candidates:
        try:
            cache = load_cache(candidate)
        except Exception:
            continue
        if cache:
            return cache
    return {}


def _cached_at(record):
    """The record's own timestamp as an aware datetime, or None when it carries no readable one."""
    raw = (record or {}).get("cached_at")
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), timezone.utc)
    if isinstance(raw, str):
        try:
            at = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return at.astimezone(timezone.utc) if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return None


def cache_entry(cache, symbol, now=None):
    """(record | None, why | None) for one symbol. Absent or too old is named, never silently a number."""
    record = (cache or {}).get(symbol)
    if not isinstance(record, dict):
        return None, "no_source_value"
    at = _cached_at(record)
    if at is None or (now or datetime.now(timezone.utc)) - at > timedelta(days=CACHE_MAX_AGE_DAYS):
        return None, "stale_source_value"
    return record, None


def perf_payload(record, stored, *, symbol=""):
    """(fields to write, notes) for one symbol. Pure — the rule, not the plumbing.

    ``record`` is one cache record (or None); ``stored`` is what the row holds today for the two columns.
    A plausible value is written. An implausible one is dropped and named; if the row already serves an
    implausible value, that value is written as NULL so it stops being served. A plausible stored value is
    left alone when the source has nothing — clearing honest data for want of a refresh is not an option.
    """
    fields: dict = {}
    notes: dict = {}
    has_source = isinstance(record, dict)
    for column, key in _PERF_SOURCES:
        value = finite_or_none((record or {}).get(key)) if has_source else None
        rejected = _bound_reason(column, value) if value is not None else None
        if value is not None and rejected is None:
            fields[column] = value
            continue
        if rejected is not None:
            notes[column] = f"rejected_implausible:{rejected}"
        kept = _bound_reason(column, (stored or {}).get(column))
        if kept:
            fields[column] = None
            notes[column] = (notes[column] + "; " if column in notes else "") + f"cleared_implausible:{kept}"
        elif column not in notes:
            notes[column] = "no_source_value"
    return fields, notes


def _target_symbols(cur):
    target = _flag("--symbols")
    if target:
        return [s.strip().upper() for s in target.split(",") if s.strip()]
    cur.execute(_TARGET_SQL)
    return [r[0] for r in cur.fetchall()]


def preview() -> dict:
    """Dry run (AGENTS.md §6): READ ONLY session, SELECTs only -- no DDL, no Finviz read, no write."""
    conn = _get_conn()
    _receipt_lib().enforce_readonly(conn)
    cur = conn.cursor()
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'symbol_profiles' AND column_name = ANY(%s)""",
                ([c for c, _ in _PERF_COLS],))
    have_cols = sorted(r[0] for r in cur.fetchall())
    syms = _target_symbols(cur)
    conn.rollback()
    return {"symbols": len(syms), "would_fetch": len(syms[:SYMBOL_CAP]), "first_symbols": syms[:10],
            "perf_columns_present": have_cols, "would_run_ddl": len(have_cols) < len(_PERF_COLS)}


def enrich() -> dict:
    conn = _get_conn(); cur = conn.cursor()
    for col, typ in _PERF_COLS:
        cur.execute(  # nosemgrep: tq-py-sql-fstring -- col/typ from the fixed _PERF_COLS tuple
            f"ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS {col} {typ}")
    conn.commit()

    syms = _target_symbols(cur)
    if not syms:
        print(f'{{"ok": true, "symbols": {len(syms)}, "note": "empty"}}')
        return {"symbols": 0, "attempted": 0, "updated": 0, "rejected": 0, "errors": 0, "empty": 0,
                "cleared_implausible": 0, "no_source": 0}

    # What the rows hold today, so an implausible value already being served can be cleared. One scan of the
    # same 439-row universe the target query already walks; no per-symbol query.
    stored: dict = {}
    try:
        cur.execute("SELECT upper(symbol), ytd_return_pct, dividend_yield_pct FROM symbol_profiles "
                    "WHERE instrument_type IN ('etf','fund','inverse_etf')")
        stored = {r[0]: {"ytd_return_pct": r[1], "dividend_yield_pct": r[2]} for r in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001 — no stored values: nothing to clear, everything else still runs
        print(f'{{"ok": true, "note": "pre-read failed: {type(exc).__name__}"}}', file=sys.stderr)

    cache = finviz_cache()
    now = datetime.now(timezone.utc)
    done = rejected = errors = empty = cleared = no_source = 0
    for s in syms[:SYMBOL_CAP]:
        record, why = cache_entry(cache, s, now)
        fields, notes = perf_payload(record, stored.get(s), symbol=s)
        if not fields:
            empty += 1
            if why:
                no_source += 1
            continue
        try:
            rcpt = upsert_profile(cur, s, fields, source="etf_performance_enrich")
            done += rcpt.rows_written
            rejected += rcpt.rows_rejected
            cleared += sum(1 for note in notes.values() if "cleared_implausible" in note)
        except Exception:
            errors += 1
            continue
    conn.commit()
    import json
    print(json.dumps({"ok": True, "symbols": len(syms), "updated": done, "rejected": rejected,
                      "cleared_implausible": cleared, "no_source": no_source}))
    return {"symbols": len(syms), "attempted": len(syms[:SYMBOL_CAP]), "updated": done, "rejected": rejected,
            "errors": errors, "empty": empty, "cleared_implausible": cleared, "no_source": no_source}


def run_failed(res: dict) -> bool:
    """Honest exit: symbols attempted and every one raised or returned no value."""
    return res["attempted"] > 0 and (res["errors"] + res["empty"]) >= res["attempted"]


def main(argv=None) -> int:
    args = _arguments(argv)
    lr = _receipt_lib()
    if args.dry_run or args.no_fetch:
        target = args.symbols or "ETF/fund/inverse_etf symbols from symbol_profiles, stalest perf_updated_at first"
        print(f"DRY-RUN {LANE_ID}: would select {target}; read the Finviz enrichment cache for up to {SYMBOL_CAP} "
              "symbols (no network); drop any YTD outside +/-150% or yield outside 25% instead of writing it; "
              "persist through the symbol_profiles writer and write a live receipt; "
              "no DB, credential file or network opened")
        return 0
    _load_env()
    started = lr.now_iso()
    try:
        res = enrich()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="etf_performance_enrich.py", error=f"{type(exc).__name__}: {exc}",
                              output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    failed = run_failed(res)
    rc = 1 if failed else 0
    lr.write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                          script="etf_performance_enrich.py", summary=res, output=lane_output(res))
    return rc


def _count(res: dict, key: str):
    """The receipt field as an int, or None when the run did not report it. Unknown is not zero."""
    value = res.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def lane_output(res: dict) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: symbol_profiles rows upserted with YTD/dividend
    fields). No ETF/fund symbol in symbol_profiles is fatal (``universe_empty_unexpected``)."""
    produced, attempted = int(res.get("updated") or 0), int(res.get("attempted") or 0)
    skipped = {"writer_rejected": int(res.get("rejected") or 0), "fetch_error": int(res.get("errors") or 0),
               "no_values": int(res.get("empty") or 0)}
    # A run that did not report these fields must not present them as a clean zero (taxonomy #2). Every
    # enrich() result carries them, so absent means the receipt was built from something else: stay absent.
    cleared = _count(res, "cleared_implausible")
    if cleared:
        skipped["cleared_implausible"] = cleared
    no_source = _count(res, "no_source")
    if no_source:
        skipped["no_source_value"] = no_source
    if not int(res.get("symbols") or 0):
        skipped["universe_empty_unexpected"] = 1
    return {"produced_count": produced, "attempted_count": max(attempted, produced), "skipped_reasons": skipped,
            "empty_reason": None}


if __name__ == "__main__":
    raise SystemExit(main())
