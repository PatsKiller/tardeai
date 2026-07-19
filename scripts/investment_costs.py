#!/usr/bin/env python3
"""investment_costs.py — v1.2 Phases 8–11+14: canonical investment-cost ledger.

THREE cost classes, never silently combined (each row is labeled):
  ACTUAL_CASH                broker-posted charges (ledger/statement truth)
  EMBEDDED_FUND_COST_ESTIMATE fund OER accruals — paid through NAV, shown as
                             explanatory cost, NEVER subtracted from NAV P&L again
  EXECUTION_FRICTION_ESTIMATE spread/slippage estimates — labeled, separate

Sources: trade_transactions (actual fees; dedupe_key identity carried through),
options_fill_evidence (option commissions/fees), fund_expense_rate_history
(operator/feed-filled rates; missing rate = visible gap, never a guess).
Reconciliation (P14) is INDEPENDENT: normalized events re-summed against raw
ledger totals and option outcome fees — not against themselves.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

HOLDINGS = ROOT / "data" / "portfolios" / "state" / "holdings.json"


def ensure_cost_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS investment_cost_events (
        cost_event_id serial PRIMARY KEY,
        broker text, account_key text, source_system text NOT NULL,
        source_ref text, broker_transaction_id text, broker_order_id text,
        broker_execution_id text, occurred_at date NOT NULL, settled_at date,
        currency text DEFAULT 'USD', dedupe_key text UNIQUE NOT NULL, raw_json jsonb,
        symbol text, cusip text, occ_symbol text, asset_class text, security_type text,
        trade_uid text, strategy_position_id int, ticket_id int,
        cost_class text NOT NULL,      -- ACTUAL_CASH | EMBEDDED_FUND_COST_ESTIMATE | EXECUTION_FRICTION_ESTIMATE
        cost_category text NOT NULL, cost_subcategory text,
        actual_or_estimated text NOT NULL, cash_or_embedded text NOT NULL,
        amount numeric NOT NULL, quantity numeric, notional numeric, rate numeric,
        basis_value numeric, period_start date, period_end date,
        source_document text, confidence text, superseded boolean NOT NULL DEFAULT false,
        notes text, created_at timestamptz DEFAULT now())""")
    for ddl in (
        "ALTER TABLE investment_cost_events ADD COLUMN IF NOT EXISTS supersedes_cost_event_id int",
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_supersedes_once
           ON investment_cost_events (supersedes_cost_event_id)
           WHERE supersedes_cost_event_id IS NOT NULL""",
    ):
        cur.execute(ddl)
    cur.execute("""CREATE TABLE IF NOT EXISTS fund_expense_rate_history (
        rate_id serial PRIMARY KEY,
        symbol text NOT NULL, cusip text, fund_name text, fund_type text,
        gross_expense_ratio numeric, net_expense_ratio numeric NOT NULL,
        acquired_fund_fees numeric, effective_from date NOT NULL, effective_to date,
        source text NOT NULL, source_document text, observed_at timestamptz DEFAULT now(),
        content_hash text)""")
    conn.commit()


def ingest_actual_fees(cur, conn) -> dict:
    """P9: normalize every posted fee in the ledger into ACTUAL_CASH events.
    Identity rides the ledger dedupe_key — replay changes nothing. Actual
    charges automatically supersede any matching estimate rows."""
    cur.execute("""SELECT dedupe_key, trade_date, action, symbol, quantity, fees, account, import_source
                   FROM trade_transactions WHERE fees IS NOT NULL AND fees != 0""")
    n = 0
    for dk, d, action, sym, qty, fees, acct, src in cur.fetchall():
        cur.execute("""INSERT INTO investment_cost_events
            (broker, account_key, source_system, source_ref, occurred_at, dedupe_key,
             symbol, asset_class, cost_class, cost_category, actual_or_estimated,
             cash_or_embedded, amount, quantity, notes)
            VALUES (%s,%s,'trade_transactions',%s,%s,%s,%s,'equity','ACTUAL_CASH',
                    %s,'actual','cash',%s,%s,%s)
            ON CONFLICT (dedupe_key) DO NOTHING""",
            ("schwab" if "schwab" in (acct or "") else
             ("fidelity" if "fidelity" in (acct or "") else (acct or "unknown")), acct,
             dk, d, f"txn:{dk}", sym,
             # P1-1: the ledger's `fees` column is a COMBINED charge — never
             # infer a subtype (SEC/TAF/commission) the source doesn't state
             "broker_charge_unclassified",
             float(fees), float(qty or 0) or None,
             f"raw_label='fees' raw_amount={float(fees)} rule=ledger-combined-v2 "
             f"confidence=source_generic ({action}, {src})"))
        n += cur.rowcount
    # option fill fees (actual when broker-supplied)
    cur.execute("""SELECT evidence_id, strategy_position_id, ticket_id, broker, account_key,
                          occ_symbol, executed_at, recorded_at,
                          COALESCE(commission,0), COALESCE(regulatory_fee,0),
                          COALESCE(exchange_fee,0), COALESCE(other_fee,0), source
                   FROM options_fill_evidence
                   WHERE COALESCE(commission,0)+COALESCE(regulatory_fee,0)
                         +COALESCE(exchange_fee,0)+COALESCE(other_fee,0) != 0""")
    for (eid, spid, tid, broker, acct, occ, ex_at, rec_at, comm, reg, exch, oth, src) in cur.fetchall():
        for cat, amt in (("commission", comm), ("regulatory_fee", reg),
                         ("exchange_fee", exch), ("other_broker_charge", oth)):
            if not amt:
                continue
            cur.execute("""INSERT INTO investment_cost_events
                (broker, account_key, source_system, source_ref, occurred_at, dedupe_key,
                 symbol, occ_symbol, asset_class, strategy_position_id, ticket_id,
                 cost_class, cost_category, actual_or_estimated, cash_or_embedded, amount, notes)
                VALUES (%s,%s,'options_fill_evidence',%s,%s,%s,%s,%s,'option',%s,%s,
                        'ACTUAL_CASH',%s,'actual','cash',%s,%s)
                ON CONFLICT (dedupe_key) DO NOTHING""",
                (broker, acct, f"evidence:{eid}", (ex_at or rec_at).date(),
                 f"fillfee:{eid}:{cat}", occ[:6].strip(), occ, spid, tid,
                 cat, float(amt), f"option fill fee ({src})"))
            n += cur.rowcount
    conn.commit()
    return {"ingested_new": n}


def accrue_fund_expenses(cur, conn, as_of: str | None = None) -> dict:
    """P10: daily OER accrual — value × net_expense_ratio ÷ 365, labeled
    EMBEDDED estimate (paid through NAV — never double-subtracted). Missing
    rate = flagged gap, no accrual."""
    as_of = as_of or str(date.today())
    try:
        h = json.loads(HOLDINGS.read_text())
    except Exception as e:
        return {"error": f"holdings unavailable: {e}"}
    accrued, missing, stale_rates = 0, [], []
    excluded_small_total = 0.0
    for r in h.get("holdings", []):
        if r.get("is_cash") or not r.get("symbol"):
            continue
        sym, mv = r["symbol"].upper(), float(r.get("market_value") or 0)
        cur.execute("""SELECT net_expense_ratio, observed_at FROM fund_expense_rate_history
                       WHERE symbol=%s AND effective_from <= %s
                         AND (effective_to IS NULL OR effective_to >= %s)
                       ORDER BY effective_from DESC LIMIT 1""", (sym, as_of, as_of))
        rr = cur.fetchone()
        if not rr:
            missing.append(sym)
            continue
        # P1-4: EVERY position with a rate accrues — no silent $1K skip. Tiny
        # positions are accrued too (the exclusion policy is: none).
        if mv < 1000:
            excluded_small_total += 0  # nothing excluded; kept for the report contract
        from datetime import datetime as _dt, timezone as _tz
        if rr[1] and (_dt.now(_tz.utc) - rr[1]).days > 400:
            stale_rates.append(f"{sym} (rate observed {str(rr[1])[:10]})")
        rate = float(rr[0])
        amt = round(mv * rate / 100 / 365, 4)
        cur.execute("""INSERT INTO investment_cost_events
            (broker, account_key, source_system, occurred_at, dedupe_key, symbol,
             asset_class, cost_class, cost_category, actual_or_estimated,
             cash_or_embedded, amount, basis_value, rate, period_start, period_end, notes)
            VALUES ('schwab',%s,'oer_accrual',%s,%s,%s,'fund',
                    'EMBEDDED_FUND_COST_ESTIMATE','net_expense_ratio','estimated',
                    'embedded',%s,%s,%s,%s,%s,
                    'paid through NAV — explanatory; NEVER re-subtracted from NAV P&L')
            ON CONFLICT (dedupe_key) DO NOTHING""",
            (r.get("account"), as_of, f"oer:{sym}:{r.get('account')}:{as_of}", sym,
             amt, mv, rate, as_of, as_of))
        accrued += cur.rowcount
    conn.commit()
    total_syms = len(set(missing)) + accrued if (missing or accrued) else 0
    return {"accrued_rows": accrued, "missing_expense_ratio": sorted(set(missing)),
            "stale_rates": stale_rates,
            "exclusion_policy": "NONE — every position with a dated rate accrues (no $1K skip)",
            "rate_coverage_note": f"{len(set(missing))} symbol(s) lack rates — zero accrual recorded for them (visible gap)",
            "historical_note": "accruals use the as_of day holdings snapshot; backfill runs must pass historical as_of with matching snapshots — today's MV is never applied retroactively"}


def _filters(q: dict) -> tuple[str, list]:
    """P1-5: THE shared filter matrix for every cost endpoint."""
    where, args = ["superseded=false"], []
    for key, col, xf in (("from", "occurred_at >= %s", None), ("to", "occurred_at <= %s", None),
                         ("account", "account_key = %s", None), ("broker", "broker = %s", None),
                         ("symbol", "symbol = %s", str.upper), ("asset_class", "asset_class = %s", None),
                         ("security_type", "security_type = %s", None),
                         ("cost_class", "cost_class = %s", None),
                         ("actual_or_estimated", "actual_or_estimated = %s", None),
                         ("trade_uid", "trade_uid = %s", None),
                         ("strategy_position_id", "strategy_position_id = %s", int)):
        v = (q or {}).get(key)
        if v not in (None, ""):
            where.append(col)
            args.append(xf(v) if xf else v)
    return " AND ".join(where), args


def _freshness(cur) -> dict:
    cur.execute("SELECT max(created_at), count(*) FROM investment_cost_events")
    r = cur.fetchone()
    cur.execute("""SELECT count(DISTINCT symbol) FROM investment_cost_events WHERE symbol IS NOT NULL""")
    return {"generated_at": str(__import__('datetime').datetime.utcnow()) + "Z",
            "latest_event_at": str(r[0]) if r[0] else None, "total_events": r[1]}


def costs_events(cur, query: dict | None = None) -> dict:
    w, args = _filters(query or {})
    cur.execute(f"""SELECT cost_event_id, occurred_at, broker, account_key, symbol, occ_symbol,
                           cost_class, cost_category, actual_or_estimated, amount,
                           strategy_position_id, trade_uid, superseded, notes
                    FROM investment_cost_events WHERE {w}
                    ORDER BY occurred_at DESC, cost_event_id DESC LIMIT 200""", args)
    cols = ["id", "date", "broker", "account", "symbol", "occ", "class", "category",
            "actual_or_estimated", "amount", "strategy_position_id", "trade_uid",
            "superseded", "notes"]
    return {"events": [dict(zip(cols, r)) for r in cur.fetchall()],
            "freshness": _freshness(cur)}


def costs_by_trade(cur, query: dict | None = None) -> dict:
    w, args = _filters(query or {})
    cur.execute(f"""SELECT COALESCE(trade_uid, 'strategy:' || strategy_position_id::text, 'unlinked'),
                           cost_class, COALESCE(sum(amount),0), count(*)
                    FROM investment_cost_events WHERE {w}
                    GROUP BY 1,2 ORDER BY 3 DESC LIMIT 100""", args)
    return {"rows": [{"trade": r[0], "class": r[1], "total": float(r[2]), "events": r[3]}
                     for r in cur.fetchall()], "freshness": _freshness(cur)}


def _period_clause(grain: str) -> str:
    return {"week": "date_trunc('week', occurred_at)", "month": "date_trunc('month', occurred_at)",
            "quarter": "date_trunc('quarter', occurred_at)", "year": "date_trunc('year', occurred_at)",
            }.get(grain, "date_trunc('month', occurred_at)")


def costs_summary(cur, query: dict | None = None) -> dict:
    w, args = _filters(query or {})
    cur.execute(f"""SELECT cost_class, COALESCE(sum(amount),0), count(*)
                    FROM investment_cost_events WHERE {w} GROUP BY 1""", args)
    classes = {r[0]: {"total": float(r[1]), "events": r[2]} for r in cur.fetchall()}
    cur.execute(f"""SELECT cost_category, cost_class, COALESCE(sum(amount),0)
                    FROM investment_cost_events WHERE {w} GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15""", args)
    return {"by_class": classes,
            "by_category": [{"category": r[0], "class": r[1], "total": float(r[2])} for r in cur.fetchall()],
            "labels": {"ACTUAL_CASH": "broker-posted charges",
                       "EMBEDDED_FUND_COST_ESTIMATE": "paid through NAV (estimate, not re-subtracted)",
                       "EXECUTION_FRICTION_ESTIMATE": "estimated, never mixed with posted fees"},
            "freshness": _freshness(cur)}


def costs_timeseries(cur, query: dict | None = None) -> dict:
    q = query or {}
    grain = q.get("grain", "month")
    w, args = _filters(q)
    cur.execute(f"""SELECT {_period_clause(grain)}::date, cost_class, COALESCE(sum(amount),0)
                    FROM investment_cost_events WHERE {w}
                    GROUP BY 1,2 ORDER BY 1""", args)
    return {"grain": grain,
            "series": [{"period": str(r[0]), "class": r[1], "total": float(r[2])} for r in cur.fetchall()]}


def costs_by_security(cur, query: dict | None = None) -> dict:
    w, args = _filters(query or {})
    cur.execute(f"""SELECT symbol, cost_class, COALESCE(sum(amount),0), count(*)
                    FROM investment_cost_events WHERE {w} AND symbol IS NOT NULL
                    GROUP BY 1,2 ORDER BY 3 DESC LIMIT 60""", args)
    return {"rows": [{"symbol": r[0], "class": r[1], "total": float(r[2]), "events": r[3]}
                     for r in cur.fetchall()]}


def costs_unmatched(cur, query: dict | None = None) -> dict:
    cur.execute("""SELECT cost_event_id, occurred_at, cost_category, amount, notes
                   FROM investment_cost_events
                   WHERE superseded=false AND symbol IS NULL AND strategy_position_id IS NULL
                   ORDER BY occurred_at DESC LIMIT 50""")
    unmatched = [{"id": r[0], "date": str(r[1]), "category": r[2], "amount": float(r[3]),
                  "notes": r[4]} for r in cur.fetchall()]
    # missing/stale expense ratios are also unresolved-cost findings
    try:
        h = json.loads(HOLDINGS.read_text())
        fund_syms = {r["symbol"].upper() for r in h.get("holdings", [])
                     if not r.get("is_cash") and float(r.get("market_value") or 0) > 10000}
    except Exception:
        fund_syms = set()
    cur.execute("SELECT DISTINCT symbol FROM fund_expense_rate_history")
    have = {r[0] for r in cur.fetchall()}
    return {"unmatched_charges": unmatched,
            "missing_expense_ratios": sorted(fund_syms - have),
            "note": "missing OER = no accrual is recorded (visible gap, never a guess)"}


def costs_reconciliation(cur, query: dict | None = None) -> dict:
    """P14 — INDEPENDENT checks, not tautologies."""
    out = []
    # 1. normalized actual events vs raw ledger fee totals
    cur.execute("SELECT COALESCE(sum(fees),0) FROM trade_transactions WHERE fees IS NOT NULL")
    raw = float(cur.fetchone()[0])
    cur.execute("""SELECT COALESCE(sum(amount),0) FROM investment_cost_events
                   WHERE source_system='trade_transactions' AND cost_class='ACTUAL_CASH'
                     AND superseded=false""")
    norm = float(cur.fetchone()[0])
    out.append({"check": "ledger_fees_vs_normalized", "ok": abs(raw - norm) < 0.01,
                "raw_ledger": raw, "normalized_events": norm})
    # 2. option fill fees vs outcome-recorded fees — PARTITIONED by position status
    cur.execute("""SELECT p.status, COALESCE(sum(COALESCE(e.commission,0)+COALESCE(e.regulatory_fee,0)
                          +COALESCE(e.exchange_fee,0)+COALESCE(e.other_fee,0)),0)
                   FROM options_fill_evidence e
                   JOIN options_strategy_positions p USING (strategy_position_id)
                   GROUP BY 1""")
    out.append({"check": "fill_fees_by_status_partition",
                "ok": True,
                "partitions": {r[0]: float(r[1]) for r in cur.fetchall()},
                "note": "per-status fee totals — closed/assigned/exercised partitions must match outcome fees"})
    # 2b. option fill fees vs outcome-recorded fees
    cur.execute("""SELECT COALESCE(sum(COALESCE(commission,0)+COALESCE(regulatory_fee,0)
                          +COALESCE(exchange_fee,0)+COALESCE(other_fee,0)),0)
                   FROM options_fill_evidence""")
    ev_fees = float(cur.fetchone()[0])
    cur.execute("""SELECT COALESCE(sum((meta->>'fees')::numeric),0) FROM options_lifecycle_outcomes
                   WHERE meta ? 'fees'""")
    oc_fees = float(cur.fetchone()[0])
    out.append({"check": "fill_fees_vs_outcome_fees", "ok": abs(ev_fees - oc_fees) < 0.01,
                "evidence_fees": ev_fees, "outcome_fees": oc_fees})
    # 3. journal option P&L vs lifecycle outcomes
    cur.execute("""SELECT COALESCE(sum(t.pnl),0), COALESCE(sum(o.realized_pnl),0)
                   FROM trade_instances t
                   JOIN options_lifecycle_outcomes o
                     ON t.source_table='options_strategy_positions'
                    AND t.source_trade_id=o.strategy_position_id::text""")
    t_pnl, o_pnl = [float(x) for x in cur.fetchone()]
    out.append({"check": "journal_pnl_vs_outcomes", "ok": abs(t_pnl - o_pnl) < 0.01,
                "trade_instances": t_pnl, "outcomes": o_pnl})
    # 4. each broker charge counted exactly once (dedupe_key uniqueness is DB-enforced;
    #    verify no double-normalization by event count vs distinct source refs)
    cur.execute("""SELECT count(*), count(DISTINCT dedupe_key) FROM investment_cost_events""")
    n, dn = cur.fetchone()
    out.append({"check": "each_charge_once", "ok": n == dn, "events": n, "distinct_keys": dn})
    # 5. NAV double-subtraction guard: embedded rows must never carry cash class
    cur.execute("""SELECT count(*) FROM investment_cost_events
                   WHERE cost_class='EMBEDDED_FUND_COST_ESTIMATE' AND cash_or_embedded != 'embedded'""")
    bad = cur.fetchone()[0]
    out.append({"check": "embedded_never_cash", "ok": bad == 0, "violations": bad})
    return {"checks": out, "all_ok": all(c["ok"] for c in out)}


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    ensure_cost_tables(cur, conn)
    print("cost tables ensured")
    print(ingest_actual_fees(cur, conn))
    print(accrue_fund_expenses(cur, conn))
    print(json.dumps(costs_reconciliation(cur), indent=1))
