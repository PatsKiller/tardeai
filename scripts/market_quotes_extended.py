#!/usr/bin/env python3
"""Extended-session prints for the Market Risk Engine (DSN-20261031-market-risk-engine P1-T4).

Per run: Alpaca SIP 5-minute bars from the previous NYSE session's 04:00 ET pre-market open to ``now - sip_delay``
(the free plan's SIP delay), and daily bars for the reference close, through the quote ingest's existing credentials
(``external_market_data_ingest._alpaca_creds``), with bounded retry and backoff. For every symbol, the newest COMPLETE
bar inside an extended session of an NYSE trading day -- pre-market 04:00-09:30, after-hours close_time(d)-20:00 (13:00
on early closes) -- becomes one row in ``market_quotes_extended`` through its single writer
(``lib.writers.market_quotes_extended_writer``). Overnight bars (20:00-04:00) and non-trading days are never labelled.
``reference_close`` is the daily-bar close of the last session that closed before the bar, labelled with its basis.

Never ``market_quotes``: that is the latest-quote ledger and ~20 readers take its newest row with no source filter.
Default is a dry run (prints the rows; writes nothing) and it is FIXTURE-ONLY: ``--bars-json`` replays a saved
response; without it the dry run refuses unless ``--live-read`` asks for a labelled live Alpaca read. ``--apply`` writes.
AUTHORITY: READ_ONLY_ADVISORY. Market data only; never touches a broker account or an order route.
"""

from __future__ import annotations

import argparse
import json
import sys
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib.market_risk.sessions import close_time, is_trading_day  # noqa: E402

ET = ZoneInfo("America/New_York")
CONFIG_PATH = ROOT / "config" / "market_quotes_extended.json"
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"


DOMAIN = "quote_extended_session"
AUTHORITY_PATH = ROOT / "config" / "data_source_authority.json"


def domain_promoted(path: Path = AUTHORITY_PATH) -> bool:
    """True only when the store's §7A row sits in ``domains`` (granted), not ``proposed_domains``."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return any(r.get("domain") == DOMAIN for r in d.get("domains") or [])


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("schema") != "MarketQuotesExtended@v2":
        raise ValueError(f"{path}: expected schema MarketQuotesExtended@v2")
    return cfg


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def previous_session(d: date) -> date:
    p = d - timedelta(days=1)
    while not is_trading_day(p):
        p -= timedelta(days=1)
    return p


def session_of(start_et: datetime, cfg: dict[str, Any]) -> str | None:
    """'premarket' / 'afterhours' for a bar starting inside an extended session of an NYSE trading day, else None
    (regular session, overnight 20:00-04:00, weekends, holidays)."""
    d, t = start_et.date(), start_et.timetz().replace(tzinfo=None)
    if not is_trading_day(d):
        return None
    if _hhmm(cfg["premarket_open_et"]) <= t < _hhmm(cfg["regular_open_et"]):
        return "premarket"
    if close_time(d) <= t < _hhmm(cfg["afterhours_close_et"]):
        return "afterhours"
    return None


def _start(b: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(b["t"]).replace("Z", "+00:00")).astimezone(ET)


def rows_from_bars(
    bars: dict[str, list[dict]],
    daily: dict[str, list[dict]],
    cfg: dict[str, Any],
    *,
    now: datetime,
    refused_out: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    step = timedelta(minutes=int(cfg.get("bar_timeframe_minutes", 5)))
    out: list[dict[str, Any]] = []
    refused = refused_out if refused_out is not None else []
    for sym, series in sorted((bars or {}).items()):
        done = [b for b in series if _start(b) + step <= now and session_of(_start(b), cfg)]
        if not done:
            continue
        last = max(done, key=_start)
        start = _start(last)
        sess = session_of(start, cfg)
        # reference: the close of exactly the session this print moves from -- the same trading day for after-hours,
        # the previous NYSE session for pre-market. A missing or late daily bar refuses the row; it never falls back
        # to an older close (review of #2384 round 2: QQQ read -2.86% instead of -1.47% at 10-29 18:15).
        want = start.date() if sess == "afterhours" else previous_session(start.date())
        refs = [float(db["c"]) for db in (daily or {}).get(sym) or [] if _start(db).date() == want]
        if not refs:
            refused.append({"symbol": sym, "reason": f"no daily close for {want.isoformat()}"})
            continue
        ref_date, ref = want, refs[-1]
        price = float(last["c"])
        if price <= 0 or ref <= 0:
            continue
        out.append(
            {
                "symbol": sym,
                "session": sess,
                "session_date": start.date(),
                "bar_start": start.astimezone(timezone.utc),
                "bar_end": (start + step).astimezone(timezone.utc),
                "price": price,
                "volume": int(last.get("v") or 0),
                "reference_close": ref,
                "reference_date": ref_date,
                "reference_basis": cfg["reference_basis"],
                "change_pct": round(100.0 * (price - ref) / ref, 4),
                "feed": cfg.get("feed", "sip"),
            }
        )
    return out


def _get_with_retry(
    get: Callable[..., Any],
    url: str,
    *,
    headers: dict,
    params: dict,
    cfg: dict,
    sleep: Callable[[float], None] = _time.sleep,
) -> dict:
    retry = cfg.get("retry") or {}
    waits = list(retry.get("backoff_seconds") or [2, 6, 18])
    attempts = int(retry.get("attempts", 3))
    last = None
    for i in range(attempts):
        r = get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            return r.json() or {}
        last = r.status_code
        if r.status_code not in (429, 500, 502, 503, 504) or i == attempts - 1:
            break
        sleep(waits[min(i, len(waits) - 1)])
    raise RuntimeError(f"alpaca bars HTTP {last}")


def fetch(
    cfg: dict[str, Any],
    *,
    now: datetime,
    get: Callable[..., Any] | None = None,
    creds=None,
    sleep: Callable[[float], None] = _time.sleep,
) -> tuple[dict, dict]:
    if get is None:
        import requests

        get = requests.get
    if creds is None:
        import external_market_data_ingest as ingest

        creds = ingest._alpaca_creds()
    key, sec = creds
    if not (key and sec):
        raise RuntimeError("alpaca credentials unavailable to the quote ingest (no request sent)")
    h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    end = now - timedelta(minutes=int(cfg.get("sip_delay_minutes", 16)))
    d = now.astimezone(ET).date()
    start = datetime.combine(previous_session(d), _hhmm(cfg["premarket_open_et"]), ET)
    common = {
        "symbols": ",".join(cfg["symbols"]),
        "feed": cfg.get("feed", "sip"),
        "limit": 10000,
        "end": end.astimezone(timezone.utc).isoformat(),
    }
    bars, daily, token = {}, {}, None
    while True:
        p = dict(
            common,
            timeframe=f"{int(cfg.get('bar_timeframe_minutes', 5))}Min",
            start=start.astimezone(timezone.utc).isoformat(),
            **({"page_token": token} if token else {}),
        )
        j = _get_with_retry(get, BARS_URL, headers=h, params=p, cfg=cfg, sleep=sleep)
        for s, v in (j.get("bars") or {}).items():
            bars.setdefault(s, []).extend(v)
        token = j.get("next_page_token")
        if not token:
            break
    dstart = datetime.combine(d - timedelta(days=int(cfg.get("daily_lookback_days", 10))), time(0, 0), ET)
    j = _get_with_retry(
        get,
        BARS_URL,
        headers=h,
        params=dict(common, timeframe="1Day", start=dstart.astimezone(timezone.utc).isoformat()),
        cfg=cfg,
        sleep=sleep,
    )
    daily = j.get("bars") or {}
    return bars, daily


def run(
    *,
    apply: bool,
    bars_json: str | None = None,
    now: datetime | None = None,
    cfg: dict | None = None,
    conn: Any = None,
    fetcher: Callable[..., tuple[dict, dict]] | None = None,
    live_read: bool = False,
) -> dict[str, Any]:
    """A dry run is fixture-only (review F7, 2026-10-31): without ``bars_json`` (or an injected ``fetcher``) it
    refuses rather than call Alpaca, unless ``live_read`` is set -- then the output says ``source: alpaca_live``."""
    cfg = cfg or load_config()
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    if bars_json:
        saved = json.loads(Path(bars_json).read_text())
        bars, daily = saved["bars"], saved.get("daily") or {}
        source = f"fixture:{bars_json}"
    elif fetcher is not None:
        bars, daily = fetcher(cfg, now=now)
        source = "injected_fetcher"
    elif apply or live_read:
        bars, daily = fetch(cfg, now=now)
        source = "alpaca_live"
    else:
        return {"now": now.isoformat(), "apply": False, "status": "refused", "source": None, "inserted": 0,
                "detail": "dry run is fixture-only: pass --bars-json FILE, or --live-read to read Alpaca live "
                          "(read-only market data, writes nothing)"}
    refused: list[dict[str, Any]] = []
    rows = rows_from_bars(bars, daily, cfg, now=now, refused_out=refused)
    out: dict[str, Any] = {
        "now": now.isoformat(),
        "apply": apply,
        "source": source,
        "candidates": len(rows),
        "inserted": 0,
        "refused": refused,
        "rows": [{k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in r.items()} for r in rows],
    }
    if not apply or not rows:
        return out
    if not domain_promoted():
        raise SystemExit(
            "refusing --apply: §7A domain quote_extended_session is still in proposed_domains "
            "(config/data_source_authority.json); promote it in the activation PR first"
        )
    from lib.writers.market_quotes_extended_writer import write_extended_quotes

    own = conn is None
    if own:
        import external_market_data_ingest as ingest

        conn = ingest._get_conn()
    try:
        res = write_extended_quotes(conn.cursor(), rows)
        conn.commit()
        out.update(inserted=res["inserted"], rejected=res["rejected"], table=res["table"])
    finally:
        if own:
            conn.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write market_quotes_extended (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    ap.add_argument("--bars-json", help="replay a saved {bars, daily} response instead of calling Alpaca")
    ap.add_argument("--now", help="evaluation instant (ISO-8601); default now")
    ap.add_argument("--live-read", action="store_true",
                    help="dry run against live Alpaca market data (read-only; labelled source alpaca_live)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now) if a.now else None
    if now is not None and now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    out = run(apply=bool(a.apply) and not a.dry_run, bars_json=a.bars_json, now=now, live_read=a.live_read)
    print(json.dumps(out, indent=2, default=str))
    return 2 if out.get("status") == "refused" else 0


if __name__ == "__main__":
    raise SystemExit(main())
