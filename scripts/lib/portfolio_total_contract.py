"""PortfolioTotal@v1 — one portfolio total and one position count, published once and read by every surface.

LQ-20261107-1611 (CC v3 audit A5; supersedes the labelling-only LQ-20261107-1391). The audit measured
three portfolio totals on three pages, each computed its own way:

* Home header  — ``/api/v2/overview portfolio_value`` = the data-broker snapshot total, which is
  ``lib.cio_truth.portfolio_for`` over the DB-first holdings document (Finviz-repriced marks);
* All-accounts — ``/api/v2/portfolio/performance current_value`` = the stored
  ``holdings.json portfolio_totals.total_value`` (broker marks at the last sync);
* Book header  — a page-side re-sum of ``/api/v2/portfolio/holdings`` rows.

On a Friday close that gap was $3,771 — the overnight move between two price bases — and nothing on
the page said which figure was the book. Two integers also stood for "positions": 12 (non-cash over
$100) on Home, 34 (every row, cash included) on the Book, and a per-account chip count.

This module is the one place the number is decided:

* ``value`` — the store's own ``portfolio_totals.total_value`` **when it agrees with the row sum**
  (the export and the repricer write it as that sum). When the field and the rows disagree the row sum
  is published instead, the basis changes to ``holdings[].market_value``, and a finding is raised: a
  half-applied reprice must not ship a header that does not equal its own rows.
* ``position_count`` — one named scope, ``holdings.non_cash_over_100``, with its definition and every
  other named scope published beside it so a consumer never has to guess which population it has.
* ``alternatives`` — every other number the page could have shown, each with its delta and why it
  differs. They are evidence, never the total.

Pure: no I/O except ``load_portfolio_total`` (a convenience for callers that hold no document).
``build_portfolio_total`` never raises on a malformed store; it publishes ``value: None`` with a
finding, because a zero would be a lie (tq-ts-missing-as-zero) and a raise would take the page down.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

try:  # scripts/ on sys.path (the served API) vs repo root (tests)
    from scripts.lib.canonical_observation import position_count_contract
except ImportError:  # pragma: no cover - import shape depends on the caller
    from lib.canonical_observation import position_count_contract  # type: ignore[no-redef] -- the served API puts scripts/ on sys.path, tests put the repo root; one of the two names is always missing

CONTRACT_VERSION = "PortfolioTotal@v1"
TOTAL_FIELD = "portfolio_totals.total_value"
CASH_FIELD = "portfolio_totals.total_cash"
BROKER_TOTAL_FIELD = "portfolio_totals.broker_market_value_total"
# The headline count is the held instruments, not a value line: a $97 lot ticking to $101 moved the old
# "over $100" headline (12 <-> 13) with nothing bought or sold (LQ-1611 F3). The $100 scope stays published by name.
POSITION_SCOPE = "holdings.held"
POSITION_SCOPE_DEFINITION = (
    "non-cash instruments held, one per (account, symbol): quantity above 0 (or not reported) and a priced "
    "market_value above $0; unpriced lots are counted separately, never as positions"
)
OVER_100_SCOPE = "holdings.non_cash_over_100"
SCOPE_DEFINITIONS = {
    POSITION_SCOPE: POSITION_SCOPE_DEFINITION,
    OVER_100_SCOPE: "non-cash instruments, one per (account, symbol), whose market_value is above $100",
    "holdings.held_under_100": "held instruments priced above $0 and at or below $100",
    "holdings.unpriced": "non-cash lots with a quantity but no market_value above $0 (e.g. a CUSIP with no quote)",
    "holdings.all_rows": "every row in the holdings store, cash rows included, one per (account, symbol)",
    "holdings.non_cash": "non-cash holding rows, whatever their value",
    "holdings.cash": "cash rows (CASH/SPAXX/FDRXX) in the holdings store",
}
CASH_SYMBOLS = frozenset({"CASH", "SPAXX", "FDRXX"})


def _load_min_position_usd(default: float = 100.0) -> float:
    """The over-floor threshold lives in config/position_count_authority.json (LQ-20261107-1820)."""
    import json
    from pathlib import Path

    try:
        raw = json.loads((Path(__file__).resolve().parents[2] / "config" / "position_count_authority.json")
                         .read_text(encoding="utf-8"))
        v = float(raw["min_position_usd"])
        return v if v == v and v >= 0 else default
    except (OSError, ValueError, KeyError, TypeError):
        return default


MIN_POSITION_USD = _load_min_position_usd()
DEFAULT_TOLERANCE_USD = 1.0
BASIS_STORE_FIELD = TOTAL_FIELD
BASIS_ROW_SUM = "holdings[].market_value"


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def is_cash_row(row: Mapping[str, Any]) -> bool:
    """A cash row: the flag, or one of the broker's money-market symbols."""
    return bool(row.get("is_cash")) or str(row.get("symbol") or "").upper() in CASH_SYMBOLS


def _row_key(r: Mapping[str, Any]) -> tuple[str, str]:
    return (_account_of(r), str(r.get("symbol") or "").upper())


def _account_of(r: Mapping[str, Any]) -> str:
    return str(r.get("account") or r.get("account_key") or "")


def _quantity(r: Mapping[str, Any]) -> Optional[float]:
    for f in ("quantity", "shares"):
        q = _num(r.get(f))
        if q is not None:
            return q
    return None


def position_scopes(rows: Iterable[Mapping[str, Any]], *, min_position_usd: float = MIN_POSITION_USD,
                    extra: Optional[Mapping[str, int]] = None) -> dict[str, int]:
    """Every named population, counted once. A split (account, symbol) is summed first, then classified."""
    all_rows = 0
    cash_rows = 0
    value: dict[tuple[str, str], float] = {}
    qty_seen: dict[tuple[str, str], bool] = {}
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        all_rows += 1
        if is_cash_row(r):
            cash_rows += 1
            continue
        key = _row_key(r)
        mv = _num(r.get("market_value"))
        value[key] = value.get(key, 0.0) + (mv if mv is not None else 0.0)
        q = _quantity(r)
        qty_seen[key] = qty_seen.get(key, False) or q is None or q > 0
    held = {k for k, v in value.items() if qty_seen.get(k) and v > 0}
    unpriced = {k for k, v in value.items() if qty_seen.get(k) and v <= 0}
    scopes = {
        POSITION_SCOPE: len(held),
        OVER_100_SCOPE: sum(1 for k in held if value[k] > min_position_usd),
        "holdings.held_under_100": sum(1 for k in held if value[k] <= min_position_usd),
        "holdings.unpriced": len(unpriced),
        "holdings.all_rows": all_rows,
        "holdings.non_cash": len(value),
        "holdings.cash": cash_rows,
    }
    scopes.update({k: int(v) for k, v in (extra or {}).items()})
    return scopes


def position_summary(scopes: Mapping[str, int]) -> str:
    """The one line a page prints under the total: the headline count and what it leaves out, by name."""
    n = scopes.get(POSITION_SCOPE, 0)
    parts = [f"{n} position{'' if n == 1 else 's'}"]
    under = scopes.get("holdings.held_under_100", 0)
    if under:
        parts.append(f"{under} under ${MIN_POSITION_USD:,.0f}")
    unp = scopes.get("holdings.unpriced", 0)
    if unp:
        parts.append(f"{unp} unpriced lot{'' if unp == 1 else 's'} excluded")
    return " · ".join(parts)


def accounts_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-account value, cash and held count from the same rows as the total (LQ-1611 F1).

    An account with an unusable market_value is ``value: None`` — unknown, never a short sum.
    """
    out: dict[str, dict[str, Any]] = {}
    acct_rows: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        if isinstance(r, Mapping):
            acct_rows.setdefault(_account_of(r), []).append(r)
    for acct, rs in acct_rows.items():
        cash = sum(_num(r.get("market_value")) or 0.0 for r in rs if is_cash_row(r))
        out[acct] = {
            "value": rows_total(rs),
            "cash": round(cash, 2),
            "position_count": position_scopes(rs)[POSITION_SCOPE],
        }
    return out


def rows_total(rows: Iterable[Mapping[str, Any]]) -> Optional[float]:
    """The value the page's own rows sum to; None when any row's market_value is unusable."""
    total = 0.0
    seen = False
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        mv = _num(r.get("market_value"))
        if mv is None:
            return None
        total += mv
        seen = True
    return round(total, 2) if seen else None


def _finding(code: str, detail: str, *, alert: bool, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "detail": detail, "alert": alert, "evidence": evidence}


def build_portfolio_total(document: Optional[Mapping[str, Any]], *,
                          snapshot_totals: Optional[Mapping[str, Any]] = None,
                          extra_scopes: Optional[Mapping[str, int]] = None,
                          scope_definitions: Optional[Mapping[str, str]] = None,
                          tolerance_usd: float = DEFAULT_TOLERANCE_USD,
                          min_position_usd: float = MIN_POSITION_USD) -> dict[str, Any]:
    """One total, one count, and every alternative named. Never raises on a malformed store."""
    doc = document if isinstance(document, Mapping) else {}
    rows = [r for r in (doc.get("holdings") or []) if isinstance(r, Mapping)]
    totals = doc.get("portfolio_totals") if isinstance(doc.get("portfolio_totals"), Mapping) else {}
    findings: list[dict[str, Any]] = []

    store_value = _num(totals.get("total_value"))
    row_value = rows_total(rows) if rows else None

    if not rows:
        value, basis = None, None
        findings.append(_finding("HOLDINGS_EMPTY", "the holdings store has no rows: no total can be "
                                 "published (a zero would be a lie)", alert=True))
    elif store_value is None:
        value, basis = row_value, BASIS_ROW_SUM
        findings.append(_finding("TOTAL_FIELD_MISSING", f"{TOTAL_FIELD} is absent or unreadable; the row "
                                 f"sum is published instead", alert=True,
                                 row_sum=row_value, scenario=doc.get("document_source")))
    elif row_value is not None and abs(store_value - row_value) > tolerance_usd:
        value, basis = row_value, BASIS_ROW_SUM
        findings.append(_finding("TOTAL_FIELD_DRIFT", f"{TOTAL_FIELD} {store_value:,.2f} disagrees with the "
                                 f"row sum {row_value:,.2f} by {store_value - row_value:+,.2f}; the row sum is "
                                 "published so the header always equals the rows it shows", alert=True,
                                 field_value=store_value, row_sum=row_value,
                                 delta=round(store_value - row_value, 2)))
    else:
        value, basis = store_value, BASIS_STORE_FIELD

    counts = position_scopes(rows, min_position_usd=min_position_usd, extra=extra_scopes)
    counts_contract = position_count_contract(counts)
    counts_contract["definitions"] = {s: (scope_definitions or {}).get(s) or SCOPE_DEFINITIONS.get(s)
                                      or f"scope {s}" for s in counts}
    counts_contract["primary_scope"] = POSITION_SCOPE
    counts_contract["primary_definition"] = counts_contract["definitions"][POSITION_SCOPE]

    alternatives: list[dict[str, Any]] = []
    if basis == BASIS_STORE_FIELD and row_value is not None and abs(value - row_value) <= tolerance_usd:
        alternatives.append({"name": "row_sum", "value": row_value, "delta": round(value - row_value, 2),
                             "basis": BASIS_ROW_SUM,
                             "why": "the rows this page lists, summed; it agrees with the store field"})
    broker_total = _num(totals.get("broker_market_value_total"))
    if broker_total is not None:
        delta = round(value - broker_total, 2) if value is not None else None
        alternatives.append({
            "name": "broker_marks",
            "value": broker_total,
            "delta": delta,
            "basis": BROKER_TOTAL_FIELD,
            "why": "the broker's own marks at the last sync; the difference from the published total is "
                   "the repricer's re-mark since that sync (expected between reprice passes, not an error)",
        })
    proj = _num((snapshot_totals or {}).get("total_value"))
    if proj is not None:
        delta = round(value - proj, 2) if value is not None else None
        alternatives.append({
            "name": "broker_projection",
            "value": proj,
            "delta": delta,
            "basis": "portfolio_snapshot.totals.total_value",
            "why": "the data-broker projection re-sums the same rows through lib.cio_truth; a delta means "
                   "its document render (DB first) or the repricer's marks moved between the two reads",
        })
        if delta is not None and abs(delta) > tolerance_usd:
            findings.append(_finding("PROJECTION_DISAGREES", f"the broker projection total {proj:,.2f} differs "
                                     f"from the published total {value:,.2f} by {proj - value:+,.2f}; the "
                                     "projection is published as an alternative, never as the total",
                                     alert=False, projection=proj, published=value, delta=delta))

    cash = _num(totals.get("total_cash"))
    by_account = accounts_from_rows(rows)
    acct_values = [a["value"] for a in by_account.values()]
    by_account_sum = round(sum(acct_values), 2) if acct_values and None not in acct_values else None
    alerting = [f["code"] for f in findings if f["alert"]]
    return {
        "contract_version": CONTRACT_VERSION,
        "value": value,
        "basis": basis,
        "basis_label": (
            "the holdings store's portfolio_totals.total_value — every row repriced on the last pass"
            if basis == BASIS_STORE_FIELD else
            "sum of the holdings rows shown (the store's total_value disagreed with them)"
            if basis == BASIS_ROW_SUM else
            "no total: the holdings store did not answer"
        ),
        "as_of": totals.get("as_of") or doc.get("positions_built_at") or doc.get("as_of"),
        "row_sum": row_value,
        "row_sum_unusable": bool(rows) and row_value is None,
        "document_source": doc.get("document_source"),
        "document_fallback_reason": doc.get("document_fallback_reason"),
        "cash": {"value": cash, "basis": CASH_FIELD} if cash is not None else None,
        "position_count": counts[POSITION_SCOPE],
        "position_scope": POSITION_SCOPE,
        "position_scope_definition": counts_contract["primary_definition"],
        "position_counts": counts_contract,
        "position_summary": position_summary(counts),
        "by_account": by_account,
        "by_account_sum": by_account_sum,
        "alternatives": alternatives,
        "tolerance_usd": float(tolerance_usd),
        "agree": not alerting,
        "findings": findings,
    }


def load_portfolio_total(state_dir: Any, *, snapshot_totals: Optional[Mapping[str, Any]] = None,
                         extra_scopes: Optional[Mapping[str, int]] = None):
    """Read ``holdings.json`` under ``state_dir`` and build the contract. Never raises on a bad store."""
    import json
    from pathlib import Path

    try:
        doc = json.loads((Path(state_dir) / "holdings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out = build_portfolio_total(None, snapshot_totals=snapshot_totals, extra_scopes=extra_scopes)
        out["findings"].append(_finding("HOLDINGS_UNREADABLE", f"holdings.json could not be read: "
                                        f"{type(exc).__name__}", alert=True))
        out["agree"] = False
        return out
    return build_portfolio_total(doc, snapshot_totals=snapshot_totals, extra_scopes=extra_scopes)


__all__ = [
    "CONTRACT_VERSION", "POSITION_SCOPE", "POSITION_SCOPE_DEFINITION", "SCOPE_DEFINITIONS",
    "DEFAULT_TOLERANCE_USD", "MIN_POSITION_USD", "build_portfolio_total", "load_portfolio_total",
    "position_scopes", "position_summary", "accounts_from_rows", "rows_total", "is_cash_row", "OVER_100_SCOPE",
]
