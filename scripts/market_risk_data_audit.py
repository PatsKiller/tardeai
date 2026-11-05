#!/usr/bin/env python3
"""Market Risk Engine data audit — is the data the engine needs really there, and how fresh is it?

Read-only (``SET default_transaction_read_only``): for each ``DataReader`` method of
``scripts/lib/market_risk/reader.py`` it prints the newest row's ``as_of``, the row counts over the engine's
lookbacks, then, per scoring category, whether today's evaluation would be measured, partial or UNKNOWN and why,
and which planned stores do not exist yet. Writes nothing, sends nothing, calls no model and no provider.

Usage:
    .venv/bin/python scripts/market_risk_data_audit.py              # now
    .venv/bin/python scripts/market_risk_data_audit.py --as-of 2026-10-29T22:15:00+00:00 --json

Design: DSN-20261031-market-risk-engine P1 (data). MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk.reader import PgReader  # noqa: E402

INDEX = ["SPY", "QQQ", "IWM", "DIA", "RSP", "SMH", "SOXX", "XLK"]
CROSS = ["TLT", "HYG", "JNK", "LQD", "UUP", "USO", "GLD", "UVXY", "VIXY"]
FRED = ["BAMLH0A0HYM2", "DGS10", "T10Y2Y", "DTWEXBGS", "DCOILWTICO", "VIXCLS", "VXNCLS"]
VOL_KEYS = ["vix_close", "vvix_close", "vix9d_close", "vix3m_close", "vxn_close", "skew_close"]
PLANNED_STORES = [
    "market_breadth_daily",
    "market_internals_intraday",
    "institutional_flow_daily",
    "option_chain_strikes",
    "etf_holdings_snapshot",
    "market_risk_snapshots",
    "market_risk_episodes",
]
LOOKBACK = {"daily_sessions": 260, "fred_obs": 260, "option_sessions": 20, "sma_long": 200, "sma_mid": 50, "z_min": 20}


def _newest(rows: list[dict], key: str = "as_of") -> str | None:
    vals = [r.get(key) for r in rows if r.get(key)]
    return max(vals) if vals else None


def audit(reader: PgReader, now: datetime) -> dict:
    out: dict = {"as_of": now.isoformat(), "methods": {}, "categories": {}, "gaps": []}
    bars = reader.daily_bars(INDEX + CROSS, sessions=LOOKBACK["daily_sessions"], end=now)
    per: dict[str, list[dict]] = {}
    for r in bars:
        per.setdefault(r["symbol"], []).append(r)
    out["methods"]["daily_bars"] = {
        s: {
            "sessions": len(per.get(s, [])),
            "newest": per[s][-1]["date"] if per.get(s) else None,
            "newest_provisional": per[s][-1]["provisional"] if per.get(s) else None,
            "sources": sorted({r["source"] for r in per.get(s, [])}),
        }
        for s in INDEX + CROSS
    }
    q = reader.quotes(INDEX + CROSS, start=now - timedelta(days=3), end=now)
    idx = [r for r in q if r["symbol"] in ("SPY", "QQQ")]
    pre = [r for r in idx if 240 <= (_et_minutes(r["as_of"]) or -1) < 570]
    post = [r for r in idx if 960 <= (_et_minutes(r["as_of"]) or -1) < 1200]
    out["methods"]["quotes"] = {
        "rows_72h": len(q),
        "newest": _newest(q),
        "spy_qqq_premarket_rows_72h": len(pre),
        "spy_qqq_afterhours_rows_72h": len(post),
    }
    ri = reader.regime_indicators(end=now)
    keys = {r["indicator_key"]: r for r in ri}
    out["methods"]["regime_indicators"] = {
        "snapshot_id": ri[0]["snapshot_id"] if ri else None,
        "newest": _newest(ri),
        "vol_keys_present": [k for k in VOL_KEYS if k in keys],
        "vol_keys_missing": [k for k in VOL_KEYS if k not in keys],
    }
    fr = reader.fred(FRED, observations=LOOKBACK["fred_obs"], end=now)
    fper: dict[str, list[dict]] = {}
    for r in fr:
        fper.setdefault(r["series_id"], []).append(r)
    out["methods"]["fred"] = {
        s: {"observations": len(fper.get(s, [])), "newest": _newest(fper.get(s, []))} for s in FRED
    }
    op = reader.option_snapshots(["SPY", "QQQ"], sessions=LOOKBACK["option_sessions"], end=now)
    out["methods"]["option_snapshots"] = {
        s: {"sessions": sum(1 for r in op if r["symbol"] == s), "newest": _newest([r for r in op if r["symbol"] == s])}
        for s in ("SPY", "QQQ")
    }
    ss = reader.sector_states(end=now)
    out["methods"]["sector_states"] = {
        "etfs": len(ss),
        "newest": _newest(ss),
        "states": {r["etf"]: r["state"] for r in ss},
    }
    ec = reader.earnings_calendar(start=now - timedelta(days=1), end=now + timedelta(days=7))
    out["methods"]["earnings_calendar"] = {"events_next_7d": len(ec), "newest_update": _newest(ec)}
    mc = reader.macro_calendar(start=now - timedelta(days=1), end=now + timedelta(days=60))
    out["methods"]["macro_calendar"] = {
        "events_next_60d": len(mc),
        "note": reader.macro_calendar_note,
        "sources": sorted({e["source"] for e in mc}),
        "events": [f"{e['date']} {e.get('event')}" for e in mc],
    }

    def sess(s: str) -> int:
        return len(per.get(s, []))

    cats = out["categories"]
    idx_hist = min(sess("SPY"), sess("QQQ"), sess("SMH"))
    cats["technical"] = _grade(
        idx_hist >= LOOKBACK["sma_long"],
        idx_hist >= LOOKBACK["sma_mid"],
        f"SPY/QQQ/SMH daily history {idx_hist} sessions (200-DMA needs {LOOKBACK['sma_long']})",
    )
    cats["breadth"] = _grade(
        False,
        len(ss) >= 9,
        "market_breadth_daily does not exist; only sector_momentum_state breadth_pct and RSP vs SPY",
    )
    cats["volatility"] = _grade(
        not out["methods"]["regime_indicators"]["vol_keys_missing"],
        "vix_close" in keys,
        f"vol keys missing from the latest collector snapshot: "
        f"{out['methods']['regime_indicators']['vol_keys_missing'] or 'none'}",
    )
    opt_min = min(v["sessions"] for v in out["methods"]["option_snapshots"].values())
    cats["options_flow"] = _grade(
        opt_min >= 20,
        opt_min >= 5,
        f"SPY/QQQ option snapshots {opt_min} sessions; one row per session date (unique "
        "(as_of, symbol): a later run the same day overwrites the 10:00 row)",
    )
    fred_min = min(v["observations"] for k, v in out["methods"]["fred"].items() if k != "VXNCLS")
    cats["macro_credit"] = _grade(
        fred_min >= 252,
        fred_min >= LOOKBACK["z_min"],
        f"FRED shortest series {fred_min} observations (252 for a 1-year z-score)",
    )
    cross = [s for s in CROSS if s not in ("UVXY", "VIXY")]
    absent = [s for s in cross if sess(s) == 0]
    have = [sess(s) for s in cross if sess(s)]
    cats["cross_asset"] = _grade(
        not absent and min(have) >= 252,
        len(have) >= 4 and min(have) >= 20,
        f"no daily data at all for {absent or 'none'}; others shortest {min(have) if have else 0} "
        "sessions (1-year correlation z needs 252)",
    )
    cal_ok = not reader.macro_calendar_note
    cats["event"] = _grade(
        len(ec) > 0 and cal_ok,
        len(ec) > 0,
        f"{len(ec)} earnings events next 7d (no index weights yet); macro calendar "
        f"{'runtime file' if cal_ok else 'FOMC-only fallback: macro_calendar.json never written'}",
    )
    cats["seasonal"] = _grade(True, True, "computed from the calendar")
    cats["extended_hours"] = _grade(
        len(pre) >= 24 and len(post) >= 24,
        bool(pre or post),
        f"SPY/QQQ quotes in 72h: {len(pre)} pre-market (04:00-09:30), {len(post)} after-hours "
        "(16:00-20:00); the engine needs */15 (P1-T4); no futures source",
    )
    for t in PLANNED_STORES:
        if not reader._rows("SELECT to_regclass(%s) IS NOT NULL AS present", [t])[0]["present"]:
            out["gaps"].append(t)
    return out


def _grade(full: bool, partial: bool, why: str) -> dict:
    return {"status": "MEASURED" if full else ("PARTIAL" if partial else "UNKNOWN"), "why": why}


def _et_minutes(iso: str | None) -> int | None:
    if not iso:
        return None
    from zoneinfo import ZoneInfo

    t = datetime.fromisoformat(iso).astimezone(ZoneInfo("America/New_York"))
    return t.hour * 60 + t.minute


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", help="ISO-8601 instant with offset (default: now)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.as_of) if a.as_of else datetime.now(timezone.utc)
    reader = PgReader()
    try:
        rep = audit(reader, now)
    finally:
        reader.close()
    if a.json:
        print(json.dumps(rep, indent=2, default=str))
        return 0
    print(f"Market Risk Engine data audit as of {rep['as_of']} (read-only)")
    for name, body in rep["methods"].items():
        print(f"\n[{name}]")
        if name in ("daily_bars", "fred", "option_snapshots"):
            for k, v in body.items():
                print(f"  {k:<14} {json.dumps(v, default=str)}")
        else:
            print("  " + json.dumps(body, default=str))
    print("\n[categories]")
    for k, v in rep["categories"].items():
        print(f"  {k:<15} {v['status']:<9} {v['why']}")
    print(f"\n[planned stores not yet present] {', '.join(rep['gaps']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
