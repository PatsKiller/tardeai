#!/usr/bin/env python3
"""numbers_truth_audit.py — every number a page shows, checked against its truth.

Design: DSN-20261109-numbers-truth-audit.md (operator ask 2026-11-09 17:10 ET), rev 1 sections 1-2, aligned by
REV 2 (sources, pages, no duplicates) and REV 3 (the `authority` check family G1/G2/G3). Catalog-driven: every
row of config/numbers_truth_catalog.json is one displayed figure, the surface it is served from
(API path + JSON pointer, or runtime artifact + key), and the truth it must agree with (DB, Finviz, or a
derived value). This script never guesses a figure and never repairs one (AGENTS.md §0 rule 5):

  * a figure whose truth cannot be read is NOT_MEASURED — never PASS, never FAIL;
  * every finding carries BOTH sides and their timestamps;
  * the findings list M (``summary["findings"]``) is the interface to the strike/heal/ticket lane (LQ-1702):
    each element carries the design's fingerprint ``page|figure_id|account|symbol`` plus severity, status,
    both sides, the domain and the producer lane.

Check families
  numbers    book_total, account_total, row_scalar (qty / market value / price / stop price / stop qty /
             stop state), cross_source (stop_lifecycle vs its retiring stop_last_known copy), coverage
             (held - working-stop coverage, the XLV case), same_figure (day P&L header vs its account rows),
             session_label (the stop card's named session day vs the brief's last_close.session_date)
  authority  G1 authority_static   run scripts/check_data_source_authority.py --json, one finding per rule+file
             G2 authority_writes    rows written in the last hour by a provider the authority file does not
                                    declare for that domain (first instance: market_quotes source='yfinance')
             G3 authority_source    a figure's own source field must equal its domain's declared authority

Schedule (n8n lane numbers-truth-audit, hourly :07 — wired by LQ-1703, never a cron here). Between 04:00 and
16:15 ET on a weekday this script issues NO HTTP to :7777 (AGENTS.md §28.8): it audits the served artifacts the
API reads, in-process. Outside that window it may also GET the catalog's API rows, one request per endpoint,
paced ≥1 s. A row that declares only an API surface is NOT_MEASURED inside the window, with that reason.

Read-only: a psycopg2 session with ``set_session(readonly=True, autocommit=True)`` (the desk_truth_monitor
pattern; db_adapter reaches the broker transport and is not used — AGENTS.md §24.3), runtime artifacts read with
``open()``. No broker, no order route, no credential, no store write, no scheduler, no LLM. The only file this
script writes is its own LaneRunReceipt@v2 (``--apply``); ``--dry-run`` (the default) writes nothing.

Exit 0 = the audit completed (findings are output, not failure); 1 = a required source is unreadable
(dependency_unavailable); 2 = usage. MBI_BEHAVIOR = 0. Authority: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = "scripts/numbers_truth_audit.py"
SCHEMA = "NumbersTruthAudit@v1"
LANE = "numbers-truth-audit"
AUTHORITY = "READ_ONLY_ADVISORY"
DEFAULT_CATALOG = ROOT / "config" / "numbers_truth_catalog.json"
ET = ZoneInfo("America/New_York")
DEP = "dependency_unavailable"

#: DSN F: a long run holds the executor drain (LQ-1685). Past this, unmeasured rows are reported, not run.
MAX_RUNTIME_S = 120.0
#: The receipt stays bounded: the list M is capped and the overflow is counted, never silently dropped.
MAX_FINDINGS = 200
#: AGENTS.md §28.8: no HTTP to :7777 on a weekday in this window.
HTTP_WINDOW = (time(4, 0), time(16, 15))

# The newest stop_lifecycle snapshot carries EVERY order of a (account, symbol): one live row plus the
# cancelled/replaced/filled history. The row that describes the displayed stop is the live one only —
# comparing a page number against an arbitrary historical row is a false positive (verified live
# 2026-11-09: ANET had five rows in the same snapshot, one `working`; rollover V had six, one `working`).
LIVE_STOP_LIFECYCLES = ("working", "near_trigger")
#: One request per endpoint, ≥1 s apart (DSN §2).
HTTP_PACING_S = 1.0
HTTP_TIMEOUT_S = 5.0

_SEVERITIES = ("P0", "P1", "P2", "P3")
_STATUSES = ("MISMATCH", "NOT_MEASURED")
_WEEKDAYS = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "weds": 2, "wednesday": 2,
             "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5,
             "sun": 6, "sunday": 6}
_TYPED_EMPTY = frozenset({"source_unreadable", "truth_unreadable", "stale_truth", "in_window_artifact_only",
                          "no_such_field", "no_weekday_named", "deadline_exceeded", "checker_unsupported",
                          "audit_error", "authority_gate_unavailable", "no_rows"})


# ── small helpers ───────────────────────────────────────────────────────────────────────────────────────────────


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _ts(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if v in (None, ""):
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _canon(v: Any) -> str:
    return str(v or "").strip().lower().replace(" ", "_").replace("-", "_")


def _session_date(v: Any) -> Optional[date]:
    """A session date is a DATE, not an instant. Parsing '2026-11-09' as UTC midnight and converting to ET
    yields 2026-11-08 — a Sunday — so the weekday of every weekday-named label would be wrong. Date-only
    strings are taken as their own calendar date; full timestamps convert to the ET trading day."""
    if isinstance(v, datetime):
        return v.astimezone(ET).date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    if len(s) == 10 and s[4:5] == "-" and s[7:8] == "-":
        try:
            return date.fromisoformat(s)  # a date-only string is its own calendar date, never UTC midnight
        except ValueError:
            return None
    d = _ts(v)
    return d.astimezone(ET).date() if d is not None else None


def _hhmm(text: str) -> time:
    h, m = str(text).split(":")
    return time(int(h), int(m))


def http_window_open(now: datetime) -> bool:
    """True when HTTP to :7777 is permitted: a weekend, or a weekday outside 04:00-16:15 ET (§28.8)."""
    local = now.astimezone(ET)
    if local.weekday() >= 5:
        return True
    return not (HTTP_WINDOW[0] <= local.time() <= HTTP_WINDOW[1])


def pointer(doc: Any, ptr: str) -> Any:
    """RFC 6901 read. A missing path returns None — the caller grades NOT_MEASURED, never a guess."""
    if ptr in ("", "/"):
        return doc
    cur = doc
    for raw in str(ptr).lstrip("/").split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, Mapping):
            if key not in cur:
                return None
            cur = cur[key]
        elif isinstance(cur, list):
            try:
                cur = cur[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def first_value(obj: Any, pointers: Iterable[str]) -> tuple[Any, Optional[str]]:
    """First pointer that resolves to a non-null value. A payload may carry a legacy alias (price/current_price)."""
    for p in pointers or ():
        v = pointer(obj, p)
        if v is not None and v != "":
            return v, p
    return None, None


def fingerprint(page: str, figure_id: str, account: Any = None, symbol: Any = None) -> str:
    """The design's key: page|figure_id|account|symbol (LQ-1702 groups strikes on this string)."""
    return f"{page}|{figure_id}|{account or ''}|{symbol or ''}"


def _counted(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it] = out.get(it, 0) + 1
    return dict(sorted(out.items()))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── findings (list M — the interface to LQ-1702) ────────────────────────────────────────────────────────────────


def finding(row: Mapping[str, Any], code: str, status: str, detail: str, *, shown: Optional[Mapping[str, Any]] = None,
            truth: Optional[Mapping[str, Any]] = None, account: Any = None, symbol: Any = None,
            severity: Optional[str] = None, reason: Optional[str] = None) -> dict[str, Any]:
    sev = str(severity or row.get("severity") or "P2").upper()
    if sev not in _SEVERITIES:
        raise ValueError(f"severity must be one of {_SEVERITIES}, got {sev!r}")
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {_STATUSES}, got {status!r}")
    return {
        "fingerprint": fingerprint(str(row.get("page")), str(row.get("figure_id")), account, symbol),
        "page": row.get("page"), "figure_id": row.get("figure_id"), "account": account, "symbol": symbol,
        "severity": sev, "status": status, "code": code, "detail": str(detail)[:600],
        "shown": dict(shown or {}), "truth": dict(truth or {}),
        "domain": row.get("domain"), "producer_lane": row.get("producer_lane"),
        "reason": reason,
    }


def not_measured(row: Mapping[str, Any], reason: str, detail: str, *, account: Any = None, symbol: Any = None,
                 shown: Any = None, truth: Any = None) -> dict[str, Any]:
    """An unreadable side is NOT_MEASURED — never PASS, never FAIL (DSN §1)."""
    return finding(row, "NT_NOT_MEASURED", "NOT_MEASURED", detail, account=account, symbol=symbol,
                   reason=reason if reason in _TYPED_EMPTY else "truth_unreadable",
                   shown={"value": shown} if shown is not None else None,
                   truth={"value": truth} if truth is not None else None)


# ── truth bundle (read-only sources) ───────────────────────────────────────────────────────────────────────────


class Bundle:
    """Every truth source, each independently readable or explicitly unavailable. Never raises on a source."""

    def __init__(self) -> None:
        self.p: dict[str, dict[str, Any]] = {}

    def put(self, name: str, *, rows: Any = None, as_of: Any = None, reason: Optional[str] = None,
            **extra: Any) -> None:
        ok = reason is None
        self.p[name] = {"status": "ok" if ok else "unavailable", "reason": reason, "rows": rows,
                        "as_of": as_of, **extra}

    #: The catalog names the store; the bundle names the source. One alias table, so a row can say
    #: "positions_current" (what the catalog declares) and still reach the loaded bundle entry.
    ALIASES = {"positions_current": "positions", "stop_lifecycle": "stops", "market_quotes": "quotes",
               "market_quotes_extended": "quotes_extended"}

    def get(self, name: str) -> dict[str, Any]:
        return self.p.get(self.ALIASES.get(name, name)) or {
            "status": "unavailable", "reason": "source_unreadable", "rows": None, "as_of": None}

    def ok(self, name: str) -> bool:
        return self.get(name)["status"] == "ok"


def _ident(name: Any) -> str:
    """A table/column name from the catalog, validated before it reaches SQL text."""
    s = str(name or "")
    if not s or not all(c.isalnum() or c == "_" for c in s) or s[0].isdigit():
        raise ValueError(f"unsafe identifier {name!r}")
    return s


def _select(conn: Any, sql: str, params: Optional[Any] = None) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(sql, params or ())
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def pg_connect():  # pragma: no cover - exercised on the host only
    import psycopg2

    conn = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD", ""), connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _quote_where(policy: Mapping[str, Any]) -> tuple[str, list[Any]]:
    q = (policy.get("sources") or {}).get("quotes") or {}
    allowed = [str(s) for s in q.get("allowed") or ["alpaca", "finviz"]]
    prefixes = [str(s) for s in q.get("allowed_prefixes") or ["refresh:schwab"]]
    never = [str(s) for s in q.get("never") or ["yfinance"]]
    pats = [p + "%" for p in prefixes]
    sql = "source = ANY(%s)"
    params: list[Any] = [allowed]
    if pats:
        sql += " OR source LIKE ANY(%s)"
        params.append(pats)
    if never:
        sql += " AND NOT (source = ANY(%s))"
        params.append(never)
    return sql, params


def load_truth(policy: Mapping[str, Any], *, conn_factory: Callable[[], Any] = pg_connect,
               brief_path: Optional[Path] = None) -> Bundle:
    """Read every truth source once. A failed source is recorded unavailable; the others still load."""
    b = Bundle()
    holder: dict[str, Any] = {}

    def conn():
        if "c" not in holder:
            holder["c"] = conn_factory()
        return holder["c"]

    try:
        rows = _select(conn(), "SELECT account_key, symbol, qty, broker_market_value, is_cash, asset_type, as_of, "
                               "source FROM positions_current")
        newest = max([t for t in (_ts(r.get("as_of")) for r in rows) if t], default=None)
        b.put("positions", rows=rows, as_of=newest)
    except Exception as exc:  # noqa: BLE001 -- a source that cannot answer is NOT_MEASURED, never clean
        b.put("positions", reason=f"positions_unreadable: {type(exc).__name__}")
    try:
        rows = _select(conn(), "SELECT account, symbol, broker, order_id, order_type, status, stop_price, qty, "
                               "held_qty, coverage, lifecycle, health, flags, snapshot_at FROM stop_lifecycle "
                               "WHERE snapshot_at = (SELECT max(snapshot_at) FROM stop_lifecycle)")
        newest = max([t for t in (_ts(r.get("snapshot_at")) for r in rows) if t], default=None)
        b.put("stops", rows=rows, as_of=newest)
    except Exception as exc:  # noqa: BLE001 -- an unreadable stop snapshot is NOT_MEASURED, never a silent pass
        b.put("stops", reason=f"stops_unreadable: {type(exc).__name__}")
    try:
        b.put("stop_last_known", rows=_select(conn(), "SELECT broker, account, symbol, order_id, order_type, "
                                                      "stop_price, qty, status, captured_at FROM stop_last_known"))
    except Exception as exc:  # noqa: BLE001 -- the retiring copy is evidence only; its absence is recorded
        b.put("stop_last_known", reason=f"stop_last_known_unreadable: {type(exc).__name__}")
    try:
        where, params = _quote_where(policy)
        rows = _select(conn(), f"SELECT DISTINCT ON (symbol) symbol, source, price, prev_close, fetched_at "
                               f"FROM market_quotes WHERE ({where}) ORDER BY symbol, fetched_at DESC", params)
        newest = max([t for t in (_ts(r.get("fetched_at")) for r in rows) if t], default=None)
        retired: dict[str, str] = {}
        never = [str(s) for s in ((policy.get("sources") or {}).get("quotes") or {}).get("never") or []]
        if never:
            try:
                for r in _select(conn(), "SELECT DISTINCT ON (symbol) symbol, source FROM market_quotes "
                                         "WHERE source = ANY(%s) ORDER BY symbol, fetched_at DESC", [never]):
                    retired[str(r.get("symbol") or "").upper()] = str(r.get("source") or "")
            except Exception:  # noqa: BLE001 -- the retired-row view is evidence, not a required source
                retired = {}
        b.put("quotes", rows=rows, as_of=newest, retired_by_symbol=retired,
              by_symbol={str(r.get("symbol") or "").upper(): r for r in rows})
    except Exception as exc:  # noqa: BLE001 -- unreadable quotes are NOT_MEASURED downstream, never a pass
        b.put("quotes", reason=f"quotes_unreadable: {type(exc).__name__}")
    try:
        # Index/extended-hours quotes (the VIX tile's provenance says market_quotes_extended:schwab:$VIX).
        # `feed` is this store's provider column and `bar_end` its observation time.
        rows = _select(conn(), "SELECT DISTINCT ON (symbol) symbol, feed AS source, price, bar_end AS fetched_at "
                               "FROM market_quotes_extended ORDER BY symbol, bar_end DESC")
        newest = max([t for t in (_ts(r.get("fetched_at")) for r in rows) if t], default=None)
        b.put("quotes_extended", rows=rows, as_of=newest,
              by_symbol={str(r.get("symbol") or "").upper(): r for r in rows})
    except Exception as exc:  # noqa: BLE001 -- unreadable extended quotes are NOT_MEASURED, never a pass
        b.put("quotes_extended", reason=f"quotes_extended_unreadable: {type(exc).__name__}")
    try:
        b.put("brief", doc=json.loads(Path(brief_path).read_text(encoding="utf-8")) if brief_path else None,
              reason=None if brief_path and Path(brief_path).exists() else "source_unreadable",
              path=str(brief_path) if brief_path else None)
    except (OSError, ValueError) as exc:
        b.put("brief", reason=f"brief_unreadable: {type(exc).__name__}")
    if "c" in holder:
        try:
            holder["c"].close()
        except Exception as exc:  # noqa: BLE001 -- a close failure cannot change what was already read
            holder["close_error"] = type(exc).__name__
    return b


# ── served side ────────────────────────────────────────────────────────────────────────────────────────────────


class Unreadable(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _state_root(explicit: Optional[str]) -> Path:
    return Path(explicit or os.environ.get("TRADEAI_STATE_ROOT")
                or str(Path.home() / "trade-ai-releases" / "persistent-state"))


def read_artifact(state_root: Path, rel: str) -> tuple[Any, dict[str, Any]]:
    path = Path(rel)
    if not path.is_absolute():
        path = state_root / rel
    if not path.exists():
        raise Unreadable("source_unreadable", f"artifact not found: {rel}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Unreadable("source_unreadable", f"artifact unreadable: {type(exc).__name__}")
    return doc, {"source": f"artifact:{rel}", "as_of": _ts(doc.get("generated_at") or doc.get("as_of"))
                 if isinstance(doc, Mapping) else None}


def http_get_json(base_url: str, path_with_query: str, *, sleeper: Callable[[float], None] = _time.sleep,
                  opener: Optional[Callable[[str, float], Any]] = None) -> Any:
    """One GET, paced. Only reached outside the §28.8 window; never a broker read."""
    url = base_url.rstrip("/") + path_with_query
    sleeper(HTTP_PACING_S)
    if opener is not None:
        return opener(url, HTTP_TIMEOUT_S)
    import urllib.request

    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310 -- host-local :7777 only
        return json.loads(resp.read().decode("utf-8"))


def served(row: Mapping[str, Any], *, state_root: Path, http_open: bool, base_url: str,
           fetcher: Optional[Callable[[str], Any]] = None) -> tuple[Any, dict[str, Any]]:
    """The served document for one row. Inside the window an api-only row is NOT_MEASURED, not fetched."""
    spec = row.get("served_from") or {}
    kind = str(spec.get("kind") or "")
    if kind == "artifact":
        return read_artifact(state_root, str(spec.get("path")))
    if kind == "pair":  # two artifacts compared (the stop card label against the brief)
        a, ma = read_artifact(state_root, str(spec.get("path")))
        bdoc, mb = read_artifact(state_root, str(spec.get("other_path")))
        return {"primary": a, "other": bdoc}, {"source": f"artifact:{spec.get('path')}+{spec.get('other_path')}",
                                               "as_of": ma.get("as_of")}
    if kind == "api":
        query = str(spec.get("query") or "")
        if not http_open:
            raise Unreadable("in_window_artifact_only", "inside 04:00-16:15 ET: no HTTP to :7777 (§28.8)")
        try:
            doc = (fetcher or (lambda q: http_get_json(base_url, q)))(str(spec.get("path")) + query)
        except Exception as exc:  # noqa: BLE001 -- an unreachable endpoint is NOT_MEASURED
            raise Unreadable("source_unreadable", f"api unreadable: {type(exc).__name__}")
        if isinstance(doc, Mapping) and isinstance(doc.get("data"), Mapping) and "ok" in doc:
            doc = doc["data"]  # every /api/v2 route wraps its payload as {ok, data}: the pointers read `data`
        return doc, {"source": f"api:{spec.get('path')}", "as_of": None}
    raise Unreadable("checker_unsupported", f"served_from.kind {kind!r} is not a catalog kind")


# ── comparators (pure) ────────────────────────────────────────────────────────────────────────────────────────


def _tolerance(spec: Mapping[str, Any], shown: float, truth: float) -> bool:
    t = spec or {}
    kind = str(t.get("kind") or "exact")
    value = _num(t.get("value"))
    if kind == "exact":
        return abs(shown - truth) <= 1e-9
    if kind == "abs":
        return abs(shown - truth) <= (value if value is not None else 0.01)
    if kind == "pct":
        if truth == 0:
            return abs(shown) <= (value if value is not None else 0.5)
        return abs(shown - truth) / abs(truth) * 100.0 <= (value if value is not None else 0.5)
    raise ValueError(f"unknown tolerance kind {kind!r}")


def _fmt(v: Any) -> str:
    f = _num(v)
    return f"{f:,.4f}".rstrip("0").rstrip(".") if f is not None else str(v)


_STATE_FROM_LIFECYCLE = {"working": "active", "near_trigger": "active", "active": "active",
                         "filled": "filled", "cancelled": "none", "canceled": "none", "expired": "none",
                         "rejected": "none", "replaced": "none"}


class _AbsentUnset:
    """Sentinel: the catalog declared no absence value, so a missing truth row is unmeasured, not zero."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unset>"


_ABSENT_UNSET = _AbsentUnset()


def _same_value(a: Any, b: Any) -> bool:
    """Equality for a displayed value against a declared absence: numbers numerically, words as words."""
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) <= 1e-9
    return _canon(a) == _canon(b)


def _one(obj: Any, ptrs: Any) -> tuple[Any, Optional[str]]:
    """``first_value`` that also accepts a bare pointer string or column name."""
    if isinstance(ptrs, str):
        ptrs = [ptrs]
    return first_value(obj, ptrs or ())


def _row_key(obj: Mapping[str, Any], keymap: Mapping[str, Any]) -> Optional[tuple[str, ...]]:
    parts: list[str] = []
    for _, candidates in keymap.items():
        val, _ = _one(obj, candidates)
        if val is None:
            return None
        parts.append(_canon(val))
    return tuple(parts)


def _key_label(keys: Iterable[str]) -> tuple[Optional[str], Optional[str]]:
    """(account, symbol) out of a key tuple; unknown extra parts are ignored for display only."""
    vals = list(keys)
    return (vals[0] if vals else None), (vals[1] if len(vals) > 1 else None)


def truth_bundle_coverage(bundle: Bundle, cfg: Mapping[str, Any], *, now: datetime, session: bool) -> dict[str, Any]:
    """Reuse desk_truth_monitor.held_exit_coverage for the DB side — no second coverage SQL (REV 2 C)."""
    from scripts import desk_truth_monitor as D

    pos = bundle.get("positions")
    stp = bundle.get("stops")
    if pos["status"] != "ok" or stp["status"] != "ok":
        return {"status": "unavailable", "reason": "truth_unreadable", "rows": None}
    res = D.held_exit_coverage(list(pos["rows"] or []), list(stp["rows"] or []), cfg, now=now, session=session)
    if res.get("coverage_verdict") == "NOT_MEASURED":
        return {"status": "unavailable", "reason": "stale_truth", "rows": res}
    return {"status": "ok", "rows": res}


# ── one catalog row → findings ───────────────────────────────────────────────────────────────────────────────


def row_scalar(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
               now: datetime, session: bool) -> list[dict[str, Any]]:
    """Per-object compare: qty, market value, price, stop price, stop qty, stop state."""
    spec = row["served_from"]
    truth_spec = row.get("truth") or {}
    provider = str(truth_spec.get("provider") or "")
    src = bundle.get(provider)
    if src["status"] != "ok":
        return [not_measured(row, "truth_unreadable", f"{provider} unavailable: {src.get('reason')}")]
    rows_ptr = spec.get("rows")
    value_ptrs = list(spec.get("value") or ())
    # A truth value is a COLUMN of the store ("qty"), not a JSON pointer into a payload.
    tval_spec = truth_spec.get("value")
    truth_col = tval_spec if isinstance(tval_spec, str) else None
    truth_ptrs = list(tval_spec or ()) if not isinstance(tval_spec, str) else []
    keymap = spec.get("key") or {}
    tkey = truth_spec.get("key") or keymap
    real_ptr: dict[tuple[str, ...], Optional[str]] = {}
    if rows_ptr:
        srows = pointer(doc, rows_ptr)
        if not isinstance(srows, list):
            return [not_measured(row, "no_such_field", f"served rows {rows_ptr!r} not found", shown=rows_ptr)]
        smap = {}
        for r in srows:
            if isinstance(r, Mapping):
                k = _row_key(r, keymap)
                if k is not None:
                    smap[k] = r
        tmap: dict[tuple[str, ...], Any] = {}
        grouped: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
        for r in src["rows"] or []:
            k = _row_key(r, tkey)
            if k is not None:
                grouped.setdefault(k, []).append(r)
        if provider == "stop_lifecycle":
            live = {_canon(x) for x in LIVE_STOP_LIFECYCLES}
            for k, rows in grouped.items():
                tmap[k] = next((r for r in rows if _canon(r.get("lifecycle")) in live), None)
        else:
            for k, rows in grouped.items():
                tmap[k] = rows[-1]
    else:
        # Single-figure form: one served scalar against the one truth row (the VIX tile vs the $VIX row).
        shown0, ptr0 = first_value(doc, value_ptrs)
        if shown0 is None:
            return [not_measured(row, "no_such_field", f"served field {value_ptrs} not found")]
        smap, value_ptrs, real_ptr = {(): {"value": shown0}}, ["/value"], {(): ptr0}
        want = str(truth_spec.get("symbol") or "").strip().upper()
        cand = src["rows"] or []
        trow0 = next((r for r in cand if str(r.get("symbol") or "").upper() == want), None) if want \
            else (cand[0] if cand else None)
        if trow0 is None:
            return [not_measured(row, "truth_unreadable", f"{provider} has no {want or 'newest'} row")]
        tmap = {(): trow0}
    freshness = _num(spec.get("truth_fresh_min_in_session") if spec.get("truth_fresh_min_in_session") is not None
                     else truth_spec.get("fresh_min_in_session"))
    if session and freshness is not None:
        newest = src.get("as_of")
        if newest is None or (now - newest) > timedelta(minutes=freshness):
            return [not_measured(row, "stale_truth",
                                 f"{provider} newest {'unknown' if newest is None else newest.isoformat()} "
                                 f"older than {freshness:g} min in session",
                                 truth={"as_of": newest.isoformat() if newest else None})]
    transform = truth_spec.get("transform")
    out: list[dict[str, Any]] = []
    tol = row.get("tolerance") or {}
    # A selection surface (the brief's stop_advice, the CIO holdings list) lists only what it chose to show;
    # an object it omits is not a missing figure. Either spelling (row level or served_from) is accepted.
    only_displayed = bool(spec.get("only_displayed") or row.get("only_displayed"))
    for k in sorted(set(smap) | set(tmap)):
        acct, sym = _key_label(k)
        srow, trow = smap.get(k), tmap.get(k)
        row_obj, km = (srow, keymap) if srow is not None else (trow, tkey)
        if isinstance(row_obj, Mapping) and isinstance(km, Mapping):
            a, _ = _one(row_obj, km.get("account"))
            s, _ = _one(row_obj, km.get("symbol"))
            acct, sym = (a if a is not None else acct), (s if s is not None else sym)
        shown, sp = first_value(srow, value_ptrs) if srow is not None else (None, None)
        sp = real_ptr.get(k, sp) if real_ptr else sp
        raw_truth, tp = ((trow.get(truth_col), truth_col) if trow is not None and truth_col
                         else first_value(trow, truth_ptrs)) if trow is not None else (None, None)
        truth_v = raw_truth
        if transform == "lifecycle_state" and raw_truth is not None:
            truth_v = _STATE_FROM_LIFECYCLE.get(_canon(raw_truth), "unknown")
        # The value of an object with no live row is the catalog's declared absence ("absent": 0 / "none"),
        # never an accident of the row being missing (REV 2: stop_last_known may keep a retired row).
        absent = truth_spec.get("absent", _ABSENT_UNSET)
        if trow is None and absent is not _ABSENT_UNSET:
            truth_v = absent
        # A field the page displays as null is a claim of absence (the stop card's "no working stop"),
        # not an omission, when the catalog says so.
        shown_null_is_absence = bool(spec.get("shown_null_is_absence"))
        code = str(spec.get("code") or "NT_VALUE_MISMATCH")
        truth_side = {"value": truth_v, "raw": raw_truth, "field": tp, "provider": provider,
                      "as_of": (src.get("as_of").isoformat() if isinstance(src.get("as_of"), datetime) else
                                src.get("as_of")) if src.get("as_of") else None}
        if shown is None and only_displayed and not shown_null_is_absence:
            continue  # the field is not displayed on this row; a selection surface shows only what it chose
        # A row whose own provenance says the figure is not a broker fact (a PLANNED stop is the CIO's
        # recommendation, `stop_source: planned`) has no stop_lifecycle truth to be graded against.
        only_when = spec.get("only_when")
        if isinstance(only_when, Mapping) and srow is not None:
            fval, fptr = _one(srow, only_when.get("field"))
            allowed = only_when.get("equals")
            allowed_c = {_canon(x) for x in ([allowed] if isinstance(allowed, str) else (allowed or []))}
            if fptr is not None and _canon(fval) not in allowed_c:
                continue
        if (isinstance(trow, Mapping) and trow.get("is_cash")) or (isinstance(srow, Mapping) and srow.get("is_cash")):
            continue  # a cash balance has no shares, no price and no stop
        if shown is None and truth_v is None:
            continue
        if srow is not None and shown is None and shown_null_is_absence:
            if absent is not _ABSENT_UNSET and _same_value(truth_v, absent):
                continue  # the page says "no stop" and the store has no live stop: they agree
            out.append(finding(row, code, "MISMATCH", f"{acct} {sym}: the page shows no stop; truth "
                           f"{_fmt(truth_v)} ({provider})", account=acct, symbol=sym,
                           shown={"value": None, "source": meta.get("source")}, truth=truth_side))
            continue
        shown_side = {"value": shown, "as_of": (first_value(srow, spec.get("as_of") or ())[0]
                                                 if srow is not None and spec.get("as_of") else None),
                      "source": meta.get("source"), "field": sp}
        if srow is None:
            if only_displayed:
                continue  # the page lists a selection; an object it does not list is not a missing figure
            if truth_v is not None:
                out.append(finding(row, code, "MISMATCH", f"{acct} {sym}: the page does not show it; truth "
                               f"{_fmt(truth_v)} ({provider})", account=acct, symbol=sym,
                               shown={"value": None, "source": meta.get("source")}, truth=truth_side))
            continue
        if trow is None and shown is not None:
            if provider == "stop_lifecycle":
                # The store has this object but no LIVE stop for it: a displayed working stop is exactly the
                # SPCX failure — a stop_last_known row the broker had already cancelled or let expire.
                if absent is not _ABSENT_UNSET and _same_value(shown, absent):
                    continue  # the page and the store both say "no working stop"
                out.append(finding(row, code, "MISMATCH",
                                   f"{acct} {sym}: the page shows {_fmt(shown)}; stop_lifecycle has no WORKING "
                                   f"stop for it (only cancelled/replaced/filled/expired rows)",
                                   account=acct, symbol=sym, shown=shown_side,
                                   truth={"value": None, "provider": provider, "live": False}))
                continue
            retired = (src.get("retired_by_symbol") or {}) if isinstance(src, Mapping) else {}
            rsym = str(sym or "").upper()
            if rsym in retired:
                # REV 2 A: a page number backed only by a retired provider is a FAIL, never a pass.
                out.append(finding(row, "NT_QUOTE_SOURCE", "MISMATCH",
                                   f"{sym}: the page shows {_fmt(shown)}; market_quotes has no allowed row, only "
                                   f"{retired[rsym]!r} (retired)", account=acct, symbol=sym, shown=shown_side,
                                   truth={"value": None, "provider": provider, "retired": retired[rsym]}))
            elif provider == "market_quotes":
                if _num(shown) == 0:
                    # A 0.00 mark on an instrument with no quote is a placeholder (unpriced fixed income),
                    # not a displayed number that disagrees with anything.
                    continue
                # The page shows a price the quote store cannot verify: unreadable truth, never a pass, never a fail.
                out.append(not_measured(row, "no_rows", f"{sym}: no allowed quote row; the displayed price "
                                                     f"cannot be verified", account=acct, symbol=sym,
                                        shown={"value": shown, "field": sp}))
            else:
                out.append(finding(row, code, "MISMATCH", f"{acct} {sym}: the page shows {_fmt(shown)}; "
                               f"{provider} has no row", account=acct, symbol=sym, shown=shown_side,
                               truth={"value": None, "provider": provider}))
            continue
        if isinstance(shown, bool) or isinstance(truth_v, bool) or isinstance(shown, str) \
                or isinstance(truth_v, str) or truth_v is None:
            # A state/vocabulary value (stop_state) is compared as a word, never coerced to a number.
            if _canon(shown) != _canon(truth_v):
                out.append(finding(row, code, "MISMATCH", f"{acct} {sym}: the page shows {shown!r}; truth "
                               f"{truth_v!r} ({provider})", account=acct, symbol=sym, shown=shown_side,
                               truth=truth_side))
            continue
        sf, tf = _num(shown), _num(truth_v)
        if sf is None or tf is None:
            out.append(finding(row, code, "MISMATCH", f"{acct} {sym}: the page shows {shown!r}; truth "
                           f"{truth_v!r} is not comparable", account=acct, symbol=sym, shown=shown_side,
                           truth=truth_side))
            continue
        if not _tolerance(tol, sf, tf):
            unit = "" if str(tol.get("kind")) == "pct" else (tol.get("unit") or "")
            out.append(finding(row, code, "MISMATCH",
                               f"{acct} {sym}: the page shows {_fmt(sf)}{unit}; truth {_fmt(tf)}{unit} "
                               f"({provider})", account=acct, symbol=sym, shown=shown_side, truth=truth_side))
    return out


def book_total(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
               now: datetime, session: bool) -> list[dict[str, Any]]:
    """The one book total vs positions_current: non-cash broker_market_value + cash rows' dollar balance."""
    pos = bundle.get("positions")
    if pos["status"] != "ok":
        return [not_measured(row, "truth_unreadable", f"positions_current unavailable: {pos.get('reason')}")]
    newest = pos.get("as_of")
    stale_min = _num((row.get("truth") or {}).get("fresh_min_in_session"))
    if session and stale_min is not None and (newest is None or (now - newest) > timedelta(minutes=stale_min)):
        return [not_measured(row, "stale_truth", f"positions_current newest "
                             f"{'unknown' if newest is None else newest.isoformat()} older than {stale_min:g} min",
                             truth={"as_of": newest.isoformat() if newest else None})]
    total = 0.0
    missing = 0
    for r in pos["rows"] or []:
        if r.get("is_cash"):
            v = _num(r.get("qty"))
        else:
            v = _num(r.get("broker_market_value"))
        if v is None:
            missing += 1
            continue
        total += v
    if missing:
        return [not_measured(row, "truth_unreadable", f"{missing} positions_current row(s) carry no value")]
    spec = row["served_from"]
    shown, sp = first_value(doc, spec.get("value") or ())
    if shown is None:
        return [not_measured(row, "no_such_field", f"served field {spec.get('value')} not found")]
    sf = _num(shown)
    if sf is None:
        return [finding(row, str(spec.get("code") or "NT_TOTAL_MISMATCH"), "MISMATCH",
                        f"the page shows {shown!r}, not a number", shown={"value": shown})]
    if _tolerance(row.get("tolerance") or {"kind": "abs", "value": 1.0}, sf, total):
        return []
    return [finding(row, str(spec.get("code") or "NT_TOTAL_MISMATCH"), "MISMATCH",
                    f"the page shows {_fmt(sf)}; positions_current sums to {_fmt(total)} "
                    f"(diff {_fmt(sf - total)}, {len(pos['rows'] or [])} rows)",
                    shown={"value": sf, "field": sp, "source": meta.get("source"),
                           "as_of": meta.get("as_of").isoformat() if isinstance(meta.get("as_of"), datetime) else None},
                    truth={"value": round(total, 2), "provider": "positions_current",
                           "as_of": newest.isoformat() if newest else None})]


def account_total(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
                  now: datetime, session: bool) -> list[dict[str, Any]]:
    pos = bundle.get("positions")
    if pos["status"] != "ok":
        return [not_measured(row, "truth_unreadable", f"positions_current unavailable: {pos.get('reason')}")]
    sums: dict[str, float] = {}
    for r in pos["rows"] or []:
        v = _num(r.get("qty")) if r.get("is_cash") else _num(r.get("broker_market_value"))
        if v is None:
            return [not_measured(row, "truth_unreadable", "positions_current row with no value")]
        sums[_canon(r.get("account_key"))] = sums.get(_canon(r.get("account_key")), 0.0) + v
    spec = row["served_from"]
    srows = pointer(doc, spec.get("rows") or "")
    if not isinstance(srows, list):
        return [not_measured(row, "no_such_field", "served account rows not found")]
    out: list[dict[str, Any]] = []
    seen = set()
    for r in srows:
        if not isinstance(r, Mapping):
            continue
        acct, _ = first_value(r, spec.get("key") or ())
        val, _ = first_value(r, spec.get("value") or ())
        k = _canon(acct)
        if not k:
            continue
        seen.add(k)
        if k not in sums:
            out.append(finding(row, str(spec.get("code") or "NT_ACCOUNT_TOTAL_MISMATCH"), "MISMATCH",
                               f"{k}: the page shows an account total; positions_current has no row",
                               account=k, shown={"value": val, "source": meta.get("source")},
                               truth={"value": None, "provider": "positions_current"}))
            continue
        sf, tf = _num(val), sums[k]
        if sf is None or not _tolerance(row.get("tolerance") or {"kind": "abs", "value": 1.0}, sf, tf):
            out.append(finding(row, str(spec.get("code") or "NT_ACCOUNT_TOTAL_MISMATCH"), "MISMATCH",
                               f"{k}: the page shows {_fmt(val)}; positions_current sums to {_fmt(tf)}",
                               account=k, shown={"value": sf if sf is not None else val, "source": meta.get("source")},
                               truth={"value": round(tf, 2), "provider": "positions_current",
                                      "as_of": pos.get("as_of").isoformat() if pos.get("as_of") else None}))
    for k in sorted(set(sums) - seen):
        out.append(finding(row, str(spec.get("code") or "NT_ACCOUNT_TOTAL_MISMATCH"), "MISMATCH",
                           f"{k}: positions_current holds {_fmt(sums[k])}; the page shows no account total",
                           account=k, shown={"value": None}, truth={"value": round(sums[k], 2)}))
    return out


def coverage(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
             now: datetime, session: bool) -> list[dict[str, Any]]:
    """Held - working-stop coverage, the XLV case. The page's own count/list against the derived truth."""
    cfg = row.get("_coverage_cfg") or {}
    cov = truth_bundle_coverage(bundle, cfg, now=now, session=session)
    if cov["status"] != "ok":
        return [not_measured(row, str(cov.get("reason") or "truth_unreadable"),
                             "coverage cannot be measured from positions_current + stop_lifecycle")]
    res = cov["rows"]
    truth_n = int(res.get("uncovered") or 0)
    spec = row["served_from"]
    shown, _ = first_value(doc, spec.get("value") or ())
    if shown is None:
        return [not_measured(row, "no_such_field", f"served field {spec.get('value')} not found")]
    sf = _num(shown)
    if sf is None:
        return [finding(row, "NT_UNPROTECTED", "MISMATCH", f"the page shows {shown!r}, not a count",
                        shown={"value": shown, "source": meta.get("source")})]
    if int(sf) == truth_n:
        return []
    missing = [f["key"].split(":", 1)[1] for f in res.get("findings") or []
               if f.get("code") == "UNCOVERED" and f.get("alert")]
    return [finding(row, "NT_UNPROTECTED", "MISMATCH",
                    f"the page shows {int(sf)} unprotected; held - working-stop coverage is {truth_n}"
                    + (f" ({', '.join(missing)})" if missing else ""),
                    shown={"value": int(sf), "source": meta.get("source")},
                    truth={"value": truth_n, "provider": "positions_current x stop_lifecycle",
                           "accounts": missing, "snapshot_age_h": res.get("snapshot_age_h"),
                           "as_of": (bundle.get("stops").get("as_of").isoformat()
                                     if bundle.get("stops").get("as_of") else None)})]


def cross_source(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
                 now: datetime, session: bool) -> list[dict[str, Any]]:
    """stop_lifecycle (canonical) vs stop_last_known (retiring copy): a disagreement is itself a finding."""
    life, slk = bundle.get("stops"), bundle.get("stop_last_known")
    if life["status"] != "ok" or slk["status"] != "ok":
        return [not_measured(row, "truth_unreadable", "stop_lifecycle or stop_last_known unavailable")]
    working = {str(x) for x in row.get("working_lifecycles") or ["working", "near_trigger"]}
    lm = {(str(r.get("account")), str(r.get("symbol") or "").upper()): r for r in life["rows"] or []}
    km = {(str(r.get("account")), str(r.get("symbol") or "").upper()): r for r in slk["rows"] or []
          if str(r.get("status") or "").lower() in {"working", "active", "open", "new", "accepted"}}
    out: list[dict[str, Any]] = []
    for key in sorted(set(lm) | set(km)):
        acct, sym = (key[0], key[1]) if len(key) == 2 else (None, None)
        l, k = lm.get(key), km.get(key)
        shown = {"value": k.get("stop_price") if k is not None else None,
                 "status": k.get("status") if k is not None else None, "source": "stop_last_known",
                 "as_of": k.get("captured_at") if k is not None else None}
        truth = {"value": l.get("stop_price") if l is not None else None,
                 "lifecycle": l.get("lifecycle") if l is not None else None, "provider": "stop_lifecycle",
                 "as_of": life.get("as_of").isoformat() if life.get("as_of") else None}
        if k is None:
            continue
        if l is None:
            out.append(finding(row, "NT_STOP_CROSS_CHECK", "MISMATCH",
                               f"{acct} {sym}: stop_last_known still shows a {k.get('status')} stop; "
                               "stop_lifecycle has no row (expired or cancelled at the broker)",
                               account=acct, symbol=sym, shown=shown, truth=truth))
            continue
        lifecycle = str(l.get("lifecycle") or "")
        lp, kp = _num(l.get("stop_price")), _num(k.get("stop_price"))
        if lifecycle not in working and lifecycle != "filled":
            out.append(finding(row, "NT_STOP_CROSS_CHECK", "MISMATCH",
                               f"{acct} {sym}: stop_last_known still shows a {k.get('status')} stop; "
                               f"stop_lifecycle says {lifecycle}", account=acct, symbol=sym,
                               shown=shown, truth=truth))
        elif lp is not None and kp is not None and abs(lp - kp) > 0.005:
            out.append(finding(row, "NT_STOP_CROSS_CHECK", "MISMATCH",
                               f"{acct} {sym}: stop_lifecycle {_fmt(lp)} vs stop_last_known {_fmt(kp)}",
                               account=acct, symbol=sym, shown=shown, truth=truth))
    return out


def same_figure(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
                now: datetime, session: bool) -> list[dict[str, Any]]:
    """One figure, several surfaces. Reuses scripts/lib/site_audit/cross_checks.same_figure_everywhere."""
    from scripts.lib.site_audit import cross_checks as X

    spec = row["served_from"]
    surfaces: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for s in spec.get("surfaces") or []:
        name = str(s.get("name") or s.get("value") or s.get("rows") or "surface")
        if s.get("sum_of"):
            rows = pointer(doc, s.get("rows") or "")
            if isinstance(rows, Mapping):
                rows = list(rows.values())  # today_by_account is keyed by account id
            if not isinstance(rows, list):
                unresolved.append(f"{name} (rows not served)")
                continue
            vals = [_num(pointer(r, s["sum_of"])) for r in rows if isinstance(r, Mapping)]
            vals = [v for v in vals if v is not None]
            if vals:
                surfaces.append({"name": s.get("name"), "value": round(sum(vals), 2)})
            else:
                unresolved.append(f"{name} (every row's {s['sum_of']} is null)")
            continue
        v, _ = first_value(doc, s.get("value") or ())
        if _num(v) is not None:
            surfaces.append({"name": s.get("name"), "value": _num(v)})
        else:
            unresolved.append(f"{name} (null or absent)")
    if len(surfaces) < 2:
        return [not_measured(row, "no_such_field",
                             "the served figure is not measurable: " + "; ".join(unresolved or ["no surfaces"]))]
    found = X.same_figure_everywhere(str(spec.get("figure") or row.get("figure_id")), surfaces)
    return [finding(row, "NT_DAY_PNL_SPLIT", "MISMATCH", f["what"], shown=f["evidence"],
                    severity="P1") for f in found]


def session_label(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
                  now: datetime, session: bool) -> list[dict[str, Any]]:
    """The stop card's named session day vs brief.last_close.session_date (the 'Friday' label)."""
    spec = row["served_from"]
    primary = doc.get("primary") if isinstance(doc, Mapping) and "primary" in doc else None
    other = doc.get("other") if isinstance(doc, Mapping) and "other" in doc else None
    if primary is None or not isinstance(other, Mapping):
        return [not_measured(row, "source_unreadable", "the label and the brief did not both resolve")]
    session_date = pointer(other, str(spec.get("date_pointer") or "/last_close/session_date"))
    day = _session_date(session_date)
    if day is None:
        return [not_measured(row, "no_such_field", f"brief last_close.session_date {session_date!r} unreadable")]
    out: list[dict[str, Any]] = []
    expected = day.weekday()
    named: list[tuple[str, int]] = []
    for p in spec.get("text_pointers") or ():
        text = pointer(primary, p)
        if not isinstance(text, str):
            continue
        for token in text.replace("'", " ").replace(",", " ").replace("’", " ").split():
            idx = _WEEKDAYS.get(token.strip(".").lower())
            if idx is not None:
                named.append((p, idx))
    if not named:
        return [not_measured(row, "no_weekday_named", "the served label names no weekday")]
    for p, idx in named:
        if idx != expected:
            shown_text = pointer(primary, p)
            out.append(finding(row, "NT_SESSION_LABEL", "MISMATCH",
                               f"the card names {shown_text!r} but the last close is "
                               f"{day} ({day.strftime('%A')})",
                               shown={"value": shown_text, "source": meta.get("source")},
                               truth={"value": str(day), "provider": "cio_overnight_brief",
                                      "as_of": other.get("generated_at")}))
            break
    own = pointer(primary, str(spec.get("own_date_pointer") or "/window/session_date"))
    own_day = _session_date(own)
    if own_day is not None and own_day != day:
        out.append(finding(row, "NT_SESSION_LABEL", "MISMATCH",
                           f"the card's session_date {own!r} is not the brief's {session_date!r}",
                           shown={"value": own, "source": meta.get("source")},
                           truth={"value": session_date, "provider": "cio_overnight_brief"}))
    return out


def authority_source(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
                     now: datetime, session: bool) -> list[dict[str, Any]]:
    """G3: the figure's own provenance field must equal its domain's declared authority."""
    spec = row["served_from"]
    policy = row.get("_policy") or {}
    dom = (policy.get("domains") or {}).get(str(row.get("domain") or "")) or {}
    allowed = {_canon(x) for x in dom.get("allowed_sources") or []}
    never = {_canon(x) for x in dom.get("never_sources") or []}
    rows = pointer(doc, spec.get("rows") or "") if spec.get("rows") else [doc]
    if not isinstance(rows, list):
        return [not_measured(row, "no_such_field", "served rows not found")]
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        acct, _ = first_value(r, spec.get("key") or ()) if spec.get("key") else (None, None)
        sym, _ = first_value(r, ["/symbol"])
        val, p = first_value(r, spec.get("value") or ())
        v = _canon(val)
        if not v:
            out.append(not_measured(row, "no_such_field", f"no provenance field at {spec.get('value')}",
                                    account=acct, symbol=sym))
            continue
        base = v.split(":", 1)[0]
        if v in never or base in never:
            out.append(finding(row, "NT_QUOTE_SOURCE", "MISMATCH",
                               f"{sym or acct}: served from a retired source {val!r}",
                               account=acct, symbol=sym, shown={"value": val, "field": p},
                               truth={"value": sorted(allowed), "provider": str(row.get("domain"))},
                               severity=str(row.get("severity") or "P1")))
        elif allowed and v not in allowed and base not in allowed:
            out.append(finding(row, "NT_QUOTE_SOURCE", "MISMATCH",
                               f"{sym or acct}: served source {val!r} is not the declared authority "
                               f"{sorted(allowed)}", account=acct, symbol=sym,
                               shown={"value": val, "field": p},
                               truth={"value": sorted(allowed), "provider": str(row.get("domain"))}))
    return out


# ── authority G2 / G1 ───────────────────────────────────────────────────────────────────────────────────────


def authority_writes(policy: Mapping[str, Any], *, conn_factory: Callable[[], Any] = pg_connect,
                     now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """G2: rows written in the last hour by a provider the authority file does not declare for that domain."""
    out: list[dict[str, Any]] = []
    open_errors: list[str] = []  # a close failure cannot change what was read; keep the fact, not silence
    now = now or datetime.now(timezone.utc)
    try:
        conn = conn_factory()
    except Exception as exc:  # noqa: BLE001 -- an unreachable DB is reported as truth_unreadable, not raised
        return [not_measured({"page": "*", "figure_id": "authority.writes", "severity": "P1",
                              "domain": "authority", "producer_lane": "numbers-truth-audit"},
                             "truth_unreadable", f"DB unavailable: {type(exc).__name__}")]
    try:
        for dom_name, dom in sorted((policy.get("write_watch") or {}).items()):
            table = _ident(dom.get("table"))
            tcol = _ident(dom.get("time_col") or "fetched_at")
            pcol = _ident(dom.get("provider_col") or "source")
            declared = {_canon(x) for x in dom.get("declared_sources") or []}
            prefixes = tuple(_canon(x) for x in dom.get("declared_prefixes") or [])
            never = {_canon(x) for x in dom.get("never_sources") or []}
            try:
                rows = _select(conn, f"SELECT {pcol} AS provider, count(*) AS n, max({tcol}) AS newest "
                                     f"FROM {table} WHERE {tcol} > now() - interval '1 hour' GROUP BY {pcol}")
            except Exception as exc:  # noqa: BLE001 -- one domain's read failure is that domain's finding
                out.append(not_measured({"page": "*", "figure_id": f"authority.writes.{dom_name}",
                                         "severity": "P1", "domain": dom_name,
                                         "producer_lane": "numbers-truth-audit"},
                                        "truth_unreadable", f"{table} unreadable: {type(exc).__name__}"))
                continue
            for r in rows:
                prov = _canon(r.get("provider"))
                # An account-scoped writer name (moomoo_opend, alpaca_live_api) is the registered provider
                # under a suffix; only an undeclared or retired provider is a finding.
                retired = prov in never
                if not retired and (prov in declared or (prefixes and prov.startswith(prefixes))):
                    continue
                row = {"page": "*", "figure_id": f"authority.writes.{dom_name}", "severity": "P1",
                       "domain": dom_name, "producer_lane": dom.get("producer_lane")}
                out.append(finding(row, "NT_AUTHORITY_WRITE", "MISMATCH",
                                   f"{table}: {int(r.get('n') or 0)} row(s) written in the last hour by "
                                   f"{r.get('provider')!r}, which {dom_name} does not declare"
                                   + (" (retired)" if prov in never else ""),
                                   account=None, symbol=None,
                                   shown={"value": prov, "rows": int(r.get("n") or 0),
                                          "as_of": str(r.get("newest"))},
                                   truth={"value": sorted(declared), "provider": f"{dom_name}.{table}"}))
    finally:
        try:
            conn.close()
        except Exception as exc:  # noqa: BLE001 -- a close failure cannot change what was already read
            open_errors.append(type(exc).__name__)
    return out


def authority_static(*, root: Optional[Path] = None, runner: Optional[Callable[[list[str], Path], Any]] = None,
                     timeout_s: float = 90.0) -> list[dict[str, Any]]:
    """G1: the authority gate at this code root (the live release's HEAD). One finding per rule+file."""
    base = Path(root or ROOT)
    cmd = [sys.executable, str(base / "scripts" / "check_data_source_authority.py"), "--json"]
    row = {"page": "*", "figure_id": "authority.static", "severity": "P1", "domain": "authority",
           "producer_lane": "numbers-truth-audit"}
    try:
        if runner is not None:
            proc = runner(cmd, base)
        else:
            proc = subprocess.run(cmd, cwd=str(base), capture_output=True, text=True, timeout=timeout_s)
        doc = json.loads(getattr(proc, "stdout", "") or "{}")
    except subprocess.TimeoutExpired:
        return [not_measured(row, "authority_gate_unavailable", "the authority gate exceeded its time budget")]
    except Exception as exc:  # noqa: BLE001 -- any runner failure is an unavailable gate, never a pass
        return [not_measured(row, "authority_gate_unavailable", f"the authority gate did not answer: "
                             f"{type(exc).__name__}")]
    findings = doc.get("findings") if isinstance(doc, Mapping) else None
    if not isinstance(findings, list):
        return [not_measured(row, "authority_gate_unavailable", "the authority gate returned no findings list")]
    out: list[dict[str, Any]] = []
    for f in findings:
        if not isinstance(f, Mapping):
            continue
        files = f.get("files") or f.get("file") or f.get("lane") or f.get("store") or f.get("kind") or ""
        key = files[0] if isinstance(files, list) and files else str(files)
        rule = str(f.get("check") or "AUTHORITY")
        detail = {k: v for k, v in f.items() if k not in ("check", "files", "action")}
        out.append(finding(row, "NT_AUTHORITY_STATIC", "MISMATCH",
                           f"{rule}: {json.dumps(detail, default=str)[:400]}",
                           account=None, symbol=None,
                           shown={"value": rule, "file": key},
                           truth={"value": "clean", "provider": "config/data_source_authority.json"}))
    return out


# ── the audit ────────────────────────────────────────────────────────────────────────────────────────────────


#: The stores a served price may name in its own provenance field. The page moved from `market_quotes` to
#: `market_quotes_extended` for extended-hours names (live 2026-11-09: SKYD and SPCX held `8.70`/`142.07` with
#: `quote_source: market_quotes_extended`); grading every row against one store made correct prices look wrong.
QUOTE_STORES = {"market_quotes": "quotes", "market_quotes_extended": "quotes_extended"}


def row_quote(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
              now: datetime, session: bool) -> list[dict[str, Any]]:
    """A displayed price graded against the allowed quote stores, with its own provenance label graded too.

    The truth is the freshest allowed row for the symbol, whichever store holds it: the page's ``quote_source``
    is what the page CLAIMS, and a claim is not evidence. Live 2026-11-09: ANET served 186.25 tagged
    ``market_quotes_extended`` while that store's newest row (169.95) was 14 h old and ``market_quotes`` held
    186.26 at 16:45 — the number was right and the label was wrong, so the finding is NT_QUOTE_SOURCE, never a
    price mismatch. And a stale store must never be compared at all: an old bar is not a contradicting price."""
    spec = row["served_from"]
    src_field = str(spec.get("source_field") or "quote_source")
    keymap = spec.get("key") or {}
    val = list(spec.get("value") or ())
    tol = row.get("tolerance") or {}
    policy = row.get("_policy") or {}
    srows = pointer(doc, str(spec.get("rows") or ""))
    if not isinstance(srows, list):
        return [not_measured(row, "no_such_field", f"served rows {spec.get('rows')!r} not found")]
    fresh_min = _num(spec.get("truth_fresh_min_in_session")
                     if spec.get("truth_fresh_min_in_session") is not None
                     else (row.get("truth") or {}).get("fresh_min_in_session"))
    if fresh_min is None:
        fresh_min = 15.0
    closed_min = _num(policy.get("quote_fresh_min_closed"))
    closed_min = 240.0 if closed_min is None else closed_min
    bound = timedelta(minutes=fresh_min if session else closed_min)
    where = (Path(str(spec.get("path") or "")).name if str(spec.get("kind")) == "artifact" else "the page")
    out: list[dict[str, Any]] = []
    for s in srows:
        if not isinstance(s, Mapping):
            continue
        shown, sp = first_value(s, val)
        if shown is None or _num(shown) == 0:
            continue  # not displayed, or a 0.00 placeholder on an unquoted instrument
        acct = _one(s, keymap.get("account"))[0]
        sym = _one(s, keymap.get("symbol"))[0]
        if _canon(sym) == "cash" or _canon(s.get("asset_type")) == "cash" or s.get("is_cash"):
            continue  # a cash balance is a dollar amount, not a quoted instrument
        rsym = str(sym or "").upper()
        source = str(_one(s, src_field)[0] or "")
        shown_side = {"value": shown, "field": sp, "source": source, "page": spec.get("path")}
        retired: dict[str, str] = {}
        candidates: list[tuple[str, Mapping[str, Any], datetime]] = []
        unreadable: list[str] = []
        seen_by_store: dict[str, datetime] = {}
        for name, key in QUOTE_STORES.items():
            st = bundle.get(key)
            retired.update(st.get("retired_by_symbol") or {})
            if st["status"] != "ok":
                unreadable.append(f"{name}: {st.get('reason')}")
                continue
            trow = (st.get("by_symbol") or {}).get(rsym)
            seen = _ts(trow.get("fetched_at")) if isinstance(trow, Mapping) else None
            if isinstance(trow, Mapping) and seen is not None:
                candidates.append((name, trow, seen))
                seen_by_store[name] = seen
        fresh = [c for c in candidates if (now - c[2]) <= bound]
        if fresh:
            # The store the row names is the truth when it can answer freshly; only a stale or absent
            # named store lets another allowed store supply the number (and then the label is wrong).
            name, trow, seen = next((c for c in fresh if c[0] == source), max(fresh, key=lambda c: c[2]))
            truth = _num(trow.get("price"))
            sf = _num(shown)
            label_ok = source == name
            if truth is None or sf is None or not _tolerance(tol, sf, truth):
                out.append(finding(row, "NT_PRICE_MISMATCH", "MISMATCH",
                                   f"{acct} {sym}: {where} shows {_fmt(sf)}; truth {_fmt(truth)} ({name}, "
                                   f"{seen.isoformat()})", account=acct, symbol=sym, shown=shown_side,
                                   truth={"value": truth, "provider": name, "as_of": seen.isoformat()}))
            elif not label_ok:
                # REV 3 G3: the figure's source field must name the store the number actually comes from.
                # The evidence is the labeled store's OWN clock: if it cannot have produced a number this
                # fresh, the label is wrong whatever the number is.
                own = seen_by_store.get(source)
                if own is not None:
                    why = (f"its own newest row is {own.isoformat()} "
                           f"({(now - own).total_seconds() / 3600:.1f} h old)")
                elif source in QUOTE_STORES:
                    why = "its own store has no row for it"
                else:
                    why = "it names no allowed store at all"
                out.append(finding(row, "NT_QUOTE_SOURCE", "MISMATCH",
                                   f"{acct} {sym}: {where} shows {_fmt(sf)} with {src_field} {source!r}, but {why}; "
                                   f"the value is {name}'s ({seen.isoformat()})", account=acct, symbol=sym,
                                   shown=shown_side,
                                   truth={"value": truth, "provider": name, "as_of": seen.isoformat()}))
            continue
        if candidates:
            ages = "; ".join(f"{n} {seen.isoformat()} ({(now - seen).total_seconds() / 3600:.1f} h)"
                             for n, _t, seen in candidates)
            out.append(not_measured(row, "stale_truth",
                                    f"{acct} {sym}: {where} shows {_fmt(shown)}; no allowed store has a row "
                                    f"within {bound.total_seconds() / 60:.0f} min ({ages})",
                                    account=acct, symbol=sym, shown=shown_side,
                                    truth={"as_of": max(c[2] for c in candidates).isoformat()}))
            continue
        if unreadable:
            # A store that could not be read may hold the row: absence is unproven, never a fail.
            out.append(not_measured(row, "truth_unreadable", f"{sym}: {'; '.join(unreadable)}",
                                    account=acct, symbol=sym, shown=shown_side))
            continue
        if rsym in retired:
            # REV 2 A: a page number backed only by a retired provider is a FAIL, never a pass.
            out.append(finding(row, "NT_QUOTE_SOURCE", "MISMATCH",
                               f"{acct} {sym}: {where} shows {_fmt(shown)}; no allowed store has a row, only "
                               f"{retired[rsym]!r} (retired)", account=acct, symbol=sym, shown=shown_side,
                               truth={"value": None, "retired": retired[rsym]}))
            continue
        # No allowed store holds a row and nothing was unreadable: the number cannot be verified either way.
        out.append(not_measured(row, "no_rows", f"{acct} {sym}: no allowed quote row for it; the displayed "
                                                f"{_fmt(shown)} cannot be verified", account=acct, symbol=sym,
                                shown=shown_side))
    return out


def row_identity(row: Mapping[str, Any], bundle: Bundle, doc: Any, meta: Mapping[str, Any], *,
                 now: datetime, session: bool) -> list[dict[str, Any]]:
    """One served row's arithmetic: market value must be its own displayed price times its own shares.

    Live 2026-11-09: the holdings payload served SKYD price 8.70 with market_value 8,550 (the price field was
    still 8.55, and the value was built from it), and SRNE price 0.2954 with a $0.30 value. Neither is a
    cross-store question — the page contradicts itself, which no store comparison can see."""
    spec = row["served_from"]
    keymap = spec.get("key") or {}
    tol = row.get("tolerance") or {}
    rows = pointer(doc, str(spec.get("rows") or ""))
    if not isinstance(rows, list):
        return [not_measured(row, "no_such_field", f"served rows {spec.get('rows')!r} not found")]
    a_ptrs, b_ptrs = list(spec.get("value_a") or ()), list(spec.get("value_b") or ())
    m_ptrs = list(spec.get("times") or ())
    out: list[dict[str, Any]] = []
    for s in rows:
        if not isinstance(s, Mapping):
            continue
        av, ap = first_value(s, a_ptrs)
        bv, bp = first_value(s, b_ptrs)
        mv, mp = first_value(s, m_ptrs)
        an, bn, mn = _num(av), _num(bv), _num(mv)
        if an is None or bn is None or mn is None or an == 0 or bn == 0:
            continue  # not displayed, cash, or a 0.00 placeholder
        acct = _one(s, keymap.get("account"))[0]
        sym = _one(s, keymap.get("symbol"))[0]
        derived = bn * mn
        if not _tolerance(tol, an, derived):
            out.append(finding(row, "NT_VALUE_MISMATCH", "MISMATCH",
                               f"{acct} {sym}: the page shows value {_fmt(an)} but its own price {_fmt(bn)} "
                               f"x {_fmt(mn)} shares = {_fmt(derived)}",
                               account=acct, symbol=sym,
                               shown={"value": an, "field": ap, "source": spec.get("path") or "api"},
                               truth={"value": derived, "price": bn, "shares": mn,
                                      "fields": [bp, mp], "derived": "price x shares"}))
    return out


CHECKS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "row_scalar": row_scalar,
    "row_quote": row_quote,
    "row_identity": row_identity,
    "book_total": book_total,
    "account_total": account_total,
    "coverage": coverage,
    "cross_source": cross_source,
    "same_figure": same_figure,
    "session_label": session_label,
    "authority_source": authority_source,
}


def load_catalog(path: Optional[Path] = None) -> dict[str, Any]:
    return json.loads((path or DEFAULT_CATALOG).read_text(encoding="utf-8"))


_ROUTE_RE = None


def nav_routes(nav_path: Path) -> set[str]:
    """The current nav's routes: every ``to: '...'`` literal in lib/navConfig.ts (REV 2 B, current nav only)."""
    global _ROUTE_RE
    import re

    if _ROUTE_RE is None:
        _ROUTE_RE = re.compile(r"\bto:\s*['\"]([^'\"]+)['\"]")
    return set(_ROUTE_RE.findall(Path(nav_path).read_text(encoding="utf-8")))


def validate_catalog(catalog: Mapping[str, Any], *, root: Optional[Path] = None) -> list[str]:
    """A catalog row for a route that is not in navConfig, or a checker that does not exist, is a defect."""
    problems: list[str] = []
    base = Path(root or ROOT)
    if str(catalog.get("schema") or "") != "NumbersTruthCatalog@v1":
        problems.append(f"schema must be NumbersTruthCatalog@v1, got {catalog.get('schema')!r}")
    rows = [r for r in catalog.get("rows") or [] if isinstance(r, Mapping)]
    if not rows:
        problems.append("no rows")
    try:
        routes = nav_routes(base / str(catalog.get("nav_config") or "apps/command-center-v3/src/lib/navConfig.ts"))
    except OSError as exc:
        problems.append(f"navConfig unreadable: {type(exc).__name__}")
        routes = set()
    codes = {str(c) for c in catalog.get("codes") or []}
    seen: set[tuple[str, str]] = set()
    for r in rows:
        page, fid = str(r.get("page") or ""), str(r.get("figure_id") or "")
        where = f"{page} {fid}"
        if not page or not fid:
            problems.append(f"row without page/figure_id: {r!r}"[:200])
            continue
        if routes and page not in routes:
            problems.append(f"{where}: page is not a route in navConfig.ts")
        if str(r.get("severity") or "").upper() not in _SEVERITIES:
            problems.append(f"{where}: severity must be one of {_SEVERITIES}")
        if str(r.get("check") or "") not in CHECKS:
            problems.append(f"{where}: check {r.get('check')!r} is not implemented")
        kind = str((r.get("served_from") or {}).get("kind") or "")
        if kind not in ("artifact", "pair", "api"):
            problems.append(f"{where}: served_from.kind {kind!r} is not a catalog kind")
        code = str((r.get("served_from") or {}).get("code") or "")
        if code and codes and code not in codes:
            problems.append(f"{where}: code {code!r} is not declared in the catalog's codes list")
        if (page, fid) in seen:
            problems.append(f"{where}: duplicate page/figure_id")
        seen.add((page, fid))
    return problems


def _in_session(now: datetime, policy: Mapping[str, Any]) -> bool:
    """The catalog's own session window; a weekday-only gate, like desk_truth_monitor's."""
    local = now.astimezone(ET)
    if local.weekday() >= 5:
        return False
    try:
        s = policy.get("session_et") or {}
        return _hhmm(str(s.get("start") or "09:30")) <= local.time() <= _hhmm(str(s.get("end") or "16:15"))
    except (TypeError, ValueError):
        return False


def audit(catalog: Mapping[str, Any], bundle: Bundle, *, now: datetime, state_root: Path, http_open: bool,
          base_url: str, fetcher: Optional[Callable[[str], Any]] = None,
          deadline: Optional[float] = None, authority_runners: Optional[Mapping[str, Callable[..., Any]]] = None
          ) -> dict[str, Any]:
    """Run every catalog row. Deterministic; a row that cannot be measured says so and moves on."""
    policy = catalog.get("policy") or {}
    session = _in_session(now, policy)
    rows = [r for r in catalog.get("rows") or [] if isinstance(r, Mapping)]
    findings: list[dict[str, Any]] = []
    measured: dict[str, int] = {}
    deadline = deadline if deadline is not None else _time.monotonic() + MAX_RUNTIME_S - 5
    # The authority family runs FIRST: it is static/config work with a fixed cost, and a slow live-data pass
    # must never starve the one gate that reads no market state at all (2026-11-09: a 101 s dry run pushed it
    # past the budget and the whole G1 static check silently became a NOT_MEASURED finding).
    # One GET per distinct (path+query) per run: several catalog rows read the same endpoint, and the lane's
    # 120 s allowlist timeout is not a place to spend a second of pacing per row on the same document.
    _cache: dict[str, Any] = {}
    _base = fetcher or (lambda q: http_get_json(base_url, q))

    def _cached(path: str) -> Any:
        if path not in _cache:
            _cache[path] = _base(path)
        return _cache[path]

    auth: dict[str, Any] = {}
    runners = dict(authority_runners or {})
    if policy.get("authority"):
        findings.extend(authority_writes(policy, conn_factory=runners.get("conn_factory", pg_connect), now=now))
        if _time.monotonic() <= deadline:
            findings.extend(authority_static(runner=runners.get("runner"), root=runners.get("root")))
        else:
            findings.append(not_measured({"page": "*", "figure_id": "authority.static", "severity": "P1",
                                          "domain": "authority", "producer_lane": LANE},
                                         "deadline_exceeded", "the authority gate was not run"))
        auth["write_watch_domains"] = sorted((policy.get("write_watch") or {}))
    for r in rows:
        row = dict(r)
        row["_policy"] = policy
        row["_coverage_cfg"] = policy.get("coverage") or {}
        kind = str(row.get("check") or "")
        fn = CHECKS.get(kind)
        if fn is None:
            findings.append(not_measured(row, "checker_unsupported", f"check {kind!r} is not implemented"))
            continue
        if _time.monotonic() > deadline:
            findings.append(not_measured(row, "deadline_exceeded", "the run reached its time budget"))
            continue
        try:
            doc, meta = served(row, state_root=state_root, http_open=http_open, base_url=base_url,
                               fetcher=_cached)
            found = fn(row, bundle, doc, meta, now=now, session=session)
        except Unreadable as exc:
            findings.append(not_measured(row, exc.reason, exc.detail))
            continue
        except Exception as exc:  # noqa: BLE001 -- one row's defect never stops the audit
            findings.append(not_measured(row, "audit_error", f"{kind} failed: {type(exc).__name__}"))
            continue
        measured[kind] = measured.get(kind, 0) + 1
        findings.extend(found)
    findings.sort(key=lambda f: (f["severity"], f["page"], f["figure_id"], str(f["account"]), str(f["symbol"]),
                                 f["code"]))
    counts = {"by_status": _counted(f["status"] for f in findings),
              "by_code": _counted(f["code"] for f in findings),
              "by_severity": _counted(f["severity"] for f in findings)}
    return {"schema": SCHEMA, "authority": AUTHORITY, "lane_id": LANE, "as_of": now.isoformat(),
            "http_window_open": http_open, "session": session, "rows": len(rows), "measured": measured,
            "finding_count": len(findings), "findings": findings[:MAX_FINDINGS],
            "findings_truncated": max(0, len(findings) - MAX_FINDINGS), "counts": counts,
            "authority_checks": auth}


def host_bundle(catalog: Mapping[str, Any], state_root: Path) -> Bundle:
    brief_rel = ((catalog.get("policy") or {}).get("brief") or {}).get("artifact")
    return load_truth(catalog.get("policy") or {}, brief_path=(state_root / brief_rel) if brief_rel else None)


# ── receipt + CLI ────────────────────────────────────────────────────────────────────────────────────────────


def _ledger_line(rep: Mapping[str, Any]) -> str:
    c = rep.get("counts") or {}
    st = c.get("by_status") or {}
    sev = c.get("by_severity") or {}
    return (f"rows={rep.get('rows')} measured={sum((rep.get('measured') or {}).values())} "
            f"findings={rep.get('finding_count')} mismatch={st.get('MISMATCH', 0)} "
            f"not_measured={st.get('NOT_MEASURED', 0)} P0={sev.get('P0', 0)} P1={sev.get('P1', 0)}")


def build_summary(rep: Mapping[str, Any]) -> dict[str, Any]:
    """The LaneRunReceipt summary. ``findings`` is the list M LQ-1702 consumes (fingerprint-keyed)."""
    summary = {k: rep.get(k) for k in ("as_of", "http_window_open", "session", "rows", "measured", "finding_count",
                                       "findings_truncated", "counts", "authority_checks", "elapsed_s",
                                       "unreadable_sources")}
    summary["findings"] = list(rep.get("findings") or [])
    return summary


def render(rep: Mapping[str, Any]) -> str:
    lines = [f"numbers truth audit  {rep.get('as_of')}  ({AUTHORITY})",
             f"  http_window_open: {rep.get('http_window_open')}  in_session: {rep.get('session')}",
             "  " + _ledger_line(rep)]
    for f in rep.get("findings") or []:
        lines.append(f"  [{f['severity']} {f['status']} {f['code']}] {f['fingerprint']}: {f['detail']}")
    if rep.get("findings_truncated"):
        lines.append(f"  ... {rep['findings_truncated']} more finding(s) not shown")
    return "\n".join(lines)


def run_strike_lane(summary: Mapping[str, Any], *, state_root: Path, now: datetime) -> dict[str, Any]:
    """Feed the findings list M to the strike/heal/ticket engine (LQ-20261107-1726).

    The engine's own durable write is its state file under this lane's state root. The only page it can make is the
    D34 hub, and only for the codes named in ``config/numbers_truth_heal.json`` ``page_codes``; every other code is a
    strike/ticket/FINDING record with no Telegram, text or email. Imported here rather than at module scope so an
    engine that cannot load never stops the audit from producing the receipt it has already earned.
    """
    from scripts.lib import numbers_truth_strikes as S  # noqa: PLC0415 — the engine is this caller's opt-in

    return S.run(findings=summary.get("findings") or [], state_path_=S.state_path(state_root), apply=True, now=now)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: print, write nothing")
    g.add_argument("--apply", action="store_true", help="write this lane's LaneRunReceipt@v2")
    ap.add_argument("--catalog", help="catalog path (default config/numbers_truth_catalog.json)")
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT)")
    ap.add_argument("--base-url", default=os.environ.get("TRADEAI_API_BASE", "http://127.0.0.1:7777"),
                    help="API base for the catalog's api rows, used only outside the §28.8 window")
    ap.add_argument("--no-db", action="store_true", help="grade DB-backed rows NOT_MEASURED (tests, demos)")
    ap.add_argument("--no-http", action="store_true", help="treat every api row as in-window (no request)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--now", help=argparse.SUPPRESS)
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    now = _ts(a.now) if a.now else datetime.now(timezone.utc)
    if now is None:
        return 2
    try:
        catalog = load_catalog(Path(a.catalog) if a.catalog else None)
    except (OSError, ValueError) as exc:
        print(f"[{LANE}] catalog unreadable: {type(exc).__name__}", file=sys.stderr)
        return 1
    state_root = _state_root(a.state_root)
    problems = validate_catalog(catalog)
    if problems:
        for p in problems:
            print(f"[{LANE}] catalog: {p}", file=sys.stderr)
        return 2
    http_open = bool(http_window_open(now)) and not a.no_http
    if a.no_db:
        bundle = Bundle()
        for name in ("positions", "stops", "stop_last_known", "quotes"):
            bundle.put(name, reason="source_unreadable")
        brief_rel = ((catalog.get("policy") or {}).get("brief") or {}).get("artifact")
        try:
            doc = json.loads((state_root / brief_rel).read_text(encoding="utf-8")) if brief_rel else None
            bundle.put("brief", doc=doc, reason=None if doc is not None else "source_unreadable")
        except (OSError, ValueError):
            bundle.put("brief", reason="source_unreadable")
    else:
        bundle = host_bundle(catalog, state_root)
    started = _time.monotonic()
    rep = audit(catalog, bundle, now=now, state_root=state_root, http_open=http_open, base_url=a.base_url,
                deadline=started + MAX_RUNTIME_S - 8)
    rep["elapsed_s"] = round(_time.monotonic() - started, 2)
    unreadable = [n for n in ("positions", "stops", "quotes") if not bundle.ok(n)]
    rep["unreadable_sources"] = unreadable
    global_ok = len(unreadable) < 3
    if not global_ok:
        rep["error"] = "dependency_unavailable: no truth source was readable"
    rc = 0 if global_ok else 1

    if not a.apply:
        print(json.dumps(rep, indent=1, default=str, sort_keys=True) if a.json else render(rep))
        if not a.json:
            from scripts.lib import lane_last_receipt as R

            R.dry_run_report(LANE, {"finding_count": rep.get("finding_count"),
                                    "counts": rep.get("counts"), "rows": rep.get("rows"),
                                    "error": rep.get("error")},
                             would_write=[str(R.receipt_path(LANE, a.state_root))] if global_ok else [],
                             receipt=R.receipt_path(LANE, a.state_root))
        return rc

    from scripts.lib import lane_last_receipt as R

    summary = build_summary(rep)  # includes the list M
    # produced_count/attempted_count/skipped_reasons as kwargs, not an ``output=`` dict: only this spelling
    # makes lane_last_receipt write LaneRunReceipt@v2 with the output block the lane contract grades
    # (LQ-1703's allowlist pins output_receipt v2 and produced_count).
    written = R.write_lane_receipt(LANE, ok=global_ok, exit_code=rc, started_at=now, script=SCRIPT,
                                   summary=summary, error=rep.get("error"),
                                   path=R.receipt_path(LANE, a.state_root),
                                   produced_count=1 if global_ok else 0, attempted_count=1,
                                   skipped_reasons={} if global_ok else {DEP: 1}, empty_reason=None)
    # LQ-20261107-1726: the receipt is written above; the findings now feed the strike/heal/ticket engine, which is
    # the only caller of the D34 critical page. A failure here is reported (stderr + the apply JSON), never hidden,
    # and never turns a written receipt into a failed run — the next hourly run re-plans from the same state file.
    strikes: Optional[dict[str, Any]] = None
    strikes_error: Optional[str] = None
    try:
        got = run_strike_lane(summary, state_root=state_root, now=now)
        strikes = {k: got.get(k) for k in ("counts", "state_path", "heals", "tickets", "cleared",
                                           "not_measured", "malformed", "known_disagreements")}
    except Exception as exc:  # noqa: BLE001 — a struck-out engine is an outcome of this run, not a reason to lose it
        strikes_error = f"{type(exc).__name__}: {exc}"[:400]
        print(f"[{LANE}] strike lane failed: {strikes_error}", file=sys.stderr)
    print(json.dumps({"mode": "apply", "ok": global_ok, "receipt": str(written) if written else None,
                      "finding_count": rep.get("finding_count"),
                      "by_status": (rep.get("counts") or {}).get("by_status"),
                      "error": rep.get("error"), "strikes": strikes, "strikes_error": strikes_error},
                     default=str))
    return 0 if global_ok and written is not None else 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
