#!/usr/bin/env python3
"""options_lifecycle_model.py — Phase 1: canonical strategy-position model.

THE lifecycle desk's persistence layer. Positions are STRATEGIES (covered call,
CSP, protective put, long option, spreads, collar, unknown-multi-leg), never
loose legs — a recognized spread is one economic object and is managed
atomically. Broker state is canonical (Phase 0 §5); these tables are the
reconciled mirror plus the desk's own decision/outcome memory.

Design rules (from the 2026-07-19 diagnosis):
  - UNKNOWN stays UNKNOWN, never zero: nullable columns + data_quality_status.
  - Every economic read persists its own quote evidence (mark, source, ts,
    spread%) — chains are transient in this system (B-4).
  - Roll ancestry is first-class (roll_parent_id / roll_root_id) so cumulative
    credits/debits survive any number of rolls.
  - options_monitored_* (empty, per-leg, 2026-06) are SUPERSEDED by these
    entities and stay frozen; nothing new writes them.
  - DDL commits immediately (fail-soft-rollback gotcha, hit 4x in Defense).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STRATEGY_TYPES = (
    "covered_call", "cash_secured_put", "protective_put", "long_call",
    "long_put", "debit_spread", "credit_spread", "collar", "straddle",
    "strangle", "unknown_multi_leg",
)
POSITION_STATUS = ("open", "closing", "closed", "rolled", "assigned",
                   "exercised", "expired", "unknown")
LEG_ROLES = ("short_call", "long_call", "short_put", "long_put")
DATA_QUALITY = ("ok", "stale", "incomplete_basis", "missing_leg",
                "ambiguous", "unreconciled")
RECOMMENDATIONS = ("HOLD", "LET_MATURE", "HARVEST_PARTIAL", "HARVEST_FULL",
                   "DEFEND", "ROLL", "CLOSE", "ACCEPT_ASSIGNMENT",
                   "EXERCISE_REVIEW", "DATA_BLOCKED")


def ensure_tables(cur, conn) -> None:
    cur.execute("""CREATE TABLE IF NOT EXISTS options_strategy_positions (
        strategy_position_id serial PRIMARY KEY,
        broker text NOT NULL,
        account_key text NOT NULL,
        strategy_type text NOT NULL,
        underlying text NOT NULL,
        status text NOT NULL DEFAULT 'open',
        opened_at timestamptz,
        closed_at timestamptz,
        source text NOT NULL,                    -- broker_sync | paper_lane | operator_manual
        roll_parent_id int REFERENCES options_strategy_positions(strategy_position_id),
        roll_root_id int,
        operator_objective text,                 -- e.g. income | hedge | assignment_ok | thesis
        management_policy_version text,
        latest_snapshot_id int,
        data_quality_status text NOT NULL DEFAULT 'unreconciled',
        linked_share_symbol text,                -- covered/protective: the share leg
        linked_share_qty numeric,
        notes text,
        created_at timestamptz DEFAULT now(),
        updated_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS options_strategy_legs (
        leg_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL REFERENCES options_strategy_positions(strategy_position_id),
        occ_symbol text NOT NULL,                -- canonical OCC: RRRRRRYYMMDD[C/P]SSSSSSSS
        leg_role text NOT NULL,
        option_type text NOT NULL,               -- call | put
        instruction text NOT NULL,               -- BTO/STO at open; BTC/STC to flatten
        side text NOT NULL,                      -- long | short
        contracts numeric NOT NULL,
        multiplier int NOT NULL DEFAULT 100,
        strike numeric NOT NULL,
        expiration date NOT NULL,
        opening_price numeric,                   -- per contract; NULL = UNKNOWN, never 0
        opening_fees numeric,
        current_mark numeric,
        mark_source text,
        quote_timestamp timestamptz,
        broker_position_id text,
        status text NOT NULL DEFAULT 'open',
        closed_price numeric,
        closed_at timestamptz,
        created_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_open_leg_identity
        ON options_strategy_legs (strategy_position_id, occ_symbol, side)
        WHERE status = 'open'""")
    cur.execute("""CREATE TABLE IF NOT EXISTS options_position_snapshots (
        snapshot_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL REFERENCES options_strategy_positions(strategy_position_id),
        snapshot_at timestamptz NOT NULL DEFAULT now(),
        underlying_price numeric,
        legs_json jsonb NOT NULL,                -- per-leg bid/ask/mark/greeks/iv/oi at capture
        strategy_mark numeric,                   -- net mark of the whole structure (signed)
        mark_source text,
        quote_timestamp timestamptz,
        max_spread_pct numeric,                  -- worst leg spread — liquidity truth
        net_delta numeric, net_gamma numeric, net_theta numeric, net_vega numeric,
        iv_shortest_leg numeric,
        dte_nearest int,
        moneyness_pct numeric,                   -- spot vs nearest strike, signed
        unrealized_pnl numeric,
        realized_pnl numeric,                    -- from closed legs/partials + prior rolls
        total_strategy_pnl numeric,
        pct_max_profit_captured numeric,         -- NULL when max profit is unbounded
        max_profit_possible numeric,             -- NULL = unbounded (long options)
        max_favorable_excursion numeric,
        max_adverse_excursion numeric,
        giveback_from_peak numeric,
        extrinsic_value numeric,
        assignment_flags jsonb,                  -- {itm_short:bool, exdiv_date, extrinsic_lt_div:bool, ...}
        data_quality_flags jsonb NOT NULL DEFAULT '[]',
        created_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS options_lifecycle_decisions (
        decision_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL REFERENCES options_strategy_positions(strategy_position_id),
        snapshot_id int NOT NULL REFERENCES options_position_snapshots(snapshot_id),
        policy_version text NOT NULL,
        recommendation text NOT NULL,
        urgency text NOT NULL DEFAULT 'green',   -- green | amber | red
        confidence text,                         -- low | medium | high (never a fake number)
        rationale text NOT NULL,                 -- the exact decision sentence
        alternatives jsonb,                      -- [{action, note}...]
        operator_response text,                  -- accepted | rejected | deferred | none
        operator_response_at timestamptz,
        superseded_by int,
        resolved boolean NOT NULL DEFAULT false,
        eventual_outcome text,
        created_at timestamptz DEFAULT now())""")
    conn.commit()  # DDL commits NOW — before any fail-soft path can roll it back


def occ_symbol(underlying: str, expiration: str, opt_type: str, strike: float) -> str:
    """Canonical OCC identity: root padded to 6, YYMMDD, C/P, strike*1000 in 8."""
    exp = expiration.replace("-", "")[2:]  # 2026-08-21 -> 260821
    return f"{underlying.upper():<6}{exp}{'C' if opt_type.lower().startswith('c') else 'P'}{int(round(strike * 1000)):08d}"


def parse_occ(occ: str) -> dict | None:
    """OCC symbol -> identity dict; None (never a guess) when it doesn't parse."""
    try:
        root = occ[:6].strip()
        yy, mm, dd = int(occ[6:8]), int(occ[8:10]), int(occ[10:12])
        t = occ[12].upper()
        strike = int(occ[13:21]) / 1000.0
        if t not in ("C", "P") or not root:
            return None
        return {"underlying": root, "expiration": f"20{yy:02d}-{mm:02d}-{dd:02d}",
                "option_type": "call" if t == "C" else "put", "strike": strike}
    except Exception:
        return None


def classify_strategy(legs: list[dict], held_shares: float = 0) -> str:
    """Economic grouping from leg shapes. Unknown stays unknown — a structure we
    can't name is managed as unknown_multi_leg with DATA_BLOCKED actions, never
    silently treated as independent legs."""
    if not legs:
        return "unknown_multi_leg"
    calls = [l for l in legs if l["option_type"] == "call"]
    puts = [l for l in legs if l["option_type"] == "put"]
    shorts = [l for l in legs if l["side"] == "short"]
    longs = [l for l in legs if l["side"] == "long"]
    if len(legs) == 1:
        l = legs[0]
        covered = held_shares >= l["contracts"] * l.get("multiplier", 100)
        if l["side"] == "short" and l["option_type"] == "call":
            return "covered_call" if covered else "unknown_multi_leg"  # naked short call is NOT manageable here
        if l["side"] == "short" and l["option_type"] == "put":
            return "cash_secured_put"
        if l["side"] == "long" and l["option_type"] == "put":
            return "protective_put" if covered else "long_put"
        return "long_call"
    if len(legs) == 2:
        if len(calls) == 1 and len(puts) == 1:
            c, p = calls[0], puts[0]
            if c["side"] == "short" and p["side"] == "long":
                return "collar"
            if c["side"] == p["side"] == "long":
                return "straddle" if c["strike"] == p["strike"] else "strangle"
        if len(shorts) == 1 and len(longs) == 1 and calls and puts is not None:
            same_type = (len(calls) == 2 or len(puts) == 2)
            if same_type:
                s, g = shorts[0], longs[0]
                # net direction decides credit vs debit when opening prices known;
                # strike relation is the structural tell and always available
                if s.get("opening_price") is not None and g.get("opening_price") is not None:
                    net = s["opening_price"] - g["opening_price"]
                    return "credit_spread" if net > 0 else "debit_spread"
                return "credit_spread" if abs(s["strike"] - g["strike"]) > 0 else "unknown_multi_leg"
    return "unknown_multi_leg"


def register_strategy(cur, conn, *, broker: str, account_key: str, underlying: str,
                      legs: list[dict], source: str, opened_at=None,
                      operator_objective: str | None = None,
                      held_shares: float = 0, policy_version: str = "",
                      notes: str | None = None) -> int:
    """Create one strategy position + its legs atomically. Legs: dicts with
    option_type, side, instruction, contracts, strike, expiration, and optional
    opening_price/opening_fees/broker_position_id/occ_symbol/multiplier."""
    stype = classify_strategy(legs, held_shares=held_shares)
    dq = "ok"
    if any(l.get("opening_price") is None for l in legs):
        dq = "incomplete_basis"
    if stype == "unknown_multi_leg":
        dq = "ambiguous"
    cur.execute("""INSERT INTO options_strategy_positions
        (broker, account_key, strategy_type, underlying, status, opened_at, source,
         operator_objective, management_policy_version, data_quality_status,
         linked_share_symbol, linked_share_qty, notes)
        VALUES (%s,%s,%s,%s,'open',%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING strategy_position_id""",
        (broker, account_key, stype, underlying.upper(),
         opened_at or datetime.now(timezone.utc), source, operator_objective,
         policy_version, dq,
         underlying.upper() if stype in ("covered_call", "protective_put", "collar") and held_shares else None,
         held_shares or None, notes))
    spid = cur.fetchone()[0]
    cur.execute("UPDATE options_strategy_positions SET roll_root_id=%s WHERE strategy_position_id=%s",
                (spid, spid))
    for l in legs:
        occ = l.get("occ_symbol") or occ_symbol(underlying, str(l["expiration"]), l["option_type"], float(l["strike"]))
        role = (("short_" if l["side"] == "short" else "long_") + l["option_type"])
        cur.execute("""INSERT INTO options_strategy_legs
            (strategy_position_id, occ_symbol, leg_role, option_type, instruction, side,
             contracts, multiplier, strike, expiration, opening_price, opening_fees,
             broker_position_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (spid, occ, role, l["option_type"], l["instruction"], l["side"],
             l["contracts"], l.get("multiplier", 100), l["strike"], l["expiration"],
             l.get("opening_price"), l.get("opening_fees"), l.get("broker_position_id")))
    conn.commit()
    return spid


def strategy_with_legs(cur, spid: int) -> dict | None:
    cur.execute("""SELECT strategy_position_id, broker, account_key, strategy_type, underlying,
                          status, opened_at, closed_at, source, roll_parent_id, roll_root_id,
                          operator_objective, management_policy_version, latest_snapshot_id,
                          data_quality_status, linked_share_symbol, linked_share_qty
                   FROM options_strategy_positions WHERE strategy_position_id=%s""", (spid,))
    r = cur.fetchone()
    if not r:
        return None
    cols = ["strategy_position_id", "broker", "account_key", "strategy_type", "underlying",
            "status", "opened_at", "closed_at", "source", "roll_parent_id", "roll_root_id",
            "operator_objective", "management_policy_version", "latest_snapshot_id",
            "data_quality_status", "linked_share_symbol", "linked_share_qty"]
    pos = dict(zip(cols, r))
    cur.execute("""SELECT leg_id, occ_symbol, leg_role, option_type, instruction, side, contracts,
                          multiplier, strike, expiration, opening_price, opening_fees,
                          current_mark, mark_source, quote_timestamp, status, closed_price, closed_at
                   FROM options_strategy_legs WHERE strategy_position_id=%s ORDER BY leg_id""", (spid,))
    lcols = ["leg_id", "occ_symbol", "leg_role", "option_type", "instruction", "side", "contracts",
             "multiplier", "strike", "expiration", "opening_price", "opening_fees",
             "current_mark", "mark_source", "quote_timestamp", "status", "closed_price", "closed_at"]
    pos["legs"] = [dict(zip(lcols, x)) for x in cur.fetchall()]
    return pos


def open_strategies(cur) -> list[dict]:
    cur.execute("""SELECT strategy_position_id FROM options_strategy_positions
                   WHERE status IN ('open','closing') ORDER BY strategy_position_id""")
    return [strategy_with_legs(cur, r[0]) for r in cur.fetchall()]


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    ensure_tables(cur, conn)
    print("options lifecycle tables ensured")
    # identity self-checks (pure functions, no writes)
    assert occ_symbol("CSCO", "2026-08-21", "call", 125) == "CSCO  260821C00125000"
    assert parse_occ("CSCO  260821C00125000") == {"underlying": "CSCO", "expiration": "2026-08-21",
                                                  "option_type": "call", "strike": 125.0}
    assert classify_strategy([{"option_type": "call", "side": "short", "contracts": 1}], held_shares=100) == "covered_call"
    assert classify_strategy([{"option_type": "call", "side": "short", "contracts": 1}], held_shares=0) == "unknown_multi_leg"
    assert classify_strategy([{"option_type": "put", "side": "long", "contracts": 2}], held_shares=200) == "protective_put"
    assert classify_strategy([{"option_type": "put", "side": "long", "contracts": 2}]) == "long_put"
    assert classify_strategy([
        {"option_type": "call", "side": "short", "strike": 190, "contracts": 2, "opening_price": 7.5},
        {"option_type": "call", "side": "long", "strike": 200, "contracts": 2, "opening_price": 4.1},
    ]) == "credit_spread"
    assert classify_strategy([
        {"option_type": "call", "side": "short", "strike": 190, "contracts": 2},
        {"option_type": "put", "side": "long", "strike": 150, "contracts": 2},
    ]) == "collar"
    print("identity + classification self-checks PASS")
