#!/usr/bin/env python3
"""options_fill_evidence.py — v1.2 Phases 3–6: atomic, idempotent, CUMULATIVE
fill evidence + durable journal projection + roll/assignment/expiry transitions.

Canonical broker-fill identity (dedupe_key UNIQUE):
  broker + account + broker_order_id + broker_execution_id + OCC + qty + price + executed_at
Replaying identical evidence changes nothing. Everything the evidence implies —
leg deltas, strategy status, CUMULATIVE outcome, projection outbox — commits in
ONE transaction; the trade_instances projection then runs from a durable outbox
with retry (a close is never silently unjournaled again).

Fail-closed rules: fractional contracts refused unless broker truth explicitly
says otherwise; overfill/wrong-OCC/wrong-instruction refused; a roll package
with one side filled and the other missing becomes a package-risk incident.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUTBOX_MAX_ATTEMPTS = 8


def ensure_evidence_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS options_fill_evidence (
        evidence_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        ticket_id int,
        leg_id int,
        broker text NOT NULL,
        account_key text NOT NULL,
        broker_order_id text,
        broker_execution_id text,
        occ_symbol text NOT NULL,
        instruction text NOT NULL,
        contracts numeric NOT NULL,
        price numeric NOT NULL,
        commission numeric,
        regulatory_fee numeric,
        exchange_fee numeric,
        other_fee numeric,
        currency text DEFAULT 'USD',
        executed_at timestamptz,
        source text NOT NULL,
        raw_json jsonb,
        dedupe_key text UNIQUE NOT NULL,
        recorded_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS journal_projection_outbox (
        outbox_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        projection_kind text NOT NULL,          -- trade_instance | journal_event
        payload_hash text NOT NULL,
        state text NOT NULL DEFAULT 'NEW',      -- NEW|PROCESSING|PROJECTED|RETRY|FAILED|RECONCILED
        attempts int NOT NULL DEFAULT 0,
        last_error text,
        next_retry_at timestamptz DEFAULT now(),
        projected_at timestamptz,
        created_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS options_stock_basis_transfers (
        transfer_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        leg_id int,
        kind text NOT NULL,                     -- assignment_delivery|assignment_acquisition|exercise_acquisition|exercise_disposition
        underlying text NOT NULL,
        account_key text NOT NULL,
        shares numeric NOT NULL,
        strike numeric NOT NULL,
        premium_per_share_transferred numeric,  -- option premium folded into stock basis
        effective_stock_basis_per_share numeric,
        evidence_ref text NOT NULL,
        recorded_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_event_evidence
        ON options_journal_events (strategy_position_id, event, COALESCE(evidence_ref,''))""")
    conn.commit()


def _dedupe_key(broker, account, f) -> str:
    core = "|".join(str(x) for x in (
        broker, account, f.get("broker_order_id") or "", f.get("broker_execution_id") or "",
        f["occ_symbol"].strip(), f["contracts"], f["price"], f.get("executed_at") or ""))
    return hashlib.sha256(core.encode()).hexdigest()[:32]


def _fees_of(f) -> float:
    return sum(float(f.get(k) or 0) for k in ("commission", "regulatory_fee",
                                              "exchange_fee", "other_fee"))


def _emit_event_idem(cur, spid, event, source, ref, details=None):
    cur.execute("SELECT roll_root_id FROM options_strategy_positions WHERE strategy_position_id=%s",
                (spid,))
    r = cur.fetchone()
    cur.execute("""INSERT INTO options_journal_events
        (strategy_position_id, roll_root_id, event, evidence_source, evidence_ref, details)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (strategy_position_id, event, COALESCE(evidence_ref,'')) DO NOTHING""",
        (spid, r[0] if r else None, event, source, ref, json.dumps(details or {}, default=str)))


def _queue_projection(cur, spid: int, kind: str = "trade_instance"):
    payload_hash = hashlib.sha256(f"{spid}|{kind}|{datetime.now(timezone.utc).date()}".encode()).hexdigest()[:16]
    cur.execute("""INSERT INTO journal_projection_outbox (strategy_position_id, projection_kind, payload_hash)
                   VALUES (%s,%s,%s)""", (spid, kind, payload_hash))


def record_broker_evidence(cur, conn, ticket_id: int, fills: list[dict], source: str,
                           operator_note: str = "", allow_fractional: bool = False) -> dict:
    """THE evidence entry point (v1.2). Atomic; cumulative; idempotent."""
    from options_lifecycle_model import strategy_with_legs
    ensure_evidence_tables(cur, conn)
    cur.execute("""SELECT ticket_json, status, strategy_position_id, kind
                   FROM options_lifecycle_tickets WHERE ticket_id=%s""", (ticket_id,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "unknown ticket"}
    if r[1] not in ("armed", "partial"):
        return {"ok": False, "error": f"ticket is {r[1]} — evidence lands only on armed/partial tickets"}
    ticket = r[0] if isinstance(r[0], dict) else json.loads(r[0])
    spid, kind = r[2], r[3]
    s = strategy_with_legs(cur, spid)
    broker, account = s["broker"], s["account_key"]

    try:
        # ── validate + insert evidence (idempotent per fill) ──────────────────
        inserted = []
        for f in fills:
            n = float(f["contracts"])
            if n <= 0:
                raise ValueError(f"non-positive contracts {n}")
            if abs(n - round(n)) > 1e-9 and not allow_fractional:
                raise ValueError(f"fractional contracts {n} refused — broker truth must explicitly allow")
            tleg = next((t for t in ticket["legs"]
                         if (t.get("occ_symbol") or t.get("occ_target") or "").strip() == f["occ_symbol"].strip()
                         and t["instruction"] == f["instruction"]), None)
            if not tleg:
                raise ValueError(f"fill {f['instruction']} {f['occ_symbol'].strip()} matches no ticket leg "
                                 "(wrong OCC/instruction) — fail closed")
            dk = _dedupe_key(broker, account, f)
            cur.execute("""INSERT INTO options_fill_evidence
                (strategy_position_id, ticket_id, broker, account_key, broker_order_id,
                 broker_execution_id, occ_symbol, instruction, contracts, price,
                 commission, regulatory_fee, exchange_fee, other_fee, executed_at,
                 source, raw_json, dedupe_key)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (dedupe_key) DO NOTHING RETURNING evidence_id""",
                (spid, ticket_id, broker, account, f.get("broker_order_id"),
                 f.get("broker_execution_id"), f["occ_symbol"].strip(), f["instruction"],
                 n, float(f["price"]), f.get("commission"), f.get("regulatory_fee"),
                 f.get("exchange_fee"), f.get("other_fee"), f.get("executed_at"),
                 source, json.dumps(f, default=str), dk))
            row = cur.fetchone()
            if row:
                inserted.append({"evidence_id": row[0], **{k: f[k] for k in ("occ_symbol", "contracts", "price")}})
            # duplicate replay: no row, changes nothing — by design

        # ── CUMULATIVE state per ticket leg (across ALL evidence, not this batch) ──
        cum = {}
        cur.execute("""SELECT occ_symbol, instruction, sum(contracts),
                              sum(contracts * price),
                              sum(COALESCE(commission,0)+COALESCE(regulatory_fee,0)
                                  +COALESCE(exchange_fee,0)+COALESCE(other_fee,0))
                       FROM options_fill_evidence WHERE ticket_id=%s
                       GROUP BY occ_symbol, instruction""", (ticket_id,))
        for occ, instr, qty, notional, fees in cur.fetchall():
            cum[(occ.strip(), instr)] = {"qty": float(qty), "vwap": float(notional) / float(qty),
                                         "fees": float(fees)}

        # overfill check + leg application from cumulative truth
        complete = True
        for t in ticket["legs"]:
            occ = (t.get("occ_symbol") or t.get("occ_target") or "").strip()
            c = cum.get((occ, t["instruction"]), {"qty": 0.0})
            if c["qty"] > float(t["contracts"]) + 1e-9:
                raise ValueError(f"OVERFILL {occ}: cumulative {c['qty']} > ticket {t['contracts']}")
            if c["qty"] < float(t["contracts"]) - 1e-9:
                complete = False

        # apply CLOSE-side leg state from cumulative fills
        realized_total, fees_total = 0.0, 0.0
        for (occ, instr), c in cum.items():
            fees_total += c["fees"]
            leg = next((l for l in s["legs"] if l["occ_symbol"].strip() == occ
                        and l["status"] in ("open", "closed")), None)
            if leg is None or instr in ("BTO", "STO"):
                continue  # open-side of a roll handled below
            filled, px = c["qty"], c["vwap"]
            if leg["opening_price"] is not None:
                realized_total += ((float(leg["opening_price"]) - px) if leg["side"] == "short"
                                   else (px - float(leg["opening_price"]))) * filled * int(leg["multiplier"])
            if abs(filled - float(leg["contracts"])) < 1e-9 and leg["status"] == "open":
                cur.execute("""UPDATE options_strategy_legs SET status='closed', closed_price=%s,
                               closed_at=now() WHERE leg_id=%s AND status='open'""", (px, leg["leg_id"]))
            elif filled < float(leg["contracts"]) and leg["status"] == "open":
                # residual stays open at reduced size; closed slice recorded once
                cur.execute("""SELECT count(*) FROM options_strategy_legs
                               WHERE strategy_position_id=%s AND occ_symbol=%s AND status='closed'""",
                            (spid, leg["occ_symbol"]))
                already = cur.fetchone()[0]
                if not already:
                    cur.execute("UPDATE options_strategy_legs SET contracts=%s WHERE leg_id=%s",
                                (float(leg["contracts"]) - filled, leg["leg_id"]))
                    cur.execute("""INSERT INTO options_strategy_legs
                        (strategy_position_id, occ_symbol, leg_role, option_type, instruction, side,
                         contracts, multiplier, strike, expiration, opening_price, status,
                         closed_price, closed_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'closed',%s,now())""",
                        (spid, leg["occ_symbol"], leg["leg_role"], leg["option_type"],
                         leg["instruction"], leg["side"], filled, leg["multiplier"],
                         leg["strike"], leg["expiration"], leg["opening_price"], px))
                else:
                    # later batch grows the closed slice; the open residual shrinks
                    # to (original total − cumulative filled), never below zero
                    prev_closed = already_qty(cur, spid, leg["occ_symbol"])
                    original_total = float(leg["contracts"]) + prev_closed
                    cur.execute("""UPDATE options_strategy_legs SET contracts=%s, closed_price=%s
                                   WHERE strategy_position_id=%s AND occ_symbol=%s AND status='closed'""",
                                (filled, px, spid, leg["occ_symbol"]))
                    residual = max(0.0, original_total - filled)
                    if residual > 1e-9:
                        cur.execute("UPDATE options_strategy_legs SET contracts=%s WHERE leg_id=%s",
                                    (residual, leg["leg_id"]))
                    else:
                        cur.execute("""UPDATE options_strategy_legs SET status='closed', closed_price=%s,
                                       closed_at=now(), contracts=0 WHERE leg_id=%s""", (px, leg["leg_id"]))

        result = {"ok": True, "inserted": len(inserted), "cumulative": {f"{k[1]} {k[0]}": v for k, v in cum.items()},
                  "ticket_complete": complete, "realized_cumulative": round(realized_total, 2),
                  "fees_cumulative": round(fees_total, 2)}

        # ── roll completion (P5) ──────────────────────────────────────────────
        if kind == "roll":
            result["roll"] = _apply_roll(cur, s, ticket, ticket_id, cum, source)
            complete = result["roll"].get("package_complete", False)

        # ── ticket + strategy + cumulative outcome + projection, one transaction ──
        s2 = strategy_with_legs(cur, spid)
        all_closed = not [l for l in s2["legs"] if l["status"] == "open"]
        cur.execute("""UPDATE options_lifecycle_tickets SET status=%s,
                       evidence_json=COALESCE(evidence_json,'[]'::jsonb) || %s::jsonb, updated_at=now()
                       WHERE ticket_id=%s""",
                    ("filled" if complete else "partial",
                     json.dumps([{"source": source, "fills": [dict(f) for f in fills],
                                  "note": operator_note,
                                  "at": datetime.now(timezone.utc).isoformat()}], default=str),
                     ticket_id))
        if all_closed and kind == "close":
            cur.execute("""UPDATE options_strategy_positions SET status='closed', closed_at=now(),
                           updated_at=now() WHERE strategy_position_id=%s""", (spid,))
        # cumulative outcome UPSERT-by-position (P&L + fees across every batch)
        cur.execute("""SELECT decision_id, recommendation FROM options_lifecycle_decisions
                       WHERE strategy_position_id=%s AND superseded_by IS NULL
                       ORDER BY decision_id DESC LIMIT 1""", (spid,))
        dec = cur.fetchone()
        cur.execute("SELECT outcome_id FROM options_lifecycle_outcomes WHERE strategy_position_id=%s",
                    (spid,))
        existing_outcome = cur.fetchone()
        if all_closed and kind == "close":
            if existing_outcome:
                cur.execute("""UPDATE options_lifecycle_outcomes SET realized_pnl=%s, ticket_id=%s,
                               meta=%s, closed_at=now() WHERE strategy_position_id=%s""",
                            (round(realized_total - fees_total, 2), ticket_id,
                             json.dumps({"fees": fees_total, "source": source}), spid))
            else:
                cur.execute("""INSERT INTO options_lifecycle_outcomes
                    (strategy_position_id, ticket_id, recommendation_at_action, decision_id,
                     operator_action, realized_pnl, meta)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (spid, ticket_id, dec[1] if dec else None, dec[0] if dec else None,
                     "followed" if source != "operator_manual" else "manual",
                     round(realized_total - fees_total, 2),
                     json.dumps({"fees": fees_total, "source": source})))
        # journal events + DURABLE projection queue — final state exists BEFORE projecting
        _emit_event_idem(cur, spid, "CLOSE" if (all_closed and kind == "close")
                         else ("ROLL" if kind == "roll" else "PARTIAL_CLOSE"),
                         source, ref=f"ticket:{ticket_id}",
                         details={"cumulative_realized": realized_total, "fees": fees_total})
        _queue_projection(cur, spid)
        conn.commit()
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": f"fail closed, nothing recorded: {str(e)[:200]}"}

    if all_closed and kind == "close":
        from options_lifecycle_alerts import resolve_alerts_for
        resolve_alerts_for(cur, conn, spid)
    process_projection_outbox(cur, conn)   # eager attempt; failures stay durable
    result["position_closed"] = all_closed
    return result


def already_qty(cur, spid, occ):  # helper kept for clarity in partial re-fills
    cur.execute("""SELECT COALESCE(sum(contracts),0) FROM options_strategy_legs
                   WHERE strategy_position_id=%s AND occ_symbol=%s AND status='closed'""", (spid, occ))
    return float(cur.fetchone()[0])


def _apply_roll(cur, s: dict, ticket: dict, ticket_id: int, cum: dict, source: str) -> dict:
    """P5: roll = ONE package. Close side + open side reconciled from cumulative
    evidence; when both complete → child strategy with lineage; one side only →
    package-risk incident (fail closed, loudly visible)."""
    from options_lifecycle_model import parse_occ, occ_symbol as mk_occ
    spid = s["strategy_position_id"]
    close_done = all(cum.get(((t.get("occ_symbol") or "").strip(), t["instruction"]), {"qty": 0})["qty"]
                     >= float(t["contracts"]) - 1e-9 for t in ticket.get("close_legs", []))
    open_fills = {}
    for t in ticket.get("open_legs", []):
        # replacement identity from the ticket's target (underlying/exp/type/strike)
        occ = mk_occ(s["underlying"], str(t["expiration"]),
                     "call" if "call" in str(t.get("occ_target", "")).lower() or t.get("option_type") == "call"
                     else "put" if t.get("option_type") == "put" or "put" in str(t.get("occ_target", "")).lower()
                     else ("call" if t["side"] in ("short",) and s["strategy_type"] == "covered_call" else "put"),
                     float(t["strike"]))
        c = cum.get((occ.strip(), t["instruction"]))
        if c and c["qty"] >= float(t["contracts"]) - 1e-9:
            open_fills[occ] = {**t, "vwap": c["vwap"], "fees": c["fees"], "occ": occ}
    open_done = len(open_fills) == len(ticket.get("open_legs", []))
    if close_done and not open_done:
        _emit_event_idem(cur, spid, "ADJUST", source, ref=f"ticket:{ticket_id}:package_risk",
                         details={"incident": "ROLL PACKAGE RISK: close side filled, replacement NOT — "
                                              "position is unhedged vs plan; operator review required"})
        return {"package_complete": False, "incident": "close_filled_replacement_missing"}
    if open_done and not close_done:
        _emit_event_idem(cur, spid, "ADJUST", source, ref=f"ticket:{ticket_id}:package_risk",
                         details={"incident": "ROLL PACKAGE RISK: replacement filled, close side NOT — "
                                              "double exposure; operator review required"})
        return {"package_complete": False, "incident": "replacement_filled_close_missing"}
    if not (close_done and open_done):
        return {"package_complete": False}
    # both sides complete → close parent, create child with lineage + REAL fills
    cur.execute("""UPDATE options_strategy_positions SET status='rolled', closed_at=now(),
                   updated_at=now() WHERE strategy_position_id=%s""", (spid,))
    root = s.get("roll_root_id") or spid
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, status, opened_at, source,
         roll_parent_id, roll_root_id, operator_objective, management_policy_version,
         data_quality_status, linked_share_symbol, linked_share_qty, notes)
        SELECT broker, account_key, strategy_type, underlying, 'open', now(), 'roll_evidence',
               %s, %s, operator_objective, management_policy_version, 'ok',
               linked_share_symbol, linked_share_qty, 'child of roll ticket ' || %s
        FROM options_strategy_positions WHERE strategy_position_id=%s
        RETURNING strategy_position_id""", (spid, root, str(ticket_id), spid))
    child = cur.fetchone()[0]
    for occ, t in open_fills.items():
        ident = parse_occ(occ)
        role = (("short_" if t["side"] == "short" else "long_") + ident["option_type"])
        cur.execute("""INSERT INTO options_strategy_legs
            (strategy_position_id, occ_symbol, leg_role, option_type, instruction, side,
             contracts, multiplier, strike, expiration, opening_price, opening_fees,
             basis_source, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,100,%s,%s,%s,%s,'broker_fill','open')""",
            (child, occ, role, ident["option_type"], t["instruction"], t["side"],
             float(t["contracts"]), ident["strike"], ident["expiration"],
             t["vwap"], t["fees"]))
    _emit_event_idem(cur, spid, "ROLL", source, ref=f"ticket:{ticket_id}",
                     details={"child": child, "root": root})
    _emit_event_idem(cur, child, "OPEN", source, ref=f"roll_ticket:{ticket_id}",
                     details={"parent": spid, "root": root})
    _queue_projection(cur, child)
    return {"package_complete": True, "child_strategy_position_id": child, "roll_root_id": root}


# ── P6: assignment / exercise / expiration ────────────────────────────────────

def record_expire_worthless(cur, conn, spid: int, occ: str, source: str, ref: str) -> dict:
    cur.execute("""UPDATE options_strategy_legs SET status='closed', closed_price=0, closed_at=now()
                   WHERE strategy_position_id=%s AND occ_symbol=%s AND status='open'
                   RETURNING leg_id""", (spid, occ))
    if not cur.fetchone():
        conn.rollback()
        return {"ok": False, "error": "no open leg for that OCC"}
    _finish_if_flat(cur, spid, "expired")
    _emit_event_idem(cur, spid, "EXPIRE_WORTHLESS", source, ref=ref)
    _queue_projection(cur, spid)
    conn.commit()
    process_projection_outbox(cur, conn)
    return {"ok": True}


def record_assignment(cur, conn, spid: int, occ: str, source: str, ref: str) -> dict:
    """Short option assigned. Option leg realizes at 0 (premium fully earned —
    counted ONCE); share movement lands as a stock-basis transfer record — the
    stock side is counted ONCE there, never inside option P&L."""
    from options_lifecycle_model import parse_occ
    cur.execute("""SELECT leg_id, side, contracts, multiplier, strike, option_type, opening_price
                   FROM options_strategy_legs
                   WHERE strategy_position_id=%s AND occ_symbol=%s AND status='open'""", (spid, occ))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "no open leg for that OCC"}
    leg_id, side, n, mult, strike, otype, op = r
    if side != "short":
        return {"ok": False, "error": "assignment applies to short legs only"}
    cur.execute("""UPDATE options_strategy_legs SET status='closed', closed_price=0, closed_at=now()
                   WHERE leg_id=%s""", (leg_id,))
    cur.execute("""SELECT account_key, underlying FROM options_strategy_positions
                   WHERE strategy_position_id=%s""", (spid,))
    acct, und = cur.fetchone()
    shares = float(n) * int(mult)
    kind = "assignment_delivery" if otype == "call" else "assignment_acquisition"
    # premium transfers into effective stock economics EXACTLY once, via basis:
    # call-away: effective sale = strike + premium; put-assign: effective basis = strike − premium
    prem = float(op) if op is not None else None
    eff = ((float(strike) + prem) if otype == "call" else (float(strike) - prem)) if prem is not None else None
    cur.execute("""INSERT INTO options_stock_basis_transfers
        (strategy_position_id, leg_id, kind, underlying, account_key, shares, strike,
         premium_per_share_transferred, effective_stock_basis_per_share, evidence_ref)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (spid, leg_id, kind, und, acct, shares, strike, prem, eff, ref))
    _finish_if_flat(cur, spid, "assigned")
    _emit_event_idem(cur, spid, "ASSIGNED", source, ref=ref,
                     details={"shares": shares, "strike": float(strike),
                              "effective_stock_basis_per_share": eff,
                              "double_count_guard": "premium in basis transfer ONLY; option leg closes at 0"})
    _queue_projection(cur, spid)
    conn.commit()
    process_projection_outbox(cur, conn)
    return {"ok": True, "stock_transfer": kind, "shares": shares,
            "effective_basis_per_share": eff}


def record_exercise(cur, conn, spid: int, occ: str, source: str, ref: str) -> dict:
    """Long option exercised — premium folds into stock basis exactly once."""
    cur.execute("""SELECT leg_id, side, contracts, multiplier, strike, option_type, opening_price
                   FROM options_strategy_legs
                   WHERE strategy_position_id=%s AND occ_symbol=%s AND status='open'""", (spid, occ))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "no open leg for that OCC"}
    leg_id, side, n, mult, strike, otype, op = r
    if side != "long":
        return {"ok": False, "error": "exercise applies to long legs only"}
    cur.execute("""UPDATE options_strategy_legs SET status='closed', closed_price=0, closed_at=now()
                   WHERE leg_id=%s""", (leg_id,))
    cur.execute("SELECT account_key, underlying FROM options_strategy_positions WHERE strategy_position_id=%s",
                (spid,))
    acct, und = cur.fetchone()
    shares = float(n) * int(mult)
    prem = float(op) if op is not None else None
    kind = "exercise_acquisition" if otype == "call" else "exercise_disposition"
    eff = ((float(strike) + prem) if otype == "call" else (float(strike) - prem)) if prem is not None else None
    cur.execute("""INSERT INTO options_stock_basis_transfers
        (strategy_position_id, leg_id, kind, underlying, account_key, shares, strike,
         premium_per_share_transferred, effective_stock_basis_per_share, evidence_ref)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (spid, leg_id, kind, und, acct, shares, strike, prem, eff, ref))
    _finish_if_flat(cur, spid, "exercised")
    _emit_event_idem(cur, spid, "EXERCISED", source, ref=ref,
                     details={"shares": shares, "effective_stock_basis_per_share": eff})
    _queue_projection(cur, spid)
    conn.commit()
    process_projection_outbox(cur, conn)
    return {"ok": True, "stock_transfer": kind, "shares": shares, "effective_basis_per_share": eff}


def _finish_if_flat(cur, spid: int, terminal_status: str):
    cur.execute("""SELECT count(*) FROM options_strategy_legs
                   WHERE strategy_position_id=%s AND status='open'""", (spid,))
    if cur.fetchone()[0] == 0:
        cur.execute("""UPDATE options_strategy_positions SET status=%s, closed_at=now(), updated_at=now()
                       WHERE strategy_position_id=%s""", (terminal_status, spid))


# ── P4: durable projection processor ─────────────────────────────────────────

def process_projection_outbox(cur, conn, limit: int = 20) -> dict:
    from options_journal_bridge import ensure_bridge_tables, upsert_trade_instance
    ensure_bridge_tables(cur, conn)
    cur.execute("""SELECT outbox_id, strategy_position_id FROM journal_projection_outbox
                   WHERE state IN ('NEW','RETRY') AND next_retry_at <= now()
                   ORDER BY outbox_id LIMIT %s""", (limit,))
    rows = cur.fetchall()
    done, failed = 0, 0
    for oid, spid in rows:
        cur.execute("UPDATE journal_projection_outbox SET state='PROCESSING', attempts=attempts+1 WHERE outbox_id=%s",
                    (oid,))
        conn.commit()
        try:
            r = upsert_trade_instance(cur, conn, spid)
            if not r.get("ok"):
                raise RuntimeError(r.get("error", "projection failed"))
            cur.execute("""UPDATE journal_projection_outbox SET state='PROJECTED', projected_at=now()
                           WHERE outbox_id=%s""", (oid,))
            done += 1
        except Exception as e:
            cur.execute("""UPDATE journal_projection_outbox
                           SET state=CASE WHEN attempts >= %s THEN 'FAILED' ELSE 'RETRY' END,
                               last_error=%s,
                               next_retry_at=now() + make_interval(mins => least(attempts * 10, 120))
                           WHERE outbox_id=%s""", (OUTBOX_MAX_ATTEMPTS, str(e)[:300], oid))
            failed += 1
        conn.commit()
    return {"projected": done, "failed_or_retry": failed}


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    ensure_evidence_tables(cur, conn)
    print("fill-evidence + outbox + stock-transfer tables ensured")
    print(process_projection_outbox(cur, conn))
