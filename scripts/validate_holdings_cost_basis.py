#!/usr/bin/env python3
"""validate_holdings_cost_basis.py — assert the June-5 cost-basis + income repair against known anchors.
Reads holdings.json + income_ledger.json + the /api/v2/open-trades/intelligence endpoint. Exits non-zero
on any failure. Read-only."""
import json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HJ = json.load(open(os.path.join(ROOT, "data/portfolios/state/holdings.json")))
LED = json.load(open(os.path.join(ROOT, "data/portfolios/state/income_ledger.json")))
H = {(h.get("account"), h.get("symbol")): h for h in HJ["holdings"]}
checks = []


def near(a, b, tol):
    return a is not None and abs(a - b) <= tol


def chk(name, ok, detail=""):
    checks.append((name, ok, detail))


def cb(acct, sym):
    return (H.get((acct, sym)) or {}).get("cost_basis")


# selected CSVs are June 5 (not April)
chk("sources are June 5 files", all("20260605" in s for s in LED["sources"]), str(LED["sources"]))
# SCHG rollover
chk("SCHG rollover basis = $52,379 ±1", near(cb("schwab_rollover_ira", "SCHG"), 52379, 1), str(cb("schwab_rollover_ira", "SCHG")))
schg = H.get(("schwab_rollover_ira", "SCHG")) or {}
chk("SCHG rollover avg = $30.8112 ±0.01", near((schg.get("cost_basis") or 0) / (schg.get("shares") or 1), 30.8112, 0.01))
# SCHD rollover
chk("SCHD rollover basis = $127,953.70 ±1", near(cb("schwab_rollover_ira", "SCHD"), 127953.70, 1), str(cb("schwab_rollover_ira", "SCHD")))
# V rollover (snapshot includes 06/01 reinvest → ~$45.34 avg)
vr = H.get(("schwab_rollover_ira", "V")) or {}
vavg = (vr.get("cost_basis") or 0) / (vr.get("shares") or 1)
chk("V rollover has basis (not None)", vr.get("cost_basis") is not None, str(vr.get("cost_basis")))
chk("V rollover avg ~ $44.76 or $45.34", near(vavg, 44.76, 0.2) or near(vavg, 45.34, 0.2), f"{vavg:.4f}")
chk("V rollover source operator_provided", vr.get("cost_basis_source") == "operator_provided")
# Roth V (~$5,677.10)
chk("Roth V basis ~ $5,677.10 ±2", near(cb("schwab_roth", "V") or cb("schwab_roth_ira", "V"), 5677.10, 2), str(cb("schwab_roth", "V")))
# income totals
chk("income grand total = $10,543.13 ±0.05", near(LED["grand_total_income"], 10543.13, 0.05), str(LED["grand_total_income"]))
acc = LED["accounts"]
chk("rollover income = $9,326.14", near(acc.get("schwab_rollover_ira", {}).get("income_total"), 9326.14, 0.05))
chk("taxable income = $1,095.40", near(acc.get("schwab_taxable", {}).get("income_total"), 1095.40, 0.05))
chk("roth income = $121.59", near(acc.get("schwab_roth_ira", {}).get("income_total"), 121.59, 0.05))
# FCNTX flagged (not fabricated)
fc = H.get(("schwab_rollover_ira", "FCNTX")) or {}
chk("FCNTX flagged needs_transfer_mapping (basis None)", fc.get("cost_basis") is None and fc.get("cost_basis_source") == "basis_needs_transfer_mapping", str(fc.get("cost_basis_source")))
# Open Trades JSON strict + no fabricated basis
try:
    raw = urllib.request.urlopen("http://localhost:7777/api/v2/open-trades/intelligence", timeout=60).read().decode()
    json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    chk("Open Trades JSON strict valid", True)
except Exception as e:
    chk("Open Trades JSON strict valid", False, str(e)[:60])

ok = all(c[1] for c in checks)
for n, o, dd in checks:
    print(f"  [{'PASS' if o else 'FAIL'}] {n}" + (f" — {dd}" if (not o and dd) else ""))
print(f"\n{sum(1 for c in checks if c[1])}/{len(checks)} PASS — {'GREEN' if ok else 'FAILED'}")
sys.exit(0 if ok else 1)
