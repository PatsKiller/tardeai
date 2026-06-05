#!/usr/bin/env python3
"""Regression: /api/v2/open-trades/intelligence shows only true current positions (no stale phantoms).
Exits non-zero on any failure."""
import json, re, sys, urllib.request
raw = urllib.request.urlopen("http://localhost:7777/api/v2/open-trades/intelligence", timeout=60).read().decode()
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
