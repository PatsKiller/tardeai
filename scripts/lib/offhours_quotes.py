"""Off-hours quote collection for the Market Risk Engine (pre-market, after-hours, overnight).

Why: the Market Risk Engine (#2383) reads ``market_quotes`` rows from sources ``alpaca`` and ``schwab``, and no job
collects a quote after about 16:10 ET or before the 09:30 open (2026-10-30 selloff RCA,
DSN-20261031-market-risk-engine). Settings: ``config/market_risk_offhours_quotes.yaml``.

This module is pure: config, universe, session tags, collection windows, and turning a provider payload into
``market_quotes`` rows. It never opens a network connection, a database or a credential. The entry points inject
``fetch`` and ``write``:

* Alpaca: ``scripts/external_market_data_ingest.py --quotes-offhours`` (the existing quote lane's entry; IEX feed).
* Schwab: ``scripts/market_quotes_offhours_schwab.py`` (OFF by default; AGENTS.md 28.2.0 / PR #2407 pending).

Both write through the one ``market_quotes`` writer, ``scripts/lib/writers/market_quotes_writer.py``.

Timestamps: every written row carries ``fetched_at`` = the quote's OWN trade time (tz-aware UTC, from the
provider payload), never the write time; its session (premarket / regular / after_hours / overnight / closed /
weekend / holiday) is derived from that timestamp with the house holiday calendar (``scripts/market_session.py``)
and printed on the receipt. ``market_quotes`` has no session column, so a reader derives the same tag from
``fetched_at`` (``session_tag``).

AUTHORITY: READ_ONLY_ADVISORY. Market data only; never an order, stop, account, position or auth endpoint.
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "market_risk_offhours_quotes.yaml"
SCHEMA = "MarketRiskOffHoursQuotes@v1"
RECEIPT_SCHEMA = "OffHoursQuoteRun@v1"
ET = ZoneInfo("America/New_York")
PROVIDERS = ("alpaca", "schwab")
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


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
    for key in ("universe", "sessions", "alpaca", "schwab"):
        if not isinstance(doc.get(key), dict):
            raise ConfigError(f"{p}: section {key!r} missing")
    return doc


def _lookup(doc: Any, dotted: str) -> Any:
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _symbols(values: Any) -> list[str]:
    return [str(s).strip().upper() for s in (values or []) if str(s).strip()]


def resolve_universe(cfg: dict[str, Any], *, root: Path = ROOT) -> tuple[list[str], dict[str, Any]]:
    """(symbols, provenance). The fixed proxies from the config plus each ``include_from_policy`` list read from the
    engine policy file. A missing policy key is named in ``missing_refs``; nothing is filled in for it."""
    import yaml

    uni = cfg.get("universe") or {}
    base = _symbols(uni.get("symbols"))
    prov: dict[str, Any] = {"base": base, "included": {}, "missing_refs": [], "policy_file": uni.get("policy_file")}
    policy: dict[str, Any] = {}
    refs = list(uni.get("include_from_policy") or [])
    if refs:
        pf = root / str(uni.get("policy_file") or "")
        try:
            policy = yaml.safe_load(pf.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            prov["policy_error"] = f"{type(exc).__name__}: {exc}"
    for ref in refs:
        vals = _lookup(policy, str(ref))
        if isinstance(vals, list) and vals:
            prov["included"][str(ref)] = _symbols(vals)
        else:
            prov["missing_refs"].append(str(ref))
    merged = list(dict.fromkeys([*base, *(s for v in prov["included"].values() for s in v)]))
    return merged, prov


# ── timestamps and sessions ─────────────────────────────────────────────────────────────────────────


def parse_ts(value: Any) -> datetime | None:
    """A provider timestamp -> tz-aware UTC datetime. Accepts RFC3339 with up to nanosecond fractions (Alpaca),
    epoch milliseconds (Schwab), or a datetime. Anything else is None (the row is skipped, never guessed)."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else None
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
        digits, tz = frac[:n], frac[n:]
        s = f"{head}.{digits[:6].ljust(6, '0')}{tz}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def _hhmm(text: str) -> time:
    h, m = str(text).split(":")
    return time(int(h), int(m))


def session_tag(ts: datetime, cfg: dict[str, Any] | None = None) -> str:
    """premarket | regular | after_hours | overnight | closed | weekend | holiday, from the timestamp itself."""
    from market_session import current_market_session, is_trading_day

    base = current_market_session(ts)
    if base == "afterhours":
        return "after_hours"
    if base in ("premarket", "regular"):
        return base
    et = ts.astimezone(ET)
    start = _hhmm(((cfg or {}).get("sessions") or {}).get("overnight_start") or "20:00")
    if et.time() >= start and is_trading_day(et + timedelta(days=1)):
        return "overnight"
    if et.time() < time(4, 0) and is_trading_day(et):
        return "overnight"
    return base


def alpaca_prev_close(snap: dict[str, Any], now: datetime | None = None) -> Any:
    """The last completed session's close, relative to ``now`` (default: the wall clock).

    Alpaca's ``prevDailyBar`` is the bar BEFORE ``dailyBar``. Before today's first bar exists (overnight,
    pre-market, a Monday morning) ``dailyBar`` is still the previous session, so ``prevDailyBar`` is two sessions
    back. Measured 2026-09-14 07:15-09:00 ET: HPE stored prev_close 55.23 (Thursday) against a Friday close of
    62.09 (Yahoo), so day_change_pct read +12.4% for a stock that had not traded; 7 of 9 litmus symbols were wrong
    the same way. (Moved here from external_market_data_ingest._alpaca_prev_close, which now delegates.)
    """
    daily = snap.get("dailyBar") or {}
    prev = (snap.get("prevDailyBar") or {}).get("c")
    try:
        bar_day = datetime.fromisoformat(str(daily.get("t")).replace("Z", "+00:00")).astimezone(ET).date()
        today = (now.astimezone(ET) if now else datetime.now(ET)).date()
    except Exception:
        return prev
    if daily.get("c") and bar_day < today:
        return daily.get("c")
    return prev


# ── collection windows ──────────────────────────────────────────────────────────────────────────────


def alpaca_window(now: datetime, cfg: dict[str, Any]) -> tuple[bool, str]:
    from market_session import is_trading_day

    a = cfg.get("alpaca") or {}
    et = now.astimezone(ET)
    if a.get("trading_days_only", True) and not is_trading_day(et):
        return False, "not_a_trading_day"
    for w in a.get("windows") or []:
        if _hhmm(w["start"]) <= et.time().replace(second=0, microsecond=0) <= _hhmm(w["end"]):
            return True, str(w.get("label") or f"{w['start']}-{w['end']}")
    return False, "outside_window"


def schwab_window(now: datetime, cfg: dict[str, Any]) -> tuple[bool, str]:
    from market_session import current_market_session

    w = (cfg.get("schwab") or {}).get("window") or {}
    et = now.astimezone(ET)
    week_min = et.weekday() * 1440 + et.hour * 60 + et.minute
    s = _hhmm(w.get("start", "18:00"))
    e = _hhmm(w.get("end", "09:30"))
    start = _DAYS[str(w.get("start_day", "sun")).lower()] * 1440 + s.hour * 60 + s.minute
    end = _DAYS[str(w.get("end_day", "fri")).lower()] * 1440 + e.hour * 60 + e.minute
    inside = (start <= week_min or week_min <= end) if start > end else (start <= week_min <= end)
    if not inside:
        return False, "outside_window"
    if (cfg.get("schwab") or {}).get("skip_regular_session", True) and current_market_session(et) == "regular":
        return False, "regular_session"
    return True, "futures_overnight"


# ── payload -> rows ─────────────────────────────────────────────────────────────────────────────────


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _finish(sym: str, price: float, prev: float | None, ts: datetime, now: datetime, pcfg: dict[str, Any],
            cfg: dict[str, Any], rows: list, skipped: list) -> None:
    age_min = (now - ts).total_seconds() / 60.0
    if age_min > float(pcfg.get("max_trade_age_minutes", 30)):
        skipped.append({"symbol": sym, "reason": "stale_trade", "as_of": ts.isoformat(), "age_minutes": round(age_min, 1)})
        return
    if age_min < -5:
        skipped.append({"symbol": sym, "reason": "future_timestamp", "as_of": ts.isoformat()})
        return
    tag = session_tag(ts, cfg)
    if tag not in set(pcfg.get("write_sessions") or ()):
        skipped.append({"symbol": sym, "reason": f"session_{tag}", "as_of": ts.isoformat()})
        return
    chg = round((price - prev) / prev * 100, 4) if prev else None
    rows.append({"row": {"symbol": sym, "price": price, "prev_close": prev, "day_change_pct": chg, "fetched_at": ts},
                 "session": tag, "as_of": ts.isoformat()})


def alpaca_rows(snapshots: Any, now: datetime, cfg: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Alpaca ``/v2/stocks/snapshots`` payload -> (rows, skipped). Price is ``latestTrade.p`` at ``latestTrade.t``
    only: the regular-session ``dailyBar`` close is never relabelled as an off-hours quote."""
    rows: list[dict] = []
    skipped: list[dict] = []
    pcfg = cfg.get("alpaca") or {}
    for sym, snap in (snapshots.items() if isinstance(snapshots, dict) else []):
        if not isinstance(snap, dict):
            skipped.append({"symbol": sym, "reason": "not_a_snapshot"})
            continue
        trade = snap.get("latestTrade") or {}
        price, ts = _num(trade.get("p")), parse_ts(trade.get("t"))
        if price is None or ts is None:
            skipped.append({"symbol": sym, "reason": "no_trade_price_or_time"})
            continue
        _finish(str(sym).upper(), price, _num(alpaca_prev_close(snap, now)), ts, now, pcfg, cfg, rows, skipped)
    return rows, skipped


def schwab_rows(payload: Any, now: datetime, cfg: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Schwab ``/marketdata/v1/quotes`` payload -> (rows, skipped). An equity's ``extended`` block (pre/post
    market) wins over ``quote``; futures and indices use ``quote``. prev_close is Schwab's ``quote.closePrice``."""
    rows: list[dict] = []
    skipped: list[dict] = []
    pcfg = cfg.get("schwab") or {}
    for sym, blk in (payload.items() if isinstance(payload, dict) else []):
        if not isinstance(blk, dict) or not isinstance(blk.get("quote"), dict):
            skipped.append({"symbol": sym, "reason": "not_a_quote"})
            continue
        q = blk["quote"]
        ext = blk.get("extended") if isinstance(blk.get("extended"), dict) else {}
        price, ts = _num(ext.get("lastPrice")), parse_ts(ext.get("tradeTime"))
        if price is None or ts is None:
            price, ts = _num(q.get("lastPrice")), parse_ts(q.get("tradeTime"))
        if price is None or ts is None:
            skipped.append({"symbol": sym, "reason": "no_trade_price_or_time"})
            continue
        _finish(str(sym).upper(), price, _num(q.get("closePrice")), ts, now, pcfg, cfg, rows, skipped)
    return rows, skipped


# ── one run ─────────────────────────────────────────────────────────────────────────────────────────


def schwab_symbols(cfg: dict[str, Any], universe: list[str]) -> list[str]:
    s = cfg.get("schwab") or {}
    extra = universe if s.get("include_universe", True) else []
    return list(dict.fromkeys([*(str(x).strip() for x in s.get("futures") or []),
                               *(str(x).strip() for x in s.get("indices") or []), *extra]))


def run(provider: str, *, cfg: dict[str, Any], now: datetime, fetch: Callable[[list[str]], Any],
        write: Callable[[list[dict]], Any] | None, dry_run: bool, force_window: bool = False,
        root: Path = ROOT) -> dict[str, Any]:
    """Collect once. ``fetch(symbols)`` returns the provider payload; ``write(rows)`` appends market_quotes rows and
    returns the writer receipt. With ``dry_run`` the write callable is never called (and may be None)."""
    if provider not in PROVIDERS:
        raise ValueError(f"provider {provider!r}")
    receipt: dict[str, Any] = {"schema": RECEIPT_SCHEMA, "provider": provider, "source": provider,
                               "now": now.astimezone(timezone.utc).isoformat(), "dry_run": bool(dry_run),
                               "written": 0, "rows": [], "skipped": []}
    pcfg = cfg.get(provider) or {}
    if not pcfg.get("enabled"):
        receipt["status"] = "disabled"
        receipt["detail"] = f"{provider}.enabled is false in config/market_risk_offhours_quotes.yaml"
        return receipt
    ok, why = (alpaca_window if provider == "alpaca" else schwab_window)(now, cfg)
    receipt["window"] = why
    if not ok and not force_window:
        receipt["status"] = "outside_window"
        return receipt
    universe, prov = resolve_universe(cfg, root=root)
    receipt["universe"] = prov
    symbols = universe if provider == "alpaca" else schwab_symbols(cfg, universe)
    receipt["symbols"] = symbols
    payload = fetch(symbols)
    if isinstance(payload, dict) and payload.get("_status"):
        receipt["status"] = str(payload["_status"])
        receipt["detail"] = payload.get("_detail")
        return receipt
    rows, skipped = (alpaca_rows if provider == "alpaca" else schwab_rows)(payload, now, cfg)
    receipt["rows"] = [{"symbol": r["row"]["symbol"], "price": r["row"]["price"], "prev_close": r["row"]["prev_close"],
                        "day_change_pct": r["row"]["day_change_pct"], "fetched_at": r["as_of"],
                        "session": r["session"]} for r in rows]
    receipt["skipped"] = skipped
    if dry_run:
        receipt["status"] = "dry_run"
        return receipt
    if write is None:
        raise ValueError("write callable required unless dry_run")
    wr = write([r["row"] for r in rows]) if rows else None
    receipt["written"] = int(getattr(wr, "rows_accepted", 0) or 0)
    receipt["rejected"] = list(getattr(wr, "rejected", []) or [])
    receipt["status"] = "ok"
    return receipt
