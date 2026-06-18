#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from datetime import date
from pathlib import Path

ACCOUNT_MAP = {
    "fidelity": "fidelity_rollover_ira",
    "rollover": "schwab_rollover_ira",
    "roth": "schwab_roth",
    "taxable": "schwab_taxable",
}

def choose_anchor(holdings):
    candidates = [h for h in holdings if not h.get("is_loan") and not h.get("is_cash")]
    if not candidates:
        return None
    proprietary = [h for h in candidates if "-" in str(h.get("symbol", ""))]
    if proprietary:
        contra = [h for h in proprietary if "CONTRA" in str(h.get("symbol", "")).upper() or "CONTRA" in str(h.get("name", "")).upper()]
        if contra:
            return max(contra, key=lambda x: x.get("market_value", 0) or 0)
        return max(proprietary, key=lambda x: x.get("market_value", 0) or 0)
    return max(candidates, key=lambda x: x.get("market_value", 0) or 0)

def repair_account(data, acct_key, reported_total, as_of):
    acct = data["account_summaries"].setdefault(acct_key, {})
    holdings = [h for h in data.get("holdings", []) if h.get("account") == acct_key and not h.get("is_loan")]
    derived_total = round(sum(h.get("market_value", 0) or 0 for h in holdings), 2)
    drift = round(reported_total - derived_total, 2)
    acct["reported_total_value"] = round(reported_total, 2)
    acct["reported_total_as_of"] = as_of
    acct["total_value"] = round(reported_total, 2)

    print(f"[reconcile] {acct_key}: derived ${derived_total:,.2f} vs broker ${reported_total:,.2f} → drift ${drift:+,.2f}")
    if abs(drift) >= 0.01:
        anchor = choose_anchor(holdings)
        if anchor:
            before = round(anchor.get("market_value", 0) or 0, 2)
            anchor["market_value"] = round(before + drift, 2)
            shares = float(anchor.get("shares") or 0)
            if shares > 0 and not anchor.get("is_cash"):
                anchor["price"] = round(anchor["market_value"] / shares, 6)
            print(f"[reconcile]   anchor={anchor.get('symbol')} before=${before:,.2f} after=${anchor['market_value']:,.2f}")
        else:
            print("[reconcile]   WARNING: no anchor holding found; account summary updated, holdings unchanged.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--fidelity", type=float)
    ap.add_argument("--rollover", type=float)
    ap.add_argument("--roth", type=float)
    ap.add_argument("--taxable", type=float)
    ap.add_argument("--as-of", default=date.today().isoformat())
    args = ap.parse_args()

    hp = Path(args.project_root) / "data" / "portfolios" / "state" / "holdings.json"
    data = json.loads(hp.read_text(encoding="utf-8"))

    for arg_name, acct_key in ACCOUNT_MAP.items():
        value = getattr(args, arg_name)
        if value is not None:
            repair_account(data, acct_key, float(value), args.as_of)

    pt = data.setdefault("portfolio_totals", {})
    total = round(sum((v.get("total_value") or 0) for v in data.get("account_summaries", {}).values()), 2)
    day = round(sum((v.get("day_change") or 0) for v in data.get("account_summaries", {}).values()), 2)
    pt["total_value"] = total
    pt["day_change"] = day
    pt["day_change_pct"] = round((day / (total - day) * 100) if (total - day) else 0, 4)
    pt["as_of"] = args.as_of

    hp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"[reconcile] Wrote {hp}")
    print(f"[reconcile] Portfolio total now ${total:,.2f} | day ${day:+,.2f}")

if __name__ == "__main__":
    main()
