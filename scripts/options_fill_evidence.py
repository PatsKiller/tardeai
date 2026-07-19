#!/usr/bin/env python3
"""options_fill_evidence.py — v1.2.1 P0-3/4/5/6/7: atomic, idempotent, CUMULATIVE
fill evidence with hardened identity, row locking, single-owner premium
accounting, complete roll outcomes, and concurrent-safe durable projection.

CANONICAL FILL MATH (P0-3): the immutable ticket leg defines target_contracts.
The evidence ledger defines cumulative_filled/cumulative_notional/VWAP/fees;
canonical leg state is PROJECTED from (target, cumulative) — never derived from
a previously-mutated residual.

IDENTITY (P0-4): dedupe includes broker+account+strategy+ticket+order id+
execution id+OCC+instruction+qty+price+ts. Broker evidence REQUIRES a broker
execution id (or an explicitly documented substitute); operator evidence
requires operator + source reference. Ticket, strategy, and legs are locked
FOR UPDATE for the whole mutation.

PREMIUM ACCOUNTING (P0-5): MODEL A, one owner per premium dollar —
premium REMAINS in option P&L (assignment/exercise closes the leg at 0, i.e.
full premium realized in the options component); the stock transfer uses
STRIKE-ONLY economics; effective-strike-after-premium is explanatory display
data only. premium_transferred_to_stock is therefore always 0 under Model A.

ROLL (P0-6): parent gets realized close P&L + fees + an outcomes row +
projection; child opens from actual fills with lineage; one-sided packages
become PERSISTENT incidents (options_package_incidents) with a red health
finding — never false completion.

OUTBOX (P0-7): unique (spid, kind, payload_hash); workers claim with
FOR UPDATE SKIP LOCKED; stranded PROCESSING rows recover after a timeout;
a stale projection cannot overwrite a newer one (state-version guard).
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
PROCESSING_TIMEOUT_MIN = 10
PREMIUM_ACCOUNTING_MODE = "A_option_retains_premium"


def ensure_evidence_tables(cur, conn):
    # concurrency guard: DDL takes AccessExclusive locks — when the newest table
    # already exists (steady state), skip the whole block so concurrent evidence
    # writers never contend on catalog locks (deadlock seen in P0-4 testing)
    cur.execute("""SELECT to_regclass('options_package_incidents'), to_regclass('options_fill_evidence'),
                          to_regclass('options_execution_friction')""")
    if all(cur.fetchone()):
        cur.execute("""SELECT 1 FROM information_schema.columns
                       WHERE table_name='journal_projection_outbox' AND column_name='claimed_at'""")
        if cur.fetchone():
            return
    cur.execute("""CREATE TABLE IF NOT EXISTS options_fill_evidence (
        evidence_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        ticket_id int,
        leg_id int,
        broker text NOT NULL,
        account_key text NOT NULL,
        broker_order_id text,
        broker_execution_id text,
        broker_id_substitute text,          -- documented substitute when broker lacks exec ids
        operator_evidence_ref text,         -- REQUIRED for operator evidence
        operator_name text,
        occ_symbol text NOT NULL,
        instruction text NOT NULL,
        contracts numeric NOT NULL,
        price numeric NOT NULL,
        commission numeric, regulatory_fee numeric, exchange_fee numeric, other_fee numeric,
        currency text DEFAULT 'USD',
        executed_at timestamptz,
        source text NOT NULL,
        raw_json jsonb,
        dedupe_key text UNIQUE NOT NULL,
        recorded_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS journal_projection_outbox (
        outbox_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        projection_kind text NOT NULL,
        canonical_state_version text,
        payload_hash text NOT NULL,
        state text NOT NULL DEFAULT 'NEW',
        attempts int NOT NULL DEFAULT 0,
        last_error text,
        claimed_at timestamptz,
        next_retry_at timestamptz DEFAULT now(),
        projected_at timestamptz,
        created_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_outbox_projection
        ON journal_projection_outbox (strategy_position_id, projection_kind, payload_hash)""")
    cur.execute("ALTER TABLE journal_projection_outbox ADD COLUMN IF NOT EXISTS canonical_state_version text")
    cur.execute("ALTER TABLE journal_projection_outbox ADD COLUMN IF NOT EXISTS claimed_at timestamptz")
    cur.execute("""CREATE TABLE IF NOT EXISTS options_stock_basis_transfers (
        transfer_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        leg_id int,
        kind text NOT NULL,
        underlying text NOT NULL,
        account_key text NOT NULL,
        shares numeric NOT NULL,
        strike numeric NOT NULL,
        premium_per_share_transferred numeric,
        effective_stock_basis_per_share numeric,
        evidence_ref text NOT NULL,
        recorded_at timestamptz DEFAULT now())""")
    for ddl in (
        "ALTER TABLE options_stock_basis_transfers ADD COLUMN IF NOT EXISTS premium_accounting_mode text",
        "ALTER TABLE options_stock_basis_transfers ADD COLUMN IF NOT EXISTS premium_retained_in_options numeric",
        "ALTER TABLE options_stock_basis_transfers ADD COLUMN IF NOT EXISTS premium_transferred_to_stock numeric NOT NULL DEFAULT 0",
        "ALTER TABLE options_stock_basis_transfers ADD COLUMN IF NOT EXISTS stock_basis_transfer_amount numeric",
        "ALTER TABLE options_stock_basis_transfers ADD COLUMN IF NOT EXISTS option_realized_after_transfer numeric",
    ):
        cur.execute(ddl)
    cur.execute("""CREATE TABLE IF NOT EXISTS options_package_incidents (
        incident_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        ticket_id int,
        state text NOT NULL,   -- ROLL_CLOSE_FILLED_OPEN_MISSING | ROLL_OPEN_FILLED_CLOSE_MISSING | ROLL_PARTIAL_PACKAGE | ROLL_DATA_MISMATCH
        detail text,
        created_at timestamptz DEFAULT now(),
        resolved_at timestamptz,
        resolved_by text)""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_event_evidence
        ON options_journal_events (strategy_position_id, event, COALESCE(evidence_ref,''))""")
    # v1.2.2 P0-1: IMMUTABLE per-ticket close allocations — every closed contract
    # is attributable to its ticket + evidence; a later ticket can NEVER touch an
    # earlier ticket's allocation (replaces the 90-day slice heuristic).
    cur.execute("""CREATE TABLE IF NOT EXISTS options_close_allocations (
        allocation_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        ticket_id int NOT NULL,
        leg_id int NOT NULL,
        occ_symbol text NOT NULL,
        contracts numeric NOT NULL,
        vwap numeric NOT NULL,
        fees numeric NOT NULL DEFAULT 0,
        realized numeric,                  -- (open − vwap)·sign·contracts·mult when basis known
        created_at timestamptz DEFAULT now(),
        updated_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_close_alloc_ticket_leg
        ON options_close_allocations (ticket_id, leg_id)""")
    cur.execute("ALTER TABLE options_strategy_legs ADD COLUMN IF NOT EXISTS original_contracts numeric")
    from options_execution_friction import ensure_friction_tables
    ensure_friction_tables(cur, conn)
    conn.commit()


def _dedupe_key(broker, account, spid, ticket_id, f) -> str:
    core = "|".join(str(x) for x in (
        broker, account, spid, ticket_id,
        f.get("broker_order_id") or "", f.get("broker_execution_id") or f.get("operator_evidence_ref") or "",
        f["occ_symbol"].strip(), f["instruction"], f["contracts"], f["price"],
        f.get("executed_at") or ""))
    return hashlib.sha256(core.encode()).hexdigest()[:32]


def _lock_for_mutation(cur, spid: int, ticket_id: int):
    """P0-4: serialize every strategy mutation — ticket, strategy, legs."""
    cur.execute("SELECT ticket_id FROM options_lifecycle_tickets WHERE ticket_id=%s FOR UPDATE", (ticket_id,))
    cur.execute("SELECT strategy_position_id FROM options_strategy_positions WHERE strategy_position_id=%s FOR UPDATE",
                (spid,))
    cur.execute("SELECT leg_id FROM options_strategy_legs WHERE strategy_position_id=%s FOR UPDATE", (spid,))


def _emit_event_idem(cur, spid, event, source, ref, details=None):
    cur.execute("SELECT roll_root_id FROM options_strategy_positions WHERE strategy_position_id=%s", (spid,))
    r = cur.fetchone()
    cur.execute("""INSERT INTO options_journal_events
        (strategy_position_id, roll_root_id, event, evidence_source, evidence_ref, details)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (strategy_position_id, event, COALESCE(evidence_ref,'')) DO NOTHING""",
        (spid, r[0] if r else None, event, source, ref, json.dumps(details or {}, default=str)))


def _state_version(cur, spid: int) -> str:
    cur.execute("""SELECT status, closed_at, updated_at FROM options_strategy_positions
                   WHERE strategy_position_id=%s""", (spid,))
    r = cur.fetchone()
    return hashlib.sha256(("|".join(str(x) for x in (r or ()))).encode()).hexdigest()[:12]


def _queue_projection(cur, spid: int, kind: str = "trade_instance"):
    sv = _state_version(cur, spid)
    cur.execute("""INSERT INTO journal_projection_outbox
        (strategy_position_id, projection_kind, canonical_state_version, payload_hash)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (strategy_position_id, projection_kind, payload_hash) DO NOTHING""",
        (spid, kind, sv, sv))


def _validate_identity(f: dict, source: str, allow_substitute: bool):
    if source == "operator_manual":
        if not (f.get("operator_evidence_ref") and f.get("operator_name")):
            raise ValueError("operator evidence requires operator_name + operator_evidence_ref "
                             "(document/screenshot) — no silent empty identity")
    else:
        if not f.get("broker_execution_id"):
            if f.get("broker_id_substitute"):
                pass  # explicitly documented substitute (e.g. alpaca fill id reused)
            else:
                raise ValueError("broker evidence requires broker_execution_id or an explicitly "
                                 "documented broker_id_substitute — no silent empty identity")


def _cumulative(cur, ticket_id: int) -> dict:
    cur.execute("""SELECT occ_symbol, instruction, sum(contracts), sum(contracts*price),
                          sum(COALESCE(commission,0)+COALESCE(regulatory_fee,0)
                              +COALESCE(exchange_fee,0)+COALESCE(other_fee,0))
                   FROM options_fill_evidence WHERE ticket_id=%s GROUP BY 1,2""", (ticket_id,))
    return {(occ.strip(), instr): {"qty": float(q), "vwap": float(n) / float(q), "fees": float(f)}
            for occ, instr, q, n, f in cur.fetchall()}


def _project_close_leg(cur, spid: int, leg: dict, ticket_id: int, ticket_filled: float,
                       ticket_vwap: float, ticket_fees: float):
    """v1.2.2 P0-1: per-TICKET immutable allocation. This ticket's allocation
    row (unique on ticket+leg) carries its own filled/vwap/fees/realized; the
    ORIGINAL leg's residual = original_total − Σ allocations across ALL tickets.
    Earlier tickets' allocations are never read for identity, never updated,
    never deleted."""
    if ticket_filled <= 1e-9:
        return
    realized = None
    if leg["opening_price"] is not None:
        realized = ((float(leg["opening_price"]) - ticket_vwap) if leg["side"] == "short"
                    else (ticket_vwap - float(leg["opening_price"]))) \
                   * ticket_filled * int(leg["multiplier"])
    cur.execute("""INSERT INTO options_close_allocations
        (strategy_position_id, ticket_id, leg_id, occ_symbol, contracts, vwap, fees, realized)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (ticket_id, leg_id) DO UPDATE SET
          contracts=EXCLUDED.contracts, vwap=EXCLUDED.vwap, fees=EXCLUDED.fees,
          realized=EXCLUDED.realized, updated_at=now()""",
        (spid, ticket_id, leg["leg_id"], leg["occ_symbol"], ticket_filled, ticket_vwap,
         ticket_fees, realized))
    cur.execute("""SELECT COALESCE(sum(contracts),0) FROM options_close_allocations
                   WHERE leg_id=%s""", (leg["leg_id"],))
    total_alloc = float(cur.fetchone()[0])
    # original total = residual currently on the leg row + allocations OTHER than
    # this ticket's previous value is already superseded by the upsert; recompute
    # from the immutable opening contracts: derive from ticket target semantics —
    # the leg row's contracts field holds ORIGINAL total until first allocation,
    # after which we track residual = original − total_alloc via original stored once.
    cur.execute("""SELECT original_contracts FROM options_strategy_legs WHERE leg_id=%s""",
                (leg["leg_id"],))
    orig = cur.fetchone()[0]
    if orig is None:
        orig = leg["contracts"]
        cur.execute("UPDATE options_strategy_legs SET original_contracts=%s WHERE leg_id=%s",
                    (orig, leg["leg_id"]))
    residual = max(0.0, float(orig) - total_alloc)
    if residual < 1e-9:
        cur.execute("""SELECT sum(contracts*vwap)/NULLIF(sum(contracts),0)
                       FROM options_close_allocations WHERE leg_id=%s""", (leg["leg_id"],))
        blended = cur.fetchone()[0]
        cur.execute("""UPDATE options_strategy_legs SET status='closed', closed_price=%s,
                       closed_at=now(), contracts=%s WHERE leg_id=%s""",
                    (blended, float(orig), leg["leg_id"]))
    else:
        cur.execute("UPDATE options_strategy_legs SET contracts=%s WHERE leg_id=%s",
                    (residual, leg["leg_id"]))


def strategy_realized_from_allocations(cur, spid: int) -> tuple[float | None, float]:
    """P0-1 outcome model (documented choice): ONE strategy outcome accumulating
    realized close evidence across EVERY ticket's allocations. Returns
    (realized_or_None_if_any_unknown, fees_total)."""
    cur.execute("""SELECT realized, fees FROM options_close_allocations
                   WHERE strategy_position_id=%s""", (spid,))
    rows = cur.fetchall()
    fees = sum(float(f or 0) for _, f in rows)
    if any(r is None for r, _ in rows):
        return None, fees
    return sum(float(r) for r, _ in rows), fees


def record_broker_evidence(cur, conn, ticket_id: int, fills: list[dict], source: str,
                           operator_note: str = "", allow_fractional: bool = False) -> dict:
    """THE evidence entry point. Atomic; cumulative from targets; locked."""
    from options_lifecycle_model import strategy_with_legs
    ensure_evidence_tables(cur, conn)
    try:
        cur.execute("""SELECT ticket_json, status, strategy_position_id, kind
                       FROM options_lifecycle_tickets WHERE ticket_id=%s""", (ticket_id,))
        r = cur.fetchone()
        if not r:
            return {"ok": False, "error": "unknown ticket"}
        if r[1] == "filled":
            # v1.2.2: sequential replay of a FILLED ticket is an idempotent
            # no-op returning the canonical result — never an error
            spid0 = r[2]
            cur.execute("""SELECT count(*) FROM options_fill_evidence WHERE ticket_id=%s""", (ticket_id,))
            n_ev = cur.fetchone()[0]
            cur.execute("""SELECT broker, account_key FROM options_strategy_positions
                           WHERE strategy_position_id=%s""", (spid0,))
            b0, a0 = cur.fetchone()
            known = True
            for f in fills or []:
                cur.execute("SELECT 1 FROM options_fill_evidence WHERE dedupe_key=%s",
                            (_dedupe_key(b0, a0, spid0, ticket_id, f),))
                if not cur.fetchone():
                    known = False
            realized, fees = strategy_realized_from_allocations(cur, spid0)
            return {"ok": True, "idempotent_noop": True, "ticket_complete": True,
                    "position_closed": True, "inserted": 0,
                    "evidence_rows": n_ev, "all_fills_known": bool(known),
                    "realized_cumulative": realized, "fees_cumulative": fees}
        if r[1] not in ("armed", "partial"):
            return {"ok": False, "error": f"ticket is {r[1]} — evidence lands only on armed/partial tickets"}
        ticket = r[0] if isinstance(r[0], dict) else json.loads(r[0])
        spid, kind = r[2], r[3]
        _lock_for_mutation(cur, spid, ticket_id)          # P0-4 serialization
        s = strategy_with_legs(cur, spid)
        broker, account = s["broker"], s["account_key"]

        inserted = 0
        for f in fills:
            n = float(f["contracts"])
            if n <= 0:
                raise ValueError(f"non-positive contracts {n}")
            if abs(n - round(n)) > 1e-9 and not allow_fractional:
                raise ValueError(f"fractional contracts {n} refused — broker truth must explicitly allow")
            _validate_identity(f, source if not f.get("operator_evidence_ref") else "operator_manual",
                               allow_substitute=True)
            tleg = next((t for t in ticket["legs"]
                         if (t.get("occ_symbol") or t.get("occ_target") or "").strip() == f["occ_symbol"].strip()
                         and t["instruction"] == f["instruction"]), None)
            if not tleg:
                raise ValueError(f"fill {f['instruction']} {f['occ_symbol'].strip()} matches no ticket leg "
                                 "(wrong OCC/instruction) — fail closed")
            cur.execute("""INSERT INTO options_fill_evidence
                (strategy_position_id, ticket_id, broker, account_key, broker_order_id,
                 broker_execution_id, broker_id_substitute, operator_evidence_ref, operator_name,
                 occ_symbol, instruction, contracts, price, commission, regulatory_fee,
                 exchange_fee, other_fee, executed_at, source, raw_json, dedupe_key)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (dedupe_key) DO NOTHING""",
                (spid, ticket_id, broker, account, f.get("broker_order_id"),
                 f.get("broker_execution_id"), f.get("broker_id_substitute"),
                 f.get("operator_evidence_ref"), f.get("operator_name"),
                 f["occ_symbol"].strip(), f["instruction"], n, float(f["price"]),
                 f.get("commission"), f.get("regulatory_fee"), f.get("exchange_fee"),
                 f.get("other_fee"), f.get("executed_at"), source,
                 json.dumps(f, default=str), _dedupe_key(broker, account, spid, ticket_id, f)))
            inserted += cur.rowcount

        cum = _cumulative(cur, ticket_id)
        # targets are IMMUTABLE ticket legs; overfill vs target, completeness vs target
        complete = True
        realized_total = fees_total = 0.0
        for t in ticket["legs"]:
            occ = (t.get("occ_symbol") or t.get("occ_target") or "").strip()
            target = float(t["contracts"])
            c = cum.get((occ, t["instruction"]), {"qty": 0.0, "vwap": 0.0, "fees": 0.0})
            if c["qty"] > target + 1e-9:
                raise ValueError(f"OVERFILL {occ}: cumulative {c['qty']} > target {target}")
            if c["qty"] < target - 1e-9:
                complete = False
            fees_total += c["fees"]
            if t["instruction"] in ("BTC", "STC") and c["qty"] > 0:
                # original leg row: the one whose identity matches and is not the closed slice
                leg = next((l for l in s["legs"] if l["occ_symbol"].strip() == occ
                            and l["status"] == "open"), None) or \
                      next((l for l in s["legs"] if l["occ_symbol"].strip() == occ), None)
                if leg:
                    if leg["opening_price"] is not None:
                        realized_total += ((float(leg["opening_price"]) - c["vwap"])
                                           if leg["side"] == "short"
                                           else (c["vwap"] - float(leg["opening_price"]))) \
                                          * c["qty"] * int(leg["multiplier"])
                    if leg["status"] == "open":
                        _project_close_leg(cur, spid, leg, ticket_id, c["qty"], c["vwap"], c["fees"])

        result = {"ok": True, "inserted": inserted, "ticket_complete": complete,
                  "realized_cumulative": round(realized_total, 2),
                  "fees_cumulative": round(fees_total, 2),
                  "cumulative": {f"{k[1]} {k[0]}": v for k, v in cum.items()}}
        if kind == "roll":
            result["roll"] = _apply_roll(cur, s, ticket, ticket_id, cum, source,
                                         realized_total, fees_total)
            complete = result["roll"].get("package_complete", False)

        s2 = strategy_with_legs(cur, spid)
        all_closed = not [l for l in s2["legs"] if l["status"] == "open"]
        cur.execute("""UPDATE options_lifecycle_tickets SET status=%s,
                       evidence_json=COALESCE(evidence_json,'[]'::jsonb) || %s::jsonb, updated_at=now()
                       WHERE ticket_id=%s""",
                    ("filled" if complete else "partial",
                     json.dumps([{"source": source, "fills": [dict(x) for x in fills],
                                  "note": operator_note,
                                  "at": datetime.now(timezone.utc).isoformat()}], default=str), ticket_id))
        if all_closed and kind == "close":
            cur.execute("""UPDATE options_strategy_positions SET status='closed', closed_at=now(),
                           updated_at=now() WHERE strategy_position_id=%s""", (spid,))
            # v1.2.2 P0-1 outcome model: ONE strategy outcome accumulated from
            # ALL tickets' immutable allocations — not just this ticket's batch
            acc_realized, acc_fees = strategy_realized_from_allocations(cur, spid)
            if acc_realized is not None:
                _upsert_outcome(cur, spid, ticket_id, acc_realized, acc_fees, source)
        cur.execute("SAVEPOINT friction_sp")
        try:
            from options_execution_friction import record_friction
            cum_named = {k: {**v, "fills_count": len([1 for f in fills
                                                      if f["occ_symbol"].strip() == k[0]])}
                         for k, v in cum.items()}
            record_friction(cur, conn, {**ticket, "strategy_position_id": spid},
                            ticket_id, cum_named, source, manage_txn=False)
            cur.execute("RELEASE SAVEPOINT friction_sp")
        except Exception as _fe:
            cur.execute("ROLLBACK TO SAVEPOINT friction_sp")
            print(f"  [friction] non-blocking: {str(_fe)[:100]}")
        _emit_event_idem(cur, spid,
                         "CLOSE" if (all_closed and kind == "close")
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
    process_projection_outbox(cur, conn)
    result["position_closed"] = all_closed
    return result


def _upsert_outcome(cur, spid, ticket_id, realized, fees, source):
    cur.execute("""SELECT decision_id, recommendation FROM options_lifecycle_decisions
                   WHERE strategy_position_id=%s AND superseded_by IS NULL
                   ORDER BY decision_id DESC LIMIT 1""", (spid,))
    dec = cur.fetchone()
    cur.execute("SELECT outcome_id FROM options_lifecycle_outcomes WHERE strategy_position_id=%s", (spid,))
    if cur.fetchone():
        cur.execute("""UPDATE options_lifecycle_outcomes SET realized_pnl=%s, ticket_id=%s,
                       meta=%s, closed_at=now() WHERE strategy_position_id=%s""",
                    (round(realized - fees, 2), ticket_id,
                     json.dumps({"fees": fees, "source": source}), spid))
    else:
        cur.execute("""INSERT INTO options_lifecycle_outcomes
            (strategy_position_id, ticket_id, recommendation_at_action, decision_id,
             operator_action, realized_pnl, meta)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (spid, ticket_id, dec[1] if dec else None, dec[0] if dec else None,
             "followed" if source != "operator_manual" else "manual",
             round(realized - fees, 2), json.dumps({"fees": fees, "source": source})))


def _apply_roll(cur, s, ticket, ticket_id, cum, source, realized_close, fees_close) -> dict:
    """P0-6: parent outcome + child lineage + PERSISTENT package incidents."""
    from options_lifecycle_model import parse_occ, occ_symbol as mk_occ
    spid = s["strategy_position_id"]
    close_done = all(cum.get(((t.get("occ_symbol") or "").strip(), t["instruction"]),
                             {"qty": 0})["qty"] >= float(t["contracts"]) - 1e-9
                     for t in ticket.get("close_legs", []))
    open_fills, open_partial = {}, False
    for t in ticket.get("open_legs", []):
        otype = (t.get("option_type") or
                 ("call" if "C" in str(t.get("occ_target", "")).split()[-1][:1].upper() else "put"))
        occ = mk_occ(s["underlying"], str(t["expiration"]), otype, float(t["strike"]))
        c = cum.get((occ.strip(), t["instruction"]))
        if c and c["qty"] >= float(t["contracts"]) - 1e-9:
            open_fills[occ] = {**t, "vwap": c["vwap"], "fees": c["fees"], "occ": occ,
                               "option_type": otype}
        elif c:
            open_partial = True
    open_done = len(open_fills) == len(ticket.get("open_legs", [])) and not open_partial

    def incident(state, detail):
        cur.execute("""INSERT INTO options_package_incidents
            (strategy_position_id, ticket_id, state, detail)
            SELECT %s,%s,%s,%s WHERE NOT EXISTS (
              SELECT 1 FROM options_package_incidents
              WHERE strategy_position_id=%s AND ticket_id=%s AND state=%s AND resolved_at IS NULL)""",
            (spid, ticket_id, state, detail, spid, ticket_id, state))
        _emit_event_idem(cur, spid, "ADJUST", source, ref=f"ticket:{ticket_id}:{state}",
                         details={"incident": detail})
        return {"package_complete": False, "incident": state}

    if close_done and not open_done:
        return incident("ROLL_CLOSE_FILLED_OPEN_MISSING",
                        "close side filled, replacement NOT — position unhedged vs plan; operator review")
    if open_done and not close_done:
        return incident("ROLL_OPEN_FILLED_CLOSE_MISSING",
                        "replacement filled, close side NOT — double exposure; operator review")
    if not (close_done and open_done):
        return incident("ROLL_PARTIAL_PACKAGE", "both sides incomplete — package pending") \
            if (open_partial or any(cum.values())) else {"package_complete": False}

    # both sides complete → PARENT: rolled + realized outcome + projection
    cur.execute("""UPDATE options_strategy_positions SET status='rolled', closed_at=now(),
                   updated_at=now() WHERE strategy_position_id=%s""", (spid,))
    _upsert_outcome(cur, spid, ticket_id, realized_close, fees_close, source)
    cur.execute("""UPDATE options_package_incidents SET resolved_at=now(), resolved_by='package_completed'
                   WHERE strategy_position_id=%s AND ticket_id=%s AND resolved_at IS NULL""",
                (spid, ticket_id))
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
             float(t["contracts"]), ident["strike"], ident["expiration"], t["vwap"], t["fees"]))
    _emit_event_idem(cur, spid, "ROLL", source, ref=f"ticket:{ticket_id}",
                     details={"child": child, "root": root,
                              "parent_realized": realized_close, "parent_fees": fees_close})
    _emit_event_idem(cur, child, "OPEN", source, ref=f"roll_ticket:{ticket_id}",
                     details={"parent": spid, "root": root})
    _queue_projection(cur, child)
    return {"package_complete": True, "child_strategy_position_id": child, "roll_root_id": root}


# ── P0-5: assignment / exercise (MODEL A: option retains the premium) ────────

def _transfer(cur, spid, leg_id, kind, und, acct, shares, strike, prem, ref):
    eff = None
    if prem is not None:
        eff = (float(strike) + prem) if kind in ("assignment_delivery", "exercise_disposition") \
            else (float(strike) - prem)
    cur.execute("""INSERT INTO options_stock_basis_transfers
        (strategy_position_id, leg_id, kind, underlying, account_key, shares, strike,
         premium_per_share_transferred, effective_stock_basis_per_share, evidence_ref,
         premium_accounting_mode, premium_retained_in_options, premium_transferred_to_stock,
         stock_basis_transfer_amount, option_realized_after_transfer)
        VALUES (%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,0,%s,%s)""",
        (spid, leg_id, kind, und, acct, shares, strike, eff, ref,
         PREMIUM_ACCOUNTING_MODE,
         (prem or 0) * shares if prem is not None else None,   # premium stays IN OPTIONS
         float(strike) * shares,                                # stock uses STRIKE-ONLY economics
         (prem or 0) * shares if prem is not None else None))
    return eff


def record_assignment(cur, conn, spid: int, occ: str, source: str, ref: str) -> dict:
    """Short leg assigned. MODEL A: leg closes at 0 → full premium realized in
    OPTION P&L (once). Stock transfer records strike-only economics; effective
    strike shown as explanatory only."""
    cur.execute("""SELECT leg_id, side, contracts, multiplier, strike, option_type, opening_price
                   FROM options_strategy_legs
                   WHERE strategy_position_id=%s AND occ_symbol=%s AND status='open' FOR UPDATE""",
                (spid, occ))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "no open leg for that OCC"}
    leg_id, side, n, mult, strike, otype, op = r
    if side != "short":
        return {"ok": False, "error": "assignment applies to short legs only"}
    cur.execute("UPDATE options_strategy_legs SET status='closed', closed_price=0, closed_at=now() WHERE leg_id=%s",
                (leg_id,))
    cur.execute("SELECT account_key, underlying FROM options_strategy_positions WHERE strategy_position_id=%s",
                (spid,))
    acct, und = cur.fetchone()
    shares = float(n) * int(mult)
    prem = float(op) if op is not None else None
    kind = "assignment_delivery" if otype == "call" else "assignment_acquisition"
    eff = _transfer(cur, spid, leg_id, kind, und, acct, shares, strike, prem, ref)
    _finish_if_flat(cur, spid, "assigned")
    realized = (prem or 0) * shares if prem is not None else None
    if realized is not None:
        _upsert_outcome(cur, spid, None, realized, 0.0, source)
    _emit_event_idem(cur, spid, "ASSIGNED", source, ref=ref,
                     details={"model": PREMIUM_ACCOUNTING_MODE, "shares": shares,
                              "strike_only_stock_amount": float(strike) * shares,
                              "premium_retained_in_options": realized,
                              "effective_strike_explanatory": eff})
    _queue_projection(cur, spid)
    conn.commit()
    process_projection_outbox(cur, conn)
    return {"ok": True, "stock_transfer": kind, "shares": shares,
            "premium_accounting_mode": PREMIUM_ACCOUNTING_MODE,
            "premium_retained_in_options": realized,
            "effective_strike_explanatory": eff}


def record_exercise(cur, conn, spid: int, occ: str, source: str, ref: str) -> dict:
    """Long leg exercised. MODEL A: leg closes at 0 → premium fully realized as
    option COST (negative P&L) once; stock lands at strike-only economics."""
    cur.execute("""SELECT leg_id, side, contracts, multiplier, strike, option_type, opening_price
                   FROM options_strategy_legs
                   WHERE strategy_position_id=%s AND occ_symbol=%s AND status='open' FOR UPDATE""",
                (spid, occ))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "no open leg for that OCC"}
    leg_id, side, n, mult, strike, otype, op = r
    if side != "long":
        return {"ok": False, "error": "exercise applies to long legs only"}
    cur.execute("UPDATE options_strategy_legs SET status='closed', closed_price=0, closed_at=now() WHERE leg_id=%s",
                (leg_id,))
    cur.execute("SELECT account_key, underlying FROM options_strategy_positions WHERE strategy_position_id=%s",
                (spid,))
    acct, und = cur.fetchone()
    shares = float(n) * int(mult)
    prem = float(op) if op is not None else None
    kind = "exercise_acquisition" if otype == "call" else "exercise_disposition"
    eff = _transfer(cur, spid, leg_id, kind, und, acct, shares, strike, prem, ref)
    realized = -(prem or 0) * shares if prem is not None else None
    if realized is not None:
        _upsert_outcome(cur, spid, None, realized, 0.0, source)
    _finish_if_flat(cur, spid, "exercised")
    _emit_event_idem(cur, spid, "EXERCISED", source, ref=ref,
                     details={"model": PREMIUM_ACCOUNTING_MODE, "shares": shares,
                              "premium_cost_in_options": realized,
                              "effective_strike_explanatory": eff})
    _queue_projection(cur, spid)
    conn.commit()
    process_projection_outbox(cur, conn)
    return {"ok": True, "stock_transfer": kind, "shares": shares,
            "premium_accounting_mode": PREMIUM_ACCOUNTING_MODE,
            "effective_strike_explanatory": eff}


def record_expire_worthless(cur, conn, spid: int, occ: str, source: str, ref: str) -> dict:
    cur.execute("""UPDATE options_strategy_legs SET status='closed', closed_price=0, closed_at=now()
                   WHERE strategy_position_id=%s AND occ_symbol=%s AND status='open'
                   RETURNING leg_id, side, contracts, multiplier, opening_price""", (spid, occ))
    r = cur.fetchone()
    if not r:
        conn.rollback()
        return {"ok": False, "error": "no open leg for that OCC"}
    _, side, n, mult, op = r
    if op is not None:
        realized = (float(op) if side == "short" else -float(op)) * float(n) * int(mult)
        _upsert_outcome(cur, spid, None, realized, 0.0, source)
    _finish_if_flat(cur, spid, "expired")
    _emit_event_idem(cur, spid, "EXPIRE_WORTHLESS", source, ref=ref)
    _queue_projection(cur, spid)
    conn.commit()
    process_projection_outbox(cur, conn)
    return {"ok": True}


def _finish_if_flat(cur, spid: int, terminal_status: str):
    cur.execute("SELECT count(*) FROM options_strategy_legs WHERE strategy_position_id=%s AND status='open'",
                (spid,))
    if cur.fetchone()[0] == 0:
        cur.execute("""UPDATE options_strategy_positions SET status=%s, closed_at=now(), updated_at=now()
                       WHERE strategy_position_id=%s""", (terminal_status, spid))


# ── P0-7: concurrent-safe durable projection ─────────────────────────────────

def process_projection_outbox(cur, conn, limit: int = 20) -> dict:
    from options_journal_bridge import ensure_bridge_tables, upsert_trade_instance
    ensure_bridge_tables(cur, conn)
    # stranded PROCESSING recovery
    cur.execute("""UPDATE journal_projection_outbox SET state='RETRY',
                   last_error=COALESCE(last_error,'') || ' [stranded PROCESSING recovered]'
                   WHERE state='PROCESSING'
                     AND claimed_at < now() - make_interval(mins => %s)""", (PROCESSING_TIMEOUT_MIN,))
    conn.commit()
    # atomic claim: no two workers take the same row
    cur.execute("""SELECT outbox_id, strategy_position_id, canonical_state_version
                   FROM journal_projection_outbox
                   WHERE state IN ('NEW','RETRY') AND next_retry_at <= now()
                   ORDER BY outbox_id LIMIT %s
                   FOR UPDATE SKIP LOCKED""", (limit,))
    rows = cur.fetchall()
    for oid, _, _ in rows:
        cur.execute("""UPDATE journal_projection_outbox SET state='PROCESSING', claimed_at=now(),
                       attempts=attempts+1 WHERE outbox_id=%s""", (oid,))
    conn.commit()
    done = failed = skipped_stale = 0
    for oid, spid, sv in rows:
        try:
            if _state_version(cur, spid) != sv:
                # a NEWER state exists — this projection is stale; the newer
                # outbox row (queued by that mutation) owns the write
                cur.execute("""UPDATE journal_projection_outbox SET state='RECONCILED',
                               last_error='superseded by newer state version', projected_at=now()
                               WHERE outbox_id=%s""", (oid,))
                skipped_stale += 1
                conn.commit()
                continue
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
    return {"projected": done, "failed_or_retry": failed, "skipped_stale": skipped_stale}


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    ensure_evidence_tables(cur, conn)
    print("evidence/outbox/transfer/incident tables ensured")
    print(process_projection_outbox(cur, conn))
