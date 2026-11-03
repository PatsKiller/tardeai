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
import re
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


def account_aliases() -> dict[str, str]:
    """Registry key -> the short account name served readers use (config/account_display_names.json aliases)."""
    try:
        config = json.loads((Path(__file__).resolve().parents[1] / "config/account_display_names.json")
                            .read_text(encoding="utf-8"))
        return {registry: short for short, registry in (config.get("aliases") or {}).items()}
    except Exception:  # noqa: BLE001 - no mapping is a stated pass-through, never an invented name
        return {}


def build_account_summaries(rows: list[dict[str, Any]], *, generated_at: datetime,
                            aliases: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Classified account_summaries through the EXISTING classifier, so the export is a usable Step 3 fallback."""
    aliases = aliases or {}
    try:
        from lib.account_state import classify_account_state  # type: ignore
    except ImportError:  # pragma: no cover - imported as scripts.<module>
        from scripts.lib.account_state import classify_account_state  # type: ignore
    try:
        from lib.cio_domain_registry import CIODomainRegistry  # type: ignore
        market_only = CIODomainRegistry.load().get("portfolio").freshness_market_hours_only is True
    except Exception:  # noqa: BLE001
        market_only = False
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("account_key")), []).append(row)
    summaries: dict[str, dict[str, Any]] = {}
    for key, group in groups.items():
        stamps = []
        total = 0.0
        for row in group:
            as_of = row.get("as_of")
            if isinstance(as_of, datetime):
                stamps.append(as_of.astimezone(timezone.utc))
            value = _number(row.get("broker_market_value"))
            if value is not None:
                total += value
        newest = max(stamps) if stamps else None
        # `market_hours_only` arrives with #2524; call it only where the classifier accepts it so this
        # module works on main and after that merge.
        import inspect
        kwargs = {"sync_kind": "api", "last_sync_at": newest, "now": generated_at}
        if "market_hours_only" in inspect.signature(classify_account_state).parameters:
            kwargs["market_hours_only"] = market_only
        block = classify_account_state(**kwargs)
        summaries[aliases.get(key, key)] = {
            "account_key": key,
            "state": block.get("state"),
            "total_value": round(total, 2),
            "source": "positions_current",
            "account_state": {name: block.get(name) for name in
                              ("state", "state_reason", "state_as_of", "last_sync_at", "last_sync_age_hours")},
        }
    return summaries


def run_binding(conn, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind the export to one COMPLETE, PROMOTED positions_sync_runs receipt.

    positions_current is only trustworthy as the output of a run that finished complete and was promoted, with
    one row per expected account/position. A missing, partial or mixed receipt refuses the export rather than
    replacing a full book with a partial one.
    """
    try:
        cur = conn.cursor()
        cur.execute("""SELECT run_id, finished_at, accounts_ok, position_rows
                         FROM positions_sync_runs
                        WHERE status = 'complete' AND promoted = TRUE
                     ORDER BY finished_at DESC NULLS LAST LIMIT 1""")
        row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        raise ExportError(f"positions_sync_runs is unreachable: {type(exc).__name__}") from exc
    if not row:
        raise ExportError("no complete, promoted positions sync run to bind the export to")
    run_id, finished_at, accounts_ok, position_rows = row
    accounts = {r.get("account_key") for r in rows}
    if not accounts_ok:
        raise ExportError("the promoted run recorded no successful accounts")
    missing = accounts - set(accounts_ok)
    if missing:
        raise ExportError(f"positions_current holds accounts the promoted run did not confirm: {sorted(missing)[:5]}")
    if int(position_rows or 0) != len(rows):
        raise ExportError(f"row count mismatch: run {run_id} wrote {position_rows}, positions_current has {len(rows)}")
    return {"run_id": int(run_id), "finished_at": finished_at, "accounts": sorted(accounts_ok),
            "position_rows": int(position_rows)}


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
                    gaps: list[str] | None = None,
                    account_summaries: Mapping[str, dict[str, Any]] | None = None,
                    aliases: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Pure: build the holdings document from the DB rows. No file is read."""
    quotes, profiles, lookthrough = quotes or {}, profiles or {}, lookthrough or {}
    aliases = aliases or {}
    gaps = list(gaps or [])
    holdings: list[dict[str, Any]] = []
    total_value = 0.0
    total_cash = 0.0
    day_change = 0.0
    day_change_known = False
    newest: datetime | None = None
    for row in rows:
        # A partial book is worse than a refusal: a non-cash row with an unusable quantity or no market
        # value cannot be rendered as a fact. Cash rows must still carry a value.
        qty = _number(row.get("qty"))
        market_value = _number(row.get("broker_market_value"))
        if qty is None or market_value is None:
            raise ExportError(f"unusable position numerics for {row.get('account_key')}:{row.get('symbol')}")
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
            "account": aliases.get(str(row.get("account_key")), row.get("account_key")),
            "account_id": aliases.get(str(row.get("account_key")), row.get("account_key")),
            "account_key": row.get("account_key"),
            "broker": row.get("broker"),
            "shares": qty,
            "quantity": qty,
            "cost_basis_total": cost_basis,
            "cost_basis": cost_basis,   # served readers (value_and_pl) read this name
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
        # Portfolio day change from the same DB quotes: qty × (price − prior close). Unknown marks
        # contribute nothing and leave the field null rather than a fabricated zero.
        price = _number(quote.get("price"))
        prior = _number(quote.get("reference_close"))
        if not is_cash and price is not None and prior is not None:
            day_change += qty * (price - prior)
            day_change_known = True
    newest_stamp = _iso(newest) if newest is not None else None
    return {
        "schema": SCHEMA,
        "generated_at": _iso(generated_at),
        "as_of": newest_stamp,
        "source": "positions_current",
        "gaps": gaps,
        "account_summaries": dict(account_summaries or {}),
        "holdings": holdings,
        "portfolio_totals": {
            "as_of": newest_stamp,
            "total_value": round(total_value, 2),
            "total_cash": round(total_cash, 2),
            "day_change": round(day_change, 2) if day_change_known else None,
            "day_change_pct": (round(day_change / (total_value - day_change) * 100.0, 2)
                               if day_change_known and (total_value - day_change) else None),
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
def _archive(directory: Path, path: Path) -> None:
    """Retention moves an own snapshot into `archive/`; it never unlinks. Deletion belongs to the cleaner."""
    target = directory / "archive"
    target.mkdir(parents=True, exist_ok=True)
    dest = target / path.name
    if dest.exists():
        dest = target / f"{path.stem}-{secrets.token_hex(3)}{path.suffix}"
    os.replace(path, dest)


def _prune(directory: Path, keep: int, prefix: str, *, protect: Path | None = None) -> list[Path]:
    files = [p for p in _own_backups(directory) if p.name.startswith(prefix)]
    removed = files[:-keep] if keep > 0 else files
    removed = [p for p in removed if protect is None or p != protect]
    for path in removed:
        try:
            _archive(directory, path)
        except OSError:
            pass
    return removed


# STRICT names only: a foreign file that happens to share the prefix (e.g. holdings-hourly-FOREIGN.json)
# is neither trimmed nor allowed to displace the snapshot just written.
OWN_HOURLY = re.compile(r"^holdings-hourly-\d{8}T\d{2}\.json$")
OWN_DAILY = re.compile(r"^holdings-daily-\d{8}\.json$")


def _own_backups(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [p for p in directory.iterdir()
             if p.is_file() and (OWN_HOURLY.match(p.name) or OWN_DAILY.match(p.name))]
    return sorted(files, key=lambda p: p.name)


def _enforce_size_cap(directory: Path, cap: int, *, protect: Path | None = None) -> list[Path]:
    # ONLY this module's own snapshots: an unrelated *.json in the backups directory is never a candidate.
    files = sorted(_own_backups(directory), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files if p.exists())
    removed: list[Path] = []
    for path in files:
        if total <= cap:
            break
        if protect is not None and path == protect:
            continue
        try:
            size = path.stat().st_size
            _archive(directory, path)
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
    removed = _prune(backups, hourly_keep, "holdings-hourly-", protect=hourly)
    removed += _prune(backups, daily_keep, "holdings-daily-", protect=daily)
    removed += _enforce_size_cap(backups, size_cap_bytes, protect=hourly)
    return {"hourly": str(hourly), "daily": str(daily), "pruned": [str(p) for p in removed]}


# ── export ─────────────────────────────────────────────────────────────────────
def export(*, conn, store: Path | str | None = None, backups: Path | str | None = None,
           state_root: Path | str | None = None, now: datetime | None = None,
           hourly_keep: int = DEFAULT_HOURLY_KEEP, daily_keep: int = DEFAULT_DAILY_KEEP,
           size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES, dry_run: bool = False) -> dict[str, Any]:
    """Render from the DB and atomically replace the store. Never reads the store as input.

    `dry_run=True` runs the identical query/join/validation/binding path and stops before any write.
    """
    now = now or datetime.now(timezone.utc)
    store = Path(store) if store is not None else store_path(state_root)
    backups = Path(backups) if backups is not None else store.parent / "backups"
    rows = positions_rows(conn)              # refusal happens here, before any write
    if not rows:
        raise ExportError("positions_current returned no rows; refusing to replace the store")
    binding = run_binding(conn, rows)
    # Refuse an aliased destination: the resolved store must stay under the resolved state root.
    root_hint = Path(state_root).expanduser() if state_root is not None else default_state_root()
    resolved_store, resolved_root = Path(os.path.realpath(store)), Path(os.path.realpath(root_hint))
    if not resolved_store.is_relative_to(resolved_root):
        raise ExportError(f"store escapes the state root: {resolved_store} not under {resolved_root}")
    resolved_backups = Path(os.path.realpath(backups))
    if not resolved_backups.is_relative_to(resolved_root):
        raise ExportError(f"backups directory escapes the state root: {resolved_backups} not under {resolved_root}")
    aliases = account_aliases()
    summaries = build_account_summaries(rows, generated_at=now, aliases=aliases)
    symbols = [r.get("symbol") for r in rows]
    quotes = quote_rows(conn)
    profiles = profile_rows(conn, symbols)
    lookthrough, lookthrough_gap = lookthrough_rows(conn, [s for s in symbols if s])
    gaps = [g for g in (lookthrough_gap,) if g]
    document = render_document(rows, generated_at=now, quotes=quotes, profiles=profiles,
                               lookthrough=lookthrough, gaps=gaps, account_summaries=summaries,
                               aliases=aliases)
    document["sync_run_id"] = binding["run_id"]
    text = json.dumps(document, indent=1, sort_keys=True) + "\n"
    if dry_run:
        return {"ok": True, "dry_run": True, "store": str(store), "bytes": len(text),
                "holdings": len(document["holdings"]), "generated_at": document["generated_at"],
                "sync_run_id": binding["run_id"]}
    # Backup first: if the backup cannot be written or read back, the current file is never replaced.
    retention = write_backups(text, backups, now=now, hourly_keep=hourly_keep,
                              daily_keep=daily_keep, size_cap_bytes=size_cap_bytes)
    if not Path(retention["hourly"]).exists() or Path(retention["hourly"]).stat().st_size == 0:
        raise ExportError("backup was not durably written; the current store was left untouched")
    atomic_write(store, text)
    return {"ok": True, "store": str(store), "bytes": len(text),
            "holdings": len(document["holdings"]), "generated_at": document["generated_at"],
            "sync_run_id": binding["run_id"],
            "retention": retention}


# ── freshness alert ───────────────────────────────────────────────────────────
def export_age_minutes(store: Path | str, *, now: datetime) -> float | None:
    """Age from the document's own generated_at clock (mtime only as a fallback): touching a stale file
    must not make it read fresh."""
    try:
        document = json.loads(Path(store).read_text(encoding="utf-8"))
        generated = document.get("generated_at")
        if isinstance(generated, str) and generated:
            born = datetime.fromisoformat(generated.replace("Z", "+00:00"))
            if born.tzinfo is None:
                born = born.replace(tzinfo=timezone.utc)
            return round((now - born).total_seconds() / 60.0, 1)
    except Exception:  # noqa: BLE001 - unreadable falls back to mtime, then to None
        pass
    try:
        mtime = Path(store).stat().st_mtime
    except OSError:
        return None
    return round((now - datetime.fromtimestamp(mtime, timezone.utc)).total_seconds() / 60.0, 1)


def in_market_hours(now: datetime) -> bool:
    """Official NYSE session bounds when the calendar is available; weekday/time only as a stated fallback."""
    et = now.astimezone(ET)
    try:
        from lib.cio_market_session import get_session_service  # type: ignore
        service = get_session_service()
        if not service.is_trading_day(et.date()):
            return False
        open_dt, close_dt, _early = service.official_bounds(et.date())
        if open_dt is not None and close_dt is not None:
            return open_dt <= et <= close_dt
    except Exception:  # noqa: BLE001 - fall back to weekday arithmetic and say so in the alert result
        pass
    return et.weekday() < 5 and MARKET_OPEN <= et.time() <= MARKET_CLOSE


def consecutive_sync_failures(conn) -> int:
    """How many of the two most recent finished sync runs failed (2 = the operator's page condition)."""
    try:
        cur = conn.cursor()
        cur.execute("""SELECT status FROM positions_sync_runs
                        WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 2""")
        rows = [r[0] for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return 0
    return sum(1 for status in rows if status in ("failed", "partial"))


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
    document: dict[str, Any] = {}
    empty = True
    try:
        document = json.loads(Path(store).read_text(encoding="utf-8"))
        empty = not (document.get("holdings") or [])
    except Exception:  # noqa: BLE001 - missing/corrupt is the "not a valid export" case
        empty = True
    sync_failures = consecutive_sync_failures(conn) if conn is not None else 0
    sync_bad = sync_failures >= 2
    mismatch = None
    if conn is not None and not empty:
        db_total = db_total_value(conn)
        rendered = (document.get("portfolio_totals") or {}).get("total_value")
        if db_total is not None and isinstance(rendered, (int, float)):
            delta = abs(float(rendered) - db_total)
            mismatch = round(delta, 2) if delta > 1.0 else None
    if not empty and mismatch is None and not sync_bad and not in_market_hours(now):
        return {"status": "outside_market_hours", "age_minutes": age, "sent": False}
    if not empty and mismatch is None and not sync_bad and age is not None and age <= max_age_minutes:
        try:
            if state_root is not None:
                root_real = Path(os.path.realpath(Path(state_root).expanduser()))
                marker = Path(store).parent / "backups" / ".alert-episode.json"
                if Path(os.path.realpath(marker)).is_relative_to(root_real):
                    marker.unlink()
            else:
                (Path(store).parent / "backups" / ".alert-episode.json").unlink()
        except OSError:
            pass
        return {"status": "fresh", "age_minutes": age, "sent": False}
    # Episode dedupe: one page per distinct episode, reset on recovery. Undelivered sends retry next run.
    episode_file: Path | None = Path(store).parent / "backups" / ".alert-episode.json"
    if state_root is not None:
        root_real = Path(os.path.realpath(Path(state_root).expanduser()))
        if not Path(os.path.realpath(episode_file)).is_relative_to(root_real):
            episode_file = None  # never write alert state outside an explicit state root
    episode = (f"{document.get('generated_at') or 'missing'}|empty={empty}|delta={mismatch}"
               f"|sync_failures={sync_failures}|stale={age is not None and age > max_age_minutes}")
    if episode_file is not None:
        try:
            if json.loads(episode_file.read_text(encoding="utf-8")).get("episode") == episode:
                return {"status": "already_alerted", "age_minutes": age, "sent": False, "episode": episode}
        except Exception:  # noqa: BLE001 - no prior episode
            pass
    if send is None:
        try:
            from telegram_alert import send_telegram_outcome as send  # type: ignore
        except ModuleNotFoundError:
            from scripts.telegram_alert import send_telegram_outcome as send  # type: ignore
    why = ("the export is empty or unreadable" if empty else
           f"{sync_failures} consecutive positions-sync runs failed" if sync_bad else
           f"totals differ from the DB by ${mismatch}" if mismatch is not None else
           f"the export is {'missing' if age is None else f'{age} min old'}")
    text = (f"*[{priority}] holdings export needs attention*\n"
            f"{why} (threshold: {max_age_minutes} min in market hours, $1 totals delta).")
    try:
        outcome = send(text, priority=priority)
        delivered = outcome is True or (isinstance(outcome, Mapping) and outcome.get("delivered") is True)
    except Exception as exc:  # noqa: BLE001 — an alert failure must not mask the export state
        return {"status": "send_error", "age_minutes": age, "sent": False, "error_type": type(exc).__name__}
    if delivered and episode_file is not None:
        try:
            episode_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(episode_file, json.dumps({"episode": episode, "at": _iso(now)}) + "\n")
        except OSError:
            pass
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
        # The SAME query/join/binding/validation path as --apply, stopping before any write.
        store = Path(args.store) if args.store else store_path()
        backups = Path(args.backups) if args.backups else store.parent / "backups"
        try:
            conn = _connect()
            try:
                receipt = export(conn=conn, store=store, backups=backups, dry_run=True)
            finally:
                _close(conn)
        except ExportError as exc:
            print(f"holdings-export: REFUSED — {exc}", file=sys.stderr)
            return 1
        print(json.dumps(receipt, indent=1, sort_keys=True) if args.json else
              f"holdings-export: dry run OK, {receipt['holdings']} rows, run {receipt['sync_run_id']}")
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
    """Read-only, REPEATABLE READ session: every SELECT in one export sees one snapshot (no credential in code)."""
    from lib.cio_market_context_state import connect_trade_ai_readonly  # type: ignore
    conn = connect_trade_ai_readonly()
    conn.set_session(isolation_level="REPEATABLE READ", readonly=True, autocommit=False)
    return conn


def _close(conn) -> None:
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        pass
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    raise SystemExit(main())
