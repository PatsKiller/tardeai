"""Street detail — Data Broker read model for the prospectus's institutional blocks (read-only, no provider call).

One projection over stores the house already writes, so the prospectus never reads a projection-owned table directly
(AGENTS.md §7A, ``check_data_source_authority`` lane ceilings) and never fetches from a market provider:

* ``yahoo_analyst_targets_history`` (analyst_opinion; writer ``scripts/pro_analyst_fetch.py``): the daily target /
  rating history, and the newest row's ``data.extended`` (analyst actions, EPS / revenue consensus, EPS trend and
  revisions, earnings history and dates, recommendation trend) — captured by the same writer from the same provider.
* ``analyst_data_history``: monthly rating-distribution rows recorded before the provider was retired (history only).
* ``catalyst_events`` (catalyst_news): items classified analyst_upgrade / analyst_downgrade / analyst.
* ``option_chain_snapshots`` and ``options_chain_snapshots``: put/call, 25-delta skew, ATM IV, term structure.
* ``options_iv_history`` (options_iv; projection option_chain): the IV series for an IV rank.
* ``sec_xbrl``, ``sec_form4``, ``sec_13f``: SEC EDGAR statements, insider transactions, 13F holders.
* ``ticker_dividends`` and ``ticker_dividend_data``: ex-date history and the recorded next ex-date.

Every function takes the injected ``db_query(sql, params, fetch="all")`` callable and returns plain dicts; a failure
returns an empty result and the caller records the gap. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from typing import Any, Callable

CONTRACT = "StreetDetail@v1"


def _rows(db_query: Callable, sql: str, params: tuple) -> list[dict]:
    try:
        return [dict(r) for r in (db_query(sql, params, fetch="all") or [])]
    except TypeError:  # an injected callable without the fetch keyword
        return [dict(r) for r in (db_query(sql, params) or [])]


def _json(v: Any) -> Any:
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return None


def target_history(db_query: Callable, symbol: str, *, days: int = 400) -> list[dict]:
    """Daily Yahoo consensus rows, oldest first: date, mean / median / low / high target, rating mean / key, count."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    rows = _rows(db_query, """SELECT snapshot_date, target_mean_price, target_median_price, target_low_price,
                                      target_high_price, recommendation_mean, recommendation_key,
                                      number_of_analyst_opinions, current_price, created_at
                               FROM yahoo_analyst_targets_history
                               WHERE upper(symbol) = %s AND snapshot_date >= %s
                               ORDER BY snapshot_date""", (symbol.upper(), since))
    return [{"date": str(r.get("snapshot_date"))[:10], "mean": r.get("target_mean_price"),
             "median": r.get("target_median_price"), "low": r.get("target_low_price"), "high": r.get("target_high_price"),
             "rating_mean": r.get("recommendation_mean"), "rating_key": r.get("recommendation_key"),
             "analysts": r.get("number_of_analyst_opinions"), "price": r.get("current_price"),
             "created_at": r.get("created_at")} for r in rows]


def extended(db_query: Callable, symbol: str, *, max_age_days: int = 21) -> dict:
    """The newest ``data.extended`` capture (pro_analyst_fetch) for a symbol, with its snapshot date; {} when absent."""
    since = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).date()
    rows = _rows(db_query, """SELECT snapshot_date, data->'extended' AS extended
                               FROM yahoo_analyst_targets_history
                               WHERE upper(symbol) = %s AND snapshot_date >= %s AND data ? 'extended'
                               ORDER BY snapshot_date DESC LIMIT 1""", (symbol.upper(), since))
    if not rows:
        return {}
    ext = _json(rows[0].get("extended"))
    if not isinstance(ext, dict):
        return {}
    return {**ext, "snapshot_date": str(rows[0].get("snapshot_date"))[:10]}


def rating_distribution_history(db_query: Callable, symbol: str, *, months: int = 8) -> list[dict]:
    """Monthly strong-buy / buy / hold / sell / strong-sell counts recorded in ``analyst_data_history``, newest first."""
    rows = _rows(db_query, """SELECT as_of, payload FROM analyst_data_history
                               WHERE upper(symbol) = %s AND payload::text <> '{}'
                               ORDER BY as_of DESC LIMIT 60""", (symbol.upper(),))
    out, seen = [], set()
    for r in rows:
        p = _json(r.get("payload")) or {}
        period = str(p.get("recommendation_period") or "")[:7]
        if not period or period in seen:
            continue
        seen.add(period)
        out.append({"period": period, "strong_buy": p.get("strong_buy"), "buy": p.get("buy"), "hold": p.get("hold"),
                    "sell": p.get("sell"), "strong_sell": p.get("strong_sell"), "as_of": r.get("as_of"),
                    "provider": p.get("provider")})
        if len(out) >= months:
            break
    return out


def analyst_catalysts(db_query: Callable, symbol: str, *, days: int = 180) -> list[dict]:
    """catalyst_events items classified as analyst actions (headline-classified news; deduped by the caller)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = _rows(db_query, """SELECT catalyst_type, headline, source, source_url, published_at
                               FROM catalyst_events
                               WHERE upper(symbol) = %s AND published_at >= %s
                                 AND catalyst_type IN ('analyst_upgrade', 'analyst_downgrade', 'analyst')
                               ORDER BY published_at DESC LIMIT 60""", (symbol.upper(), since))
    return [{"type": r.get("catalyst_type"), "headline": r.get("headline"), "source": r.get("source"),
             "url": r.get("source_url"), "at": r.get("published_at")} for r in rows]


def material_catalysts(db_query: Callable, symbol: str, *, days: int = 120) -> list[dict]:
    """High / critical catalyst events (any type) for the backward catalyst calendar."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = _rows(db_query, """SELECT catalyst_type, headline, severity, source, source_url, published_at
                               FROM catalyst_events
                               WHERE upper(symbol) = %s AND published_at >= %s AND severity IN ('high', 'critical')
                               ORDER BY published_at DESC LIMIT 40""", (symbol.upper(), since))
    return [{"type": r.get("catalyst_type"), "headline": r.get("headline"), "severity": r.get("severity"),
             "source": r.get("source"), "url": r.get("source_url"), "at": r.get("published_at")} for r in rows]


def option_snapshots(db_query: Callable, symbol: str, *, days: int = 400) -> list[dict]:
    """Daily chain summaries (oldest first): put/call by open interest and volume, ATM IV %, 25-delta skew."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    rows = _rows(db_query, """SELECT as_of, put_oi, call_oi, put_vol, call_vol, pc_oi_ratio, pc_vol_ratio, atm_iv,
                                      skew25, underlying_price
                               FROM option_chain_snapshots WHERE upper(symbol) = %s AND as_of >= %s
                               ORDER BY as_of""", (symbol.upper(), since))
    return [{**{k: r.get(k) for k in ("put_oi", "call_oi", "put_vol", "call_vol", "pc_oi_ratio", "pc_vol_ratio",
                                      "atm_iv", "skew25", "underlying_price")}, "date": str(r.get("as_of"))[:10]}
            for r in rows]


def term_structure(db_query: Callable, symbol: str) -> dict:
    """The newest chain's volatility analytics (ATM IV per expiry), with its capture time; {} when absent."""
    rows = _rows(db_query, """SELECT captured_at, vol_analytics_json FROM options_chain_snapshots
                               WHERE upper(symbol) = %s AND vol_analytics_json IS NOT NULL
                               ORDER BY captured_at DESC LIMIT 1""", (symbol.upper(),))
    if not rows:
        return {}
    va = _json(rows[0].get("vol_analytics_json"))
    return {**va, "captured_at": rows[0].get("captured_at")} if isinstance(va, dict) else {}


def iv_history(db_query: Callable, symbol: str, *, days: int = 400) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    rows = _rows(db_query, """SELECT snapshot_date, iv_pct FROM options_iv_history
                               WHERE upper(symbol) = %s AND snapshot_date >= %s ORDER BY snapshot_date""",
                 (symbol.upper(), since))
    return [{"date": str(r.get("snapshot_date"))[:10], "iv_pct": r.get("iv_pct")} for r in rows]


def xbrl(db_query: Callable, symbol: str) -> list[dict]:
    rows = _rows(db_query, """SELECT metric_name, metric_value, unit, period_start, period_end, filing_date, form_type,
                                      sec_url
                               FROM sec_xbrl WHERE upper(symbol) = %s ORDER BY period_end DESC, filing_date DESC
                               LIMIT 200""", (symbol.upper(),))
    return [{"metric": r.get("metric_name"), "value": r.get("metric_value"), "unit": r.get("unit"),
             "start": str(r["period_start"])[:10] if r.get("period_start") else None,
             "end": str(r.get("period_end"))[:10], "filed": str(r.get("filing_date"))[:10], "form": r.get("form_type"),
             "url": r.get("sec_url")} for r in rows]


def form4(db_query: Callable, symbol: str, *, days: int = 180) -> dict:
    """Insider transactions for the symbol and whether the house Form 4 store covers it at all."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    rows = _rows(db_query, """SELECT filer_name, filer_relation, transaction_type, shares, price, total_value,
                                      filing_date, transaction_date, sec_url
                               FROM sec_form4 WHERE upper(symbol) = %s AND filing_date >= %s
                               ORDER BY filing_date DESC LIMIT 80""", (symbol.upper(), since))
    ever = _rows(db_query, "SELECT count(*) AS n, max(filing_date) AS last FROM sec_form4 WHERE upper(symbol) = %s",
                 (symbol.upper(),))
    store = _rows(db_query, "SELECT count(DISTINCT symbol) AS n, max(filing_date) AS last FROM sec_form4", ())
    return {"rows": rows, "symbol_rows_ever": int((ever[0] if ever else {}).get("n") or 0),
            "store_symbols": int((store[0] if store else {}).get("n") or 0),
            "store_last": str((store[0] if store else {}).get("last") or "")[:10] or None}


def holders_13f(db_query: Callable, symbol: str) -> list[dict]:
    return _rows(db_query, """SELECT institution, shares, value_thousands, change_shares, change_pct, report_date,
                                     filing_date, sec_url
                              FROM sec_13f WHERE upper(symbol) = %s ORDER BY report_date DESC, shares DESC LIMIT 20""",
                 (symbol.upper(),))


def dividends(db_query: Callable, symbol: str) -> dict:
    hist = _rows(db_query, """SELECT ex_date, amount FROM ticker_dividends WHERE upper(symbol) = %s
                               ORDER BY ex_date DESC LIMIT 16""", (symbol.upper(),))
    rec = _rows(db_query, """SELECT ex_div_date, updated_at FROM ticker_dividend_data WHERE upper(symbol) = %s
                              ORDER BY updated_at DESC NULLS LAST LIMIT 1""", (symbol.upper(),))
    return {"history": [{"ex_date": str(r.get("ex_date"))[:10], "amount": r.get("amount")} for r in hist],
            "recorded_next_ex": str((rec[0] if rec else {}).get("ex_div_date") or "")[:10] or None}


def get_street_detail(db_query: Callable, symbol: str, *, include: tuple[str, ...] | None = None) -> dict:
    """Everything above for one symbol; each part fails independently into ``errors``."""
    parts: dict[str, Callable[[], Any]] = {
        "target_history": lambda: target_history(db_query, symbol),
        "extended": lambda: extended(db_query, symbol),
        "rating_history": lambda: rating_distribution_history(db_query, symbol),
        "analyst_catalysts": lambda: analyst_catalysts(db_query, symbol),
        "material_catalysts": lambda: material_catalysts(db_query, symbol),
        "option_snapshots": lambda: option_snapshots(db_query, symbol),
        "term_structure": lambda: term_structure(db_query, symbol),
        "iv_history": lambda: iv_history(db_query, symbol),
        "xbrl": lambda: xbrl(db_query, symbol),
        "form4": lambda: form4(db_query, symbol),
        "holders_13f": lambda: holders_13f(db_query, symbol),
        "dividends": lambda: dividends(db_query, symbol),
    }
    out: dict[str, Any] = {"contract": CONTRACT, "symbol": symbol.upper(), "errors": {},
                           "as_of": datetime.now(timezone.utc).isoformat()}
    for name, fn in parts.items():
        if include and name not in include:
            continue
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001 - a missing store is a recorded gap for the caller
            out[name] = None
            out["errors"][name] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return out


def _today() -> date:
    return datetime.now(timezone.utc).date()
