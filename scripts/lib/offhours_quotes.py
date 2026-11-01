"""Off-hours Schwab market-data quotes for the Market Risk Engine, into ``market_quotes_extended``.

Why: the Market Risk Engine (#2383) had no quote after about 16:10 ET or before the 09:30 open (2026-10-30 selloff
RCA, DSN-20261031-market-risk-engine). Alpaca extended-session prints come from #2384's producer
(``scripts/market_quotes_extended.py``); this module turns a Schwab ``/marketdata/v1/quotes`` payload into rows of the
SAME store under the SAME contract, written by its single writer
(``scripts/lib/writers/market_quotes_extended_writer.py``). Never ``market_quotes``: its newest row is the latest
quote for stop checks, the repricer and watch alerts (coordinator decision 2026-10-31, option 3).

Contract reused exactly from #2384:
* ``session`` is ``premarket`` or ``afterhours``, labelled by ``market_quotes_extended.session_of`` (early closes
  included), or -- from migrations/2026_10_31_market_quotes_extended_overnight.sql -- ``overnight`` (20:00-04:00 ET,
  Sunday night to Friday 04:00) or ``futures_open`` (Sunday 18:00-20:00 ET, futures only), labelled by
  ``lib.overnight_session.label`` with ``session_date`` = the NEXT trading day. Regular-session and other
  non-trading-day prints are NOT stored (``session_not_in_store_contract``).
* Overnight / futures-open reference = the close of the trading day before the trading date (the last regular
  close before the night began): equities ``regular.regularMarketLastPrice``, futures and indices
  ``quote.closePrice`` (Schwab's previous close / settlement). When the payload carries the reference's time
  (``regular.regularMarketTradeTime``, ``quote.settleTime``) it must fall on that date. With no such field, or a
  time on another date, the row stores the LEVEL ONLY (reference_close, reference_date, change_pct all None, basis
  ``schwab.overnight_reference_basis.level_only``) and the engine compares it with the earlier stored level. A
  reference is never invented.
* ``reference_close``: after-hours moves from the same trading day's close, pre-market from the previous session's
  close; a missing reference refuses the row (never an older close).
* ``bar_end`` is when the print became knowable. A Schwab quote is a point in time, so ``bar_end`` = the trade
  instant exactly and ``bar_start`` = ``point_quote_span_ms`` earlier (the contract requires bar_end > bar_start).
* ``--apply`` refuses while the §7A domain ``quote_extended_session`` is still proposed (``domain_promoted``).

Pure: no network, database or credential here; the entry (``scripts/market_quotes_offhours_schwab.py``) injects
``fetch`` and ``write``. Settings: ``config/market_risk_offhours_quotes.yaml``.

AUTHORITY: READ_ONLY_ADVISORY. Market data only; never an order, stop, account, position or auth endpoint.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "market_risk_offhours_quotes.yaml"
SCHEMA = "MarketRiskOffHoursQuotes@v2"
RECEIPT_SCHEMA = "OffHoursQuoteRun@v2"
STORE = "market_quotes_extended"
ET = ZoneInfo("America/New_York")
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import market_quotes_extended as mqe  # noqa: E402  (#2384: session_of, previous_session, domain_promoted)
from lib import overnight_session as ovn  # noqa: E402  (overnight / futures_open labels, next trading day)


class ConfigError(ValueError):
    pass


# ── config and universe ─────────────────────────────────────────────────────────────────────────────


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    import yaml

    p = Path(path) if path else CONFIG_PATH
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"{p}: unreadable ({type(exc).__name__}: {exc})") from exc
    if doc.get("schema") != SCHEMA:
        raise ConfigError(f"{p}: schema {doc.get('schema')!r}, expected {SCHEMA}")
    for key in ("universe", "schwab"):
        if not isinstance(doc.get(key), dict):
            raise ConfigError(f"{p}: section {key!r} missing")
    if not str((doc["schwab"].get("feed") or "")).strip():
        raise ConfigError(f"{p}: schwab.feed missing (the market_quotes_extended feed label comes from config)")
    return doc


def _lookup(doc: Any, dotted: str) -> Any:
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _read_doc(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    import yaml

    return yaml.safe_load(text)


def resolve_universe(cfg: dict[str, Any], *, root: Path = ROOT) -> tuple[list[str], dict[str, Any]]:
    """(symbols, provenance): the union of every ``universe.sources`` list, in order. A missing file or key is named
    in ``missing_refs``; nothing is filled in for it."""
    prov: dict[str, Any] = {"included": {}, "missing_refs": []}
    for src in (cfg.get("universe") or {}).get("sources") or []:
        ref = f"{src.get('file')}:{src.get('key')}"
        try:
            vals = _lookup(_read_doc(root / str(src["file"])), str(src["key"]))
        except (OSError, ValueError, KeyError) as exc:
            prov["missing_refs"].append(f"{ref} ({type(exc).__name__})")
            continue
        if isinstance(vals, list) and vals:
            prov["included"][ref] = [str(s).strip().upper() for s in vals if str(s).strip()]
        else:
            prov["missing_refs"].append(ref)
    merged = list(dict.fromkeys(s for v in prov["included"].values() for s in v))
    return merged, prov


def schwab_symbols(cfg: dict[str, Any], universe: list[str]) -> list[str]:
    s = cfg.get("schwab") or {}
    extra = universe if s.get("include_universe", True) else []
    return list(dict.fromkeys([*(str(x).strip() for x in s.get("futures") or []),
                               *(str(x).strip() for x in s.get("indices") or []), *extra]))


# ── timestamps, window ──────────────────────────────────────────────────────────────────────────────


def parse_ts(value: Any) -> datetime | None:
    """A provider timestamp -> tz-aware UTC datetime: epoch milliseconds (Schwab), RFC3339 with up to nanosecond
    fractions, or an aware datetime. Anything else (naive, junk) is None: the row is skipped, never guessed."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value <= 0:
            return None
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    s = str(value).strip().replace("Z", "+00:00")
    if "." in s:  # trim a nanosecond fraction to microseconds; fromisoformat rejects more than 6 digits
        head, frac = s.split(".", 1)
        n = 0
        while n < len(frac) and frac[n].isdigit():
            n += 1
        s = f"{head}.{frac[:n][:6].ljust(6, '0')}{frac[n:]}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def _hhmm(text: str) -> time:
    h, m = str(text).split(":")
    return time(int(h), int(m))


def schwab_window(now: datetime, cfg: dict[str, Any]) -> tuple[bool, str]:
    from market_session import current_market_session

    w = (cfg.get("schwab") or {}).get("window") or {}
    et = now.astimezone(ET)
    week_min = et.weekday() * 1440 + et.hour * 60 + et.minute
    s, e = _hhmm(w.get("start", "18:00")), _hhmm(w.get("end", "09:30"))
    start = _DAYS[str(w.get("start_day", "sun")).lower()] * 1440 + s.hour * 60 + s.minute
    end = _DAYS[str(w.get("end_day", "fri")).lower()] * 1440 + e.hour * 60 + e.minute
    inside = (start <= week_min or week_min <= end) if start > end else (start <= week_min <= end)
    if not inside:
        return False, "outside_window"
    if (cfg.get("schwab") or {}).get("skip_regular_session", True) and current_market_session(et) == "regular":
        return False, "regular_session"
    return True, "futures_overnight"


# ── payload -> market_quotes_extended rows ──────────────────────────────────────────────────────────


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def schwab_rows(payload: Any, now: datetime, cfg: dict[str, Any],
                ext_cfg: dict[str, Any] | None = None) -> tuple[list[dict], list[dict]]:
    """Schwab quotes payload -> (rows in the market_quotes_extended contract, skipped with reasons)."""
    ext_cfg = ext_cfg or mqe.load_config()
    s = cfg.get("schwab") or {}
    basis = s.get("reference_basis") or {}
    span = timedelta(milliseconds=float(s.get("point_quote_span_ms", 1)))
    rows: list[dict] = []
    skipped: list[dict] = []
    for sym, blk in (payload.items() if isinstance(payload, dict) else []):
        if not isinstance(blk, dict) or not isinstance(blk.get("quote"), dict):
            skipped.append({"symbol": sym, "reason": "not_a_quote"})
            continue
        q = blk["quote"]
        ext = blk.get("extended") if isinstance(blk.get("extended"), dict) else {}
        reg = blk.get("regular") if isinstance(blk.get("regular"), dict) else {}
        price, ts = _num(ext.get("lastPrice")), parse_ts(ext.get("tradeTime"))
        if price is None or ts is None:
            price, ts = _num(q.get("lastPrice")), parse_ts(q.get("tradeTime"))
        sym_u = str(sym).upper()
        if price is None or ts is None:
            skipped.append({"symbol": sym_u, "reason": "no_trade_price_or_time"})
            continue
        age = (now - ts).total_seconds() / 60.0
        if age > float(s.get("max_trade_age_minutes", 30)):
            skipped.append({"symbol": sym_u, "reason": "stale_trade", "as_of": ts.isoformat(), "age_minutes": round(age, 1)})
            continue
        if age < -5:
            skipped.append({"symbol": sym_u, "reason": "future_timestamp", "as_of": ts.isoformat()})
            continue
        et = ts.astimezone(ET)
        sess = mqe.session_of(et, ext_cfg)
        if sess is None:
            night = ovn.label(ts, ext_cfg, asset_type=str(blk.get("assetMainType", "")))
            if night is None:
                skipped.append({"symbol": sym_u, "reason": "session_not_in_store_contract", "as_of": ts.isoformat(),
                                "detail": "market_quotes_extended stores premarket/afterhours of NYSE trading days, "
                                          "overnight 20:00-04:00 ET Sun-Thu nights and the Sunday 18:00 futures open"})
                continue
            rows.append(_night_row(sym_u, blk, q, reg, price, ts, night, span, s))
            continue
        sdate: date = et.date()
        if sess == "afterhours":
            ref = _num(reg.get("regularMarketLastPrice")) if str(blk.get("assetMainType", "")).upper() == "EQUITY" else None
            ref_date, ref_basis = sdate, basis.get("afterhours_equity")
        else:
            ref, ref_date, ref_basis = _num(q.get("closePrice")), mqe.previous_session(sdate), basis.get("premarket")
        if ref is None or not ref_basis:
            skipped.append({"symbol": sym_u, "reason": f"no_reference_close_for_{sess}", "as_of": ts.isoformat()})
            continue
        rows.append({"symbol": sym_u, "session": sess, "session_date": sdate, "bar_start": ts - span, "bar_end": ts,
                     "price": price, "volume": None, "reference_close": ref, "reference_date": ref_date,
                     "reference_basis": ref_basis, "change_pct": round(100.0 * (price - ref) / ref, 4),
                     "feed": str(s["feed"])})
    return rows, skipped


def _same_et_date(value: Any, want: date) -> bool | None:
    """True/False when ``value`` is a provider timestamp on/off ``want`` (ET), None when there is no timestamp."""
    at = parse_ts(value)
    return None if at is None else at.astimezone(ET).date() == want


def _night_row(sym: str, blk: dict, q: dict, reg: dict, price: float, ts: datetime, night: tuple[str, date],
               span: timedelta, s: dict[str, Any]) -> dict[str, Any]:
    """One overnight / futures-open row. The reference is the close of the trading day before the trading date,
    taken only from a field that means exactly that and, when the payload dates it, only when the date matches."""
    sess, tdate = night
    ref_date = ovn.reference_date(tdate)
    basis = s.get("overnight_reference_basis") or {}
    if str(blk.get("assetMainType", "")).upper() == "EQUITY":
        ref, when, ref_basis = _num(reg.get("regularMarketLastPrice")), reg.get("regularMarketTradeTime"), basis.get("equity")
    else:
        ref, when, ref_basis = _num(q.get("closePrice")), q.get("settleTime"), basis.get("non_equity")
    level_only_why = None
    if ref is None:
        level_only_why = "no previous close / settlement in the payload"
    elif not ref_basis:
        level_only_why = "no reference basis configured"
    elif _same_et_date(when, ref_date) is False:
        level_only_why = f"reference dated {parse_ts(when).astimezone(ET).date()}, not {ref_date}"
    row = {"symbol": sym, "session": sess, "session_date": tdate, "bar_start": ts - span, "bar_end": ts,
           "price": price, "volume": None, "feed": str(s["feed"])}
    if level_only_why:
        row.update(reference_close=None, reference_date=None, change_pct=None,
                   reference_basis=str(basis.get("level_only") or "none_level_only"), level_only_reason=level_only_why)
    else:
        row.update(reference_close=ref, reference_date=ref_date, reference_basis=ref_basis,
                   change_pct=round(100.0 * (price - ref) / ref, 4))
    return row


# ── one run ─────────────────────────────────────────────────────────────────────────────────────────


def _jsonable(r: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in r.items()}


def run(*, cfg: dict[str, Any], now: datetime, fetch: Callable[[list[str]], Any],
        write: Callable[[list[dict]], Any] | None, dry_run: bool, force_window: bool = False,
        promoted: Callable[[], bool] = mqe.domain_promoted, root: Path = ROOT) -> dict[str, Any]:
    """Collect once. ``fetch(symbols)`` returns the Schwab payload (or ``{"_status": ...}``); ``write(rows)`` writes
    through market_quotes_extended_writer and returns its receipt. A dry run never calls ``write``."""
    receipt: dict[str, Any] = {"schema": RECEIPT_SCHEMA, "provider": "schwab", "store": STORE,
                               "now": now.astimezone(timezone.utc).isoformat(), "dry_run": bool(dry_run),
                               "inserted": 0, "rows": [], "skipped": []}
    s = cfg.get("schwab") or {}
    if not s.get("enabled"):
        receipt["status"] = "disabled"
        receipt["detail"] = "schwab.enabled is false in config/market_risk_offhours_quotes.yaml"
        return receipt
    ok, why = schwab_window(now, cfg)
    receipt["window"] = why
    if not ok and not force_window:
        receipt["status"] = "outside_window"
        return receipt
    if not dry_run and not promoted():
        receipt["status"] = "refused_domain_proposed"
        receipt["detail"] = "§7A domain quote_extended_session is still in proposed_domains (#2384 activation first)"
        return receipt
    universe, prov = resolve_universe(cfg, root=root)
    receipt["universe"] = prov
    symbols = schwab_symbols(cfg, universe)
    receipt["symbols"] = symbols
    payload = fetch(symbols)
    if isinstance(payload, dict) and payload.get("_status"):
        receipt["status"] = str(payload["_status"])
        receipt["detail"] = payload.get("_detail")
        return receipt
    rows, skipped = schwab_rows(payload, now, cfg)
    receipt["rows"] = [_jsonable(r) for r in rows]
    receipt["skipped"] = skipped
    if dry_run:
        receipt["status"] = "dry_run"
        return receipt
    if write is None:
        raise ValueError("write callable required unless dry_run")
    res = write(rows) if rows else {}
    receipt["inserted"] = int((res or {}).get("inserted", 0))
    receipt["rejected"] = list((res or {}).get("rejected", []))
    receipt["status"] = "ok"
    return receipt
