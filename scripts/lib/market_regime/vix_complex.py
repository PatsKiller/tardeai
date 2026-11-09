"""vix_complex.py — the volatility complex read from the stores, never from Yahoo.

LQ-20261107-940 + LQ-20261107-969 (design WU-6, FABLE-OUTLOOK-METHODOLOGY §1.3/§5): the regime collector asked
``query1.finance.yahoo.com`` for ``^VIX ^VIX9D ^VIX3M ^VVIX ^SKEW ^VXN`` on every fire and stamped the answer
``source_key='yahoo_finance'``. yfinance is a banned price source (operator price rule 2026-11-07; SPEC_MARKET_EVENT_REENTRY
§2) and the whole complex has been PARTIAL(BANNED) since. This module is the REBUILD, not a patch of that path:

* ``$VIX $VIX9D $VIX3M $VVIX $SKEW $VXN`` are CBOE indices the Schwab off-hours lane already quotes by symbol; its
  rows land in ``market_quotes_extended`` under ``feed='schwab'``. That store is read here, and ONLY under the feed
  this file's config names.
* A row whose feed is a banned source (yahoo / yahoo_finance / yfinance) is refused and NAMED in ``missing`` — it is
  never used, and never silently dropped.
* FRED ``VIXCLS`` / ``VXNCLS`` (already ingested into ``fred_economic_series``, published T+1) is the labelled
  fallback for the two closes FRED carries. It is never a substitute for the term-structure symbols it does not have.
* A value that is absent, stale, non-finite or <= 0 is UNKNOWN. It is named in ``missing``; it is never written as a
  zero (AGENTS.md §6; design hard constraint "UNKNOWN never a silent zero").
* The term-structure ratios (VIX9D/VIX, VIX/VIX3M) are derived only from two real values.

No network, no writes: the module reads two tables and returns rows for the collector to persist.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "market_regime_vix_complex.yaml"
SCHEMA = "MarketRegimeVixComplex@v1"

# Sources the design bans for this complex. A row under one of these feeds is refused BY NAME so a rogue writer
# shows up on the receipt instead of disappearing behind an "unavailable" line.
BANNED_FEEDS = frozenset({"yahoo", "yahoo_finance", "yfinance"})

GROUP = "volatility"


class ConfigError(ValueError):
    """The config cannot be trusted to describe the complex; fail loud rather than collect a half-source."""


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path or DEFAULT_CONFIG)
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"{p}: unreadable ({type(exc).__name__}: {exc})") from exc
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ConfigError(f"{p}: schema must be {SCHEMA}, not {doc.get('schema') if isinstance(doc, dict) else doc!r}")
    symbols = doc.get("symbols")
    if not isinstance(symbols, dict) or not symbols:
        raise ConfigError(f"{p}: symbols must be a non-empty mapping of Schwab symbol -> indicator key")
    for sym, key in symbols.items():
        if not str(sym).startswith("$") or not str(key).strip():
            raise ConfigError(f"{p}: bad symbols entry {sym!r}: {key!r} (a CBOE index is '$'-prefixed)")
    for name in ("feed", "store"):
        if not str(doc.get(name) or "").strip():
            raise ConfigError(f"{p}: {name} missing")
    max_age = doc.get("max_age_hours")
    if isinstance(max_age, bool) or not isinstance(max_age, (int, float)) or not math.isfinite(float(max_age)) \
            or float(max_age) <= 0:
        raise ConfigError(f"{p}: max_age_hours must be a finite positive number, not {max_age!r}")
    if float(doc.get("fresh_after_hours", 0)) > float(max_age):
        raise ConfigError(f"{p}: fresh_after_hours must not exceed max_age_hours")
    fred = doc.get("fred") or {}
    if not isinstance(fred, dict):
        raise ConfigError(f"{p}: fred must be a mapping of series id -> indicator key")
    if not str(doc.get("carried_basis_prefix") or "").strip():
        raise ConfigError(f"{p}: carried_basis_prefix missing (must match off-hours lane index_levels.basis_prefix)")
    fred_age = doc.get("fred_max_age_days", 7)
    if isinstance(fred_age, bool) or not isinstance(fred_age, (int, float)) or float(fred_age) < 1:
        raise ConfigError(f"{p}: fred_max_age_days must be a number >= 1, not {fred_age!r}")
    sig = doc.get("vix_signal") or {}
    for k in ("extreme", "high", "normal"):
        v = sig.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or float(v) <= 0:
            raise ConfigError(f"{p}: vix_signal.{k} must be a positive number, not {v!r}")
    if not (float(sig["extreme"]) >= float(sig["high"]) >= float(sig["normal"])):
        raise ConfigError(f"{p}: vix_signal thresholds must not increase: "
                          f"normal {sig['normal']} high {sig['high']} extreme {sig['extreme']}")
    return doc


def vix_signal(value: float | None, cfg: dict[str, Any]) -> str:
    """The collector's own bucket for a VIX level (thresholds are config, never literals here)."""
    if value is None:
        return "unknown"
    s = cfg.get("vix_signal") or {}
    if value > float(s["extreme"]):
        return "extreme"
    if value > float(s["high"]):
        return "high"
    if value > float(s["normal"]):
        return "normal"
    return "low"


def _num(raw: Any) -> float | None:
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _aware(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return None


def _carried_print_as_of(basis: Any, cfg: dict[str, Any]) -> datetime | None:
    """Age a Schwab index-level *carry* from the print date in ``reference_basis``, never from bar_end.

    The off-hours lane (LQ-939) stores a Friday close as an overnight LEVEL whose ``bar_end`` is that night's
    20:00 ET start. Using ``bar_end`` as the clock would report a ~52 h-old Friday print as 0.5 h fresh
    (REVIEW-LQ-969-cc-sonnet-3). Prefix comes from config (same string as
    ``config/market_risk_offhours_quotes.yaml`` ``index_levels.basis_prefix``).
    """
    prefix = str(cfg["carried_basis_prefix"]).rstrip("_")
    text = str(basis or "")
    marker = prefix + "_"
    if not text.startswith(marker):
        return None
    stamp = text[len(marker):].strip()
    try:
        day = date.fromisoformat(stamp[:10])
    except ValueError:
        return None
    # Session close is 16:00 America/New_York on the print date (the lane's carry is a regular-session print).
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 — stdlib fallback keeps the honest date even without zoneinfo
        return datetime(day.year, day.month, day.day, 21, 0, tzinfo=timezone.utc)  # 16:00 ET ≈ 21:00 UTC (EST)
    return datetime(day.year, day.month, day.day, 16, 0, tzinfo=et)


def read_quotes(conn, now: datetime, cfg: dict[str, Any]) -> tuple[dict[str, dict], list[str], list[dict]]:
    """Latest ``market_quotes_extended`` row per configured symbol under the configured feed.

    Returns ``(values_by_key, missing, receipts)``. ``missing`` names every refusal: no row, a stale row, a row
    under a banned feed, a non-positive price. ``receipts`` is the evidence list the caller prints in a dry run
    (one entry per configured symbol, refusing or accepting, so "0 rows" can never read as "nothing to do").
    """
    store = str(cfg["store"])
    feed = str(cfg["feed"])
    symbols = [str(s).upper() for s in cfg["symbols"]]
    key_of = {str(s).upper(): str(k) for s, k in cfg["symbols"].items()}
    values: dict[str, dict] = {}
    missing: list[str] = []
    receipts: list[dict] = []
    cur = conn.cursor()
    try:
        # Filter feed in SQL so a newer non-schwab row cannot hide a valid schwab print (REVIEW-LQ-969).
        cur.execute(
            f"SELECT DISTINCT ON (symbol) symbol, price, session, session_date, bar_end, reference_basis, feed "
            f"FROM {store} WHERE symbol = ANY(%s) AND feed = %s ORDER BY symbol, bar_end DESC",
            [symbols, feed],
        )  # nosemgrep: tq-py-sql-fstring -- store is the config's single literal 'market_quotes_extended'
        rows = cur.fetchall() or []
    except Exception as exc:  # noqa: BLE001 — a read failure is reported by name, the collector keeps its other rows
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — best effort on an already-broken connection
            pass
        missing.append(f"vix_complex_read_failed:{type(exc).__name__}")
        return {}, missing, receipts

    seen: dict[str, tuple] = {}
    for r in rows:
        if isinstance(r, dict):
            sym, price, session, sdate, bar_end, basis, row_feed = (
                r.get("symbol"), r.get("price"), r.get("session"), r.get("session_date"),
                r.get("bar_end"), r.get("reference_basis"), r.get("feed"))
        else:
            sym, price, session, sdate, bar_end, basis, row_feed = r
        seen[str(sym).upper()] = (price, session, sdate, bar_end, basis, row_feed)

    for sym in symbols:
        key = key_of[sym]
        row = seen.get(sym)
        if row is None:
            missing.append(f"{key}_unavailable:no_row")
            receipts.append({"symbol": sym, "key": key, "refused": "no_row"})
            continue
        price, session, sdate, bar_end, basis, row_feed = row
        if str(row_feed or "").strip().lower() in BANNED_FEEDS:
            # A banned source may not be scored; name the writer, do not launder it into "no row".
            missing.append(f"{key}_banned_source:{row_feed}")
            receipts.append({"symbol": sym, "key": key, "refused": f"banned_source:{row_feed}"})
            continue
        if str(row_feed or "") != feed:
            missing.append(f"{key}_unexpected_feed:{row_feed}")
            receipts.append({"symbol": sym, "key": key, "refused": f"unexpected_feed:{row_feed}"})
            continue
        val = _num(price)
        if val is None:
            missing.append(f"{key}_non_positive_price:{price!r}")
            receipts.append({"symbol": sym, "key": key, "refused": f"non_positive_price:{price!r}"})
            continue
        end = _aware(bar_end)
        if end is None:
            missing.append(f"{key}_no_bar_end")
            receipts.append({"symbol": sym, "key": key, "refused": "no_bar_end"})
            continue
        carried_at = _carried_print_as_of(basis, cfg)
        clock = carried_at or end
        age_h = (now.astimezone(timezone.utc) - clock.astimezone(timezone.utc)).total_seconds() / 3600.0
        if age_h > float(cfg["max_age_hours"]):
            missing.append(f"{key}_stale:{age_h:.1f}h")
            receipts.append({"symbol": sym, "key": key, "refused": f"stale:{age_h:.1f}h",
                             "carried_from": carried_at.date().isoformat() if carried_at else None})
            continue
        values[key] = {"value": val, "source": f"{store}:{feed}", "symbol": sym, "age_hours": round(age_h, 2),
                       "as_of": clock.isoformat(), "session": session,
                       "session_date": str(sdate) if sdate is not None else None,
                       "reference_basis": basis, "fresh": age_h <= float(cfg.get("fresh_after_hours") or 0),
                       "carried_from": carried_at.date().isoformat() if carried_at else None,
                       "bar_end": end.isoformat()}
        receipts.append({"symbol": sym, "key": key, "value": val, "age_hours": round(age_h, 2),
                         "as_of": clock.isoformat(),
                         "carried_from": carried_at.date().isoformat() if carried_at else None,
                         "fresh": age_h <= float(cfg.get("fresh_after_hours") or 0)})
    return values, missing, receipts

def read_fred(conn, now: datetime, cfg: dict[str, Any]) -> tuple[dict[str, dict], list[str]]:
    """Latest non-null observation per configured FRED series (published T+1; a weekend gap is not staleness).

    Used only for keys no Schwab row supplied. An observation older than ``fred_max_age_days`` is refused by name
    rather than passed off as today's close.
    """
    fred = {str(k): str(v) for k, v in (cfg.get("fred") or {}).items()}
    if not fred:
        return {}, []
    out: dict[str, dict] = {}
    missing: list[str] = []
    cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT ON (series_id) series_id, observation_date, value FROM fred_economic_series "
                    "WHERE series_id = ANY(%s) AND value IS NOT NULL ORDER BY series_id, observation_date DESC",
                    [list(fred)])
        rows = cur.fetchall() or []
    except Exception as exc:  # noqa: BLE001 — named; the Schwab half of the complex is still usable
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — best effort on an already-broken connection
            pass
        return {}, [f"fred_read_failed:{type(exc).__name__}"]
    today = now.astimezone(timezone.utc).date()
    max_days = float(cfg.get("fred_max_age_days", 7))
    for r in rows:
        sid, obs, raw = (r.get("series_id"), r.get("observation_date"), r.get("value")) if isinstance(r, dict) else r
        key = fred.get(str(sid))
        val = _num(raw)
        if key is None or val is None:
            continue
        if isinstance(obs, date):
            age_days = (today - obs).days
            if age_days > max_days:
                missing.append(f"{key}_fred_stale:{age_days}d")
                continue
            # T+1 publish: same calendar day or next is fresh; older weekend/holiday ages stay usable but not fresh.
            out[key] = {"value": val, "source": "fred_economic_series", "series_id": str(sid),
                        "observation_date": obs.isoformat(), "as_of": obs.isoformat(),
                        "age_days": age_days, "session": "close",
                        "session_date": obs.isoformat(), "reference_basis": "fred_close",
                        "fresh": age_days <= 2}
        else:
            missing.append(f"{key}_fred_no_date")
    return out, missing


def merge(schwab: dict[str, dict], fred: dict[str, dict]) -> tuple[dict[str, dict], dict[str, str]]:
    """Schwab dated close first; FRED fills gaps and displaces a *carried* Schwab level.

    A carried Friday print (``reference_basis`` = ``…carried_print_YYYY-MM-DD``) is a level, not today's close.
    Preferring it over FRED's published close is how three numbers (MRE / Schwab carry / FRED) disagree on one
    Sunday night. Dated Schwab closes (regular_close / non-carried) still beat FRED.
    """
    values = dict(fred)
    how: dict[str, str] = {k: "fred" for k in fred}
    for k, v in schwab.items():
        if v.get("carried_from") and k in fred:
            # Keep the carried level on the FRED row's payload so the receipt still shows what Schwab held.
            values[k] = {**fred[k], "schwab_carried_level": v.get("value"),
                         "schwab_carried_from": v.get("carried_from"),
                         "schwab_carried_age_hours": v.get("age_hours")}
            how[k] = "fred"
            continue
        values[k] = v
        how[k] = "schwab"
    return values, how


def complex_record(conn, now: datetime | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """One VIX/VIX3M/VVIX record with source precedence and freshness — the single read for MRE / outlook / CIO.

    Never writes. Never returns a Yahoo value. Term structure is ``unknown`` unless both legs are real and accepted.
    """
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)
    inds, missing, summary = collect(conn, "COMPLEX_READ", now, cfg, lambda: "read")
    by_key = {i["indicator_key"]: i for i in inds}
    def _leg(key: str) -> dict[str, Any] | None:
        row = by_key.get(key)
        if not row:
            return None
        payload = row.get("payload") or {}
        return {
            "value": row["value"],
            "source": row.get("source_key"),
            "value_source": payload.get("value_source"),
            "as_of": payload.get("as_of"),
            "fresh": bool(payload.get("fresh")),
            "age_hours": payload.get("age_hours"),
            "age_days": payload.get("age_days"),
            "session": payload.get("session"),
            "reference_basis": payload.get("reference_basis"),
            "carried_from": payload.get("carried_from"),
            "signal": row.get("signal"),
        }
    vix = _leg("vix_close")
    vix3m = _leg("vix3m_close")
    vvix = _leg("vvix_close")
    ratio = by_key.get("vix_vix3m_ratio")
    term = "unknown"
    if ratio is not None:
        term = str(ratio.get("signal") or "unknown")
    return {
        "schema": SCHEMA,
        "as_of": now.isoformat(),
        "vix": vix,
        "vix3m": vix3m,
        "vvix": vvix,
        "vix9d": _leg("vix9d_close"),
        "vxn": _leg("vxn_close"),
        "skew": _leg("skew_close"),
        "term_structure": term,
        "term_structure_ratio": None if ratio is None else ratio.get("value"),
        "sources": summary.get("sources") or {},
        "missing": list(missing),
        "receipts": summary.get("receipts") or [],
    }

def collect(conn, snapshot_id: str, now: datetime, cfg: dict[str, Any],
            make_id: Callable[[], str]) -> tuple[list[dict], list[str], dict[str, Any]]:
    """Build ``market_regime_indicators`` volatility rows for the complex. Never writes; never returns a 0 placeholder.

    Returns ``(indicators, missing, summary)``; ``summary`` carries the per-symbol receipt the collector prints.
    """
    schwab, missing, receipts = read_quotes(conn, now, cfg)
    fred, fred_missing = read_fred(conn, now, cfg)
    values, how = merge(schwab, fred)
    # A FRED close fills a key Schwab had no row for: drop that "no_row" line only, so the receipt reports what
    # happened (the source of record for the key is named in the payload). Every other refusal — stale, banned,
    # unexpected feed — stays on the receipt even when FRED filled the key, because it is what the writer did.
    missing = [m for m in missing if not (m.endswith(":no_row") and m.split("_unavailable:", 1)[0] in values)]
    missing.extend(fred_missing)

    out: list[dict] = []
    for key in [str(k) for k in cfg["symbols"].values()]:
        v = values.get(key)
        if v is None:
            if not any(m.startswith(f"{key}_") for m in missing):
                missing.append(f"{key}_unavailable:not_collected")
            continue
        signal = vix_signal(v["value"], cfg) if key == "vix_close" else "observed"
        out.append(_ind(make_id(), snapshot_id, key, v["value"], signal,
                        f"{v['source']}:{v.get('symbol') or v.get('series_id')}", {
                            "value_source": how.get(key), "source": v["source"], "as_of": v["as_of"],
                            "age_hours": v.get("age_hours"), "age_days": v.get("age_days"),
                            "session": v.get("session"), "session_date": v.get("session_date"),
                            "reference_basis": v.get("reference_basis"), "symbol": v.get("symbol"),
                            "series_id": v.get("series_id"), "fresh": v.get("fresh"),
                            "carried_from": v.get("carried_from"),
                            "schwab_carried_level": v.get("schwab_carried_level"),
                            "schwab_carried_from": v.get("schwab_carried_from"),
                            "bar_end": v.get("bar_end"),
                        }))
    # Term structure: derived only from two real values, and only when both are present.
    vix = (values.get("vix_close") or {}).get("value")
    vix9d = (values.get("vix9d_close") or {}).get("value")
    vix3m = (values.get("vix3m_close") or {}).get("value")
    if vix and vix9d:
        r = vix9d / vix
        out.append(_ind(make_id(), snapshot_id, "vix9d_vix_ratio", r, "inverted" if r > 1 else "contango",
                        "derived", {"numerator": "vix9d_close", "denominator": "vix_close",
                                    "inputs": {"vix9d": vix9d, "vix": vix}}))
    else:
        missing.append("vix9d_vix_ratio_unavailable:needs_vix9d_and_vix")
    if vix and vix3m:
        r = vix / vix3m
        out.append(_ind(make_id(), snapshot_id, "vix_vix3m_ratio", r, "inverted" if r > 1 else "contango",
                        "derived", {"numerator": "vix_close", "denominator": "vix3m_close",
                                    "inputs": {"vix": vix, "vix3m": vix3m}}))
    else:
        missing.append("vix_vix3m_ratio_unavailable:needs_vix_and_vix3m")

    summary = {"receipts": receipts, "sources": how, "values": {k: v["value"] for k, v in values.items()},
               "banned_feeds_refused": [r for r in receipts if str(r.get("refused", "")).startswith("banned_source")]}
    return out, missing, summary


def _ind(indicator_id: str, snapshot_id: str, key: str, value: float, signal: str, source: str,
         payload: dict[str, Any]) -> dict:
    return {"indicator_id": indicator_id, "snapshot_id": snapshot_id, "indicator_key": key,
            "indicator_group": GROUP, "value": round(float(value), 4), "signal": signal,
            "source_key": source, "payload": {k: v for k, v in payload.items() if v is not None}}


def expected_keys(cfg: dict[str, Any]) -> Iterable[str]:
    return [str(k) for k in cfg["symbols"].values()]
