#!/usr/bin/env python3
"""Build the Market Risk Engine scenario-replay fixtures from PUBLIC daily history (design
DSN-20261031-market-risk-engine §8 / plan §5.15, task P2-T12).

One-time, operator-or-agent-run builder; never scheduled, never imported by the engine. It writes
``tests/fixtures/market_risk_scenarios/``:

* ``bars.csv.gz``   date,symbol,open,high,low,close,volume — Yahoo chart API daily bars (public)
* ``fred.csv.gz``   date,series,value — FRED public graph CSV
* ``scenarios.json`` the scenario windows and expectations (hand-maintained, read by the tests)
* ``SOURCES.json``  what was fetched, row counts, first/last date, and every source that refused

No portfolio data, no credentials, no Trade AI database. Default is a dry run that prints the plan;
``--apply`` fetches and writes. Network only here; tests read the committed files offline.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "market_risk_scenarios"

YAHOO_SYMBOLS = "SPY QQQ IWM RSP SMH SOXX XLK TLT HYG LQD UUP USO GLD ^VIX ^VVIX ^VIX3M ^VIX9D".split()
FRED_SERIES = ("BAMLH0A0HYM2", "DGS10", "T10Y2Y", "DCOILWTICO", "DTWEXBGS", "VIXCLS")
START = date(2016, 1, 1)  # one year of warm-up before the earliest scenario (2017 calm control)
UA = "Mozilla/5.0 (compatible; tradeai-fixture-build/1.0)"
# FRED's graph endpoint stalls (never answers) for browser-like agents without browser headers; a plain
# tool agent is served at once (measured 2026-10-31: 20 s timeout vs 0.12 s).
FRED_UA = "curl/8.5.0"


def _get(url: str, timeout: int = 30, ua: str = UA) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed public hosts
        return r.read()


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def fetch_yahoo(symbol: str, start: date, end: date) -> list[tuple]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}"
        f"?period1={_epoch(start)}&period2={_epoch(end) + 86400}&interval=1d&events=history"
    )
    data = json.loads(_get(url))
    res = (data.get("chart") or {}).get("result") or []
    if not res:
        raise RuntimeError(f"no result: {(data.get('chart') or {}).get('error')}")
    r0 = res[0]
    tz_off = int((r0.get("meta") or {}).get("gmtoffset") or 0)
    q = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    for i, ts in enumerate(r0.get("timestamp") or []):
        c = (q.get("close") or [None])[i]
        if c is None:
            continue
        d = datetime.fromtimestamp(ts + tz_off, tz=timezone.utc).date()

        def r(v):
            return None if v is None else round(float(v), 4)

        rows.append(
            (
                d.isoformat(),
                symbol,
                r(q["open"][i]),
                r(q["high"][i]),
                r(q["low"][i]),
                r(c),
                int(q["volume"][i] or 0) if q.get("volume") else 0,
            )
        )
    return rows


def fetch_fred(series: str, start: date, end: date) -> list[tuple]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}&coed={end}"
    last: Exception | None = None
    for attempt in range(3):  # the FRED graph endpoint is slow on long ranges; retry, then refuse loudly
        try:
            text = _get(url, timeout=60, ua=FRED_UA).decode("utf-8")
            break
        except Exception as exc:  # noqa: BLE001 — re-raised below after the last attempt
            last = exc
            time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError(f"FRED {series} unavailable after 3 attempts: {last}")
    rows = []
    for rec in csv.DictReader(io.StringIO(text)):
        v = rec.get(series)
        if v in (None, "", "."):
            continue
        d = rec.get("observation_date") or rec.get("DATE")
        rows.append((d, series, round(float(v), 4)))
    return rows


def _write_gz(path: Path, header: list[str], rows: list[tuple]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(sorted(rows, key=lambda r: (r[0], r[1])))
    # mtime=0 so a rebuild with identical data yields identical bytes
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
        gz.write(buf.getvalue().encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    end = date.fromisoformat(a.end)
    out = Path(a.out)
    print(f"plan: {len(YAHOO_SYMBOLS)} Yahoo symbols + {len(FRED_SERIES)} FRED series, {START}..{end} -> {out}")
    if not a.apply:
        print("DRY RUN — nothing fetched or written (pass --apply)")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    bars: list[tuple] = []
    fred: list[tuple] = []
    sources: dict = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": str(START),
        "end": str(end),
        "yahoo": {},
        "fred": {},
        "refused": [],
    }
    for s in YAHOO_SYMBOLS:
        try:
            rows = fetch_yahoo(s, START, end)
            bars += rows
            sources["yahoo"][s] = {
                "rows": len(rows),
                "first": rows[0][0] if rows else None,
                "last": rows[-1][0] if rows else None,
            }
            print(f"yahoo {s}: {len(rows)} rows")
        except Exception as exc:  # recorded, never silent: SOURCES.json lists every refusal
            sources["refused"].append({"source": "yahoo", "id": s, "error": str(exc)[:200]})
            print(f"yahoo {s}: REFUSED {exc}", file=sys.stderr)
        time.sleep(0.4)
    for s in FRED_SERIES:
        try:
            rows = fetch_fred(s, START, end)
            fred += rows
            sources["fred"][s] = {
                "rows": len(rows),
                "first": rows[0][0] if rows else None,
                "last": rows[-1][0] if rows else None,
            }
            print(f"fred {s}: {len(rows)} rows")
        except Exception as exc:
            sources["refused"].append({"source": "fred", "id": s, "error": str(exc)[:200]})
            print(f"fred {s}: REFUSED {exc}", file=sys.stderr)
    _write_gz(out / "bars.csv.gz", ["date", "symbol", "open", "high", "low", "close", "volume"], bars)
    _write_gz(out / "fred.csv.gz", ["date", "series", "value"], fred)
    (out / "SOURCES.json").write_text(json.dumps(sources, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    sz = sum(p.stat().st_size for p in out.glob("*.gz"))
    print(f"wrote {len(bars)} bars, {len(fred)} fred rows, {sz} bytes compressed; refused={len(sources['refused'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
