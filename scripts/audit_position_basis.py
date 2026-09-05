#!/usr/bin/env python3
"""audit_position_basis.py — cross-source position & cost-basis audit (READ-ONLY).

Triggered by the 2026-06-12 SCHG finding: holdings.json said avg $16.06 (+108%!) while Schwab's API
said avg $30.81 (+8%) for the same 1,700-share rollover position — the CSV-based reconstruction was
stale. This audits EVERY Schwab position across four sources:

  A. holdings.json            (CSV-reconstructed basis; what the Open Trades cards display)
  B. live Schwab API          (get_positions: qty + averagePrice — broker's own average cost)
  C. schwab_cost_basis_lots   (Positions-export CSV ingest; authoritative when present)
  D. trade_transactions       (in-window API fills; buy-amount sum for recently opened positions)

Flags: QTY_MISMATCH (A vs B shares differ >0.5%), BASIS_DIVERGENT (A vs B avg differs >2% AND >$50
total), MISSING (in one side only). No writes anywhere — pure report.

  python3 scripts/audit_position_basis.py [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="send Telegram alert when discrepancies found")
    args = ap.parse_args()

    import schwab_transport as st
    from db_adapter import _get_conn
    cur = _get_conn().cursor()

    # A. holdings.json
    h = json.load(open(PROJECT_ROOT / "data/portfolios/state/holdings.json"))
    H = {}
    for x in h.get("holdings", []):
        acct = (x.get("account") or "")
        if not acct.startswith("schwab"):
            continue
        if x.get("is_cash") or (x.get("symbol") or "").upper() == "CASH":
            continue
        key = (acct.replace("schwab_roth", "schwab_roth_ira").replace("schwab_roth_ira_ira", "schwab_roth_ira"),
               (x.get("symbol") or "").upper())
        H[key] = {"qty": float(x.get("shares") or x.get("quantity") or 0),
                  "basis": float(x.get("cost_basis") or 0),
                  "src": x.get("cost_basis_source"), "partial": bool(x.get("basis_partial"))}

    # B. live API (direct transport; falls back to the running server's accounts-live endpoint when
    #    this shell has no Schwab creds — the server process holds them)
    cur.execute("SELECT account_key FROM broker_accounts WHERE broker ILIKE '%schwab%' ORDER BY 1")
    accounts = [r[0] for r in cur.fetchall()]
    A = {}
    api_errors = {}
    for ak in accounts:
        pos = st.get_positions(ak)
        if isinstance(pos, dict):
            api_errors[ak] = pos.get("status")
            continue
        for p in pos:
            A[(ak, p["symbol"].upper())] = {"qty": float(p["qty"]), "avg": float(p["avg_entry_price"]),
                                            "mv": float(p["market_value"])}
    if api_errors:
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:7777/api/v2/schwab/accounts-live", timeout=90) as r:
                d = json.load(r)
            d = d.get("data", d)
            for a in d.get("accounts", []):
                if a.get("positions_status") == "ok":
                    api_errors.pop(a["account_key"], None)
                    for p in a["positions"]:
                        A[(a["account_key"], p["symbol"].upper())] = {
                            "qty": float(p["qty"]), "avg": float(p["avg_entry_price"]),
                            "mv": float(p["market_value"])}
        except Exception as e:
            api_errors["_server_fallback"] = str(e)[:80]

    # C. CSV lots (unrealized)
    cur.execute("""SELECT account, symbol, quantity, cost_basis FROM schwab_cost_basis_lots
                   WHERE kind='unrealized'""")
    C = {(a, s.upper()): {"qty": float(q or 0), "basis": float(b or 0)} for a, s, q, b in cur.fetchall()}

    # D. in-window net buys from the API ledger
    cur.execute("""SELECT account, symbol,
                          sum(CASE WHEN action='Buy' THEN quantity ELSE -quantity END) net_qty,
                          sum(CASE WHEN action='Buy' THEN quantity*price ELSE -(quantity*price) END) net_cost
                   FROM trade_transactions
                   WHERE import_source='schwab_api' AND action IN ('Buy','Sell') AND account ILIKE 'schwab%'
                   GROUP BY account, symbol""")
    D = {(a, s.upper()): {"qty": float(q or 0), "cost": float(c or 0)} for a, s, q, c in cur.fetchall()}

    # 2026-06-12 (first cron alarm was noise): if the live API is ENTIRELY unreachable, comparing
    # against it is meaningless — every holding would scream MISSING_FROM_API. Fail honest instead.
    if not A:
        report = {"status": "API_UNREACHABLE — audit skipped (no comparison possible)",
                  "api_errors": api_errors, "checked": 0, "flagged": 0,
                  "note": "creds missing in this environment or server fallback timed out; "
                          "fix the environment, don't trust holdings-vs-API flags from this run"}
        print(json.dumps(report, indent=1, default=str))
        if alert:
            _alert_unreachable(api_errors)
        return report

    rows = []
    for key in sorted(set(H) | set(A)):
        acct, sym = key
        ha, aa, ca, da = H.get(key), A.get(key), C.get(key), D.get(key)
        flags = []
        info = []
        # delisted/worthless dust often appears API-side under its CUSIP (e.g. LPIH ↔ 543354104):
        # $0 market value + no price = not a money discrepancy — report as info, never alert.
        dust = (aa and aa.get("mv", 0) == 0) or (ha and not ha.get("basis") and not aa)
        h_qty = ha["qty"] if ha else None
        a_qty = aa["qty"] if aa else None
        h_avg = (ha["basis"] / ha["qty"]) if ha and ha["qty"] else None
        a_avg = aa["avg"] if aa else None
        if ha and not aa:
            if acct in api_errors:   # that account's API read failed — absence proves nothing
                info.append(f"api_unavailable_for_account ({api_errors[acct]}) — not flagged")
            else:
                (info if dust else flags).append("MISSING_FROM_API" + (" (delisted/CUSIP-alias dust)" if dust else ""))
        if aa and not ha:
            (info if dust else flags).append("MISSING_FROM_HOLDINGS" + (" (delisted/CUSIP-alias dust)" if dust else ""))
        if ha and aa:
            if h_qty and a_qty and abs(h_qty - a_qty) / max(a_qty, 1e-9) > 0.005:
                flags.append(f"QTY_MISMATCH ({h_qty:g} vs {a_qty:g})")
            if h_avg and a_avg and a_avg > 0:
                drift = abs(h_avg - a_avg) / a_avg
                dollar = abs(h_avg - a_avg) * (a_qty or 0)
                if drift > 0.02 and dollar > 50:
                    msg = f"BASIS_DIVERGENT (holdings ${h_avg:.2f} vs API ${a_avg:.2f}/sh, ${dollar:,.0f} apart)"
                    # txn_history rows diverge from the API BY DESIGN (ACATS partial-basis guard,
                    # 2026-07-18): broker basis is known-incomplete mid-transfer. Info, not alarm.
                    (info if ha.get("src") == "txn_history" else flags).append(
                        msg + (" — expected: txn_history overrides partial ACATS basis"
                               if ha.get("src") == "txn_history" else ""))
        csv_note = f"csv_lot ${ca['basis']:,.0f}/{ca['qty']:g}sh" if ca else "no_csv_lot"
        ledger_note = (f"api_fills net {da['qty']:g}sh ${da['cost']:,.0f}" if da else "no_api_fills")
        rows.append({"account": acct, "symbol": sym, "flags": flags, "info": info,
                     "holdings_qty": h_qty, "holdings_avg": round(h_avg, 4) if h_avg else None,
                     "holdings_src": ha["src"] if ha else None,
                     "api_qty": a_qty, "api_avg": a_avg,
                     "csv": csv_note, "ledger": ledger_note})

    flagged = [r for r in rows if r["flags"]]
    if args.alert and (flagged or api_errors):
        _send_alert(flagged, api_errors)
    if args.json:
        print(json.dumps({"api_errors": api_errors, "flagged": flagged, "clean": len(rows) - len(flagged),
                          "total": len(rows)}, indent=1, default=str))
        return
    print(f"\nPOSITION BASIS AUDIT — {len(rows)} schwab positions · {len(flagged)} flagged · "
          f"{len(rows) - len(flagged)} clean" + (f" · API errors: {api_errors}" if api_errors else ""))
    print("=" * 110)
    for r in rows:
        mark = "⛔" if r["flags"] else ("ℹ " if r["info"] else "✓ ")
        print(f"{mark} {r['account']:22} {r['symbol']:10} "
              f"hold {str(r['holdings_qty'] or '—'):>10} @ {str(r['holdings_avg'] or '—'):>8} ({str(r['holdings_src'] or '—')[:22]:22}) | "
              f"api {str(r['api_qty'] or '—'):>10} @ {str(r['api_avg'] or '—'):>8} | {r['csv']} | {r['ledger']}")
        for f in r["flags"] + r["info"]:
            print(f"     └─ {f}")
    if flagged:
        print(f"\n{len(flagged)} positions need attention. Remediation: scripts/sync_basis_from_broker.py "
              "(hierarchy: csv tax lot > broker API averagePrice; reconstruction is Fidelity-only).")


def _tg_send(text: str, *, producer: str, subject_key: str) -> bool:
    """Send via telegram_alert chokepoint (no raw Bot API / token selection)."""
    try:
        from telegram_alert import send_telegram
        ok = bool(send_telegram(text))
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer=producer, subject_key=subject_key,
                retention_class="operational", severity="warning",
                sanitized_body=text[:500], short_summary=text[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        return ok
    except Exception:
        return False


def _alert_unreachable(api_errors):
    """One honest line when the audit cannot run — never per-symbol noise."""
    text = (
        "⚠️ *BASIS AUDIT SKIPPED* — Schwab API unreachable from the audit "
        f"environment ({', '.join(f'{k}:{v}' for k, v in list(api_errors.items())[:4])}). "
        "No holdings flags issued (absence of API data proves nothing). "
        "Check creds/.env sourcing or server load."
    )
    _tg_send(text, producer="audit_position_basis", subject_key="ops:basis_audit")


def _send_alert(flagged, api_errors):
    """Telegram alarm via chokepoint (operator control, 2026-06-12)."""
    lines = [f"• {r['account'].replace('schwab_','')} {r['symbol']}: {'; '.join(r['flags'])[:120]}" for r in flagged[:10]]
    if api_errors:
        lines.append(f"• API errors: {api_errors}")
    text = ("⛔ *POSITION BASIS AUDIT — discrepancies found*\n" + "\n".join(lines) +
            f"\n\nRun: `python3 scripts/audit_position_basis.py` · fix: `sync_basis_from_broker.py`")
    if _tg_send(text, producer="audit_position_basis", subject_key="ops:basis_audit"):
        print(f"alert sent ({len(flagged)} flagged)")
    else:
        print("⚠ alert requested but telegram send failed or unconfigured")


if __name__ == "__main__":
    main()
