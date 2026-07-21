#!/usr/bin/env python3
"""options_lifecycle_tickets.py — Phase 6: close/roll tickets + lifecycle preflight.

Every action on a position flows through here:

  build (fresh chain per leg, ALL legs or blocked) → approve (hash-bound)
  → 2FA (Telegram pill, house pattern) → ARMED
  → evidence (broker fill or operator-recorded manual) → position updated

Safety invariants, enforced in code:
  - Quotes are refetched at build; a ticket older than
    tickets.quote_max_age_seconds cannot be approved or armed — rebuild it.
  - A spread ticket includes EVERY open leg; any unquotable leg blocks the
    build (never leg out by default — a leg-out ticket requires
    legs_subset + explicit operator_acknowledged_leg_out=True and renders an
    incremental-risk warning).
  - approval_hash = sha256 over the canonical ticket (legs, prices, TIF,
    snapshot id). ANY field change produces a new hash and invalidates the
    prior approval; verify recomputes before arming.
  - NO live submission from this module. Schwab/Fidelity render exact manual
    tickets after 2FA (the Schwab options pilot lane stays disarmed and
    untouched); Alpaca paper closes are recorded from the reconcile lane's
    evidence. A button click NEVER closes a position — only
    record_fill_evidence() with broker or operator-manual evidence does.
  - Partial fills reduce leg contracts and leave the residual position open
    and correctly sized.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from options_lifecycle_model import strategy_with_legs
from options_lifecycle_engine import policy, quote_leg
from options_lifecycle_alerts import resolve_alerts_for


def ensure_ticket_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS options_lifecycle_tickets (
        ticket_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        kind text NOT NULL,                       -- close | roll
        ticket_json jsonb NOT NULL,
        approval_hash text NOT NULL,
        status text NOT NULL DEFAULT 'draft',     -- draft|approved|awaiting_2fa|armed|filled|partial|cancelled|expired|invalidated
        tif text NOT NULL,
        twofa_code text,
        twofa_requested_at timestamptz,
        approved_at timestamptz,
        armed_at timestamptz,
        evidence_json jsonb,
        created_at timestamptz DEFAULT now(),
        updated_at timestamptz DEFAULT now())""")
    # v1.2 P1: idempotency + challenge lineage in the committed builder
    # (were workstation-only ALTERs), plus DB-ENFORCED one-active-ticket-per-key —
    # concurrent requests collapse to one row at the database, not via SELECT-then-INSERT.
    for ddl in (
        "ALTER TABLE options_lifecycle_tickets ADD COLUMN IF NOT EXISTS idempotency_key text",
        "ALTER TABLE options_lifecycle_tickets ADD COLUMN IF NOT EXISTS challenge_generation int NOT NULL DEFAULT 0",
        "ALTER TABLE options_lifecycle_tickets ADD COLUMN IF NOT EXISTS supersedes_challenge_id text",
        "ALTER TABLE options_lifecycle_tickets ADD COLUMN IF NOT EXISTS challenge_revoked_at timestamptz",
        "ALTER TABLE options_lifecycle_tickets ADD COLUMN IF NOT EXISTS challenge_revoke_reason text",
        "ALTER TABLE options_lifecycle_tickets ADD COLUMN IF NOT EXISTS challenge_used_at timestamptz",
        "ALTER TABLE options_lifecycle_tickets ADD COLUMN IF NOT EXISTS request_correlation_id text",
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_active_ticket_per_idem_key
           ON options_lifecycle_tickets (idempotency_key)
           WHERE status IN ('draft','approved','awaiting_2fa','armed','partial')
             AND idempotency_key IS NOT NULL""",
    ):
        cur.execute(ddl)
    cur.execute("""CREATE TABLE IF NOT EXISTS options_lifecycle_outcomes (
        outcome_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        ticket_id int,
        recommendation_at_action text,
        decision_id int,
        operator_action text,                     -- followed | rejected | manual | assignment | expiry
        execution_price numeric,
        realized_pnl numeric,
        max_additional_profit_after numeric,      -- filled by the calibration job later
        loss_avoided_or_forgone numeric,
        assignment_outcome text,
        roll_outcome text,
        slippage numeric,
        timing_verdict text,                      -- early | appropriate | late (calibration job)
        closed_at timestamptz DEFAULT now(),
        meta jsonb)""")
    conn.commit()


def _cfg() -> dict:
    return policy()["tickets"]


def _hash(ticket: dict, tif: str) -> str:
    core = {"legs": ticket["legs"], "net": ticket["net_debit_credit"], "tif": tif,
            "spid": ticket["strategy_position_id"], "quote_ts": ticket["quote_ts"]}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()[:24]


ACTIVE_TICKET_STATUSES = ("draft", "approved", "awaiting_2fa", "armed", "partial")


def _idem_key(spid: int, kind: str, legs: list[dict], tif: str) -> str:
    """v1.1 P2 idempotency: strategy + action + normalized legs/prices + TIF +
    policy version. One ACTIVE ticket per key, ever."""
    from options_lifecycle_engine import policy as _pol
    norm = sorted(
        [{"occ": (l.get("occ_symbol") or l.get("occ_target") or "").strip(),
          "instruction": l["instruction"], "contracts": float(l["contracts"]),
          "limit": float(l["proposed_limit"])} for l in legs],
        key=lambda x: (x["occ"], x["instruction"]))
    core = {"spid": spid, "kind": kind, "legs": norm, "tif": tif,
            "policy": _pol()["policy_version"]}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:24]


def _existing_active(cur, idem_key: str) -> dict | None:
    cur.execute("""SELECT ticket_id, ticket_json, status, approval_hash FROM options_lifecycle_tickets
                   WHERE idempotency_key=%s AND status = ANY(%s)
                   ORDER BY ticket_id DESC LIMIT 1""", (idem_key, list(ACTIVE_TICKET_STATUSES)))
    r = cur.fetchone()
    if not r:
        return None
    t = r[1] if isinstance(r[1], dict) else json.loads(r[1])
    t["ticket_id"], t["status"], t["approval_hash"] = r[0], r[2], r[3]
    t["idempotent_return"] = True   # double click / retry → SAME ticket, no new row
    return t


def _round_tick(x: float, tick: float) -> float:
    return round(round(x / tick) * tick, 2)


def _quote_all_legs(legs: list[dict]) -> tuple[dict, list[str]]:
    quotes, problems = {}, []
    for l in legs:
        q = quote_leg(l)
        if not q.get("ok") or q.get("mid") is None or q.get("bid") is None or q.get("ask") is None:
            problems.append(f"{l['occ_symbol'].strip()}: {q.get('error', 'no two-sided quote')}")
        quotes[l["leg_id"]] = q
    return quotes, problems


def build_close_ticket(cur, conn, spid: int, *, fraction: float = 1.0, tif: str | None = None,
                       legs_subset: list[int] | None = None,
                       operator_acknowledged_leg_out: bool = False) -> dict:
    """Full-structure close ticket (default). legs_subset (leg_ids) is a LEG-OUT
    and refuses without the explicit operator acknowledgement + carries a
    warning. Returns {"blocked": reason} on any data failure — fail closed."""
    c = _cfg()
    s = strategy_with_legs(cur, spid)
    if not s:
        return {"blocked": "unknown strategy position"}
    open_legs = [l for l in s["legs"] if l["status"] == "open"]
    if not open_legs:
        return {"blocked": "no open legs"}
    tif = tif or c["default_tif"]
    if tif not in c["allowed_tif"]:
        return {"blocked": f"TIF {tif} not allowed"}
    target = open_legs
    leg_out_warning = None
    if legs_subset:
        if len(open_legs) > 1 and not operator_acknowledged_leg_out:
            return {"blocked": "leg-out of a multi-leg structure requires explicit operator "
                               "acknowledgement of the incremental risk (never default)"}
        target = [l for l in open_legs if l["leg_id"] in legs_subset]
        if not target:
            return {"blocked": "legs_subset matched nothing"}
        remaining = [l for l in open_legs if l["leg_id"] not in legs_subset]
        if remaining:
            leg_out_warning = ("LEG-OUT: closing " + ", ".join(l["occ_symbol"].strip() for l in target)
                               + " leaves " + ", ".join(l["occ_symbol"].strip() for l in remaining)
                               + " NAKED of its paired leg — risk profile changes materially.")
    quotes, problems = _quote_all_legs(target)
    if problems:
        return {"blocked": "cannot quote every leg: " + "; ".join(problems)}
    now = datetime.now(timezone.utc)
    tlegs, net = [], 0.0
    est_realized, realized_known = 0.0, True
    fees = 0.0
    for l in target:
        q = quotes[l["leg_id"]]
        n = float(l["contracts"]) * fraction
        n = float(int(n)) if n >= 1 else n
        if n <= 0:
            continue
        instruction = "BTC" if l["side"] == "short" else "STC"
        limit = _round_tick(q["mid"], c["price_tick"])
        if c["do_not_cross_nbbo"]:
            limit = min(max(limit, q["bid"]), q["ask"])
        signed = -limit if instruction == "BTC" else limit   # cash impact per contract
        net += signed * n * int(l["multiplier"])
        fees += c["fees_per_contract"] * n
        if l["opening_price"] is not None:
            pnl = ((float(l["opening_price"]) - limit) if l["side"] == "short"
                   else (limit - float(l["opening_price"]))) * n * int(l["multiplier"])
            est_realized += pnl
        else:
            realized_known = False
        tlegs.append({"leg_id": l["leg_id"], "occ_symbol": l["occ_symbol"].strip(),
                      "instruction": instruction, "contracts": n,
                      "bid": q["bid"], "ask": q["ask"], "spread_pct": q.get("spread_pct"),
                      "proposed_limit": limit, "quote_source": q.get("source"),
                      "residual_after": float(l["contracts"]) - n})
    ticket = {"kind": "close", "strategy_position_id": spid, "underlying": s["underlying"],
              "strategy_type": s["strategy_type"], "broker": s["broker"],
              "account_key": s["account_key"], "legs": tlegs,
              "net_debit_credit": round(net, 2),
              "net_label": (f"pay ≈ ${abs(net):,.2f} to close" if net < 0
                            else f"collect ≈ ${net:,.2f} on close"),
              "est_realized_pnl": round(est_realized, 2) if realized_known else None,
              "est_fees": round(fees, 2), "tif": tif,
              "quote_ts": now.isoformat(),
              "quote_max_age_seconds": c["quote_max_age_seconds"],
              "expected_residual": [{"occ": l["occ_symbol"].strip(),
                                     "contracts": float(l["contracts"]) - float(next(
                                         (t["contracts"] for t in tlegs if t["leg_id"] == l["leg_id"]), 0))}
                                    for l in open_legs],
              "leg_out_warning": leg_out_warning,
              "broker_capability": _capability(s),
              "snapshot_note": "quotes fetched at build; approval binds to this exact state"}
    ticket["approval_hash"] = _hash(ticket, tif)
    idem = _idem_key(spid, "close", tlegs, tif)
    existing = _existing_active(cur, idem)
    if existing:
        return existing   # double click / network retry: one ticket, one challenge
    # race-safe: the partial unique index collapses concurrent inserts to ONE row
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, idempotency_key)
        VALUES (%s,'close',%s,%s,%s,%s)
        ON CONFLICT (idempotency_key)
          WHERE status IN ('draft','approved','awaiting_2fa','armed','partial')
          DO NOTHING
        RETURNING ticket_id""",
        (spid, json.dumps(ticket, default=str), ticket["approval_hash"], tif, idem))
    row = cur.fetchone()
    conn.commit()
    if row is None:                      # concurrent request won the insert
        return _existing_active(cur, idem)
    ticket["ticket_id"] = row[0]
    return ticket


def build_roll_ticket(cur, conn, spid: int, *, new_expiration: str,
                      strike_map: dict[str, float], tif: str | None = None) -> dict:
    """Roll = close ALL open legs + open replacements (strike_map: occ→new strike).
    Includes cumulative P&L across roll ancestry and the close-only alternative."""
    c = _cfg()
    s = strategy_with_legs(cur, spid)
    if not s:
        return {"blocked": "unknown strategy position"}
    close_part = build_close_ticket(cur, conn, spid, tif=tif)
    if close_part.get("blocked"):
        return {"blocked": f"close side blocked: {close_part['blocked']}"}
    open_legs = [l for l in s["legs"] if l["status"] == "open"]
    new_legs, problems = [], []
    net_new = 0.0
    d_delta = d_theta = 0.0
    for l in open_legs:
        new_strike = strike_map.get(l["occ_symbol"].strip(), float(l["strike"]))
        probe = {**l, "strike": new_strike, "expiration": new_expiration,
                 "occ_symbol": l["occ_symbol"]}
        q = quote_leg(probe)
        if not q.get("ok") or q.get("mid") is None:
            problems.append(f"replacement {l['option_type']} {new_strike} {new_expiration}: "
                            f"{q.get('error', 'no quote')}")
            continue
        instruction = "STO" if l["side"] == "short" else "BTO"
        limit = _round_tick(q["mid"], c["price_tick"])
        signed = limit if instruction == "STO" else -limit
        net_new += signed * float(l["contracts"]) * int(l["multiplier"])
        if q.get("delta") is not None:
            d_delta += (q["delta"] * (1 if l["side"] == "long" else -1)) * float(l["contracts"]) * 100
        if q.get("theta") is not None:
            d_theta += (q["theta"] * (1 if l["side"] == "long" else -1)) * float(l["contracts"]) * 100
        new_legs.append({"occ_target": f"{s['underlying']} {new_expiration} {l['option_type']} {new_strike}",
                         "instruction": instruction, "side": l["side"],
                         "contracts": float(l["contracts"]), "strike": new_strike,
                         "expiration": new_expiration, "proposed_limit": limit,
                         "bid": q.get("bid"), "ask": q.get("ask"), "delta": q.get("delta")})
    if problems:
        return {"blocked": "cannot quote replacement legs: " + "; ".join(problems)}
    prior = _ancestry_realized(cur, s)
    net_roll = close_part["net_debit_credit"] + net_new
    old_dte = min((l["expiration"] - datetime.now(timezone.utc).date()).days for l in open_legs)
    try:
        new_dte = (datetime.fromisoformat(new_expiration).date() - datetime.now(timezone.utc).date()).days
    except Exception:
        new_dte = None
    ticket = {"kind": "roll", "strategy_position_id": spid, "underlying": s["underlying"],
              "strategy_type": s["strategy_type"], "broker": s["broker"],
              "account_key": s["account_key"],
              "legs": close_part["legs"] + new_legs,
              "close_legs": close_part["legs"], "open_legs": new_legs,
              "net_debit_credit": round(net_roll, 2),
              "net_label": (f"roll for ≈ ${net_roll:,.2f} credit" if net_roll > 0
                            else f"roll costs ≈ ${abs(net_roll):,.2f} debit"),
              "added_duration_days": (new_dte - old_dte) if new_dte is not None else None,
              "delta_change_est": round(d_delta, 1), "theta_change_est": round(d_theta, 2),
              "cumulative_pnl_incl_prior": (round(prior + (close_part.get("est_realized_pnl") or 0), 2)
                                            if close_part.get("est_realized_pnl") is not None else None),
              "prior_rolls_realized": round(prior, 2),
              "alternate_close_only": {"ticket_id": close_part["ticket_id"],
                                       "net": close_part["net_debit_credit"],
                                       "note": "closing without replacing is always available"},
              "est_fees": round(close_part["est_fees"] * 2, 2),
              "tif": close_part["tif"], "quote_ts": close_part["quote_ts"],
              "quote_max_age_seconds": c["quote_max_age_seconds"],
              "broker_capability": _capability(s)}
    ticket["approval_hash"] = _hash(ticket, ticket["tif"])
    idem = _idem_key(spid, "roll", ticket["legs"], ticket["tif"])
    existing = _existing_active(cur, idem)
    if existing:
        return existing
    cur.execute("""INSERT INTO options_lifecycle_tickets
        (strategy_position_id, kind, ticket_json, approval_hash, tif, idempotency_key)
        VALUES (%s,'roll',%s,%s,%s,%s)
        ON CONFLICT (idempotency_key)
          WHERE status IN ('draft','approved','awaiting_2fa','armed','partial')
          DO NOTHING
        RETURNING ticket_id""",
        (spid, json.dumps(ticket, default=str), ticket["approval_hash"], ticket["tif"], idem))
    row = cur.fetchone()
    conn.commit()
    if row is None:
        return _existing_active(cur, idem)
    ticket["ticket_id"] = row[0]
    return ticket


def _ancestry_realized(cur, s: dict) -> float:
    """Realized P&L across this position's roll ancestry (closed legs with both
    prices known). Unknown legs contribute nothing and the UI shows the gap."""
    root = s.get("roll_root_id") or s["strategy_position_id"]
    cur.execute("""SELECT l.side, l.contracts, l.multiplier, l.opening_price, l.closed_price
                   FROM options_strategy_legs l
                   JOIN options_strategy_positions p ON p.strategy_position_id=l.strategy_position_id
                   WHERE p.roll_root_id=%s AND l.status='closed'
                     AND l.opening_price IS NOT NULL AND l.closed_price IS NOT NULL""", (root,))
    total = 0.0
    for side, n, mult, op, cp in cur.fetchall():
        pnl = ((float(op) - float(cp)) if side == "short" else (float(cp) - float(op)))
        total += pnl * float(n) * int(mult)
    return total


def _capability(s: dict) -> dict:
    if s["broker"] == "tradeai_automated":
        return {"route": "tradeai_automated", "note": "paper lane — closes recorded from reconcile evidence"}
    if s["broker"] == "fidelity":
        return {"route": "manual_ticket", "note": "Fidelity is manual-only; exact ticket rendered after 2FA"}
    return {"route": "manual_ticket",
            "note": "Schwab options pilot is DISARMED — exact manual ticket rendered after 2FA; "
                    "no autonomous submission exists"}


def _fresh_enough(ticket: dict) -> bool:
    try:
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(ticket["quote_ts"])).total_seconds()
        return age <= float(ticket.get("quote_max_age_seconds") or 90)
    except Exception:
        return False


def _twofa_text(code: str, ticket: dict, ticket_id: int, generation: int) -> str:
    """v1.1 P2: the pill names the EXACT order — account, position, ticket, legs,
    action, TIF, economics, snapshot time, hash suffix, expiry."""
    strikes = "/".join(str(l.get("occ_symbol") or l.get("occ_target") or "?").strip()
                       for l in ticket["legs"])
    n = "+".join(f"{float(l['contracts']):g}" for l in ticket["legs"])
    acts = "/".join(sorted({l["instruction"] for l in ticket["legs"]}))
    return (f"2FA code {code}" + (f" (reissue #{generation})" if generation > 1 else "") + "\n"
            f"OPTIONS {ticket['kind'].upper()} · ticket #{ticket_id} · pos #{ticket['strategy_position_id']}\n"
            f"{ticket['account_key']} · {ticket['underlying']} {ticket['strategy_type'].replace('_', ' ')}\n"
            f"{acts} {n}× {strikes}\nTIF {ticket['tif']} · {ticket['net_label']}\n"
            f"quotes {str(ticket['quote_ts'])[11:16]}Z · hash …{ticket['approval_hash'][-8:]}\n"
            f"Expires in {_cfg()['twofa_expiry_minutes']} min. Prior codes for this ticket are DEAD.")


def approve_ticket(cur, conn, ticket_id: int, expected_hash: str,
                   correlation_id: str = "") -> dict:
    cur.execute("""SELECT ticket_json, approval_hash, status, tif, challenge_generation
                   FROM options_lifecycle_tickets WHERE ticket_id=%s""", (ticket_id,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "unknown ticket"}
    ticket, stored_hash, status, tif, gen = (r[0] if isinstance(r[0], dict) else json.loads(r[0])), r[1], r[2], r[3], r[4]
    if status not in ("draft", "awaiting_2fa"):
        return {"ok": False, "error": f"ticket is {status}"}
    recomputed = _hash(ticket, tif)
    if not (expected_hash == stored_hash == recomputed):
        cur.execute("UPDATE options_lifecycle_tickets SET status='invalidated', updated_at=now() WHERE ticket_id=%s",
                    (ticket_id,))
        conn.commit()
        return {"ok": False, "error": "approval hash mismatch — ticket changed since it was shown; rebuild"}
    if not _fresh_enough(ticket):
        cur.execute("UPDATE options_lifecycle_tickets SET status='expired', updated_at=now() WHERE ticket_id=%s",
                    (ticket_id,))
        conn.commit()
        return {"ok": False, "error": "quotes stale — rebuild the ticket for fresh prices"}
    reissue = status == "awaiting_2fa"
    code = f"{secrets.randbelow(1000000):06d}"
    # v1.1: reissue EXPLICITLY revokes the prior challenge — never two live codes
    cur.execute("""UPDATE options_lifecycle_tickets SET status='awaiting_2fa', twofa_code=%s,
                   twofa_requested_at=now(), approved_at=COALESCE(approved_at, now()),
                   challenge_generation=challenge_generation+1,
                   supersedes_challenge_id=CASE WHEN %s THEN challenge_generation ELSE supersedes_challenge_id END,
                   challenge_revoked_at=CASE WHEN %s THEN now() ELSE challenge_revoked_at END,
                   challenge_revoke_reason=CASE WHEN %s THEN 'reissued on repeat approve' ELSE challenge_revoke_reason END,
                   request_correlation_id=%s, updated_at=now()
                   WHERE ticket_id=%s RETURNING challenge_generation""",
                (code, reissue, reissue, reissue, correlation_id or None, ticket_id))
    new_gen = cur.fetchone()[0]
    conn.commit()
    from options_lifecycle_alerts import _telegram
    _telegram(_twofa_text(code, {**ticket, "tif": tif}, ticket_id, new_gen))
    return {"ok": True, "status": "awaiting_2fa", "challenge_generation": new_gen,
            "reissued": reissue}


def verify_ticket_2fa(cur, conn, ticket_id: int, code: str) -> dict:
    cur.execute("""SELECT ticket_json, twofa_code, twofa_requested_at, status, tif, approval_hash
                   FROM options_lifecycle_tickets WHERE ticket_id=%s""", (ticket_id,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "unknown ticket"}
    ticket = r[0] if isinstance(r[0], dict) else json.loads(r[0])
    if r[3] != "awaiting_2fa":
        return {"ok": False, "error": f"ticket is {r[3]}"}
    age_min = (datetime.now(timezone.utc) - r[2]).total_seconds() / 60 if r[2] else 999
    if age_min > _cfg()["twofa_expiry_minutes"]:
        cur.execute("UPDATE options_lifecycle_tickets SET status='expired', updated_at=now() WHERE ticket_id=%s",
                    (ticket_id,))
        conn.commit()
        return {"ok": False, "error": "2FA expired — re-approve"}
    if code != r[1]:
        return {"ok": False, "error": "wrong code"}
    if _hash(ticket, r[4]) != r[5]:
        cur.execute("UPDATE options_lifecycle_tickets SET status='invalidated', updated_at=now() WHERE ticket_id=%s",
                    (ticket_id,))
        conn.commit()
        return {"ok": False, "error": "ticket changed after approval — rebuild"}
    cur.execute("""UPDATE options_lifecycle_tickets SET status='armed', armed_at=now(),
                   twofa_code=NULL, challenge_used_at=now(), updated_at=now()
                   WHERE ticket_id=%s""", (ticket_id,))
    conn.commit()
    manual = {"title": f"ARMED {ticket['kind'].upper()} TICKET — enter at {ticket['broker']}",
              "account": ticket["account_key"], "tif": ticket["tif"],
              "lines": [f"{t['instruction']} {t['contracts']:g}× {t.get('occ_symbol', t.get('occ_target'))} "
                        f"limit ${t['proposed_limit']}" for t in ticket["legs"]],
              "net": ticket["net_label"],
              "reminder": "position updates ONLY from broker fill evidence or your recorded manual execution"}
    return {"ok": True, "status": "armed", "manual_ticket": manual}


def record_fill_evidence(cur, conn, ticket_id: int, fills: list[dict], source: str,
                         operator_note: str = "") -> dict:
    """v1.2: DELEGATES to options_fill_evidence.record_broker_evidence — atomic,
    idempotent, cumulative across batches, durable journal projection, correct
    close ordering. This wrapper only preserves the v1.0 call signature."""
    from options_fill_evidence import record_broker_evidence
    return record_broker_evidence(cur, conn, ticket_id, fills, source,
                                  operator_note=operator_note)


def _superseded_record_fill_evidence(cur, conn, ticket_id: int, fills: list[dict], source: str,
                                     operator_note: str = "") -> dict:
    """v1.0 implementation — SUPERSEDED by options_fill_evidence (kept for
    reference only; validator findings #3/#4: premature journal upsert,
    non-cumulative partials). Never called."""
    cur.execute("SELECT ticket_json, status, strategy_position_id FROM options_lifecycle_tickets WHERE ticket_id=%s",
                (ticket_id,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "unknown ticket"}
    if r[1] not in ("armed", "partial"):
        return {"ok": False, "error": f"ticket is {r[1]} — evidence only lands on armed tickets"}
    ticket = r[0] if isinstance(r[0], dict) else json.loads(r[0])
    spid = r[2]
    s = strategy_with_legs(cur, spid)
    applied, realized = [], 0.0
    for f in fills:
        leg = next((l for l in s["legs"] if l["status"] == "open"
                    and l["occ_symbol"].strip() == f["occ_symbol"].strip()), None)
        if not leg:
            return {"ok": False, "error": f"fill references no open leg: {f['occ_symbol']}"}
        n = float(f["contracts"])
        if n > float(leg["contracts"]) + 1e-9:
            return {"ok": False, "error": f"fill {n} exceeds open contracts {leg['contracts']}"}
        px = float(f["price"])
        if abs(n - float(leg["contracts"])) < 1e-9:
            cur.execute("""UPDATE options_strategy_legs SET status='closed', closed_price=%s,
                           closed_at=now() WHERE leg_id=%s""", (px, leg["leg_id"]))
        else:
            cur.execute("""UPDATE options_strategy_legs SET contracts=contracts-%s WHERE leg_id=%s""",
                        (n, leg["leg_id"]))
            cur.execute("""INSERT INTO options_strategy_legs
                (strategy_position_id, occ_symbol, leg_role, option_type, instruction, side,
                 contracts, multiplier, strike, expiration, opening_price, status, closed_price, closed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'closed',%s,now())""",
                (spid, leg["occ_symbol"], leg["leg_role"], leg["option_type"], leg["instruction"],
                 leg["side"], n, leg["multiplier"], leg["strike"], leg["expiration"],
                 leg["opening_price"], px))
        if leg["opening_price"] is not None:
            pnl = ((float(leg["opening_price"]) - px) if leg["side"] == "short"
                   else (px - float(leg["opening_price"]))) * n * int(leg["multiplier"])
            realized += pnl
        applied.append({"occ": f["occ_symbol"], "contracts": n, "price": px})
    s2 = strategy_with_legs(cur, spid)
    all_closed = not [l for l in s2["legs"] if l["status"] == "open"]
    full = all(abs(float(t["contracts"]) - sum(a["contracts"] for a in applied
                                               if a["occ"].strip() == t.get("occ_symbol", "").strip())) < 1e-9
               for t in ticket["legs"] if t.get("occ_symbol"))
    new_status = "filled" if full else "partial"
    cur.execute("""UPDATE options_lifecycle_tickets SET status=%s,
                   evidence_json=COALESCE(evidence_json,'[]'::jsonb) || %s::jsonb, updated_at=now()
                   WHERE ticket_id=%s""",
                (new_status, json.dumps([{"source": source, "fills": applied,
                                          "note": operator_note,
                                          "at": datetime.now(timezone.utc).isoformat()}]), ticket_id))
    # v1.1 P5: journal events + canonical trade_instances bridge — FILL EVIDENCE ONLY
    try:
        from options_journal_bridge import ensure_bridge_tables, emit_event, upsert_trade_instance
        ensure_bridge_tables(cur, conn)
        emit_event(cur, conn, spid, "CLOSE" if all_closed else "PARTIAL_CLOSE",
                   source, ref=f"ticket:{ticket_id}", details={"fills": applied})
        upsert_trade_instance(cur, conn, spid)
    except Exception as _e:
        print(f"  [journal-bridge] non-blocking: {str(_e)[:120]}")
    if all_closed and ticket["kind"] == "close":
        cur.execute("""UPDATE options_strategy_positions SET status='closed', closed_at=now(),
                       updated_at=now() WHERE strategy_position_id=%s""", (spid,))
        resolve_alerts_for(cur, conn, spid)
        cur.execute("""SELECT decision_id, recommendation FROM options_lifecycle_decisions
                       WHERE strategy_position_id=%s AND superseded_by IS NULL
                       ORDER BY decision_id DESC LIMIT 1""", (spid,))
        dec = cur.fetchone()
        cur.execute("""INSERT INTO options_lifecycle_outcomes
            (strategy_position_id, ticket_id, recommendation_at_action, decision_id,
             operator_action, execution_price, realized_pnl, meta)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (spid, ticket_id, dec[1] if dec else None, dec[0] if dec else None,
             "followed" if source != "operator_manual" else "manual",
             None, round(realized, 2) if realized else None,
             json.dumps({"source": source, "fills": applied})))
    conn.commit()
    return {"ok": True, "status": new_status, "applied": applied,
            "realized_recorded": round(realized, 2), "position_closed": all_closed}


def cancel_ticket(cur, conn, ticket_id: int, reason: str = "") -> dict:
    cur.execute("""UPDATE options_lifecycle_tickets SET status='cancelled', updated_at=now()
                   WHERE ticket_id=%s AND status IN ('draft','approved','awaiting_2fa','armed')
                   RETURNING ticket_id""", (ticket_id,))
    ok = cur.fetchone() is not None
    conn.commit()
    return {"ok": ok, "note": "position remains actionable — cancelled tickets change nothing" if ok
            else "ticket not cancellable in its current state"}


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    ensure_ticket_tables(cur, conn)
    print("ticket + outcome tables ensured")
