#!/usr/bin/env python3
"""patch_holdings_cost_basis.py — recompute holdings.json cost basis from the corrected broker import.

Schwab: avg cost from schwab_reconstructor (sum of actual buy Amounts; transfers/share-mismatch → None).
Fidelity: per-share basis from data/portfolios/input/fidelity_cost_basis.json (Positions PDF).
Applies cost_basis only when reliable + share-consistent (≤2%); otherwise None (basis_partial). Backs up
holdings.json first. Read-only w.r.t. broker; mutates only cost_basis/gain_loss/gain_loss_pct/basis_* +
total_cost_basis in holdings.json.
"""
import json, os, sys, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schwab_reconstructor import reconstruct_schwab_positions

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HJ = os.path.join(ROOT, "data/portfolios/state/holdings.json")
INP = os.path.join(ROOT, "data/portfolios/input")
CSV = {"schwab_rollover_ira": "Rollover_IRA_XXX258_Transactions_20260408-094116.csv",
       "schwab_taxable": "Individual_XXX469_Transactions_20260408-093959.csv",
       "schwab_roth": "Roth_Contributory_IRA_XXX415_Transactions_20260408-094104.csv"}


def main():
    shutil.copy(HJ, HJ + ".bak_costbasis")
    d = json.load(open(HJ))
    recon = {}
    for acct, f in CSV.items():
        p = os.path.join(INP, f)
        if not os.path.exists(p):
            continue
        for h in reconstruct_schwab_positions(p, acct, acct, "ira", {}, set())[0]:
            cb, shx = h.get("cost_basis"), h["shares"]
            recon[(acct, h["symbol"])] = {"avg": (cb / shx if (cb and shx) else None), "sh": shx, "partial": h.get("basis_partial")}
    fid = {}
    fp = os.path.join(INP, "fidelity_cost_basis.json")
    if os.path.exists(fp):
        fid = {k: v for k, v in json.load(open(fp)).items() if not k.startswith("_")}
    applied = nulled = 0
    for h in d.get("holdings", []):
        acct, sym, shx = h.get("account"), h.get("symbol"), (h.get("shares") or 0)
        if h.get("is_cash"):
            continue
        avg, reason = None, None
        if (acct or "").startswith("schwab"):
            r = recon.get((acct, sym))
            if not r:
                continue
            if r["partial"] or r["avg"] is None:
                reason = "partial_transfer_in"
            elif r["sh"] and abs(r["sh"] - shx) / r["sh"] > 0.02:
                reason = "share_mismatch_incomplete"
            else:
                avg = r["avg"]
        elif sym in fid:
            avg = fid[sym]
        else:
            continue
        mv = h.get("market_value") or 0
        if avg and shx > 0:
            cb = round(avg * shx, 2)
            h.update({"cost_basis": cb, "gain_loss": round(mv - cb, 2),
                      "gain_loss_pct": round((mv - cb) / cb * 100, 4) if cb > 0 else None,
                      "basis_partial": False,
                      "cost_basis_source": "fidelity_positions_pdf" if sym in fid else "reconstructed_from_amounts"})
            applied += 1
        else:
            h.update({"cost_basis": None, "gain_loss": None, "gain_loss_pct": None,
                      "basis_partial": True, "cost_basis_source": reason or "unknown"})
            nulled += 1
    tcb = sum(h.get("cost_basis") or 0 for h in d["holdings"] if h.get("cost_basis"))
    d.setdefault("portfolio_totals", {})["total_cost_basis"] = round(tcb, 2)
    json.dump(d, open(HJ, "w"), indent=2, default=str)
    print(f"[patch] applied={applied} nulled={nulled} total_cost_basis=${tcb:,.0f}")


if __name__ == "__main__":
    main()
