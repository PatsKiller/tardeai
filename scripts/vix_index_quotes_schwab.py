#!/usr/bin/env python3
"""Continuous Schwab VIX index quotes, every 15 min across the whole weekday (LQ-20261107-1669).

Operator order 2026-11-09 14:50 ET: VIX refreshes at least every 15 min overnight, pre-market, regular and after-hours,
with no gap at a session boundary. The off-hours lane already FETCHES a fresh $VIX in those slots. Its store
(market_quotes_extended) cannot hold a regular-session row or a reference-less pre-market/after-hours row, so every
such print was refused. This lane writes the index level alone, in every session, through the market_quotes writer
(config/vix_index_quotes.yaml says why).

What it reads: the off-hours lane's own ``live_fetch``: GET ``/marketdata/v1/quotes`` only, the stored access token
only while fresh, never a refresh, never ``schwab_transport``, never an account, order, stop, 2FA or auth endpoint.
Every configured symbol must come back as assetMainType INDEX, or it is refused by name.

    python3 scripts/vix_index_quotes_schwab.py --dry-run --fixture F [--now ISO]   # parse a recorded payload; no DB, no net
    python3 scripts/vix_index_quotes_schwab.py --apply                            # live (only when enabled)

A dry run is fixtures-only: without ``--fixture`` it refuses rather than call Schwab.

Receipt (stdout, one JSON object per fire): ``VixIndexQuoteRun@v1`` with the 15-min ``slot`` and, per symbol, one of
  written    -- a print newer than the stored one, no older than max_trade_age_minutes;
  unchanged  -- the print is already stored (the provider has not moved the index since);
  stale_print -- the print is older than max_trade_age_minutes (Cboe is not calculating the index), not written;
  refused:<reason> -- not an index, no price/time, a future timestamp, a provider error.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SCHEMA = "VixIndexQuoteRun@v1"
CONFIG_PATH = ROOT / "config" / "vix_index_quotes.yaml"
ET = ZoneInfo("America/New_York")
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    import yaml

    cfg = yaml.safe_load(Path(path or CONFIG_PATH).read_text()) or {}
    if cfg.get("schema") != "VixIndexQuotes@v1":
        raise ValueError(f"config schema {cfg.get('schema')!r} is not VixIndexQuotes@v1")
    syms = cfg.get("symbols") or []
    if not syms or any(not str(s).startswith("$") for s in syms):
        raise ValueError("symbols must be a non-empty list of $-prefixed index symbols")
    return cfg


def _hhmm(text: str) -> time:
    h, m = str(text).split(":")
    return time(int(h), int(m))


def in_window(now: datetime, cfg: dict[str, Any]) -> tuple[bool, str]:
    """True inside the continuous ET span (default Sunday 18:00 to Friday 20:00)."""
    w = cfg.get("window") or {}
    et = now.astimezone(ET)
    minute = lambda d, t: d * 1440 + t.hour * 60 + t.minute  # noqa: E731 -- minutes since Monday 00:00
    start = minute(_DAYS[str(w.get("start_day", "sun"))], _hhmm(w.get("start", "18:00")))
    end = minute(_DAYS[str(w.get("end_day", "fri"))], _hhmm(w.get("end", "20:00")))
    at = minute(et.weekday(), et.time())
    inside = (start <= at < end) if start < end else (at >= start or at < end)
    return inside, ("in_window" if inside else "outside_window")


def slot_of(now: datetime, cadence_minutes: int = 15) -> str:
    """The ET cadence slot a fire belongs to, e.g. ``2026-11-09T14:45`` for a 14:47 fire."""
    et = now.astimezone(ET)
    floored = et - timedelta(minutes=et.minute % cadence_minutes, seconds=et.second, microseconds=et.microsecond)
    return floored.strftime("%Y-%m-%dT%H:%M")


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _ts(value: Any) -> datetime | None:
    """Schwab tradeTime is epoch milliseconds; an ISO string is accepted for recorded fixtures."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def parse_payload(payload: Any, now: datetime, cfg: dict[str, Any],
                  last_stored: dict[str, datetime | None]) -> tuple[list[dict], list[dict]]:
    """Schwab quotes payload -> (rows for market_quotes, one receipt entry per configured symbol)."""
    max_age = float(cfg.get("max_trade_age_minutes", 30))
    blocks = payload if isinstance(payload, dict) else {}
    rows: list[dict] = []
    entries: list[dict] = []
    for sym in [str(s).upper() for s in cfg["symbols"]]:
        blk = blocks.get(sym)
        entry: dict[str, Any] = {"symbol": sym}
        entries.append(entry)
        if not isinstance(blk, dict) or not isinstance(blk.get("quote"), dict):
            entry["status"] = "refused:not_in_payload" if blk is None else "refused:not_a_quote"
            continue
        asset = str(blk.get("assetMainType") or "")
        if asset.upper() != "INDEX":  # verify, never assume: a fund under a $ symbol is not the index level
            entry["status"] = f"refused:index_asset_type_{asset.strip().lower() or 'missing'}"
            continue
        q = blk["quote"]
        price, at = _num(q.get("lastPrice")), _ts(q.get("tradeTime"))
        if price is None or at is None:
            entry["status"] = "refused:no_trade_price_or_time"
            continue
        age = (now - at).total_seconds() / 60.0
        entry.update({"price": price, "print_at": at.isoformat(), "age_minutes": round(age, 1)})
        if age < -5:
            entry["status"] = "refused:future_timestamp"
        elif age > max_age:
            entry["status"] = "stale_print"
        elif last_stored.get(sym) is not None and at <= last_stored[sym]:
            entry["status"] = "unchanged"
        else:
            entry["status"] = "written"
            rows.append({"symbol": sym, "price": price, "fetched_at": at})
    return rows, entries


def run(*, cfg: dict[str, Any], now: datetime, fetch: Callable[[list[str]], Any],
        read_last: Callable[[list[str]], dict[str, datetime | None]],
        write: Callable[[list[dict]], dict] | None, dry_run: bool, force_window: bool = False) -> dict[str, Any]:
    """One fire. ``fetch``, ``read_last`` and ``write`` are injected so tests and emulation never reach Schwab or a DB."""
    receipt: dict[str, Any] = {"schema": SCHEMA, "provider": "schwab", "store": cfg.get("store", "market_quotes"),
                               "now": now.isoformat(), "slot": slot_of(now, int(cfg.get("cadence_minutes", 15))),
                               "dry_run": dry_run, "inserted": 0, "symbols": []}
    ok, why = in_window(now, cfg)
    receipt["window"] = why
    if not ok and not force_window:
        receipt["status"] = "outside_window"
        return receipt
    syms = [str(s).upper() for s in cfg["symbols"]]
    payload = fetch(syms)
    if isinstance(payload, dict) and payload.get("_status"):
        receipt["status"] = str(payload["_status"])
        receipt["detail"] = payload.get("_detail")
        return receipt
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if not str(k).startswith("_")}
    rows, entries = parse_payload(payload, now, cfg, read_last(syms))
    receipt["symbols"] = entries
    if rows and not dry_run and write is not None:
        wr = write(rows)
        receipt["inserted"] = int(wr.get("rows_written", 0))
        receipt["write"] = wr
    elif dry_run:
        receipt["would_insert"] = len(rows)
    vix = next((e for e in entries if e["symbol"] == "$VIX"), {})
    receipt["status"] = "ok" if vix.get("status") in ("written", "unchanged") else f"vix_{vix.get('status', 'absent')}"
    return receipt


def _read_last(symbols: list[str], source: str) -> dict[str, datetime | None]:
    from db_adapter import _get_conn

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT symbol, max(fetched_at) FROM market_quotes WHERE symbol = ANY(%s) AND source = %s "
                    "GROUP BY symbol", (symbols, source))
        got = {str(s).upper(): t for s, t in cur.fetchall()}
        conn.rollback()
    finally:
        conn.close()
    return {s: got.get(s) for s in symbols}


def _write(rows: list[dict], source: str) -> dict:
    from db_adapter import _get_conn
    from lib.writers.market_quotes_writer import write_market_quotes

    conn = _get_conn()
    try:
        rc = write_market_quotes(conn, rows, source=source, resolve_identity=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"rows_written": rc.rows_written, "rows_accepted": rc.rows_accepted,
            "rejected": [str(r) for r in getattr(rc, "rejected", [])][:10]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--fixture", help="recorded Schwab quotes payload (JSON); required for --dry-run")
    ap.add_argument("--now", help="ISO instant for a dry run (default: now)")
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if args.dry_run:
        if not args.fixture:
            print(json.dumps({"schema": SCHEMA, "status": "refused", "detail": "--dry-run needs --fixture"}))
            return 2
        payload = json.loads(Path(args.fixture).read_text())
        receipt = run(cfg=cfg, now=now, fetch=lambda _s: payload, read_last=lambda s: {x: None for x in s},
                      write=None, dry_run=True)
    else:
        if not cfg.get("enabled"):
            print(json.dumps({"schema": SCHEMA, "status": "disabled", "now": now.isoformat(),
                              "detail": "config/vix_index_quotes.yaml enabled: false (operator approval pending)"}))
            return 0
        import market_quotes_offhours_schwab as lane  # the one token-safe Schwab market-data read

        src = str(cfg.get("source", "schwab"))
        receipt = run(cfg=cfg, now=now, fetch=lambda s: lane.live_fetch(s, cfg),
                      read_last=lambda s: _read_last(s, src), write=lambda r: _write(r, src), dry_run=False)
    print(json.dumps(receipt, default=str, indent=1))
    return 0 if receipt.get("status") in ("ok", "outside_window", "disabled") or str(
        receipt.get("status", "")).startswith("vix_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
