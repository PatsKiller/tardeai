"""indicator-engine universe lane: gap-fill ``indicator_confluence_cache`` over the cache's own universe.

Lane repair 2026-10-15. The 08:00 cron line ``$PY scripts/indicator_engine.py`` ran only the module's CLI test mode
(``analyze_confluence('AMD', 'scalp')`` printed to ``logs/indicator_engine.log``): no universe, no write, no reader.
``scripts/indicator_engine.py --universe`` runs this module instead.

* **Universe (not invented):** :func:`universe_symbols` is the selection of the cache's existing producer,
  ``scripts/indicator_cache_refresh.py`` (05:45 lane ``indicator-cache-refresh``): watchlist_symbol_master rows in
  the AI / personal watchlist or the portfolio, plus GO/WAIT screener scans of the last 3 days and ACTIVE incubator
  symbols. Same SQL, same order of precedence.
* **Work:** for each universe symbol whose ``profile`` row is missing or older than ``stale_after_hours`` — missing
  first, then oldest — compute ``indicator_engine.analyze_confluence(symbol, profile)`` and upsert the row keyed
  ``(symbol, profile)``. Bounded by ``max_symbols``. Config: ``config/indicator_strategies.yaml`` ``universe_lane``.
* **Idempotent:** a second run in the same window finds every row fresh and writes nothing; the upsert replaces a row.
* **Connections:** the selection transaction ends before the first provider call; each upsert is one short
  transaction on db_adapter's connection (pinged and rebuilt when the server dropped it) — the pattern that fixed
  build_symbol_profiles the same day (idle_in_transaction_session_timeout 120 s).
* **Dry run:** READ ONLY session (``enforce_readonly``); selection only; returns before any provider call or write.
* **Evidence:** ``LaneOutput@v1`` counts (``lib/lane_output.py``) in the ``LaneRunReceipt@v1``
  ``data/runtime/indicator-engine_last.json`` (real run only) and on one stderr ``LANE_OUTPUT`` line (every mode).

Never imports indicator_engine (pandas / yfinance) at module import: the analyzer is passed in or imported in
:func:`run`. Advisory market data only; MBI_BEHAVIOR = 0; no broker, no send.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from lib.json_safety import indicator_cache_json_fields, indicator_cache_scalar_fields

LANE_ID = "indicator-engine"
UNIT = "indicator_confluence_cache rows upserted"
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "indicator_strategies.yaml"
DEFAULTS = {"profile": "swing", "stale_after_hours": 6, "max_symbols": 400, "cache_ttl_minutes": 60}

UNIVERSE_BASE_SQL = (
    "SELECT DISTINCT symbol FROM watchlist_symbol_master "
    "WHERE in_ai_watchlist=true OR in_personal_watchlist=true OR in_portfolio=true"
)
UNIVERSE_SCREENER_SQL = """
        SELECT DISTINCT symbol FROM trade_ai_scans
        WHERE scanned_at > NOW() - INTERVAL '3 days'
        AND decision IN ('GO', 'WAIT')
        UNION
        SELECT DISTINCT symbol FROM incubator_universe
        WHERE status = 'ACTIVE'
    """
FRESHNESS_SQL = "SELECT symbol, computed_at FROM indicator_confluence_cache WHERE profile = %s AND symbol = ANY(%s)"

UPSERT_SQL = """INSERT INTO indicator_confluence_cache
   (symbol, profile, confluence_score, confluence_tier,
    signals_bullish, signals_bearish, signals_neutral,
    strategy_badges, bearish_badges, key_levels,
    stop_price, target_price, atr, adx_regime, entry_quality,
    full_result, computed_at, expires_at)
   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW()+make_interval(mins => %s))
   ON CONFLICT (symbol,profile) DO UPDATE SET
     confluence_score=EXCLUDED.confluence_score,
     confluence_tier=EXCLUDED.confluence_tier,
     signals_bullish=EXCLUDED.signals_bullish,
     signals_bearish=EXCLUDED.signals_bearish,
     signals_neutral=EXCLUDED.signals_neutral,
     strategy_badges=EXCLUDED.strategy_badges,
     bearish_badges=EXCLUDED.bearish_badges,
     key_levels=EXCLUDED.key_levels,
     stop_price=EXCLUDED.stop_price,
     target_price=EXCLUDED.target_price,
     atr=EXCLUDED.atr,
     adx_regime=EXCLUDED.adx_regime,
     entry_quality=EXCLUDED.entry_quality,
     full_result=EXCLUDED.full_result,
     computed_at=NOW(),
     expires_at=EXCLUDED.expires_at"""


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    """``universe_lane`` from config/indicator_strategies.yaml over DEFAULTS. Unreadable file -> DEFAULTS."""
    cfg: dict[str, Any] = dict(DEFAULTS)
    try:
        import yaml

        doc = yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
        cfg.update({k: v for k, v in (doc.get("universe_lane") or {}).items() if k in DEFAULTS})
    except Exception:  # noqa: BLE001 -- the defaults are the documented values
        pass
    return cfg


def universe_symbols(cur) -> list[str]:
    """The indicator_cache_refresh universe, base names first, then screener/incubator additions."""
    cur.execute(UNIVERSE_BASE_SQL)
    base = [str(r[0]).upper() for r in cur.fetchall() if r and r[0]]
    cur.execute(UNIVERSE_SCREENER_SQL)
    seen = set(base)
    out = list(dict.fromkeys(base))
    for r in cur.fetchall():
        sym = str(r[0]).upper() if r and r[0] else ""
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _aware(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None
    if not isinstance(ts, datetime):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def stale_symbols(cur, symbols: Iterable[str], profile: str, stale_after_hours: float,
                  now: Optional[datetime] = None) -> list[str]:
    """Universe symbols whose ``profile`` row is missing or older than the threshold: missing first, then oldest."""
    syms = list(symbols)
    if not syms:
        return []
    cur.execute(FRESHNESS_SQL, (profile, syms))
    seen = {str(r[0]).upper(): _aware(r[1]) for r in cur.fetchall()}
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=float(stale_after_hours))
    missing = [s for s in syms if s not in seen or seen[s] is None]
    old = sorted((s for s in syms if seen.get(s) is not None and seen[s] < cutoff), key=lambda s: (seen[s], s))
    return missing + old


def upsert_params(symbol: str, profile: str, r: dict, ttl_minutes: int) -> tuple:
    key_levels_json, full_result_json = indicator_cache_json_fields(r)
    scalar_fields = indicator_cache_scalar_fields(r)
    return (symbol, profile, scalar_fields["confluence_score"], r.get("confluence_tier"),
            scalar_fields["signals_bullish"], scalar_fields["signals_bearish"], scalar_fields["signals_neutral"],
            r.get("strategy_badges", []), r.get("bearish_badges", []),
            key_levels_json,
            scalar_fields["stop_price"], scalar_fields["target_price"],
            scalar_fields["atr"], r.get("adx_regime"), scalar_fields["entry_quality"],
            full_result_json, int(ttl_minutes))


def proxy_codes() -> frozenset[str]:
    """Internal retirement-plan fund codes (holding_proxies.HOLDING_PROXY_MAP keys that are not a plain ticker): no
    exchange OHLCV exists for them (build_symbol_profiles applies the same rule). Empty when unreadable."""
    try:
        from holding_proxies import HOLDING_PROXY_MAP

        return frozenset(k.upper() for k in HOLDING_PROXY_MAP if not re.fullmatch(r"[A-Z]{1,5}", k.upper()))
    except Exception:  # noqa: BLE001
        return frozenset()


def _db_error_classes() -> tuple:
    try:
        import psycopg2

        return (psycopg2.OperationalError, psycopg2.InterfaceError)
    except Exception:  # noqa: BLE001
        return ()


def _skip_reason(result: dict, rate_limited: Callable[[], bool]) -> str:
    err = str((result or {}).get("error") or "")
    if rate_limited():
        return "provider_rate_limited"
    if err.startswith("No OHLCV data"):
        return "no_ohlcv"
    if "Config not loaded" in err:
        return "config_unloaded"
    return "analysis_error"


def run(*, dry_run: bool = False, limit: Optional[int] = None, symbols: Optional[list[str]] = None,
        get_conn: Optional[Callable[[], Any]] = None, analyze: Optional[Callable[[str, str], dict]] = None,
        rate_limited: Optional[Callable[[], bool]] = None, config: Optional[dict] = None,
        now: Optional[datetime] = None, exclude: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """One lane run. Returns the summary (with the ``output`` LaneOutput@v1 block); prints it as JSON on stdout."""
    from lib.lane_output import output_block

    cfg = dict(config or load_config())
    profile = str(cfg["profile"])
    cap = int(limit if limit is not None else cfg["max_symbols"])
    if get_conn is None:
        from db_adapter import _get_conn as get_conn  # type: ignore[no-redef]
    conn = get_conn()
    if conn is None:
        raise RuntimeError("db_unavailable: db_adapter returned no connection")
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)  # the server refuses any write in this session (AGENTS.md §6)
    cur = conn.cursor()
    universe = [s.upper() for s in symbols] if symbols else universe_symbols(cur)
    excluded = frozenset(proxy_codes() if exclude is None else (x.upper() for x in exclude))
    computable = [s for s in universe if s not in excluded]
    stale = stale_symbols(cur, computable, profile, float(cfg["stale_after_hours"]), now=now)
    todo = stale[:max(cap, 0)]
    conn.rollback()  # end the selection transaction before any provider call (nothing was written)
    base = {"lane_id": LANE_ID, "profile": profile, "universe": len(universe),
            "proxy_codes_excluded": len(universe) - len(computable), "stale": len(stale),
            "capped": max(len(stale) - len(todo), 0)}
    if not universe:
        out = {**base, "upserted": 0,
               "output": output_block(unit=UNIT, produced=0, attempted=0, empty_reason="no_universe")}
        print(json.dumps(out))
        return out
    if dry_run:
        out = {**base, "mode": "dry_run", "would_compute": len(todo), "sample": todo[:25],
               "would_write": {"table": "indicator_confluence_cache", "key": "(symbol, profile)",
                               "max_rows": len(todo)},
               "output": output_block(unit=UNIT, produced=0, attempted=len(todo),
                                      empty_reason="dry_run" if todo else "no_stale_symbols")}
        print(json.dumps(out))
        return out
    if analyze is None or rate_limited is None:
        import indicator_engine as ie

        analyze = analyze or ie.analyze_confluence
        rate_limited = rate_limited or ie._rate_limit_cooldown_active
    db_errors = _db_error_classes()
    ttl = int(cfg["cache_ttl_minutes"])
    produced = 0
    skipped: dict[str, int] = {}
    for sym in todo:
        result = analyze(sym, profile) or {}
        if not result.get("ok"):
            reason = _skip_reason(result, rate_limited)
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        reason = None
        for attempt in range(2):
            c = get_conn()  # db_adapter pings an idle connection and rebuilds a dropped one
            if c is None:
                reason = "db_unavailable"
                break
            try:
                c.cursor().execute(UPSERT_SQL, upsert_params(sym, profile, result, ttl))
                c.commit()
                reason = None
                break
            except db_errors:  # type: ignore[misc]
                reason = "db_connection_lost"
                try:
                    c.rollback()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    from db_adapter import close_thread_conn

                    close_thread_conn()
                except Exception:  # noqa: BLE001
                    pass
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        produced += 1
    empty = None if produced else ("no_stale_symbols" if not todo else "all_skipped")
    out = {**base, "upserted": produced,
           "output": output_block(unit=UNIT, produced=produced, attempted=len(todo), skipped=skipped,
                                  empty_reason=empty)}
    print(json.dumps(out))
    return out


def work_ok(summary: dict) -> bool:
    """A run is a failure when there was work and nothing landed, or a DB write was lost."""
    block = (summary or {}).get("output") or {}
    if block.get("attempted_count") and not block.get("produced_count"):
        return False
    if (block.get("empty_reason") == "no_universe"):
        return False
    reasons = block.get("skipped_reasons") or {}
    return not (reasons.get("db_connection_lost") or reasons.get("db_unavailable"))


def main(argv: Optional[list[str]] = None) -> int:
    """``indicator_engine.py --universe [--dry-run] [--limit N] [--symbols A,B]``."""
    import argparse

    from lib.lane_last_receipt import now_iso, write_lane_receipt
    from lib.lane_output import emit

    ap = argparse.ArgumentParser(prog="indicator_engine.py --universe", allow_abbrev=False)
    ap.add_argument("--universe", action="store_true", required=True)
    ap.add_argument("--dry-run", action="store_true", help="READ ONLY selection; no provider call, no write")
    ap.add_argument("--limit", type=int, default=None, help="override universe_lane.max_symbols")
    ap.add_argument("--symbols", help="ad-hoc list instead of the universe (no lane receipt)")
    a = ap.parse_args(argv)
    symbols = [s for s in (a.symbols or "").split(",") if s] or None
    started = now_iso()
    if a.dry_run:
        out = run(dry_run=True, limit=a.limit, symbols=symbols)
        emit(LANE_ID, "dry_run", out["output"], started_at=started)
        return 0
    try:
        out = run(limit=a.limit, symbols=symbols)
    except Exception as exc:  # noqa: BLE001 -- recorded, then a non-zero exit
        if not symbols:
            write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                               script="scripts/indicator_engine.py", error=f"{type(exc).__name__}: {exc}")
        raise
    ok = work_ok(out)
    if not symbols:
        write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=started,
                           script="scripts/indicator_engine.py", summary=out,
                           error=None if ok else "no confluence row landed")
    emit(LANE_ID, "live", out["output"], started_at=started)
    return 0 if ok else 1
