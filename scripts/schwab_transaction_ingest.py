#!/usr/bin/env python3
"""schwab_transaction_ingest.py — reconcile live Schwab transaction history into the real-account ledger
(trade_transactions). The Schwab API is the authoritative source.

  • Pulls TRADE + DIVIDEND_OR_INTEREST (dividends/interest/fees) for every linked account (~11mo, API max).
  • Aggregates TRADE *fills* by order → one ledger row per order (matches CSV per-order granularity), with
    summed qty, share-weighted avg price, summed fees, summed net amount.
  • dedupe_key = "date|action|symbol|qty|account" (same format the CSV import uses).
  • Reconcile policy: API OVERWRITES an existing row on any price/qty/fee/amount diff (and logs the diff);
    inserts what's missing; older pre-API-window CSV rows are left untouched.
  • READ-ONLY against Schwab (no trading writes). DB writes only to trade_transactions. Default DRY-RUN.

  python3 scripts/schwab_transaction_ingest.py [--apply] [--days 400]
"""
from __future__ import annotations
import argparse, collections, datetime, json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
# Load .env so SCHWAB_APP_KEY/SECRET are present when run from cron (bare subprocess, minimal env).
# Without this the Schwab transport returns NOT_PROVEN and the nightly ingest silently pulled ZERO
# rows — the journal had no Schwab trades for weeks. 2026-06-15.
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass
ACCOUNTS = ["schwab_taxable", "schwab_roth_ira", "schwab_rollover_ira"]


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _emit_health_alert(report):
    """MONITOR: fire an urgent data_integrity alert (→ SIEM + Telegram) if Schwab auth failed — the
    silent NOT_PROVEN bug that zeroed the journal trade-sync for weeks — or a weekday ingest came back
    empty with every account erroring. This is the watchdog for the failure that previously went unseen."""
    try:
        errs = {ak: a.get("error") for ak, a in report.get("accounts", {}).items() if a.get("error")}
        not_proven = any("NOT_PROVEN" in str(e).upper() or "ABSENT" in str(e).upper() for e in errs.values())
        auth_fail = False
        try:
            import schwab_token_manager as tm
            auth_fail = any(tm.is_auth_failure(str(e)) for e in errs.values())
        except Exception:
            pass
        weekday = datetime.datetime.now().weekday() < 5
        empty_all = weekday and report.get("rows_total", 0) == 0 and len(errs) >= len(ACCOUNTS)
        if not (not_proven or empty_all or auth_fail):
            return
        from alert_event_writer import save_alert_event
        if auth_fail:
            msg = f"[schwab-ingest] Schwab OAuth/refresh failure — re-auth likely required; errors={errs}"
        elif not_proven:
            msg = ("[schwab-ingest] AUTH FAILED — Schwab transport NOT_PROVEN (SCHWAB_APP_KEY/SECRET not loaded); "
                   "the journal trade-sync would pull ZERO rows")
        else:
            msg = f"[schwab-ingest] empty weekday ingest — 0 rows, {len(errs)} account error(s)"
        save_alert_event(alert_type="data_integrity", severity="urgent",
                         source_script="schwab_transaction_ingest.py", symbol=None, raw_text=msg,
                         parsed_payload={"kind": "schwab_ingest_health", "errors": errs,
                                         "rows_total": report.get("rows_total", 0)})
        print(f"  [monitor] ALERT emitted: {msg}")
    except Exception:
        pass


def _security_leg(txn):
    for i in txn.get("transferItems", []):
        if (i.get("instrument") or {}).get("assetType") not in (None, "CURRENCY") and not i.get("feeType"):
            return i
    return None


def _fees(txn):
    return round(sum(abs(i.get("cost", 0) or 0) for i in txn.get("transferItems", []) if i.get("feeType")), 2)


def _row(date, action, sym, qty, price, amount, fees, desc, account, uid, ttime=None):
    return {"trade_date": date, "action": action, "symbol": sym, "quantity": round(qty, 6), "price": price,
            "amount": round(amount, 2), "fees": fees, "description": desc[:120], "account": account, "uid": uid,
            "trade_time": ttime}


def _sec(x):
    leg = _security_leg(x)
    return (leg["instrument"].get("symbol") if leg else None) or "CASH", (abs(leg.get("amount", 0) or 0) if leg else 0)


def _sec_out(x) -> bool:
    """True when the security leg LEAVES the account. Schwab signs the leg amount (+ in, - out); `_sec` keeps
    the magnitude only, so before 2026-10-06 every RECEIVE_AND_DELIVER / share JOURNAL row read as an inflow
    (rollover IRA: 8 of 21 transfers Jul-Oct 2025 were outflows) and lots rebuilt from the ledger over-counted
    (SCHG 12,000 vs the broker's 2,000)."""
    leg = _security_leg(x)
    return bool(leg) and (leg.get("amount") or 0) < 0


def _map_rows(account_key, txns):
    """Map raw Schwab txns → ledger rows. TRADE fills aggregated per order; everything else one row each,
    preserving sub-types (qualified dividend, interest, transfers). SMA_ADJUSTMENT skipped (margin accounting)."""
    orders = collections.defaultdict(list)
    rows = []
    for x in txns:
        typ = x.get("type")
        date = (x.get("tradeDate") or x.get("time") or "")[:10]
        net = round(x.get("netAmount", 0) or 0, 2)
        uid = f"act:{x.get('activityId')}"
        desc = (x.get("description") or "")
        if typ == "TRADE":
            leg = _security_leg(x)
            if not leg:
                continue
            # net-$0 TRADE = shares moved WITHOUT cash (in-kind transfer / re-registration disguised as a
            # trade) — NOT a discretionary buy/sell. Label it a transfer so the round-trip builder skips it
            # (else a transferred-in position's later liquidation looks like a losing "swing trade").
            if abs(net) < 1.0:
                amt = leg.get("amount", 0) or 0
                rows.append(_row(date, "Transfer In" if amt > 0 else "Transfer Out",
                                 (leg["instrument"] or {}).get("symbol", ""), abs(amt), 0.0, net, 0.0,
                                 desc or "in-kind transfer", account_key, uid, x.get("time")))
                continue
            # Fills of one ORDER are aggregated. A fill with no orderId (dividend reinvestment) is its own
            # event: keyed by its activityId. Before 2026-10-06 they all shared the key (None, symbol), so a
            # year of V reinvestments became ONE 5.107-share "buy" dated at the first one.
            oid = x.get("orderId") or f"act{x.get('activityId')}"
            orders[(oid, (leg["instrument"] or {}).get("symbol"))].append((x, leg))
        elif typ == "DIVIDEND_OR_INTEREST":
            up = desc.upper()
            if "INTEREST" in up:
                action = "Bank Interest" if "BANK" in up else "Interest"
            elif x.get("qualifiedDividend"):
                action = "Qualified Dividend"
            else:
                action = "Dividend"
            sym, _ = _sec(x)
            rows.append(_row(date, action, sym, 0.0, 0.0, net, _fees(x), desc, account_key, uid, x.get("time")))
        elif typ == "JOURNAL":
            up = desc.upper()
            if any(k in up for k in ("SWEEP", "TRF FDS", "TRF FUNDS", "TYPE 1", "TYPE 2")):
                continue  # internal cash sweep / margin type reclassification — noise, not a real transfer
            sym, qty = _sec(x)
            action = "Journal" if sym == "CASH" else ("Journaled Shares Out" if _sec_out(x) else "Journaled Shares")
            rows.append(_row(date, action, sym, qty, 0.0, net, 0.0, desc, account_key, uid, x.get("time")))
        elif typ == "RECEIVE_AND_DELIVER":
            sym, qty = _sec(x)
            rows.append(_row(date, "Security Transfer Out" if _sec_out(x) else "Security Transfer", sym, qty, 0.0,
                             net, 0.0, desc, account_key, uid, x.get("time")))
        elif typ == "CASH_RECEIPT":
            rows.append(_row(date, "Cash Receipt", "CASH", 0.0, 0.0, net, 0.0, desc, account_key, uid, x.get("time")))
        # SMA_ADJUSTMENT intentionally skipped (internal margin accounting; not a cash/trade event)
    # aggregate trade fills per (order, symbol)
    for (oid, sym), fills in orders.items():
        qty = sum(abs(leg.get("amount", 0) or 0) for _, leg in fills)
        if qty == 0:
            continue
        signed = sum((leg.get("amount", 0) or 0) for _, leg in fills)
        action = "Sell" if signed < 0 else "Buy"
        gross = sum((leg.get("amount", 0) or 0) * (leg.get("price", 0) or 0) for _, leg in fills)
        wprice = round(abs(gross) / qty, 4) if qty else 0
        fees = round(sum(_fees(x) for x, _ in fills), 2)
        amount = round(sum(x.get("netAmount", 0) or 0 for x, _ in fills), 2)
        ttime = min((x.get("time") or x.get("tradeDate") or "") for x, _ in fills)
        date = (fills[0][0].get("tradeDate") or fills[0][0].get("time") or "")[:10]
        rows.append({"trade_date": date, "action": action, "symbol": sym, "quantity": round(qty, 6),
                     "price": wprice, "amount": amount, "fees": fees,
                     "description": (f"order {oid}" if not str(oid).startswith("act") else "reinvestment"),
                     "account": account_key,
                     "uid": (f"ord:{oid}" if not str(oid).startswith("act") else f"act:{oid[3:]}"),
                     "trade_time": ttime})
    return rows


def _dedupe_key(r):
    # order-distinct: include the Schwab order/activity id so slippage fills (same date/symbol/qty/side at
    # different prices) are preserved as separate ledger rows, not collapsed like the lossy CSV did.
    return f"{r['trade_date']}|{r['action']}|{r['symbol']}|{r['quantity']:.3f}|{r['account']}|{r['uid']}"


MAX_WINDOW_DAYS = 360   # Schwab refuses a transactions request spanning more than a year


def _fetch_chunked(client, h, start, end):
    """Transactions for [start, end] in windows the API accepts, oldest first. A non-list answer for any window
    is returned as-is so the caller reports it exactly as before (no partial history passes as complete)."""
    out, lo = [], start
    while lo < end:
        hi = min(end, lo + datetime.timedelta(days=MAX_WINDOW_DAYS))
        part = client.get_transactions(h, start_date=lo, end_date=hi).json()
        if not isinstance(part, list):
            return part
        out.extend(part)
        lo = hi
    seen, uniq = set(), []
    for x in out:                       # a transaction on a window boundary can come back twice
        k = x.get("activityId") or id(x)
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq


def run(apply=False, days=365):
    """Replace-in-window: the API is authoritative + complete (per-order, incl. slippage fills). Delete the
    Schwab ledger rows the API window covers and reload from the API; older pre-window CSV is kept."""
    import schwab_transport as t
    conn = _conn(); cur = conn.cursor()
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=days)
    report = {"accounts": {}, "rows_total": 0, "by_type": {}}
    all_rows = []
    for ak in ACCOUNTS:
        client, err = t.build_client(ak)
        h = t._get_hash(ak)
        if err or not h:
            report["accounts"][ak] = {"error": err or "no hash"}
            try:
                import schwab_token_manager as tm
                if tm.is_auth_failure(str(err or "")):
                    tm.record_auth_failure(str(err), account_key=ak, source="schwab_transaction_ingest:build_client")
            except Exception:
                pass
            continue
        try:
            txns = _fetch_chunked(client, h, start, now)
        except Exception as e:
            err = str(e)
            try:
                import schwab_token_manager as tm
                if tm.is_auth_failure(err):
                    tm.record_auth_failure(err, account_key=ak, source="schwab_transaction_ingest:get_transactions")
            except Exception:
                pass
            report["accounts"][ak] = {"error": err[:120]}; continue
        if not isinstance(txns, list):
            detail = f"non-list response: {str(txns)[:120]}"
            try:
                import schwab_token_manager as tm
                if tm.is_auth_failure(str(txns)):
                    tm.record_auth_failure(str(txns), account_key=ak, source="schwab_transaction_ingest:response")
            except Exception:
                pass
            report["accounts"][ak] = {"error": detail}; continue
        rows = _map_rows(ak, txns)
        all_rows.extend(rows)
        report["accounts"][ak] = {"mapped": len(rows), "by_action": dict(collections.Counter(r["action"] for r in rows))}
    if not all_rows:
        report["mode"] = "no rows"
        if apply:   # a manual dry run must not page the operator (false alarm 2026-10-06)
            _emit_health_alert(report)
        print(json.dumps(report, indent=2, default=str)); return report
    # Replace-in-window PER ACCOUNT that answered, from that account's own earliest returned date. Before
    # 2026-10-06 the delete covered ALL accounts from one global start, so an account whose read failed lost its
    # rows in the window until the next good run (and older pre-API rows of one account could be deleted by
    # another account's earlier window).
    windows = {}
    for r in all_rows:
        windows[r["account"]] = min(windows.get(r["account"], r["trade_date"]), r["trade_date"])
    window_start = min(windows.values())
    report["window_start"] = window_start
    report["windows"] = windows
    existing = 0
    for ak, ws in windows.items():
        cur.execute("""SELECT count(*) FROM trade_transactions WHERE account = %s AND trade_date >= %s""", (ak, ws))
        existing += cur.fetchone()[0]
    report["existing_in_window"] = existing
    report["rows_total"] = len(all_rows)
    if apply:
        deleted = 0
        for ak, ws in windows.items():
            cur.execute("""DELETE FROM trade_transactions WHERE account = %s AND trade_date >= %s""", (ak, ws))
            deleted += cur.rowcount
        report["deleted"] = deleted
        for r in all_rows:
            cur.execute("""INSERT INTO trade_transactions
                             (trade_date, action, symbol, quantity, price, amount, fees, description,
                              account, import_source, dedupe_key, trade_time)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'schwab_api',%s,%s)
                           ON CONFLICT (dedupe_key) DO UPDATE SET price=EXCLUDED.price, quantity=EXCLUDED.quantity,
                             amount=EXCLUDED.amount, fees=EXCLUDED.fees, description=EXCLUDED.description,
                             trade_time=EXCLUDED.trade_time""",
                        (r["trade_date"], r["action"], r["symbol"], r["quantity"], r["price"], r["amount"],
                         r["fees"], r["description"], r["account"], _dedupe_key(r), r.get("trade_time")))
        report["inserted"] = len(all_rows)
        conn.commit()
    report["mode"] = "APPLIED" if apply else "DRY-RUN (no writes)"
    if apply:
        _emit_health_alert(report)
    print(json.dumps(report, indent=2, default=str))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=365)
    a = ap.parse_args()
    run(apply=a.apply, days=a.days)


if __name__ == "__main__":
    main()
