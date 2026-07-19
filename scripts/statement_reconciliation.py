#!/usr/bin/env python3
"""statement_reconciliation.py — v1.2.3 P1-3: statement-level cost/principal
reconciliation over eConfirm aggregation periods vs the transaction ledger.
Generic charges stay generic; email/statement evidence NEVER writes the ledger."""
from __future__ import annotations


STATES = ("EXACT_RECONCILIATION", "RECONCILED_WITH_DATE_FALLBACK", "PRINCIPAL_MISMATCH",
          "CHARGE_MISMATCH", "TOTAL_MISMATCH", "INCOMPLETE_LEDGER", "AMBIGUOUS",
          "SOURCE_UNAVAILABLE")


def reconcile_period(cur, date_from: str, date_to: str, account: str | None = None) -> dict:
    """One aggregation period: parsed eConfirm fills vs ledger transactions."""
    acct_sql = " AND account_suffix=%s" if account else ""
    args = [date_from, date_to] + ([account] if account else [])
    cur.execute(f"""SELECT COALESCE(sum(principal),0), COALESCE(sum(charge_or_interest),0),
                           COALESCE(sum(total_amount),0), count(*),
                           count(*) FILTER (WHERE recon_status IN ('ECONFIRM_ONLY','pending')),
                           count(*) FILTER (WHERE recon_status='MATCH_WITH_DATE_FALLBACK')
                    FROM econfirm_evidence
                    WHERE parse_status='parsed' AND trade_date BETWEEN %s AND %s{acct_sql}""",
                args)
    s_prin, s_chg, s_tot, s_n, s_unmatched, s_fallback = cur.fetchone()
    if s_n == 0:
        return {"state": "SOURCE_UNAVAILABLE", "period": [date_from, date_to],
                "note": "no parsed source rows in period"}
    cur.execute("""SELECT COALESCE(sum(abs(quantity*price)),0), COALESCE(sum(fees),0), count(*)
                   FROM trade_transactions
                   WHERE trade_date BETWEEN %s AND %s AND action IN ('Buy','Sell')""",
                (date_from, date_to))
    l_prin, l_chg, l_n = cur.fetchone()
    cur.execute("""SELECT count(*) FROM trade_transactions t
                   WHERE t.trade_date BETWEEN %s AND %s AND t.action IN ('Buy','Sell')
                     AND NOT EXISTS (SELECT 1 FROM econfirm_evidence e
                                     WHERE e.matched_txn_dedupe_key = t.dedupe_key)""",
                (date_from, date_to))
    ledger_only = cur.fetchone()[0]
    out = {"period": [date_from, date_to], "account": account,
           "source": {"principal": float(s_prin), "generic_charges": float(s_chg),
                      "total": float(s_tot), "rows": s_n},
           "ledger": {"principal": float(l_prin), "actual_charges": float(l_chg), "rows": l_n},
           "matched": s_n - s_unmatched, "unmatched_source_rows": s_unmatched,
           "unmatched_ledger_rows": ledger_only}
    if l_n == 0:
        out["state"] = "INCOMPLETE_LEDGER"
    elif abs(float(s_prin) - float(l_prin)) > max(0.02, 0.0001 * float(s_prin)):
        out["state"] = "PRINCIPAL_MISMATCH"
    elif abs(float(s_chg) - float(l_chg)) > 0.05:
        out["state"] = "CHARGE_MISMATCH"
    elif s_unmatched:
        out["state"] = "AMBIGUOUS"
    else:
        out["state"] = ("RECONCILED_WITH_DATE_FALLBACK" if s_fallback else "EXACT_RECONCILIATION")
    return out
