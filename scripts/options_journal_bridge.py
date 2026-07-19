#!/usr/bin/env python3
"""options_journal_bridge.py — v1.1 Phase 5: authoritative journal integration.

One option STRATEGY = one primary journal trade. Canonical identity:
  strategy_position_id + roll_root_id + account_key + underlying
NEVER underlying+date (two same-day CSCO strategies stay distinct; a roll
spanning dates stays one roll-root lineage).

Writes:
  - trade_instances (the canonical instance registry) via its own idempotency
    constraint UNIQUE(source_table, source_trade_id):
      source_system='options_lifecycle', source_table='options_strategy_positions',
      source_trade_id=<spid>, trade_uid='options_strategy_positions:<spid>'
  - options_journal_events — OPEN/PARTIAL_FILL/ADJUST/ROLL/PARTIAL_CLOSE/CLOSE/
    EXPIRE_WORTHLESS/ASSIGNED/EXERCISED/CANCELLED, evidence-ref carried.
  - v_options_journal — the canonical read view (full contract incl. legs,
    ancestry, MFE/MAE/giveback, decisions, outcome validity).

Rules (enforced here):
  - Journal rows are created ONLY from fill evidence (bridge is called by
    record_fill_evidence / intake close paths — never by proposals, alerts,
    ticket creation, or 2FA).
  - trade_closed is NEVER written (it is DELETE-rebuilt from schwab_round_trips
    and carries equity round-trip semantics — writing options there would both
    double-count and be destroyed).
  - journal_options_groups (orphan, 2026-06-28) stays frozen — SUPERSEDED.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

JOURNAL_EVENTS = ("OPEN", "PARTIAL_FILL", "ADJUST", "ROLL", "PARTIAL_CLOSE", "CLOSE",
                  "EXPIRE_WORTHLESS", "ASSIGNED", "EXERCISED", "CANCELLED")


def ensure_bridge_tables(cur, conn):
    cur.execute("ALTER TABLE options_strategy_legs ADD COLUMN IF NOT EXISTS basis_source text")
    cur.execute("""CREATE TABLE IF NOT EXISTS options_journal_events (
        event_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        roll_root_id int,
        event text NOT NULL,
        evidence_source text NOT NULL,       -- broker id / 'operator_manual' / 'intake_reconciler'
        evidence_ref text,
        details jsonb,
        at timestamptz DEFAULT now())""")
    cur.execute("""CREATE OR REPLACE VIEW v_options_journal AS
        SELECT p.strategy_position_id,
               p.roll_root_id,
               p.account_key,
               p.underlying,
               'OPTION_STRATEGY'::text AS asset_class,
               p.strategy_type,
               p.broker,
               p.status,
               p.opened_at,
               p.closed_at,
               p.operator_objective,
               p.management_policy_version,
               p.data_quality_status,
               (SELECT json_agg(json_build_object(
                    'occ', l.occ_symbol, 'role', l.leg_role, 'side', l.side,
                    'contracts', l.contracts, 'strike', l.strike,
                    'expiration', l.expiration, 'opening_price', l.opening_price,
                    'opening_fees', l.opening_fees, 'closed_price', l.closed_price,
                    'status', l.status, 'basis_source', l.basis_source))
                FROM options_strategy_legs l
                WHERE l.strategy_position_id = p.strategy_position_id) AS legs,
               (SELECT json_agg(json_build_object('event', e.event, 'at', e.at,
                                                  'source', e.evidence_source,
                                                  'ref', e.evidence_ref) ORDER BY e.event_id)
                FROM options_journal_events e
                WHERE e.strategy_position_id = p.strategy_position_id) AS events,
               o.realized_pnl,
               o.operator_action,
               o.recommendation_at_action,
               s.unrealized_pnl,
               s.max_favorable_excursion,
               s.max_adverse_excursion,
               s.giveback_from_peak,
               (SELECT d.rationale FROM options_lifecycle_decisions d
                WHERE d.strategy_position_id = p.strategy_position_id
                ORDER BY d.decision_id DESC LIMIT 1) AS latest_rationale,
               CASE WHEN o.outcome_id IS NOT NULL THEN 'closed_outcome_recorded'
                    WHEN p.status = 'closed' THEN 'closed_no_outcome_row'
                    ELSE 'open' END AS outcome_validity,
               ('options_strategy_positions:' || p.strategy_position_id) AS trade_uid
        FROM options_strategy_positions p
        LEFT JOIN options_lifecycle_outcomes o USING (strategy_position_id)
        LEFT JOIN options_position_snapshots s ON s.snapshot_id = p.latest_snapshot_id""")
    conn.commit()


def emit_event(cur, conn, spid: int, event: str, source: str, ref: str = "",
               details: dict | None = None):
    assert event in JOURNAL_EVENTS, f"unknown journal event {event}"
    cur.execute("SELECT roll_root_id FROM options_strategy_positions WHERE strategy_position_id=%s",
                (spid,))
    r = cur.fetchone()
    cur.execute("""INSERT INTO options_journal_events
        (strategy_position_id, roll_root_id, event, evidence_source, evidence_ref, details)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (spid, r[0] if r else None, event, source, ref, json.dumps(details or {}, default=str)))
    conn.commit()


def upsert_trade_instance(cur, conn, spid: int) -> dict:
    """Idempotent bridge into the canonical trade_instances registry.
    Called ONLY on fill evidence (open registration w/ fills, or close)."""
    from options_lifecycle_model import strategy_with_legs
    from options_lifecycle_basis import cumulative_basis
    s = strategy_with_legs(cur, spid)
    if not s:
        return {"ok": False, "error": "unknown strategy"}
    legs = s["legs"]
    n_contracts = sum(float(l["contracts"]) for l in legs if l["side"] is not None)
    entry_known = all(l["opening_price"] is not None for l in legs)
    net_entry = (sum((1 if l["side"] == "long" else -1) * float(l["opening_price"] or 0)
                     * float(l["contracts"]) for l in legs) if entry_known else None)
    cur.execute("""SELECT realized_pnl FROM options_lifecycle_outcomes
                   WHERE strategy_position_id=%s ORDER BY outcome_id DESC LIMIT 1""", (spid,))
    o = cur.fetchone()
    realized = float(o[0]) if o and o[0] is not None else None
    cum = cumulative_basis(cur, spid)
    status = {"open": "open", "closing": "open", "closed": "closed", "rolled": "closed",
              "assigned": "closed", "exercised": "closed", "expired": "closed"}.get(s["status"], "open")
    side = ("short" if any(l["side"] == "short" for l in legs) and
            not any(l["side"] == "long" for l in legs) else
            "long" if not any(l["side"] == "short" for l in legs) else "spread")
    lineage = {"kind": "options_lifecycle_v1.1",
               "journal_identity": {"strategy_position_id": spid,
                                    "roll_root_id": s.get("roll_root_id"),
                                    "account_key": s["account_key"],
                                    "underlying": s["underlying"]},
               "strategy_type": s["strategy_type"],
               "legs": [{"occ": l["occ_symbol"].strip(), "side": l["side"],
                         "contracts": float(l["contracts"]), "status": l["status"]} for l in legs],
               "cumulative_roll_basis": cum,
               "deep_link": f"/v3/trading?tab=Options&otab=Lifecycle&spid={spid}"}
    cur.execute("""INSERT INTO trade_instances
        (trade_uid, source_system, source_table, source_trade_id, execution_broker,
         execution_account, execution_environment, trade_mode, symbol, strategy_id,
         status, side, shares, entry_price, entry_time, exit_time, pnl,
         lineage_confidence, lineage_source, lineage_notes, created_at, updated_at)
        VALUES (%s,'options_lifecycle','options_strategy_positions',%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,'exact','options_lifecycle_bridge',%s,now(),now())
        ON CONFLICT (source_table, source_trade_id) DO UPDATE SET
          status=EXCLUDED.status, exit_time=EXCLUDED.exit_time, pnl=EXCLUDED.pnl,
          lineage_notes=EXCLUDED.lineage_notes, updated_at=now()
        RETURNING id, trade_uid""",
        (f"options_strategy_positions:{spid}", str(spid), s["broker"], s["account_key"],
         "paper" if s["broker"] == "alpaca_paper" else "live",
         "paper" if s["broker"] == "alpaca_paper" else "live",
         s["underlying"], f"opt_{s['strategy_type']}",
         status, side, n_contracts, net_entry, s.get("opened_at"),
         s.get("closed_at"), realized, json.dumps(lineage, default=str)))
    row = cur.fetchone()
    conn.commit()
    return {"ok": True, "trade_instance_id": row[0], "trade_uid": row[1], "status": status}


def journal_entry(cur, spid: int) -> dict | None:
    """The canonical journal read for one strategy (from the view)."""
    cur.execute("SELECT row_to_json(v) FROM v_options_journal v WHERE strategy_position_id=%s", (spid,))
    r = cur.fetchone()
    return r[0] if r else None


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    ensure_bridge_tables(cur, conn)
    print("journal bridge tables + view ensured")
