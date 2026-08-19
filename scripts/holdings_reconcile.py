#!/usr/bin/env python3
"""holdings_reconcile.py — reconcile system holdings.json amounts against the operator's broker snapshot.

There is NO live Schwab/Fidelity API, so amounts are verified against data/portfolios/state/schwab_reference.json
(operator pastes a fresh Schwab positions export incl. external Fidelity 401k). Reports every share/price/value
mismatch. With --apply it corrects holdings.json for FEED-LESS instruments (funds/CITs that have no live
Yahoo/Finviz quote — Fidelity 401k pools, institutional trusts) to the broker-authoritative price, and fixes
share-count drift for any position; equities/ETFs keep their live repriced price (only share drift is fixed).

  python3 scripts/holdings_reconcile.py            # report only
  python3 scripts/holdings_reconcile.py --apply     # correct feed-less NAVs + share drift, recalc totals
"""
import os, sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HJ = ROOT / "data" / "portfolios" / "state" / "holdings.json"
REF = ROOT / "data" / "portfolios" / "state" / "schwab_reference.json"
FEEDLESS = {"fund", "cit"}          # no live market feed → broker is authoritative for price
PX_TOL, MV_TOL, Q_TOL = 1.5, 1.0, 0.01   # % price, % value, share tolerance


def main():
    apply = "--apply" in sys.argv
    refdoc = json.loads(REF.read_text())
    ref = refdoc["positions"]
    ref_cash = refdoc.get("cash", {})
    port = json.loads(HJ.read_text())
    # aggregate system holdings by symbol (multi-account)
    rows = {}
    for h in port["holdings"]:
        s = h["symbol"]; rows.setdefault(s, []).append(h)

    report = {"matched": 0, "price_outlier": [], "share_drift": [], "missing": [], "corrected": [], "feedless_fixed": []}
    for sym, r in ref.items():
        hs = rows.get(sym)
        if not hs:
            if (r.get("mv") or 0) > 0:
                report["missing"].append(sym)
            continue
        sys_q = sum(h.get("shares") or 0 for h in hs)
        sys_mv = sum(h.get("market_value") or 0 for h in hs)
        px = hs[0].get("price")
        qd = sys_q - r["q"]
        mvpct = (sys_mv - r["mv"]) / r["mv"] * 100 if r["mv"] else 0
        pxpct = (px - r["px"]) / r["px"] * 100 if (px and r.get("px")) else 0
        ok = True
        if abs(qd) > Q_TOL:
            report["share_drift"].append({"symbol": sym, "sys": round(sys_q, 4), "schwab": r["q"], "delta": round(qd, 4)}); ok = False
        if abs(pxpct) > PX_TOL:
            report["price_outlier"].append({"symbol": sym, "type": r.get("type"), "sys_px": px, "schwab_px": r["px"], "off_pct": round(pxpct, 1)}); ok = False
        if ok:
            report["matched"] += 1
        # ── corrections (apply) ──
        if apply:
            # 1) feed-less funds/CITs: snap price to broker (single-account assumed for these)
            if r.get("type") in FEEDLESS and abs(pxpct) > PX_TOL:
                for h in hs:
                    h["price"] = r["px"]
                    if h.get("shares") is not None:
                        h["market_value"] = round(h["shares"] * r["px"], 2)
                report["feedless_fixed"].append({"symbol": sym, "old_px": px, "new_px": r["px"]})
            # 2) share drift (any type): correct to broker shares on the primary lot
            if abs(qd) > Q_TOL and len(hs) == 1:
                hs[0]["shares"] = r["q"]
                hs[0]["market_value"] = round(r["q"] * (hs[0].get("price") or r["px"]), 2)
                report["corrected"].append({"symbol": sym, "field": "shares", "to": r["q"]})

    # ── cash reconciliation (by account) ──
    report["cash_fixed"] = []
    cash_rows = {h["account"]: h for h in port["holdings"] if h.get("is_cash") or h.get("symbol") == "CASH"}
    for acct, bal in ref_cash.items():
        cur = cash_rows.get(acct)
        cur_mv = (cur.get("market_value") if cur else 0) or 0
        if abs(cur_mv - bal) > 1.0:
            report["cash_fixed"].append({"account": acct, "sys": round(cur_mv, 2), "schwab": bal})
            if apply:
                if cur:
                    cur["market_value"] = bal; cur["shares"] = bal; cur["price"] = 1.0
                elif bal > 0:
                    port["holdings"].append({"symbol": "CASH", "account": acct, "asset_type": "cash",
                                             "is_cash": True, "shares": bal, "price": 1.0, "market_value": bal,
                                             "name": "Cash & Cash Investments", "source": "broker_reconcile"})

    if apply and (report["feedless_fixed"] or report["corrected"] or report["cash_fixed"]):
        # Stale broker snapshot (the June 2026 paste) must not rewrite August books.
        # Daily 16:10 --apply has been presenting ~$723k partial totals against a
        # ~$1.28M last-good — that is incomplete coverage, not a smaller portfolio.
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        from holdings_sanity import validate_payload
        last = json.loads(HJ.read_text())
        total = sum(h.get("market_value") or 0 for h in port["holdings"])
        port["portfolio_totals"]["total_value"] = round(total, 2)
        port["reconciled_at"] = json.loads(REF.read_text()).get("as_of")
        verdict = validate_payload(port, last)
        if not verdict.ok:
            print(json.dumps({
                "apply_blocked": True,
                "reason_code": verdict.reason_code,
                "reason": verdict.reason,
                "computed_total": total,
            }))
        else:
            from holdings_guard import protected_holdings_write  # MANDATORY wipe-guard
            protected_holdings_write(port, source="holdings_reconcile", target_path=str(HJ))

    # ── Follow-up A: outlier reconciliation — flag held EQUITY/ETF names whose live price diverges >1.5%
    # from the broker reference (the authoritative second source). Feed-less funds are snapped above, so
    # only live-feed names remain here (e.g. KBR/TDG = Finviz vs Schwab). Best-effort SIEM alert.
    live_outliers = [o for o in report["price_outlier"] if o.get("type") in ("equity", "etf")]
    if live_outliers:
        try:
            import psycopg2
            for ln in (ROOT / ".env").read_text().splitlines():
                if "=" in ln and not ln.strip().startswith("#"):
                    k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
            cc = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                                  dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                                  password=os.getenv("DB_PASSWORD")); ccur = cc.cursor()
            for o in live_outliers:
                txt = f"Price outlier: {o['symbol']} live {o['sys_px']} vs broker {o['schwab_px']} ({o['off_pct']:+}%) — verify feed"
                ccur.execute("""INSERT INTO alert_events (alert_uid, alert_type, symbol, severity, source_script,
                               raw_text, data_quality_status, requires_agent_review, created_at)
                               VALUES (%s,'data_integrity',%s,'warning','holdings_reconcile.py',%s,'valid',true,now())
                               ON CONFLICT (alert_uid) DO UPDATE SET raw_text=EXCLUDED.raw_text, created_at=now()""",
                             (f"price_outlier:{o['symbol']}:{__import__('datetime').date.today()}", o["symbol"], txt))
            cc.commit(); cc.close()
        except Exception as e:
            print(f"  [reconcile] outlier SIEM flag failed: {str(e)[:80]}")

    sys_total = sum(h.get("market_value") or 0 for h in port["holdings"])
    ref_total = json.loads(REF.read_text()).get("grand_total")
    out = {"matched": report["matched"], "price_outliers": report["price_outlier"],
           "share_drift": report["share_drift"], "missing": report["missing"],
           "feedless_fixed": report["feedless_fixed"] if apply else "(run --apply)",
           "share_corrected": report["corrected"] if apply else "(run --apply)",
           "cash_fixed": report["cash_fixed"],
           "system_total": round(sys_total, 2), "schwab_total": ref_total,
           "total_gap": round(sys_total - (ref_total or 0), 2)}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
