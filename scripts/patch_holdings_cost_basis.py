#!/usr/bin/env python3
"""patch_holdings_cost_basis.py — recompute holdings.json cost basis (and current shares) from the
LATEST Schwab transaction CSVs + Fidelity Positions PDF basis + explicit owner transfer-basis overrides,
and regenerate the income/dividend ledger.

- Latest-file discovery per account (no hardcoded dates).
- Schwab: avg cost from summed actual buy Amounts (schwab_reconstructor); transfer-in shares get basis
  only from explicit overrides (cost_basis_overrides.json), else flagged partial / needs_transfer_mapping.
- Fidelity: per-share basis from fidelity_cost_basis.json (Positions PDF).
- Income ledger: dividends/interest/cap-gains recorded separately (never as security basis).
- Backs up holdings.json. Never fabricates basis. No broker/order writes.
"""
import sys, os, json, csv, glob, shutil, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schwab_reconstructor import reconstruct_schwab_positions

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data/portfolios/state")
INP = os.path.join(ROOT, "data/portfolios/input")
HJ = os.path.join(STATE, "holdings.json")

ACCT_PATTERN = {
    "schwab_rollover_ira": "Rollover_IRA_XXX258_Transactions_*.csv",
    "schwab_taxable": "Individual_XXX469_Transactions_*.csv",
    "schwab_roth_ira": "Roth_Contributory_IRA_XXX415_Transactions_*.csv",
}
INCOME_ACTIONS = {"Cash Dividend", "Qualified Dividend", "Special Dividend", "Reinvest Dividend",
                  "Qual Div Reinvest", "Long Term Cap Gain Reinvest", "Bank Interest", "Credit Interest"}


def _norm(a):
    return (a or "").lower().replace("_ira", "")


def _ts_in_name(fn):
    m = re.search(r"Transactions_(\d{8}-\d{6})", os.path.basename(fn))
    return m.group(1) if m else "0"


def latest_csv_for_account(input_dir, account_key):
    files = glob.glob(os.path.join(input_dir, ACCT_PATTERN[account_key]))
    return max(files, key=lambda f: (_ts_in_name(f), os.path.getmtime(f))) if files else None


def _amt(s):
    s = (s or "").strip()
    if not s:
        return 0.0
    v = float(re.sub(r"[^\d.]", "", s) or 0)
    return -v if s.startswith("-") else v


def build_income_ledger(selected):
    accounts, grand = {}, 0.0
    for acct, path in selected.items():
        by_action, by_symbol, tot = {}, {}, 0.0
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                act = (r.get("Action") or "").strip()
                if act not in INCOME_ACTIONS:
                    continue
                amt = _amt(r.get("Amount"))
                if amt <= 0:
                    continue
                sym = (r.get("Symbol") or "").strip() or "(account)"
                by_action[act] = round(by_action.get(act, 0) + amt, 2)
                by_symbol[sym] = round(by_symbol.get(sym, 0) + amt, 2)
                tot += amt
        accounts[acct] = {"income_total": round(tot, 2), "source_file": os.path.basename(path),
                          "by_action": by_action, "by_symbol": by_symbol}
        grand += tot
    return {"sources": [os.path.basename(p) for p in selected.values()],
            "accounts": accounts, "grand_total_income": round(grand, 2)}


def main():
    shutil.copy(HJ, HJ + ".bak_costbasis")
    d = json.load(open(HJ))
    ov_doc = json.load(open(os.path.join(INP, "cost_basis_overrides.json")))
    overrides = {(_norm(o["account"]), o["symbol"]): o["per_share_basis"] for o in ov_doc.get("overrides", [])}
    override_sources = {(_norm(o["account"]), o["symbol"]): o.get("source", "operator_provided")
                        for o in ov_doc.get("overrides", [])}
    candidates = {(_norm(c["account"]), c["symbol"]) for c in ov_doc.get("candidate_mappings_needing_confirmation", [])}
    fid_ps = {k: v for k, v in json.load(open(os.path.join(INP, "fidelity_cost_basis.json"))).items() if not k.startswith("_")}

    selected, recon = {}, {}
    for acct in ACCT_PATTERN:
        p = latest_csv_for_account(INP, acct)
        if not p:
            continue
        selected[acct] = p
        per_acct_ov = {sym: ps for (na, sym), ps in overrides.items() if na == _norm(acct)}
        for h in reconstruct_schwab_positions(p, acct, acct, "ira", {}, set(), per_acct_ov)[0]:
            recon[(_norm(acct), h["symbol"])] = h

    applied = nulled = updated_shares = 0
    for h in d.get("holdings", []):
        acct, sym, shx = h.get("account"), h.get("symbol"), (h.get("shares") or 0)
        if h.get("is_cash"):
            continue
        if (acct or "").startswith("schwab"):
            r = recon.get((_norm(acct), sym))
            if not r or (r["shares"] or 0) <= 0.001:
                continue
            new_sh = round(r["shares"], 6)
            if abs(new_sh - shx) > 0.0005:
                h["shares"] = new_sh
                updated_shares += 1
            px = h.get("price") or 0
            mv = round(new_sh * px, 2) if px else (h.get("market_value") or 0)
            h["market_value"] = mv
            cb = r.get("cost_basis")
            if cb is not None:
                h["cost_basis"] = round(cb, 2)
                h["gain_loss"] = round(mv - cb, 2)
                h["gain_loss_pct"] = round((mv - cb) / cb * 100, 4) if cb > 0 else None
                h["basis_partial"] = False
                if (_norm(acct), sym) in overrides:
                    h["cost_basis_source"] = override_sources.get((_norm(acct), sym), "operator_provided")
                else:
                    h["cost_basis_source"] = "reconstructed_from_amounts"
                applied += 1
            else:
                h["cost_basis"] = None
                h["gain_loss"] = None
                h["gain_loss_pct"] = None
                h["basis_partial"] = True
                h["cost_basis_source"] = "basis_needs_transfer_mapping" if (_norm(acct), sym) in candidates else "partial_transfer_in"
                nulled += 1
        elif sym in fid_ps:
            mv = h.get("market_value") or 0
            cb = round(fid_ps[sym] * shx, 2)
            h["cost_basis"] = cb
            h["gain_loss"] = round(mv - cb, 2)
            h["gain_loss_pct"] = round((mv - cb) / cb * 100, 4) if cb > 0 else None
            h["basis_partial"] = False
            h["cost_basis_source"] = "fidelity_positions_pdf"
            applied += 1

    tot_val = round(sum(h.get("market_value") or 0 for h in d["holdings"]), 2)
    tot_cb = round(sum(h.get("cost_basis") or 0 for h in d["holdings"] if h.get("cost_basis")), 2)
    d.setdefault("portfolio_totals", {})["total_value"] = tot_val
    d["portfolio_totals"]["total_cost_basis"] = tot_cb
    # MANDATORY wipe-guard. protect_basis=False: this script LEGITIMATELY rewrites cost basis.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from holdings_guard import protected_holdings_write
    protected_holdings_write(d, source="patch_holdings_cost_basis", protect_basis=False, target_path=HJ)

    ledger = build_income_ledger(selected)
    json.dump(ledger, open(os.path.join(STATE, "income_ledger.json"), "w"), indent=2)

    print(f"[patch] sources: {[os.path.basename(p) for p in selected.values()]}")
    print(f"[patch] applied={applied} nulled={nulled} updated_shares={updated_shares}")
    print(f"[patch] total_value=${tot_val:,.0f} total_cost_basis=${tot_cb:,.0f}")
    print(f"[patch] income grand_total=${ledger['grand_total_income']:,.2f} | " +
          " ".join(f"{a}=${v['income_total']:,.2f}" for a, v in ledger["accounts"].items()))


if __name__ == "__main__":
    main()
