#!/usr/bin/env python3
"""Regression: /api/v2/open-trades/intelligence shows only true current positions (no stale phantoms).
Exits non-zero on any failure."""
try:  # cc_auth (2026-10-14): service token for loopback Command Center (:7777) calls
    from lib.cc_client import cc_urlopen as _cc_urlopen
except ImportError:  # pragma: no cover - scripts/ not on sys.path
    import sys as _cc_sys
    from pathlib import Path as _CcPath
    _cc_sys.path.insert(0, str(next(p for p in _CcPath(__file__).resolve().parents if p.name == "scripts")))
    from lib.cc_client import cc_urlopen as _cc_urlopen

import json, re, sys, urllib.request
raw = _cc_urlopen("http://localhost:7777/api/v2/open-trades/intelligence", timeout=60).read().decode()
json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"bare {x}")))  # strict: no NaN/Inf
d = json.loads(raw); d = d.get("data", d)
rows = d["positions"]; s = d["summary"]; exc = d.get("excluded_items", [])
from collections import Counter
checks = {
    "AXTI not a position": not any(r["symbol"] == "AXTI" for r in rows),
    "AXTI excluded not_in_current_holdings": any(e.get("symbol") == "AXTI" and e["reason"] == "not_in_current_holdings" for e in exc),
    "no zero-share cards": not any(not r.get("shares") or float(r.get("shares") or 0) <= 0 for r in rows),
    "no numeric CUSIP cards": not any(re.fullmatch(r"\d{6,12}", str(r["symbol"])) for r in rows),
    "no duplicate account+symbol": len([k for k, v in Counter((r["account"], r["symbol"]) for r in rows).items() if v > 1]) == 0,
    "alpaca paper positions present": any(r["broker"] == "alpaca" for r in rows),
    "count reflects holdings (not 152)": 20 <= s["total_positions"] <= 80,
    "source_of_truth set": s.get("source_of_truth") == "current_holdings_plus_paper_positions",
}
ok = all(checks.values())
for k, v in checks.items():
    print(f"  [{'PASS' if v else 'FAIL'}] {k}")
print(f"total={s['total_positions']} excluded_stale={s['excluded_stale_trade_rows']} -> {'GREEN' if ok else 'FAILED'}")
sys.exit(0 if ok else 1)
