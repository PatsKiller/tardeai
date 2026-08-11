#!/usr/bin/env python3
"""Production lot rebuild: tax_lots.json from broker trade_transactions.

Promotes the S6 one-shot (_s6_rebuild_lots.py) into a scheduled, reportable job.

Rules:
  - Rebuild open lots for every non-CASH holding from Buy/Sell transactions (FIFO).
  - VERIFIED when reconstructed net shares within 5% of holdings shares.
  - UNTRUSTED when mismatch >5% — still written with status tag; desk must suppress
    long_held signals when lot_data_status is UNTRUSTED.
  - NO_TXN_DATA when no buys exist — do not invent lots.
  - Never touches broker credentials; read-only DB + local JSON.

Usage:
  .venv/bin/python scripts/rebuild_tax_lots_from_transactions.py
  .venv/bin/python scripts/rebuild_tax_lots_from_transactions.py --dry-run
  .venv/bin/python scripts/rebuild_tax_lots_from_transactions.py --json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
LOTS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "tax_lots.json"
REPORT_PATH = PROJECT_ROOT / "data" / "runtime" / "tax_lots_rebuild_latest.json"
BACKUP_DIR = PROJECT_ROOT / "data" / "portfolios" / "state" / "backups"

SHARE_MATCH_TOLERANCE = 0.05  # 5%


def _norm_sym(s: str) -> str:
    return (s or "").strip().upper()


def rebuild(*, dry_run: bool = False) -> dict:
    from db_adapter import _execute

    if not HOLDINGS_PATH.exists():
        return {"ok": False, "error": f"missing holdings: {HOLDINGS_PATH}"}
    if not LOTS_PATH.exists():
        return {"ok": False, "error": f"missing tax_lots: {LOTS_PATH}"}

    holdings = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    lots_raw = json.loads(LOTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(lots_raw, dict):
        lots_raw = {}

    holdings_total: dict[str, float] = defaultdict(float)
    positions = holdings.get("holdings") or holdings.get("positions") or []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        s = _norm_sym(str(pos.get("symbol") or ""))
        if not s or s == "CASH":
            continue
        holdings_total[s] += float(pos.get("shares") or 0)

    sym_list = sorted(holdings_total.keys())
    if not sym_list:
        return {"ok": False, "error": "no holdings symbols"}

    all_txns = _execute(
        """SELECT upper(symbol) AS sym, trade_date, action, quantity, price,
                  amount, account, dedupe_key
           FROM trade_transactions
           WHERE upper(symbol)=ANY(%s) AND action IN ('Buy','Sell')
           ORDER BY trade_date, dedupe_key""",
        (sym_list,),
        fetch="all",
    ) or []

    txn_by_sym: dict[str, list] = defaultdict(list)
    for t in all_txns:
        txn_by_sym[str(t["sym"])].append(t)

    # Drop prior keys for current holdings symbols (preserve non-holding history)
    for k in list(lots_raw.keys()):
        base = _norm_sym(str(k).split(":")[0])
        if base in holdings_total:
            del lots_raw[k]

    rebuilt = untrusted = no_data = 0
    results: list[dict] = []

    for sym in sym_list:
        h_shares = float(holdings_total[sym])
        txns = txn_by_sym.get(sym, [])
        buys = [t for t in txns if t.get("action") == "Buy"]
        sells = [t for t in txns if t.get("action") == "Sell"]

        if not buys:
            results.append({
                "symbol": sym,
                "holding_shares": h_shares,
                "lot_net_shares": 0.0,
                "lots": 0,
                "status": "NO_TXN_DATA",
            })
            no_data += 1
            continue

        seen: set[str] = set()
        new_lots: list[dict] = []
        for t in buys:
            dk = str(t.get("dedupe_key") or "")
            if dk and dk in seen:
                continue
            if dk:
                seen.add(dk)
            qty = float(t["quantity"])
            price = float(t["price"])
            amt = abs(float(t.get("amount") or (qty * price)))
            date = str(t["trade_date"])[:10]
            acct = str(t.get("account") or "")
            new_lots.append({
                "lot_date": date,
                "shares": qty,
                "shares_remaining": qty,
                "cost_per_share": price,
                "total_cost": amt,
                "action": "Buy",
                "closed": False,
                "account": acct,
                "source": "trade_transactions_reconstructed",
            })

        sold_total = sum(float(t["quantity"]) for t in sells)
        for lot in new_lots:
            if sold_total <= 0:
                break
            qty = float(lot["shares_remaining"])
            if qty <= sold_total:
                lot["shares_remaining"] = 0
                lot["closed"] = True
                sold_total -= qty
            else:
                lot["shares_remaining"] = qty - sold_total
                sold_total = 0

        net_shares = sum(float(l["shares_remaining"]) for l in new_lots)
        ratio = (net_shares / h_shares) if h_shares > 0 else 0.0
        basis_prices = [
            float(l["cost_per_share"])
            for l in new_lots
            if float(l["shares_remaining"]) > 0
        ]
        if h_shares > 0 and abs(ratio - 1.0) <= SHARE_MATCH_TOLERANCE:
            status = "VERIFIED"
            rebuilt += 1
        else:
            status = "UNTRUSTED"
            untrusted += 1

        # Distribute open lots to per-account holding keys (proportional)
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            if _norm_sym(str(pos.get("symbol") or "")) != sym:
                continue
            acct = str(pos.get("account") or "")
            key = f"{sym}:{acct}"
            lots_raw.setdefault(key, [])
            pos_shares = float(pos.get("shares") or 0)
            acct_share = (pos_shares / h_shares) if h_shares > 0 else 0.0
            for l in new_lots:
                if float(l["shares_remaining"]) <= 0:
                    continue
                lot_copy = dict(l)
                lot_copy["shares"] = round(float(l["shares"]) * acct_share, 6)
                lot_copy["shares_remaining"] = round(
                    float(l["shares_remaining"]) * acct_share, 6
                )
                lot_copy["rebuild_status"] = status
                lots_raw[key].append(lot_copy)

        results.append({
            "symbol": sym,
            "holding_shares": round(h_shares, 4),
            "lot_net_shares": round(net_shares, 4),
            "lots": len([l for l in new_lots if float(l["shares_remaining"]) > 0]),
            "basis_lo": min(basis_prices) if basis_prices else None,
            "basis_hi": max(basis_prices) if basis_prices else None,
            "status": status,
            "ratio": round(ratio, 4),
        })

    report = {
        "ok": True,
        "dry_run": dry_run,
        "rebuilt_at": datetime.now(timezone.utc).isoformat(),
        "verified": rebuilt,
        "untrusted": untrusted,
        "no_txn_data": no_data,
        "symbols": len(sym_list),
        "tolerance": SHARE_MATCH_TOLERANCE,
        "results": sorted(results, key=lambda r: -float(r.get("holding_shares") or 0)),
        "untrusted_symbols": [r["symbol"] for r in results if r["status"] == "UNTRUSTED"],
        "no_txn_symbols": [r["symbol"] for r in results if r["status"] == "NO_TXN_DATA"],
    }

    if not dry_run:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = BACKUP_DIR / f"tax_lots.json.bak-{stamp}"
        shutil.copy2(LOTS_PATH, backup)
        LOTS_PATH.write_text(json.dumps(lots_raw, indent=2, default=str), encoding="utf-8")
        report["backup"] = str(backup)
        report["written"] = str(LOTS_PATH)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["report_path"] = str(REPORT_PATH)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Compute report only; do not write tax_lots.json")
    ap.add_argument("--json", action="store_true", help="Print full JSON report")
    args = ap.parse_args()
    report = rebuild(dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        if not report.get("ok"):
            print(f"FAIL: {report.get('error')}", file=sys.stderr)
            return 1
        print(
            f"tax_lots rebuild: VERIFIED={report['verified']} "
            f"UNTRUSTED={report['untrusted']} NO_TXN={report['no_txn_data']} "
            f"symbols={report['symbols']} dry_run={report['dry_run']}"
        )
        if report.get("untrusted_symbols"):
            print(f"  UNTRUSTED: {', '.join(report['untrusted_symbols'])}")
        if report.get("no_txn_symbols"):
            print(f"  NO_TXN_DATA: {', '.join(report['no_txn_symbols'])}")
        print(f"  report: {report.get('report_path')}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
