"""holds_export — render holdings.json FROM the DB (generated, self-healing backup).

Operator 2026-11-03: the DB `positions_current` is the holdings source of truth; holdings.json becomes a
generated backup. This writer is the only thing that writes that file.

Rules this module enforces:
  * The document is rendered from `positions_current` and NOTHING else. The existing file is never opened,
    read or merged — a 0-byte or corrupt file is simply replaced by the next good render.
  * Writes are atomic: unique temp in the target directory, fsync, os.replace, mode 600.
  * If the DB read fails or returns no rows, the export REFUSES and the last good file is left untouched.
  * Retention: the last 48 hourly snapshots and 30 daily snapshots under `state/backups/`, size-capped.
  * A Telegram P1 is sent when the export is older than 30 minutes during US market hours.

READ_ONLY_ADVISORY: no broker call, no credential, no order, no schedule install. The systemd unit that
runs it is a proposal in ops/systemd/ and is operator-installed (§17).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import sys
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

SCHEMA = "HoldingsExport@v1"
STORE_REL = ("data", "portfolios", "state", "holdings.json")
DEFAULT_HOURLY_KEEP = 48
DEFAULT_DAILY_KEEP = 30
DEFAULT_SIZE_CAP_BYTES = 64 * 1024 * 1024
FILE_MODE = 0o600
ET = ZoneInfo("America/New_York")
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)
DEFAULT_MAX_AGE_MINUTES = 30


class ExportError(RuntimeError):
    """The export refused. Nothing was written; the last good file is intact."""


# ── paths ────────────────────────────────────────────────────────────────────────
def default_state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT") or os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    return Path(env).expanduser() if env else Path("~/trade-ai-releases/persistent-state").expanduser()


def store_path(state_root: Path | str | None = None) -> Path:
    root = Path(state_root).expanduser() if state_root is not None else default_state_root()
    return root.joinpath(*STORE_REL)


def backups_dir(state_root: Path | str | None = None) -> Path:
    return store_path(state_root).parent / "backups"


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ── render ──────────────────────────────────────────────────────────────────────
def positions_rows(conn) -> list[dict[str, Any]]:
    """Read `positions_current` through the caller's connection. Raises ExportError on any DB failure."""
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT account_key, symbol, broker, qty, cost_basis_total, avg_cost, broker_market_value,
                      is_cash, asset_type, source, as_of
                 FROM positions_current
             ORDER BY account_key, symbol""")
        columns = [d[0] for d in (cur.description or [])]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001 — a DB failure is a refusal, never a partial document
        raise ExportError(f"positions_current is unreachable: {type(exc).__name__}") from exc
    return rows


def quote_rows(conn) -> dict[str, dict[str, Any]]:
    """Latest extended-session quote per symbol (price, price time, session, prior close, day change)."""
    try:
        cur = conn.cursor()
        cur.execute("""SELECT DISTINCT ON (symbol) symbol, price, bar_end, inserted_at, session,
                              reference_close, reference_basis, change_pct, feed
                         FROM market_quotes_extended ORDER BY symbol, inserted_at DESC""")
        columns = [d[0] for d in (cur.description or [])]
        return {row[0]: dict(zip(columns, row)) for row in cur.fetchall()}
    except Exception:  # noqa: BLE001 - an enrichment gap is stated on the row, never invented
        return {}


def profile_rows(conn, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Sector/industry and their provenance from symbol_profiles."""
    wanted = sorted({s for s in symbols if isinstance(s, str) and s})
    if not wanted:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("""SELECT symbol, sector, industry, source, updated_at
                         FROM symbol_profiles WHERE symbol = ANY(%s)""", (wanted,))
        columns = [d[0] for d in (cur.description or [])]
        return {row[0]: dict(zip(columns, row)) for row in cur.fetchall()}
    except Exception:  # noqa: BLE001
        return {}


def lookthrough_rows(conn, etfs: Iterable[str]) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    """Fund look-through from etf_holdings_snapshot, or ( {}, reason ) when the table is not applied."""
    wanted = sorted({e for e in etfs if isinstance(e, str) and e})
    if not wanted:
        return {}, None
    try:
        cur = conn.cursor()
        cur.execute("SELECT to_regclass('etf_holdings_snapshot')")
        if cur.fetchone()[0] is None:
            return {}, "fund look-through unavailable: etf_holdings_snapshot is not applied (migration 2026_10_31_etf_holdings_snapshot.sql)"
        cur.execute("""SELECT etf, holding, name, weight, as_of, source
                         FROM etf_holdings_snapshot WHERE etf = ANY(%s) ORDER BY etf, weight DESC""", (wanted,))
        columns = [d[0] for d in (cur.description or [])]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in cur.fetchall():
            item = dict(zip(columns, row))
            item["as_of"] = _iso(item["as_of"]) if isinstance(item["as_of"], datetime) else item["as_of"]
            grouped.setdefault(item.pop("etf"), []).append(item)
        return grouped, None
    except Exception as exc:  # noqa: BLE001
        return {}, f"fund look-through unavailable: {type(exc).__name__}"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def render_document(rows: Iterable[Mapping[str, Any]], *, generated_at: datetime,
                    quotes: Mapping[str, Mapping[str, Any]] | None = None,
                    profiles: Mapping[str, Mapping[str, Any]] | None = None,
                    lookthrough: Mapping[str, list[dict[str, Any]]] | None = None,
                    gaps: list[str] | None = None) -> dict[str, Any]:
    """Pure: build the holdings document from the DB rows. No file is read."""
    quotes, profiles, lookthrough = quotes or {}, profiles or {}, lookthrough or {}
    gaps = list(gaps or [])
    holdings: list[dict[str, Any]] = []
    total_value = 0.0
    total_cash = 0.0
    newest: datetime | None = None
    for row in rows:
        qty = _number(row.get("qty")) or 0.0
        market_value = _number(row.get("broker_market_value"))
        cost_basis = _number(row.get("cost_basis_total"))
        is_cash = bool(row.get("is_cash"))
        as_of = row.get("as_of")
        if isinstance(as_of, datetime):
            stamp = as_of
        elif isinstance(as_of, str) and as_of:
            try:
                stamp = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            except ValueError:
                stamp = None
        else:
            stamp = None
        if stamp is not None and (newest is None or stamp > newest):
            newest = stamp
        symbol = row.get("symbol")
        quote = quotes.get(symbol) or {}
        profile = profiles.get(symbol) or {}
        holdings.append({
            "symbol": symbol,
            "account": row.get("account_key"),
            "account_id": row.get("account_key"),
            "broker": row.get("broker"),
            "shares": qty,
            "quantity": qty,
            "cost_basis_total": cost_basis,
            "avg_cost": _number(row.get("avg_cost")),
            "market_value": market_value,
            "is_cash": is_cash,
            "asset_type": row.get("asset_type"),
            "source": row.get("source"),
            "as_of": _iso(stamp) if stamp is not None else None,
            # A: descriptive metadata with its own provenance; a gap is stated, never invented.
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "profile_source": profile.get("source") if profile else "unavailable",
            "profile_updated_at": (_iso(profile["updated_at"]) if isinstance(profile.get("updated_at"), datetime)
                                   else profile.get("updated_at")) if profile else None,
            # B: the live extended quote (price, price time, session, prior close, day change).
            "price": _number(quote.get("price")),
            "price_bar_end": _iso(quote["bar_end"]) if isinstance(quote.get("bar_end"), datetime) else quote.get("bar_end"),
            "quote_inserted_at": (_iso(quote["inserted_at"]) if isinstance(quote.get("inserted_at"), datetime)
                                  else quote.get("inserted_at")),
            "quote_session": quote.get("session"),
            "prior_close": _number(quote.get("reference_close")),
            "reference_basis": quote.get("reference_basis"),
            "day_change_pct": _number(quote.get("change_pct")),
            "quote_feed": quote.get("feed"),
            "quote_source": "market_quotes_extended" if quote else "unavailable",
            "lookthrough": lookthrough.get(symbol, []),
            "lookthrough_status": ("unavailable" if lookthrough is None else
                                   ("present" if symbol in lookthrough else
                                    ("not_a_fund" if symbol not in lookthrough else "present"))),
        })
        if market_value is not None:
            total_value += market_value
            if is_cash:
                total_cash += market_value
    return {
        "schema": SCHEMA,
        "generated_at": _iso(generated_at),
        "source": "positions_current",
        "gaps": gaps,
        "holdings": holdings,
        "portfolio_totals": {
            "as_of": _iso(newest) if newest is not None else None,
            "total_value": round(total_value, 2),
            "total_cash": round(total_cash, 2),
            "positions": len(holdings),
        },
    }


# ── atomic write ───────────────────────────────────────────────────────────────
def atomic_write(path: Path | str, text: str, *, mode: int = FILE_MODE) -> Path:
    """Unique temp in the same directory, fsync, os.replace, mode 600. Never opens `path` for reading."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    os.chmod(path, mode)
    return path


# ── retention ──────────────────────────────────────────────────────────────────
def _prune(directory: Path, keep: int, prefix: str) -> list[Path]:
    files = sorted(directory.glob(f"{prefix}*.json"), key=lambda p: p.name)
    removed = files[:-keep] if keep > 0 else files
    for path in removed:
        try:
            path.unlink()
        except OSError:
            pass
    return removed


def _enforce_size_cap(directory: Path, cap: int, *, protect: Path | None = None) -> list[Path]:
    files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files if p.exists())
    removed: list[Path] = []
    for path in files:
        if total <= cap:
            break
        if protect is not None and path == protect:
            continue
        try:
            size = path.stat().st_size
            path.unlink()
            total -= size
            removed.append(path)
        except OSError:
            continue
    return removed


def write_backups(text: str, backups: Path, *, now: datetime,
                  hourly_keep: int = DEFAULT_HOURLY_KEEP, daily_keep: int = DEFAULT_DAILY_KEEP,
                  size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES) -> dict[str, Any]:
    backups.mkdir(parents=True, exist_ok=True)
    hourly = backups / f"holdings-hourly-{now.astimezone(timezone.utc):%Y%m%dT%H}.json"
    daily = backups / f"holdings-daily-{now.astimezone(timezone.utc):%Y%m%d}.json"
    atomic_write(hourly, text)
    if not daily.exists():
        atomic_write(daily, text)
    removed = _prune(backups, hourly_keep, "holdings-hourly-")
    removed += _prune(backups, daily_keep, "holdings-daily-")
    removed += _enforce_size_cap(backups, size_cap_bytes, protect=hourly)
    return {"hourly": str(hourly), "daily": str(daily), "pruned": [str(p) for p in removed]}


# ── export ─────────────────────────────────────────────────────────────────────
def export(*, conn, store: Path | str | None = None, backups: Path | str | None = None,
           state_root: Path | str | None = None, now: datetime | None = None,
           hourly_keep: int = DEFAULT_HOURLY_KEEP, daily_keep: int = DEFAULT_DAILY_KEEP,
           size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES) -> dict[str, Any]:
    """Render from the DB and atomically replace the store. Never reads the store as input."""
    now = now or datetime.now(timezone.utc)
    store = Path(store) if store is not None else store_path(state_root)
    backups = Path(backups) if backups is not None else store.parent / "backups"
    rows = positions_rows(conn)              # refusal happens here, before any write
    if not rows:
        raise ExportError("positions_current returned no rows; refusing to replace the store")
    symbols = [r.get("symbol") for r in rows]
    quotes = quote_rows(conn)
    profiles = profile_rows(conn, symbols)
    lookthrough, lookthrough_gap = lookthrough_rows(conn, [s for s in symbols if s])
    gaps = [g for g in (lookthrough_gap,) if g]
    document = render_document(rows, generated_at=now, quotes=quotes, profiles=profiles,
                               lookthrough=lookthrough, gaps=gaps)
    text = json.dumps(document, indent=1, sort_keys=True) + "\n"
    atomic_write(store, text)
    retention = write_backups(text, backups, now=now, hourly_keep=hourly_keep,
                              daily_keep=daily_keep, size_cap_bytes=size_cap_bytes)
    return {"ok": True, "store": str(store), "bytes": len(text),
            "holdings": len(document["holdings"]), "generated_at": document["generated_at"],
            "retention": retention}


# ── freshness alert ───────────────────────────────────────────────────────────
def export_age_minutes(store: Path | str, *, now: datetime) -> float | None:
    try:
        mtime = Path(store).stat().st_mtime
    except OSError:
        return None
    return round((now - datetime.fromtimestamp(mtime, timezone.utc)).total_seconds() / 60.0, 1)


def in_market_hours(now: datetime) -> bool:
    et = now.astimezone(ET)
    return et.weekday() < 5 and MARKET_OPEN <= et.time() <= MARKET_CLOSE


def db_total_value(conn) -> float | None:
    try:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(broker_market_value), 0) FROM positions_current")
        return round(float(cur.fetchone()[0]), 2)
    except Exception:  # noqa: BLE001
        return None


def maybe_alert_stale(*, store: Path | str | None = None, state_root: Path | str | None = None,
                      now: datetime | None = None, send: Callable[..., Any] | None = None,
                      max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
                      priority: str = "P1", conn=None) -> dict[str, Any]:
    """Telegram P1 when the export is empty, older than `max_age_minutes` in market hours, or its totals
    differ from the DB by more than one dollar."""
    now = now or datetime.now(timezone.utc)
    store = Path(store) if store is not None else store_path(state_root)
    age = export_age_minutes(store, now=now)
    empty = True
    try:
        document = json.loads(Path(store).read_text(encoding="utf-8"))
        empty = not (document.get("holdings") or [])
    except Exception:  # noqa: BLE001 - missing/corrupt is the "not a valid export" case
        empty = True
    mismatch = None
    if conn is not None and not empty:
        db_total = db_total_value(conn)
        rendered = (document.get("portfolio_totals") or {}).get("total_value")
        if db_total is not None and isinstance(rendered, (int, float)):
            delta = abs(float(rendered) - db_total)
            mismatch = round(delta, 2) if delta > 1.0 else None
    if not in_market_hours(now) and not empty and mismatch is None:
        return {"status": "outside_market_hours", "age_minutes": age, "sent": False}
    if not empty and mismatch is None and age is not None and age <= max_age_minutes:
        return {"status": "fresh", "age_minutes": age, "sent": False}
    if send is None:
        try:
            from telegram_alert import send_telegram_outcome as send  # type: ignore
        except ModuleNotFoundError:
            from scripts.telegram_alert import send_telegram_outcome as send  # type: ignore
    why = ("the export is empty or unreadable" if empty else
           f"totals differ from the DB by ${mismatch}" if mismatch is not None else
           f"the export is {'missing' if age is None else f'{age} min old'}")
    text = (f"*[{priority}] holdings export needs attention*\n"
            f"{why} (threshold: {max_age_minutes} min in market hours, $1 totals delta).")
    try:
        outcome = send(text, priority=priority)
        delivered = outcome is True or (isinstance(outcome, Mapping) and outcome.get("delivered") is True)
    except Exception as exc:  # noqa: BLE001 — an alert failure must not mask the export state
        return {"status": "send_error", "age_minutes": age, "sent": False, "error_type": type(exc).__name__}
    return {"status": "stale_alerted", "age_minutes": age, "sent": bool(delivered)}


# ── CLI ────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="write the store and the backups")
    parser.add_argument("--dry-run", action="store_true", help="render and print, write nothing")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--store")
    parser.add_argument("--backups")
    args = parser.parse_args(argv)

    if args.dry_run:
        conn = _connect()
        try:
            rows = positions_rows(conn)
            document = render_document(rows, generated_at=datetime.now(timezone.utc))
        finally:
            _close(conn)
        print(json.dumps(document, indent=1, sort_keys=True))
        return 0

    if not args.apply:
        parser.error("choose --apply or --dry-run")

    store = Path(args.store) if args.store else store_path()
    backups = Path(args.backups) if args.backups else store.parent / "backups"
    try:
        conn = _connect()
        try:
            receipt = export(conn=conn, store=store, backups=backups)
        finally:
            _close(conn)
        alert = maybe_alert_stale(store=store)
    except ExportError as exc:
        # A refusal leaves the last good file untouched; the freshness check still pages if it is stale.
        alert = maybe_alert_stale(store=store)
        receipt = {"ok": False, "refused": str(exc), "store": str(store), "alert": alert}
        print(json.dumps(receipt, indent=1, sort_keys=True) if args.json else
              f"holdings-export: REFUSED — {exc}; last good file kept", file=sys.stderr)
        return 1
    receipt["alert"] = alert
    if args.json:
        print(json.dumps(receipt, indent=1, sort_keys=True))
    else:
        print(f"holdings-export: {receipt['holdings']} rows, {receipt['bytes']} bytes, "
              f"generated {receipt['generated_at']}")
    return 0


def _connect():
    """Read-only DB session from the runtime environment (no credential is written in code)."""
    from lib.cio_market_context_state import connect_trade_ai_readonly  # type: ignore
    return connect_trade_ai_readonly()


def _close(conn) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    raise SystemExit(main())
