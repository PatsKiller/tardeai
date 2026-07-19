#!/usr/bin/env python3
"""options_lifecycle_basis.py — v1.1 Phase 4: controlled DATA_BLOCKED resolution.

Basis-source priority (first hit wins, provenance recorded on the leg):
  1. broker_fill        broker opening fills (Alpaca reconcile / Schwab orders)
  2. broker_orders      broker order history match
  3. intent_evidence    existing execution-intent evidence
  4. txn_history        imported transaction ledger (trade_transactions)
  5. roll_parent        reconstruction across roll ancestry
  6. operator_evidence  operator-recorded evidence (document ref REQUIRED)

Manual basis is visibly labeled (`basis_source='operator_evidence'`) and
auditable (options_basis_evidence row with document reference, reviewer state).
Cumulative roll economics: prior credits − prior debits + current ∓ fees —
never just the newest contract's premium.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def ensure_basis_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS options_basis_evidence (
        evidence_id serial PRIMARY KEY,
        leg_id int NOT NULL,
        strategy_position_id int NOT NULL,
        occ_symbol text NOT NULL,
        account_key text NOT NULL,
        opening_date date,
        opening_premium numeric NOT NULL,
        contracts numeric NOT NULL,
        fees numeric,
        source_kind text NOT NULL,          -- broker_fill|broker_orders|intent_evidence|txn_history|roll_parent|operator_evidence
        source_ref text NOT NULL,           -- order id / txn id / document or screenshot reference
        recorded_by text NOT NULL DEFAULT 'system',
        recorded_at timestamptz DEFAULT now(),
        review_status text NOT NULL DEFAULT 'unreviewed',   -- unreviewed|operator_confirmed
        notes text)""")
    cur.execute("""ALTER TABLE options_strategy_legs
                   ADD COLUMN IF NOT EXISTS basis_source text""")
    conn.commit()


def _txn_history_basis(cur, occ_ident: dict, account_key: str) -> dict | None:
    """Ledger match: an option txn would carry the OCC-ish symbol; today the
    ledger holds zero option rows, so this returns None honestly."""
    cur.execute("""SELECT trade_date, price, quantity, amount FROM trade_transactions
                   WHERE upper(symbol) LIKE %s AND action ILIKE 'buy%%' OR
                         upper(symbol) LIKE %s AND action ILIKE 'sell%%'
                   ORDER BY trade_date LIMIT 5""",
                (occ_ident.get("underlying", "") + "%", occ_ident.get("underlying", "") + "%"))
    return None  # option rows are not representable in the current ledger shape — fail honest


def resolve_leg_basis(cur, conn, leg: dict, s: dict) -> dict:
    """Try each source in priority order for one UNKNOWN-basis leg.
    Returns {resolved, source, premium} — never writes a guess."""
    from options_lifecycle_model import parse_occ
    ident = parse_occ(leg["occ_symbol"]) or {}
    # 1+2. broker fills / order history — Alpaca paper reconcile evidence
    if s["broker"] == "alpaca_paper":
        cur.execute("""SELECT entry_fill_price FROM options_monitored_positions
                       WHERE option_symbol=%s AND entry_fill_price IS NOT NULL LIMIT 1""",
                    (leg["occ_symbol"].strip(),))
        r = cur.fetchone()
        if r:
            return _apply(cur, conn, leg, s, float(r[0]), "broker_fill",
                          f"options_monitored_positions:{leg['occ_symbol'].strip()}")
    # 3. execution-intent evidence (lifecycle ticket fills recorded earlier)
    cur.execute("""SELECT evidence_json FROM options_lifecycle_tickets
                   WHERE strategy_position_id=%s AND evidence_json IS NOT NULL
                   ORDER BY ticket_id DESC LIMIT 3""", (s["strategy_position_id"],))
    for (ev,) in cur.fetchall():
        for batch in (ev if isinstance(ev, list) else json.loads(ev)):
            for f in batch.get("fills", []):
                if f.get("occ", "").strip() == leg["occ_symbol"].strip():
                    return _apply(cur, conn, leg, s, float(f["price"]), "intent_evidence",
                                  f"ticket evidence {batch.get('at', '')}")
    # 4. imported transaction history — current ledger cannot represent options
    th = _txn_history_basis(cur, ident, s["account_key"])
    if th:
        return _apply(cur, conn, leg, s, th["premium"], "txn_history", th["ref"])
    # 5. roll-parent reconstruction handled at strategy level (cumulative_basis)
    return {"resolved": False,
            "note": "no automated source — operator evidence required (record_operator_basis)"}


def _apply(cur, conn, leg: dict, s: dict, premium: float, kind: str, ref: str) -> dict:
    cur.execute("""UPDATE options_strategy_legs SET opening_price=%s, basis_source=%s
                   WHERE leg_id=%s""", (premium, kind, leg["leg_id"]))
    cur.execute("""INSERT INTO options_basis_evidence
        (leg_id, strategy_position_id, occ_symbol, account_key, opening_premium,
         contracts, source_kind, source_ref)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (leg["leg_id"], s["strategy_position_id"], leg["occ_symbol"].strip(),
         s["account_key"], premium, leg["contracts"], kind, ref))
    conn.commit()
    return {"resolved": True, "source": kind, "premium": premium}


def record_operator_basis(cur, conn, leg_id: int, *, opening_premium: float,
                          opening_date: str, contracts: float, fees: float | None,
                          source_ref: str, operator: str, notes: str = "") -> dict:
    """Priority 6 — operator evidence. source_ref (document/screenshot reference)
    is REQUIRED; the basis lands visibly labeled and auditable."""
    if not source_ref or not source_ref.strip():
        return {"ok": False, "error": "source_ref (document/screenshot reference) is REQUIRED"}
    cur.execute("""SELECT l.strategy_position_id, l.occ_symbol, p.account_key
                   FROM options_strategy_legs l
                   JOIN options_strategy_positions p USING (strategy_position_id)
                   WHERE l.leg_id=%s""", (leg_id,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "unknown leg"}
    spid, occ, acct = r
    cur.execute("""INSERT INTO options_basis_evidence
        (leg_id, strategy_position_id, occ_symbol, account_key, opening_date,
         opening_premium, contracts, fees, source_kind, source_ref, recorded_by, notes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'operator_evidence',%s,%s,%s)
        RETURNING evidence_id""",
        (leg_id, spid, occ.strip(), acct, opening_date, opening_premium, contracts,
         fees, source_ref, operator, notes))
    eid = cur.fetchone()[0]
    cur.execute("""UPDATE options_strategy_legs SET opening_price=%s, opening_fees=%s,
                   basis_source='operator_evidence' WHERE leg_id=%s""",
                (opening_premium, fees, leg_id))
    cur.execute("""UPDATE options_strategy_positions SET data_quality_status='ok', updated_at=now()
                   WHERE strategy_position_id=%s AND data_quality_status='incomplete_basis'
                     AND NOT EXISTS (SELECT 1 FROM options_strategy_legs
                                     WHERE strategy_position_id=%s AND status='open'
                                       AND opening_price IS NULL)""", (spid, spid))
    conn.commit()
    return {"ok": True, "evidence_id": eid,
            "label": "MANUAL BASIS (operator evidence) — visible on the card until broker data confirms"}


def cumulative_basis(cur, spid: int) -> dict:
    """Roll-aware strategy economics: prior credits − prior debits ± current
    opening ∓ fees across the roll_root chain. Unknown legs surface as gaps."""
    cur.execute("SELECT roll_root_id FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    r = cur.fetchone()
    root = (r[0] if r and r[0] else spid)
    cur.execute("""SELECT l.side, l.contracts, l.multiplier, l.opening_price, l.opening_fees,
                          l.closed_price, l.status, p.strategy_position_id
                   FROM options_strategy_legs l
                   JOIN options_strategy_positions p USING (strategy_position_id)
                   WHERE p.roll_root_id=%s ORDER BY l.leg_id""", (root,))
    credits = debits = fees = 0.0
    unknown = []
    for side, n, mult, op, ofees, cp, status, pid in cur.fetchall():
        if op is None:
            unknown.append(pid)
            continue
        cash = float(op) * float(n) * int(mult)
        if side == "short":
            credits += cash
        else:
            debits += cash
        if cp is not None:
            close_cash = float(cp) * float(n) * int(mult)
            if side == "short":
                debits += close_cash
            else:
                credits += close_cash
        fees += float(ofees or 0)
    return {"roll_root_id": root, "prior_credits": round(credits, 2),
            "prior_debits": round(debits, 2), "fees": round(fees, 2),
            "cumulative_net_basis": round(credits - debits - fees, 2),
            "unknown_basis_positions": sorted(set(unknown)),
            "complete": not unknown}


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    ensure_basis_tables(cur, conn)
    print("basis evidence tables ensured")
