"""symbol_profiles -- the one write module (One Source of Truth, Phase 9).

WHY
---
Eight producers wrote this table on 2026-09-13, each carrying its own SQL:
the base profile builder (yfinance / finviz / proxy_label) and seven enrichers
that each UPDATE the columns they own (earnings, instrument type, expense
ratio, fund technicals, distributions, ETF performance, ETF analyst view).
Plural PRODUCERS are by design here -- column ownership per lane is the model.
Plural WRITE PATHS were the defect: eight statements meant eight places where a
column list, a coercion, a NULL rule or a plausibility rail could drift, which
is exactly how a 1-5 rating column came to hold ten-year performance for five
months in the Finviz store.

This module owns:
  * the column list and the ON CONFLICT rule (symbol is the primary key);
  * an ALLOW-LIST of columns per source lane, so an enricher can touch only the
    columns it owns -- a foreign column is a rejected row, not a silent write;
  * the plausibility rails the legacy writers already applied (expense ratio
    is a fraction in (0, 0.025]; RSI in [0, 100]; instrument_type and
    direction_hint from a closed vocabulary; distribution and dividend amounts
    non-negative; dates are dates; numerics are finite);
  * the earnings three-state model: SCHEDULED / NONE_SCHEDULED / UNKNOWN.
    UNKNOWN is never persisted -- a NULL next_earnings_date beside a fresh
    earnings_updated_at reads back as NONE_SCHEDULED in earnings_provider, so
    writing it would coerce "we could not find out" into "nothing is booked",
    which is the fail-open every event gate had before 2026-07-20;
  * identity: the table has NO GUID column (symbol TEXT PRIMARY KEY, see
    migrations/2026_06_12_symbol_profiles.sql). The receipt carries the
    subject_guid for every written row, resolved registry-first
    (identity_registry.lookup_symbol, which follows supersede chains via
    resolve_guid) and then through security_identity.resolve_identity_spine +
    identity_registry.subject_guid_of. Nothing here mints, rewrites or writes a
    GUID; adding the column is a migration for the operator (see notes).

Every write returns a WriteReceipt. Rejected rows are returned with a reason
and logged; they are never silently dropped.

Public surface
--------------
    upsert_profile(cur, symbol, fields, *, source, run_id=None,
                   keep_existing_if_null=()) -> WriteReceipt
    write_symbol_profiles(cur, rows, *, source, run_id=None) -> WriteReceipt
    write_earnings(cur, symbol, *, state, next_earnings_date=None, ...,
                   run_id=None) -> WriteReceipt
    earnings_state_for(next_earnings_date, *, provider_answered) -> str
    resolve_subject_guid(row) -> (guid | None, basis)

AUTHORITY: this module writes reference metadata only. No prices, no
positions, no orders, no broker calls.
"""
from __future__ import annotations

import logging
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, NamedTuple

log = logging.getLogger("symbol_profiles_writer")

TABLE = "symbol_profiles"
RECEIPT_SCHEMA = "SymbolProfileWriteReceipt@v1"

_REPO_ROOT = Path(__file__).resolve().parents[3]

# ── earnings three-state model (mirrors scripts/earnings_provider.py) ────────
EARNINGS_SCHEDULED = "SCHEDULED"
EARNINGS_NONE = "NONE_SCHEDULED"
EARNINGS_UNKNOWN = "UNKNOWN"
_EARNINGS_NONE_ALIASES = frozenset({"NONE", "NONE_SCHEDULED", "NONE_CONFIRMED"})

# ── column vocabulary ────────────────────────────────────────────────────────
BASE_COLUMNS = ("description_1s", "sector", "industry")
INSTRUMENT_TYPES = frozenset({"stock", "etf", "fund", "inverse_etf", "mutual_fund"})
DIRECTION_HINTS = frozenset({"long", "short"})
EXPENSE_RATIO_MAX = 0.025  # fraction; validate_expense_ratios.SANITY_MAX and classify_instruments agree

NUMERIC_COLUMNS = frozenset({
    "last_eps_estimate", "last_eps_actual", "last_eps_surprise_pct", "expense_ratio", "rsi14",
    "perf_week_pct", "perf_month_pct", "ytd_return_pct", "sma50_pct", "last_distribution_amount",
    "ttm_distribution_amount", "dividend_yield_pct", "ttm_dividend", "analyst_look_through_pct",
})
DATE_COLUMNS = frozenset({"next_earnings_date", "last_earnings_date", "last_distribution_date", "next_distribution_est"})
TEXT_COLUMNS = frozenset({
    "description_1s", "sector", "industry", "instrument_type", "direction_hint", "quote_type",
    "distribution_cadence", "analyst_basis",
})
NON_NEGATIVE_COLUMNS = frozenset({"last_distribution_amount", "ttm_distribution_amount", "dividend_yield_pct", "ttm_dividend"})


class Lane(NamedTuple):
    """What one producer lane may write. `columns` is ordered (it fixes SQL order)."""
    columns: tuple[str, ...]
    stamp: str | None      # timestamp column set to NOW() on every write by this lane
    mode: str              # "upsert" (creates rows; base profile) | "update" (enricher; never creates)


BASE_LANE = Lane(BASE_COLUMNS, "updated_at", "upsert")

#: The allow-list. A lane may write exactly these columns and nothing else.
LANES: dict[str, Lane] = {
    # base profile lanes -- the value is also what lands in the `source` column
    "yfinance": BASE_LANE,
    "finviz": BASE_LANE,
    "proxy_label": BASE_LANE,
    "manual": BASE_LANE,
    # enricher lanes -- each owns its columns; `source` column is untouched
    "earnings_enrich": Lane(("next_earnings_date", "last_earnings_date", "last_eps_estimate",
                             "last_eps_actual", "last_eps_surprise_pct"), "earnings_updated_at", "update"),
    "classify_instruments": Lane(("instrument_type", "direction_hint", "expense_ratio", "quote_type"), None, "update"),
    "validate_expense_ratios": Lane(("expense_ratio",), None, "update"),
    "fund_technicals_enrich": Lane(("rsi14", "perf_week_pct", "perf_month_pct", "ytd_return_pct", "sma50_pct"),
                                   "technicals_updated_at", "update"),
    "distributions_enrich": Lane(("last_distribution_date", "last_distribution_amount", "distribution_cadence",
                                  "next_distribution_est", "ttm_distribution_amount"), "distributions_updated_at", "update"),
    "etf_performance_enrich": Lane(("ytd_return_pct", "dividend_yield_pct", "ttm_dividend"), "perf_updated_at", "update"),
    "etf_analyst_enrich": Lane(("analyst_look_through_pct", "analyst_basis"), None, "update"),
}

ALL_COLUMNS: frozenset[str] = frozenset(c for lane in LANES.values() for c in lane.columns)


# ── receipt ──────────────────────────────────────────────────────────────────
@dataclass
class WriteReceipt:
    table: str = TABLE
    source: str = ""
    written_by: str = ""
    run_id: str | None = None
    written_at: str = ""
    rows_in: int = 0
    rows_written: int = 0
    rows_rejected: int = 0
    written: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    schema: str = RECEIPT_SCHEMA

    def merge(self, other: "WriteReceipt") -> "WriteReceipt":
        self.rows_in += other.rows_in
        self.rows_written += other.rows_written
        self.rows_rejected += other.rows_rejected
        self.written.extend(other.written)
        self.rejected.extend(other.rejected)
        return self

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _receipt(source: str, run_id: str | None) -> WriteReceipt:
    return WriteReceipt(source=source, written_by=f"lib.writers.symbol_profiles_writer:{source}",
                        run_id=run_id, written_at=_now_iso())


def _reject(rcpt: WriteReceipt, symbol: Any, reason: str, fields: Mapping[str, Any] | None = None) -> WriteReceipt:
    row = {"symbol": symbol, "reason": reason, "fields": dict(fields or {})}
    rcpt.rows_rejected += 1
    rcpt.rejected.append(row)
    log.warning("symbol_profiles write REJECTED lane=%s symbol=%s reason=%s", rcpt.source, symbol, reason)
    return rcpt


# ── identity (read-only; never mints) ────────────────────────────────────────
def _identity_modules():
    try:
        from scripts.lib import identity_registry, security_identity  # type: ignore
    except ImportError:
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scripts.lib import identity_registry, security_identity  # type: ignore
    return identity_registry, security_identity


def normalize_symbol(value: Any) -> str:
    _, si = _identity_modules()
    return si.normalize_symbol(value)


def resolve_subject_guid(row: Mapping[str, Any]) -> tuple[str | None, str]:
    """Registry-first, then the UUIDv5 spine, ticker alias last. Never invents.

    Returns (guid, basis). basis is "registry:<status>" when the minted registry
    already knows the symbol (its active guid, supersede chain followed), else
    "spine:<status>" from resolve_identity_spine + subject_guid_of -- which for
    a symbol-only row is the ticker alias guid the whole system already uses.
    """
    reg, si = _identity_modules()
    sym = si.normalize_symbol(row.get("symbol"))
    if not sym:
        return None, "no_symbol"
    doc = reg.load_cached()
    ent = reg.lookup_symbol(doc, sym)
    if ent and ent.get("subject_guid"):
        return reg.resolve_guid(doc, ent["subject_guid"]), f"registry:{ent.get('identity_status')}"
    spine = si.resolve_identity_spine(dict(row))
    return reg.subject_guid_of(spine, sym), f"spine:{spine.get('identity_status')}"


# ── coercion + rails ─────────────────────────────────────────────────────────
def _coerce_numeric(col: str, v: Any) -> tuple[Any, str | None]:
    if v is None:
        return None, None
    if isinstance(v, bool):
        return None, f"{col}: boolean is not a number"
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return None, f"{col}: not numeric ({v!r})"
    if not isinstance(v, (int, float)):
        return None, f"{col}: not numeric ({type(v).__name__})"
    if isinstance(v, float) and not math.isfinite(v):
        return None, f"{col}: not finite"
    if col in NON_NEGATIVE_COLUMNS and v < 0:
        return None, f"{col}: negative ({v})"
    if col == "expense_ratio" and not (0 < v <= EXPENSE_RATIO_MAX):
        return None, f"expense_ratio off rail: stored as a FRACTION in (0, {EXPENSE_RATIO_MAX}] got {v}"
    if col == "rsi14" and not (0 <= v <= 100):
        return None, f"rsi14 off rail [0, 100]: {v}"
    return v, None


def _coerce_date(col: str, v: Any) -> tuple[Any, str | None]:
    if v is None:
        return None, None
    if isinstance(v, datetime):
        return v.date(), None
    if isinstance(v, date):
        return v, None
    if hasattr(v, "date") and callable(v.date):  # pandas Timestamp
        try:
            return v.date(), None
        except Exception:  # noqa: BLE001
            pass
    if isinstance(v, str):
        try:
            return date.fromisoformat(v.strip()[:10]), None
        except ValueError:
            return None, f"{col}: not an ISO date ({v!r})"
    return None, f"{col}: not a date ({type(v).__name__})"


def _coerce_text(col: str, v: Any) -> tuple[Any, str | None]:
    if v is None:
        return None, None
    if not isinstance(v, str):
        return None, f"{col}: not text ({type(v).__name__})"
    if col == "instrument_type":
        if v not in INSTRUMENT_TYPES:
            return None, f"instrument_type off vocabulary {sorted(INSTRUMENT_TYPES)}: {v!r}"
    elif col == "direction_hint":
        if v not in DIRECTION_HINTS:
            return None, f"direction_hint off vocabulary {sorted(DIRECTION_HINTS)}: {v!r}"
    elif col == "quote_type":
        v = v.strip().upper()
        if not v:
            return None, "quote_type: empty"
    return v, None


def coerce_field(col: str, v: Any) -> tuple[Any, str | None]:
    """(value, None) on the rail; (None, reason) off it."""
    if col in NUMERIC_COLUMNS:
        return _coerce_numeric(col, v)
    if col in DATE_COLUMNS:
        return _coerce_date(col, v)
    if col in TEXT_COLUMNS:
        return _coerce_text(col, v)
    return None, f"{col}: unknown column"


# ── the write ────────────────────────────────────────────────────────────────
def _rows_affected(cur: Any) -> int:
    rc = getattr(cur, "rowcount", None)
    return rc if isinstance(rc, int) and rc >= 0 else 1


def upsert_profile(cur: Any, symbol: Any, fields: Mapping[str, Any], *, source: str,
                   run_id: str | None = None, keep_existing_if_null: Iterable[str] = ()) -> WriteReceipt:
    """Write one symbol's columns through its lane. The only SQL for this table.

    `source` selects the lane (allow-list). Base lanes (yfinance, finviz,
    proxy_label, manual) INSERT ... ON CONFLICT (symbol) DO UPDATE and set the
    `source` column to the lane; the conflict update touches only the columns
    supplied in `fields`, so a proxy_label write that omits `industry` leaves an
    existing industry alone (legacy semantics). Enricher lanes UPDATE ... WHERE
    upper(symbol)=%s and never create a row. `keep_existing_if_null` names
    columns written as COALESCE(%s, col) -- a None keeps the stored value.
    """
    rcpt = _receipt(source, run_id)
    rcpt.rows_in = 1
    fields = dict(fields or {})
    lane = LANES.get(source)
    if lane is None:
        return _reject(rcpt, symbol, f"unknown source lane {source!r}; allowed: {sorted(LANES)}", fields)
    sym = normalize_symbol(symbol)
    if not sym:
        return _reject(rcpt, symbol, "empty symbol", fields)
    foreign = sorted(set(fields) - set(lane.columns))
    if foreign:
        return _reject(rcpt, sym, f"columns not owned by lane {source!r}: {foreign}", fields)
    keep = set(keep_existing_if_null)
    bad_keep = sorted(keep - set(fields))
    if bad_keep:
        return _reject(rcpt, sym, f"keep_existing_if_null names columns not in fields: {bad_keep}", fields)
    if not fields and lane.mode == "update":
        return _reject(rcpt, sym, "no columns to write", fields)

    values: dict[str, Any] = {}
    for col in lane.columns:
        if col not in fields:
            continue
        v, reason = coerce_field(col, fields[col])
        if reason:
            return _reject(rcpt, sym, reason, fields)
        values[col] = v

    guid, basis = resolve_subject_guid({"symbol": sym})

    if lane.mode == "upsert":
        cols = ["symbol", *BASE_COLUMNS, "source", lane.stamp]
        placeholders = ["%s"] * (len(cols) - 1) + ["now()"]
        set_parts = [f"{c}=EXCLUDED.{c}" for c in BASE_COLUMNS if c in values]
        set_parts += ["source=EXCLUDED.source", f"{lane.stamp}=now()"]
        sql = (f"INSERT INTO {TABLE} ({', '.join(cols)}) VALUES ({', '.join(placeholders)}) "
               f"ON CONFLICT (symbol) DO UPDATE SET {', '.join(set_parts)}")
        params = (sym, *[values.get(c) for c in BASE_COLUMNS], source)
    else:
        set_parts, params_list = [], []
        for col in lane.columns:
            if col not in values:
                continue
            set_parts.append(f"{col}=COALESCE(%s, {col})" if col in keep else f"{col}=%s")
            params_list.append(values[col])
        if lane.stamp:
            set_parts.append(f"{lane.stamp}=NOW()")
        sql = f"UPDATE {TABLE} SET {', '.join(set_parts)} WHERE upper(symbol)=%s"
        params = (*params_list, sym)

    cur.execute(sql, params)
    n = _rows_affected(cur)
    rcpt.rows_written += n
    rcpt.written.append({"symbol": sym, "subject_guid": guid, "identity_basis": basis,
                         "columns": sorted(values), "rows_affected": n, "mode": lane.mode})
    return rcpt


def write_symbol_profiles(cur: Any, rows: Iterable[Mapping[str, Any]], *, source: str,
                          run_id: str | None = None, keep_existing_if_null: Iterable[str] = ()) -> WriteReceipt:
    """Batch form: each row is {"symbol": ..., <lane columns>...}. One receipt."""
    total = _receipt(source, run_id)
    keep = tuple(keep_existing_if_null)
    for row in rows:
        row = dict(row or {})
        sym = row.pop("symbol", None)
        total.merge(upsert_profile(cur, sym, row, source=source, run_id=run_id, keep_existing_if_null=keep))
    return total


# ── earnings: three states, fails closed ─────────────────────────────────────
def earnings_state_for(next_earnings_date: Any, *, provider_answered: bool) -> str:
    """Derive the state the way earnings_enrich always has: a provider that did
    not answer is UNKNOWN; an answer with a future date is SCHEDULED; an answer
    with none booked is NONE_SCHEDULED."""
    if not provider_answered:
        return EARNINGS_UNKNOWN
    return EARNINGS_SCHEDULED if next_earnings_date else EARNINGS_NONE


def _refused(symbol: Any, reason: str, fields: Mapping[str, Any], run_id: str | None) -> WriteReceipt:
    rcpt = _receipt("earnings_enrich", run_id)
    rcpt.rows_in = 1
    return _reject(rcpt, symbol, reason, fields)


def write_earnings(cur: Any, symbol: Any, *, state: str, next_earnings_date: Any = None,
                   last_earnings_date: Any = None, last_eps_estimate: Any = None, last_eps_actual: Any = None,
                   last_eps_surprise_pct: Any = None, run_id: str | None = None) -> WriteReceipt:
    """The earnings_date domain write. UNKNOWN is refused, never coerced to NONE.

    SCHEDULED requires a next_earnings_date; NONE_SCHEDULED forbids one. Both
    stamp earnings_updated_at=NOW(), which is what lets earnings_provider trust
    a NULL date as "looked recently, nothing booked". UNKNOWN leaves the row
    untouched so the reader sees a stale or never-enriched row -- UNKNOWN --
    and every event gate fails closed.
    """
    st = str(state or "").strip().upper()
    if st in _EARNINGS_NONE_ALIASES:
        st = EARNINGS_NONE
    fields = {"next_earnings_date": next_earnings_date, "last_earnings_date": last_earnings_date,
              "last_eps_estimate": last_eps_estimate, "last_eps_actual": last_eps_actual,
              "last_eps_surprise_pct": last_eps_surprise_pct}
    audit = {**fields, "state": st}
    if st == EARNINGS_UNKNOWN:
        return _refused(symbol, "earnings_state UNKNOWN is never persisted: a NULL next_earnings_date with a "
                                "fresh earnings_updated_at reads back as NONE_SCHEDULED; row left untouched "
                                "so it reads UNKNOWN (fail closed)", audit, run_id)
    if st not in (EARNINGS_SCHEDULED, EARNINGS_NONE):
        return _refused(symbol, f"earnings_state must be one of SCHEDULED/NONE_SCHEDULED/UNKNOWN, got {state!r}",
                        audit, run_id)
    if st == EARNINGS_SCHEDULED and not next_earnings_date:
        return _refused(symbol, "SCHEDULED requires next_earnings_date (not coerced to NONE_SCHEDULED)", audit, run_id)
    if st == EARNINGS_NONE and next_earnings_date:
        return _refused(symbol, "NONE_SCHEDULED contradicts a next_earnings_date", audit, run_id)
    return upsert_profile(cur, symbol, fields, source="earnings_enrich", run_id=run_id)


__all__ = [
    "TABLE", "RECEIPT_SCHEMA", "LANES", "Lane", "WriteReceipt", "BASE_COLUMNS", "ALL_COLUMNS",
    "INSTRUMENT_TYPES", "DIRECTION_HINTS", "EXPENSE_RATIO_MAX",
    "EARNINGS_SCHEDULED", "EARNINGS_NONE", "EARNINGS_UNKNOWN",
    "upsert_profile", "write_symbol_profiles", "write_earnings", "earnings_state_for",
    "resolve_subject_guid", "coerce_field", "normalize_symbol",
]
