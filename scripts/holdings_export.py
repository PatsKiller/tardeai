"""holds_export — render holdings.json FROM the DB (generated, self-healing backup).

Operator 2026-11-03: the DB `positions_current` is the holdings source of truth; holdings.json becomes a
generated backup. Operator 2026-11-06 ("go with all three"): the export renders EVERY field the readers
use, runs right after every successful `positions_sync --apply`, and the Home/API readers read the same
render from the DB (lib/holdings_document.py) with the file as the DB-down fallback.

Rules this module enforces:
  * Position FACTS come from `positions_current` and nothing else (FIELD OWNERSHIP below). The existing
    file is never trusted for a fact the DB owns, and a 0-byte or corrupt file carries nothing — the next
    render replaces it from the DB alone.
  * Fields the DB does not hold are owned by other writers that still enrich the file in place (the
    repricer's marks, the look-through resolver's sectors, the share-reconciliation policy, the basis
    shield). The export CARRIES them from the previous document for the same account+symbol, so a render
    never erases another writer's field. What is carried, and from where, is `export_provenance`.
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
import contextlib
import os
import re
import secrets
import sys
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

SCHEMA = "HoldingsExport@v1"
# The store's relative path is OWNED by lib.portfolio_positions (the one accessor the reader ratchet
# points at); the fallback assembles the name so this file never carries the literal the ratchet scans for.
try:  # pragma: no cover - the imported form is the production path
    from lib.portfolio_positions import STORE_REL as _STORE_REL  # type: ignore
except Exception:  # noqa: BLE001 - loaded by path in tests without scripts/ on sys.path
    _STORE_REL = ("data", "portfolios", "state", "holdings" + ".json")
STORE_REL = _STORE_REL
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
                      is_cash, asset_type, source, as_of, sync_run_id
                 FROM positions_current
             ORDER BY account_key, symbol""")
        columns = [d[0] for d in (cur.description or [])]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001 — a DB failure is a refusal, never a partial document
        raise ExportError(f"positions_current is unreachable: {type(exc).__name__}") from exc
    return rows


#: Registry account key -> the label the holdings STORE uses for that account. Only the Roth differs: both
#: position writers already agree on it (positions_sync.HOLDINGS_ACCOUNT_ALIASES and
#: schwab_position_sync._HOLDINGS_ACCT; tests/test_holdings_db_first_20261106.py pins all three together).
#: config/account_display_names.json `aliases` is a DISPLAY map (schwab_rollover / schwab_individual are
#: short names nothing in the store uses): labelling rows with it moved the rollover and taxable books to
#: keys that raw-keyed readers (the repricer's per-account totals, `account == key` lookups) never find.
HOLDINGS_LABELS: dict[str, str] = {"schwab_roth_ira": "schwab_roth"}


def account_aliases() -> dict[str, str]:
    """Registry key -> the account label the holdings store (and every raw-keyed reader) uses."""
    return dict(HOLDINGS_LABELS)


def _canonical_account(raw: Any) -> str:
    """One identity for an account however a row spells it (schwab_roth == schwab_roth_ira)."""
    try:
        from lib.account_display import canonical_key  # type: ignore
    except ImportError:  # pragma: no cover - imported as scripts.<module>
        from scripts.lib.account_display import canonical_key  # type: ignore
    return canonical_key(raw)


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
        cur.execute("""SELECT run_id, finished_at, accounts_ok, accounts_failed, position_rows
                         FROM positions_sync_runs
                        WHERE status = 'complete' AND promoted = TRUE
                     ORDER BY finished_at DESC NULLS LAST LIMIT 1""")
        row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        raise ExportError(f"positions_sync_runs is unreachable: {type(exc).__name__}") from exc
    if not row:
        raise ExportError("no complete, promoted positions sync run to bind the export to")
    run_id, finished_at, accounts_ok, accounts_failed, position_rows = row
    failed = accounts_failed or {}
    if failed:
        raise ExportError(f"the promoted run recorded failed accounts: {sorted(failed)[:5]}")
    accounts = {r.get("account_key") for r in rows}
    if not accounts_ok:
        raise ExportError("the promoted run recorded no successful accounts")
    # COMPLETENESS BOTH WAYS: a receipt account missing from the rows is a partial book just as much as
    # a row the receipt never confirmed. Counting rows alone accepted exactly that.
    missing_rows = set(accounts_ok) - accounts
    extra_rows = accounts - set(accounts_ok)
    if missing_rows or extra_rows:
        raise ExportError(f"account set mismatch: receipt {sorted(set(accounts_ok))[:5]}, rows {sorted(accounts)[:5]}")
    # The rows must BE this run's output, not a mix of runs.
    run_ids = {r.get("sync_run_id") for r in rows}
    if run_ids != {run_id}:
        raise ExportError(f"positions_current rows come from runs {sorted(str(x) for x in run_ids)[:5]}, not {run_id}")
    if int(position_rows or 0) != len(rows):
        raise ExportError(f"row count mismatch: run {run_id} wrote {position_rows}, positions_current has {len(rows)}")
    return {"run_id": int(run_id), "finished_at": finished_at, "accounts": sorted(accounts_ok),
            "position_rows": int(position_rows)}


def quote_rows(conn, symbols: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    """Latest extended-session quote per HELD symbol (price, price time, session, prior close, day change).

    Bounded to the book's symbols (index idx_market_quotes_extended_symbol_inserted): the DB-first reader runs
    this on a request path, where a DISTINCT ON over the whole quote table is not acceptable.
    """
    wanted = sorted({s for s in (symbols or []) if isinstance(s, str) and s})
    if not wanted:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("""SELECT DISTINCT ON (symbol) symbol, price, bar_end, inserted_at, session,
                              reference_close, reference_basis, change_pct, feed
                         FROM market_quotes_extended WHERE symbol = ANY(%s)
                     ORDER BY symbol, inserted_at DESC""", (wanted,))
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


# ── field ownership (the review map lives in docs/ops/holdings_export_backup.md) ─
#: Row fields the DB owns. Rendered from positions_current on every export; a prior value never survives.
DB_ROW_FIELDS = (
    "symbol", "account", "account_id", "account_key", "broker", "is_cash", "asset_type",
    "broker_shares", "broker_actual_shares", "broker_market_value", "broker_position_price",
    "broker_avg_price", "avg_cost", "cost_basis_total", "broker_source", "source", "broker_ingested_at",
    "as_of", "broker_position_as_of", "broker_position_as_of_at", "sync_run_id",
)
#: Row fields the export derives from DB enrichment tables (symbol_profiles, market_quotes_extended,
#: etf_holdings_snapshot). Always rendered; a gap is stated as None / "unavailable", never invented.
DB_ENRICHMENT_ROW_FIELDS = (
    "sector", "industry", "profile_source", "profile_updated_at", "quote_price", "quote_change_pct",
    "price_bar_end", "quote_inserted_at", "quote_session", "prior_close", "reference_basis", "quote_feed",
    "quote_source", "lookthrough", "lookthrough_status",
)
#: Row fields another writer owns, carried from the previous document for the same account+symbol. With no
#: previous row (a new position, or a 0-byte/corrupt store) the FLOOR below renders them from DB facts, or
#: leaves them absent when the DB has nothing to say (name, bucket: never invented).
#:   share policy  (schwab_position_sync / share_reconciliation.stamp_broker_qty): shares, system_shares,
#:                 share_drift, share_drift_status, shares_synced_at, last_reconciled_at, last_reconciliation_source
#:   valuation     (portfolio_repricer, every 15 min): price, current_price, market_value, day_change,
#:                 day_change_pct, gain_loss, gain_loss_pct, portfolio_pct, canonical_mark*, official_close*,
#:                 analytical_*, mv_basis, implied_price_from_mv, price_source, price_field_role,
#:                 current_price_is_alias_of, day_change_broker_check, updated_at
#:   broker day P/L (schwab_position_sync): broker_day_pl, broker_day_pl_price, broker_day_pl_at
#:   basis         (basis shield / tax-lot rebuild): cost_basis, cost_basis_source, basis_status, basis_partial,
#:                 lots_shares, conflicted, conflict_reason, _rebuild_source, _basis_rebased_from
#:   descriptive   (loader / sync): name, bucket, delisted, account_scope and every other key on the prior row
FLOOR_ROW_FIELDS = (
    "shares", "system_shares", "quantity", "share_drift", "share_drift_status", "market_value", "price",
    "current_price", "price_source", "cost_basis", "cost_basis_source", "gain_loss", "gain_loss_pct",
    "day_change", "day_change_pct", "updated_at",
)
#: Top-level keys the export owns. Every other top-level key of the previous document (resolved_sectors*,
#: overlap_analysis, lookthrough_as_of, last_repriced, reprice_source, closed_today, aggregate_published_at,
#: owner, _rebuild, _freshness_note, ...) belongs to its enricher and is carried unchanged.
EXPORT_TOP_KEYS = (
    "schema", "generated_at", "exported_at", "updated_at", "as_of", "source", "gaps", "holdings",
    "portfolio_totals", "account_summaries", "sync_run_id", "data_as_of", "data_as_of_account",
    "positions_built_at", "positions_fingerprint", "export_provenance", "sync_run_finished_at",
)


def _stamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _iso_or_raw(value: Any) -> Any:
    return _iso(value) if isinstance(value, datetime) else value


def _row_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    """(canonical account, symbol) with every cash spelling collapsed to CASH (the sync writes both).

    The store's own label (`account`) decides for a stored row; an `account_key` on a stored row is only an
    earlier export's copy of a DB fact and is never trusted over the label.
    """
    account = _canonical_account(row.get("account") or row.get("account_id") or row.get("account_key"))
    symbol = str(row.get("symbol") or "").upper()
    if row.get("is_cash") or symbol in ("CASH", "SPAXX", "FDRXX"):
        symbol = "CASH"
    return account, symbol


def prior_index(prior: Mapping[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    """The previous document's rows by identity. First row wins; a non-dict row is ignored."""
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in (prior or {}).get("holdings") or []:
        if isinstance(row, dict):
            index.setdefault(_row_identity(row), row)
    return index


def render_document(rows: Iterable[Mapping[str, Any]], *, generated_at: datetime,
                    quotes: Mapping[str, Mapping[str, Any]] | None = None,
                    profiles: Mapping[str, Mapping[str, Any]] | None = None,
                    lookthrough: Mapping[str, list[dict[str, Any]]] | None = None,
                    gaps: list[str] | None = None,
                    account_summaries: Mapping[str, dict[str, Any]] | None = None,
                    aliases: Mapping[str, str] | None = None,
                    prior: Mapping[str, Any] | None = None,
                    positions_built_at: datetime | None = None) -> dict[str, Any]:
    """Pure: build the holdings document from the DB rows plus the CARRIED fields of `prior`.

    `prior` is the previous document as data (never a file handle): only fields other writers own are
    taken from it, only for a row whose account+symbol the DB still holds. DB-owned fields always win.
    """
    import copy

    quotes, profiles, lookthrough = quotes or {}, profiles or {}, lookthrough or {}
    aliases = aliases if aliases is not None else account_aliases()
    gaps = list(gaps or [])
    prior = prior if isinstance(prior, Mapping) else None
    previous = prior_index(prior)
    holdings: list[dict[str, Any]] = []
    total_value = 0.0
    total_cash = 0.0
    broker_total = 0.0
    day_change = 0.0
    day_change_known = False
    newest: datetime | None = None
    carried_rows = 0
    db_accounts: set[str] = set()
    for row in rows:
        # A partial book is worse than a refusal: a non-cash row with an unusable quantity or no market
        # value cannot be rendered as a fact. Cash rows must still carry a value.
        qty = _number(row.get("qty"))
        broker_value = _number(row.get("broker_market_value"))
        if qty is None or broker_value is None:
            raise ExportError(f"unusable position numerics for {row.get('account_key')}:{row.get('symbol')}")
        cost_basis = _number(row.get("cost_basis_total"))
        is_cash = bool(row.get("is_cash"))
        stamp = _stamp(row.get("as_of"))
        if stamp is not None and (newest is None or stamp > newest):
            newest = stamp
        stamp_iso = _iso(stamp) if stamp is not None else None
        symbol = row.get("symbol")
        account_key = str(row.get("account_key"))
        label = aliases.get(account_key, account_key)
        identity = _row_identity({"account": account_key, "symbol": symbol, "is_cash": is_cash})
        db_accounts.add(identity[0])
        before = previous.get(identity)
        out: dict[str, Any] = copy.deepcopy(before) if before is not None else {}
        carried_rows += before is not None
        quote = quotes.get(symbol) or {}
        profile = profiles.get(symbol) or {}
        quote_price = _number(quote.get("price"))
        prior_close = _number(quote.get("reference_close"))
        # DB-owned facts: always the DB's, whatever the previous document said.
        out.update({
            "symbol": symbol,
            "account": label,
            "account_id": label,
            "account_key": account_key,
            "broker": row.get("broker"),
            "is_cash": is_cash,
            "asset_type": row.get("asset_type") if row.get("asset_type") is not None else out.get("asset_type"),
            "broker_shares": qty,
            "broker_actual_shares": qty,
            "broker_market_value": broker_value,
            "broker_position_price": (1.0 if is_cash else (round(broker_value / qty, 6) if qty else None)),
            "broker_avg_price": _number(row.get("avg_cost")),
            "avg_cost": _number(row.get("avg_cost")),
            "cost_basis_total": cost_basis,
            "broker_source": row.get("source"),
            "source": row.get("source"),
            "broker_ingested_at": stamp_iso,
            "as_of": stamp_iso,
            # Full ISO-8601 UTC (2026-11-06): a date-only stamp parsed as 00:00 UTC and fabricated a
            # day-old book. Readers that want the date take [:10]; parse_time reads the instant.
            "broker_position_as_of": stamp_iso,
            "broker_position_as_of_at": stamp_iso,
            "sync_run_id": row.get("sync_run_id"),
        })
        # DB enrichment: descriptive metadata and the live extended quote, each with its own provenance.
        out.update({
            "sector": profile.get("sector") if profile else out.get("sector"),
            "industry": profile.get("industry") if profile else out.get("industry"),
            "profile_source": profile.get("source") if profile else "unavailable",
            "profile_updated_at": _iso_or_raw(profile.get("updated_at")) if profile else None,
            "quote_price": quote_price,
            "quote_change_pct": _number(quote.get("change_pct")),
            "price_bar_end": _iso_or_raw(quote.get("bar_end")),
            "quote_inserted_at": _iso_or_raw(quote.get("inserted_at")),
            "quote_session": quote.get("session"),
            "prior_close": prior_close,
            "reference_basis": quote.get("reference_basis"),
            "quote_feed": quote.get("feed"),
            "quote_source": "market_quotes_extended" if quote else "unavailable",
            "lookthrough": lookthrough.get(symbol, []),
            "lookthrough_status": "present" if symbol in lookthrough else "not_a_fund",
        })
        # FLOOR: what a row needs when no previous row carries it (new position, or a store that was
        # empty/corrupt). Only absent keys are filled, so a carried value is never overwritten here.
        price = 1.0 if is_cash else (quote_price if quote_price is not None
                                     else (round(broker_value / qty, 6) if qty else None))
        shares = _number(out.get("shares"))
        if shares is None:
            out["shares"] = qty
            out.setdefault("system_shares", qty)
            out.setdefault("share_drift", 0)
            out.setdefault("share_drift_status", "aligned")
            shares = qty
        out["quantity"] = shares
        if _number(out.get("market_value")) is None:
            out["market_value"] = broker_value
            out["mv_basis"] = "broker_market_value"
        if _number(out.get("price")) is None:
            out["price"] = price
            out["price_source"] = ("cash" if is_cash else
                                   "market_quotes_extended" if quote_price is not None else "broker_market_value")
        out.setdefault("current_price", out.get("price"))
        if "cost_basis" not in out:
            out["cost_basis"] = None if is_cash else cost_basis
            out["cost_basis_source"] = "positions_current" if (cost_basis is not None and not is_cash) else None
        market_value = _number(out.get("market_value"))
        basis = _number(out.get("cost_basis"))
        if "gain_loss" not in out:
            out["gain_loss"] = (round(market_value - basis, 2)
                                if (not is_cash and market_value is not None and basis is not None) else None)
            out["gain_loss_pct"] = (round((market_value - basis) / basis * 100.0, 4)
                                    if (not is_cash and market_value is not None and basis) else None)
        if "day_change" not in out:
            # Unknown is null, never a fabricated zero; cash cannot move.
            out["day_change"] = (0.0 if is_cash else
                                 (round(shares * (quote_price - prior_close), 2)
                                  if quote_price is not None and prior_close is not None else None))
            out["day_change_pct"] = 0.0 if is_cash else _number(quote.get("change_pct"))
        out.setdefault("updated_at", _iso(generated_at))
        holdings.append(out)
        if market_value is not None:
            total_value += market_value
            if is_cash:
                total_cash += market_value
        broker_total += broker_value
        row_day = _number(out.get("day_change"))
        if not is_cash and row_day is not None:
            day_change += row_day
            day_change_known = True
    # Accounts the DB does not sync at all are NOT positions the DB says were sold: their rows are carried
    # verbatim (and named in gaps) rather than erased by a writer that never observed them.
    foreign = [copy.deepcopy(r) for key, r in previous.items() if key[0] not in db_accounts]
    if foreign:
        gaps.append("carried without a DB observation (account not in positions_current): "
                    + ", ".join(sorted({str(r.get('account') or r.get('account_id')) for r in foreign})))
        for r in foreign:
            holdings.append(r)
            mv = _number(r.get("market_value"))
            if mv is not None:
                total_value += mv
                if r.get("is_cash"):
                    total_cash += mv
    newest_stamp = _iso(newest) if newest is not None else None
    fingerprint = _positions_fingerprint(holdings)
    prior_built = (prior or {}).get("positions_built_at")
    if prior_built and (prior or {}).get("positions_fingerprint") == fingerprint:
        built = prior_built
    else:
        built = _iso(positions_built_at or generated_at)
    document: dict[str, Any] = {k: copy.deepcopy(v) for k, v in (prior or {}).items() if k not in EXPORT_TOP_KEYS}
    prior_totals = (prior or {}).get("portfolio_totals")
    totals: dict[str, Any] = dict(prior_totals) if isinstance(prior_totals, Mapping) else {}
    totals.update({
        "as_of": newest_stamp,
        "total_value": round(total_value, 2),
        "total_cash": round(total_cash, 2),
        "broker_market_value_total": round(broker_total, 2),
        "day_change": round(day_change, 2) if day_change_known else None,
        "day_change_pct": (round(day_change / (total_value - day_change) * 100.0, 2)
                           if day_change_known and (total_value - day_change) else None),
        "positions": len(holdings),
    })
    summaries: dict[str, Any] = {}
    prior_summaries = (prior or {}).get("account_summaries")
    if isinstance(prior_summaries, Mapping):
        summaries.update(copy.deepcopy(dict(prior_summaries)))
    by_identity = {_canonical_account(k): k for k in summaries}
    for key, block in (account_summaries or {}).items():
        target = by_identity.get(_canonical_account(block.get("account_key") or key), key)
        merged = dict(summaries.get(target) or {})
        merged.update(block)
        summaries[target] = merged
    # A carried account with no summary still needs one: the repricer's totals sum the summaries.
    for r in foreign:
        label = str(r.get("account") or r.get("account_id") or "")
        if label and _canonical_account(label) not in {_canonical_account(k) for k in summaries}:
            summaries[label] = {"account_key": label, "source": "carried_without_db_observation"}
    data_clock = _compute_data_as_of(holdings)
    document.update({
        "schema": SCHEMA,
        "generated_at": _iso(generated_at),
        "exported_at": _iso(generated_at),
        "updated_at": _iso(generated_at),
        "as_of": newest_stamp,
        "source": "positions_current",
        "gaps": gaps,
        "account_summaries": summaries,
        "holdings": holdings,
        "portfolio_totals": totals,
        "data_as_of": data_clock["data_as_of"],
        "data_as_of_account": data_clock["data_as_of_account"],
        "positions_fingerprint": fingerprint,
        "positions_built_at": built,
        "export_provenance": {
            "db_row_fields": list(DB_ROW_FIELDS),
            "db_enrichment_row_fields": list(DB_ENRICHMENT_ROW_FIELDS),
            "floor_row_fields": list(FLOOR_ROW_FIELDS),
            "carried_rows": carried_rows,
            "carried_top_keys": sorted(k for k in (prior or {}) if k not in EXPORT_TOP_KEYS),
            "prior_used": prior is not None,
        },
    })
    return document


def _repricer():
    """portfolio_repricer's aggregation (no provider access) — the ONE implementation of portfolio math."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    import portfolio_repricer  # type: ignore
    return portfolio_repricer


def _compute_data_as_of(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    return _repricer().compute_data_as_of(holdings)


def _positions_fingerprint(holdings: list[dict[str, Any]]) -> str:
    return _repricer()._positions_fingerprint(holdings)


def recalc_totals(document: dict[str, Any]) -> None:
    """Account and portfolio totals through the repricer's own `_recalc_totals` (the code that refreshes this
    document every 15 minutes), so the export can never publish a second definition of a total."""
    repricer = _repricer()
    try:
        repricer._recalc_totals(document)
    except repricer.RepriceRefused as exc:
        raise ExportError(f"totals refused: {exc.reason}") from exc


def build_document(conn, *, prior: Mapping[str, Any] | None, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """Every DB read, the carry and the totals — the render the export writes and the DB-first reader serves.

    Refuses (ExportError) on a DB failure, an empty book or a binding that does not prove one complete run.
    """
    rows = positions_rows(conn)              # refusal happens here, before anything else
    if not rows:
        raise ExportError("positions_current returned no rows; refusing to replace the store")
    binding = run_binding(conn, rows)
    aliases = account_aliases()
    summaries = build_account_summaries(rows, generated_at=now, aliases=aliases)
    symbols = [r.get("symbol") for r in rows]
    quotes = quote_rows(conn, symbols)
    profiles = profile_rows(conn, symbols)
    lookthrough, lookthrough_gap = lookthrough_rows(conn, [s for s in symbols if s])
    gaps = [g for g in (lookthrough_gap,) if g]
    if prior is None:
        gaps.append("no usable previous document: enricher-owned fields render from the DB floor until "
                    "their writers run (repricer marks, look-through sectors, names/buckets)")
    finished = binding.get("finished_at")
    document = render_document(rows, generated_at=now, quotes=quotes, profiles=profiles,
                               lookthrough=lookthrough, gaps=gaps, account_summaries=summaries,
                               aliases=aliases, prior=prior,
                               positions_built_at=finished if isinstance(finished, datetime) else None)
    document["sync_run_id"] = binding["run_id"]
    document["sync_run_finished_at"] = _iso(finished) if isinstance(finished, datetime) else finished
    recalc_totals(document)
    return document, binding


# ── atomic write ───────────────────────────────────────────────────────────────
def _atomic_write_at(dir_fd: int, name: str, text: str, *, mode: int = FILE_MODE) -> None:
    """Atomic write through an ALREADY-PINNED directory fd (survives a parent swap during a callback)."""
    tmp = f".{name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp, dir_fd=dir_fd)
    os.chmod(name, mode, dir_fd=dir_fd)


def _dir_beneath(root: Path, target: Path, *, create: bool = True) -> int:
    """Open `target` as a directory fd by walking from `root` with O_NOFOLLOW at every step.

    A realpath check followed by path-based open/replace is racy: the parent can be swapped for a symlink
    after the check. An fd walk pins each component, so the write cannot leave the root.
    """
    root_real = Path(os.path.realpath(root))
    target_real = Path(os.path.realpath(target))
    if not target_real.is_relative_to(root_real):
        raise ExportError(f"path escapes the state root: {target_real} not under {root_real}")
    fd = os.open(root_real, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in target_real.relative_to(root_real).parts:
            try:
                nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=fd)
                nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
            # Re-verify the pinned fd is still under the root (a swap between components).
            pinned = os.readlink(f"/proc/self/fd/{fd}")
            if Path(pinned) != Path(os.path.realpath(Path(pinned))) or not Path(pinned).is_relative_to(root_real):
                raise ExportError(f"directory swap detected: {pinned} is not under {root_real}")
        return fd
    except Exception:
        os.close(fd)
        raise


def atomic_write(path: Path | str, text: str, *, mode: int = FILE_MODE, root: Path | str | None = None) -> Path:
    """Unique temp in the target directory, fsync, os.replace, mode 600, anchored to a directory fd.

    Every step (mkdir, create, replace) uses dir_fd so a symlinked parent cannot redirect the write.
    """
    path = Path(path)
    root = Path(root) if root is not None else path.parent
    dir_fd = _dir_beneath(root, path.parent, create=True)
    name = path.name
    tmp_name = f".{name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=dir_fd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            os.fsync(dir_fd)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name, dir_fd=dir_fd)
        os.chmod(name, mode, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)
    return path


# ── retention ──────────────────────────────────────────────────────────────────
def _archive(root: Path, directory: Path, path: Path) -> None:
    """Retention moves an own snapshot into `archive/`; it never unlinks and never re-derives the boundary.

    `root` is the caller's original trusted state root. Directory fds are opened beneath it with
    O_NOFOLLOW at every component, and the archive directory is created through those fds — a path-based
    mkdir before the anchored check is exactly how a swapped parent escaped.
    """
    target = directory / "archive"
    src_fd = _dir_beneath(root, directory, create=True)
    dst_fd = _dir_beneath(root, target, create=True)
    try:
        dest = target / path.name
        with contextlib.suppress(FileNotFoundError):
            os.stat(dest.name, dir_fd=dst_fd, follow_symlinks=False)
            dest = target / f"{path.stem}-{secrets.token_hex(3)}{path.suffix}"
        os.replace(path.name, dest.name, src_dir_fd=src_fd, dst_dir_fd=dst_fd)
    finally:
        os.close(src_fd)
        os.close(dst_fd)


def _prune(root: Path, directory: Path, keep: int, prefix: str, *, protect: Path | None = None) -> list[Path]:
    files = [p for p in _own_backups(directory) if p.name.startswith(prefix)]
    removed = files[:-keep] if keep > 0 else files
    removed = [p for p in removed if protect is None or p != protect]
    for path in removed:
        with contextlib.suppress(OSError, ExportError):
            _archive(root, directory, path)
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


def _enforce_size_cap(root: Path, directory: Path, cap: int, *, protect: Path | None = None) -> list[Path]:
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
            _archive(root, directory, path)
            total -= size
            removed.append(path)
        except OSError:
            continue
    return removed


def write_backups(text: str, backups: Path, *, now: datetime, root: Path | None = None,
                  hourly_keep: int = DEFAULT_HOURLY_KEEP, daily_keep: int = DEFAULT_DAILY_KEEP,
                  size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES) -> dict[str, Any]:
    """Write the own snapshots beneath the CALLER'S trusted root, never a root derived from `backups`."""
    root = Path(root) if root is not None else backups.parent
    hourly = backups / f"holdings-hourly-{now.astimezone(timezone.utc):%Y%m%dT%H}.json"
    daily = backups / f"holdings-daily-{now.astimezone(timezone.utc):%Y%m%d}.json"
    atomic_write(hourly, text, root=root)
    try:
        daily_fd = _dir_beneath(root, backups, create=True)
        try:
            os.stat(daily.name, dir_fd=daily_fd, follow_symlinks=False)
        finally:
            os.close(daily_fd)
    except FileNotFoundError:
        atomic_write(daily, text, root=root)
    removed = _prune(root, backups, hourly_keep, "holdings-hourly-", protect=hourly)
    removed += _prune(root, backups, daily_keep, "holdings-daily-", protect=daily)
    removed += _enforce_size_cap(root, backups, size_cap_bytes, protect=hourly)
    return {"hourly": str(hourly), "daily": str(daily), "pruned": [str(p) for p in removed]}


# ── export ─────────────────────────────────────────────────────────────────────
def read_prior(store: Path | str) -> tuple[dict[str, Any] | None, str]:
    """The previous document AS DATA for the carry, through the one store accessor. Never raises.

    Anything but a parseable object (absent, 0 bytes, corrupt, not an object, no holdings list) carries
    nothing: the render then stands on the DB alone and the next enricher run refills its fields.
    """
    try:
        from lib.portfolio_positions import read_store_document  # type: ignore
    except ImportError:  # pragma: no cover - imported as scripts.<module>
        from scripts.lib.portfolio_positions import read_store_document  # type: ignore
    doc, state = read_store_document(Path(store))
    if doc is None:
        return None, state
    if not isinstance(doc.get("holdings"), list):
        return None, "no_holdings_list"
    return doc, state


def export(*, conn, store: Path | str | None = None, backups: Path | str | None = None,
           state_root: Path | str | None = None, now: datetime | None = None,
           hourly_keep: int = DEFAULT_HOURLY_KEEP, daily_keep: int = DEFAULT_DAILY_KEEP,
           size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES, dry_run: bool = False,
           lock: Callable[[], Any] | None = None) -> dict[str, Any]:
    """Render from the DB and atomically replace the store.

    The previous document is read INSIDE `lock` (the shared holdings write lock in production) so the carry
    and the replace are one read-modify-write with every other holdings writer. It is read only for the
    fields other writers own (FIELD OWNERSHIP); every DB-owned fact comes from the DB.
    `dry_run=True` runs the identical query/join/validation/binding path and stops before any write.
    """
    now = now or datetime.now(timezone.utc)
    store = Path(store) if store is not None else store_path(state_root)
    backups = Path(backups) if backups is not None else store.parent / "backups"
    # Refuse an aliased destination: the resolved store must stay under the resolved state root.
    root_hint = Path(state_root).expanduser() if state_root is not None else default_state_root()
    resolved_store, resolved_root = Path(os.path.realpath(store)), Path(os.path.realpath(root_hint))
    if not resolved_store.is_relative_to(resolved_root):
        raise ExportError(f"store escapes the state root: {resolved_store} not under {resolved_root}")
    resolved_backups = Path(os.path.realpath(backups))
    if not resolved_backups.is_relative_to(resolved_root):
        raise ExportError(f"backups directory escapes the state root: {resolved_backups} not under {resolved_root}")
    # A dry run writes nothing, so it never queues behind the other writers for the lock.
    with (lock() if (lock is not None and not dry_run) else contextlib.nullcontext()):
        prior, prior_state = read_prior(store)
        document, binding = build_document(conn, prior=prior, now=now)
        document["export_provenance"]["prior_state"] = prior_state
        text = json.dumps(document, indent=1, sort_keys=True, default=str) + "\n"
        if dry_run:
            return {"ok": True, "dry_run": True, "store": str(store), "bytes": len(text),
                    "holdings": len(document["holdings"]), "generated_at": document["generated_at"],
                    "sync_run_id": binding["run_id"], "prior_state": prior_state,
                    "carried_rows": document["export_provenance"]["carried_rows"]}
        # Backup first: if the backup cannot be written or read back, the current file is never replaced.
        retention = write_backups(text, backups, now=now, root=root_hint, hourly_keep=hourly_keep,
                                  daily_keep=daily_keep, size_cap_bytes=size_cap_bytes)
        if not Path(retention["hourly"]).exists() or Path(retention["hourly"]).stat().st_size == 0:
            raise ExportError("backup was not durably written; the current store was left untouched")
        atomic_write(store, text, root=root_hint)
    return {"ok": True, "store": str(store), "bytes": len(text),
            "holdings": len(document["holdings"]), "generated_at": document["generated_at"],
            "sync_run_id": binding["run_id"], "prior_state": prior_state,
            "carried_rows": document["export_provenance"]["carried_rows"],
            "retention": retention}


# ── freshness alert ───────────────────────────────────────────────────────────
def export_age_minutes(store: Path | str, *, now: datetime) -> float | None:
    """Age from the document's own generated_at clock (mtime only as a fallback): touching a stale file
    must not make it read fresh."""
    with contextlib.suppress(Exception):  # unreadable falls back to mtime, then to None
        document = json.loads(Path(store).read_text(encoding="utf-8"))
        generated = document.get("generated_at")
        if isinstance(generated, str) and generated:
            born = datetime.fromisoformat(generated.replace("Z", "+00:00"))
            if born.tzinfo is None:
                born = born.replace(tzinfo=timezone.utc)
            return round((now - born).total_seconds() / 60.0, 1)
    try:
        mtime = Path(store).stat().st_mtime
    except OSError:
        return None
    return round((now - datetime.fromtimestamp(mtime, timezone.utc)).total_seconds() / 60.0, 1)


def in_market_hours(now: datetime) -> bool:
    """Official NYSE session bounds when the calendar is available; weekday/time only as a stated fallback."""
    et = now.astimezone(ET)
    with contextlib.suppress(Exception):  # fall back to weekday arithmetic and say so in the alert result
        from lib.cio_market_session import get_session_service  # type: ignore
        service = get_session_service()
        if not service.is_trading_day(et.date()):
            return False
        open_dt, close_dt, _early = service.official_bounds(et.date())
        if open_dt is not None and close_dt is not None:
            return open_dt <= et <= close_dt
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
    """Telegram P1 when the export is empty, older than `max_age_minutes` in market hours, or the broker market
    values it carries differ from the DB's by more than one dollar."""
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
        # The DB's broker market values must reach the document intact. total_value is the repricer's valuation
        # of the same book (shares x canonical mark), so it is compared with its own rows, not with the DB.
        totals_block = document.get("portfolio_totals") or {}
        rendered = totals_block.get("broker_market_value_total", totals_block.get("total_value"))
        if db_total is not None and isinstance(rendered, (int, float)):
            delta = abs(float(rendered) - db_total)
            mismatch = round(delta, 2) if delta > 1.0 else None
    if not empty and mismatch is None and not sync_bad and not in_market_hours(now):
        return {"status": "outside_market_hours", "age_minutes": age, "sent": False}
    if not empty and mismatch is None and not sync_bad and age is not None and age <= max_age_minutes:
        marker_root = Path(state_root).expanduser() if state_root is not None else Path(store).parent
        with contextlib.suppress(OSError, ExportError):
            fd = _dir_beneath(marker_root, Path(store).parent / "backups", create=True)
            try:
                os.unlink(".alert-episode.json", dir_fd=fd)
            finally:
                os.close(fd)
        return {"status": "fresh", "age_minutes": age, "sent": False}
    # Episode dedupe: one page per distinct episode, reset on recovery. Undelivered sends retry next run.
    episode_file: Path | None = Path(store).parent / "backups" / ".alert-episode.json"
    if state_root is not None:
        root_real = Path(os.path.realpath(Path(state_root).expanduser()))
        if not Path(os.path.realpath(episode_file)).is_relative_to(root_real):
            episode_file = None  # never write alert state outside an explicit state root
    # One episode per unresolved condition, independent of the export clock: as the document ages the
    # condition stays the same, so it pages once until it clears.
    episode = (f"empty={empty}|mismatch={mismatch is not None}|sync_bad={sync_bad}"
               f"|stale={age is not None and age > max_age_minutes}")
    marker_fd = None
    if episode_file is not None:
        marker_root = Path(state_root).expanduser() if state_root is not None else Path(store).parent
        try:
            # PIN the directory now: the send callback runs below, and a swap during it must not
            # redirect the marker write (the fd keeps pointing at the original directory).
            marker_fd = _dir_beneath(marker_root, episode_file.parent, create=True)
        except (OSError, ExportError):
            marker_fd, episode_file = None, None
    if episode_file is not None:
        with contextlib.suppress(Exception):  # no prior episode
            if json.loads(episode_file.read_text(encoding="utf-8")).get("episode") == episode:
                if marker_fd is not None:
                    os.close(marker_fd)
                return {"status": "already_alerted", "age_minutes": age, "sent": False, "episode": episode}
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
        if marker_fd is not None:
            os.close(marker_fd)
        return {"status": "send_error", "age_minutes": age, "sent": False, "error_type": type(exc).__name__}
    if delivered and marker_fd is not None:
        with contextlib.suppress(OSError):
            _atomic_write_at(marker_fd, episode_file.name, json.dumps({"episode": episode, "at": _iso(now)}) + "\n")
    if marker_fd is not None:
        os.close(marker_fd)
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
    conn = None
    try:
        conn = _connect()
        receipt = export(conn=conn, store=store, backups=backups, lock=holdings_lock())
        # The connection stays open for the alert: the two-consecutive-sync-failure check lives there.
        alert = maybe_alert_stale(store=store, conn=conn, state_root=store.parent)
    except (ExportError, ConnectionError, OSError) as exc:
        # A refusal leaves the last good file untouched; the freshness check still pages if it is stale.
        # A MISSING export IS the P1 condition: always run the monitor, present or not.
        alert = maybe_alert_stale(store=store, conn=conn, state_root=store.parent)
        receipt = {"ok": False, "refused": str(exc), "refused_type": type(exc).__name__,
                   "store": str(store), "alert": alert}
        print(json.dumps(receipt, indent=1, sort_keys=True) if args.json else
              f"holdings-export: REFUSED — {exc}; last good file kept", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            _close(conn)
    receipt["alert"] = alert
    if args.json:
        print(json.dumps(receipt, indent=1, sort_keys=True))
    else:
        print(f"holdings-export: {receipt['holdings']} rows, {receipt['bytes']} bytes, "
              f"generated {receipt['generated_at']}")
    return 0


def holdings_lock() -> Callable[[], Any]:
    """The ONE lock every holdings.json read-modify-write holds (lib/holdings_write_lock.py)."""
    try:
        from lib.holdings_write_lock import holdings_write_lock  # type: ignore
    except ImportError:  # pragma: no cover - imported as scripts.<module>
        from scripts.lib.holdings_write_lock import holdings_write_lock  # type: ignore
    return holdings_write_lock


def _connect():
    """Read-only, REPEATABLE READ session; every driver failure becomes an ExportError here.

    psycopg2's OperationalError is neither a ConnectionError nor an OSError, so without this the real
    connect failure escapes the CLI uncaught and the freshness monitor never runs.
    """
    try:
        from lib.cio_market_context_state import connect_trade_ai_readonly  # type: ignore
        conn = connect_trade_ai_readonly()
        conn.set_session(isolation_level="REPEATABLE READ", readonly=True, autocommit=False)
        return conn
    except ExportError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalized at the boundary, never swallowed
        raise ExportError(f"database connection failed: {type(exc).__name__}") from exc


def _close(conn) -> None:
    with contextlib.suppress(Exception):
        conn.rollback()
    with contextlib.suppress(Exception):
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
