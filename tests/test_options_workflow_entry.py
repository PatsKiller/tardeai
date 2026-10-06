"""Evidence-linked entries reuse canonical options identities and journal writer."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from test_options_lifecycle_migration import ephemeral_db, _build_all  # noqa: F401
from test_options_workflow_execution import prepared
from test_options_workflow_submission import isolated_database_only  # noqa: F401
from options_fill_evidence import record_entry_evidence
from options_workflow_backfill import replay


def fill(p, ref="exec-1", quantity=1, price=2):
    l = p["legs"][0]
    return {"occ_symbol": l["occ_symbol"], "instruction": "BTO", "contracts": quantity,
            "price": price, "broker_execution_id": ref, "broker_order_id": "fixture-order",
            "executed_at": "2026-10-05T15:00:00+00:00"}


def proposal():
    p = prepared(n=2)
    p["legs"][0]["occ_symbol"] = "TEST  261120C00100000"
    return p


def record(conn, p, fills, ref="fixture-order"):
    return record_entry_evidence(conn.cursor(), conn, proposal=p, fills=fills,
                                 broker="schwab", source_ref=ref, source="broker_fill")


def test_partial_entry_replay_and_independent_same_day_orders(ephemeral_db):
    conn = ephemeral_db
    cur = _build_all(conn)
    p = proposal()
    one = record(conn, p, [fill(p)])
    assert one["inserted"] == 1 and not one["entry_complete"]
    assert record(conn, p, [fill(p)])["idempotent_noop"]
    two = record(conn, p, [fill(p), fill(p, "exec-2", price=3)])
    assert two["entry_complete"] and two["inserted"] == 1
    assert two["strategy_position_id"] == one["strategy_position_id"]
    cur.execute("SELECT contracts, opening_price, opening_fees FROM options_strategy_legs WHERE strategy_position_id=%s", (one["strategy_position_id"],))
    qty, vwap, fees = cur.fetchone()
    assert qty == 2 and float(vwap) == 2.5 and fees is None
    other = record(conn, p, [{**fill(p, "other-exec"), "broker_order_id": "independent-order"}], ref="independent-order")
    assert other["strategy_position_id"] != one["strategy_position_id"]
    cur.execute("SELECT COUNT(*) FROM options_journal_events WHERE strategy_position_id=%s", (one["strategy_position_id"],))
    assert cur.fetchone()[0] == 3  # OPEN + two unique fill events
    cur.execute("SELECT COUNT(*) FROM v_options_journal")
    assert cur.fetchone()[0] == 2


def test_entry_refuses_dry_overfill_and_identity_reuse(ephemeral_db):
    _build_all(ephemeral_db)
    p = proposal()
    with pytest.raises(ValueError, match="Dry-test"):
        record(ephemeral_db, p, [{**fill(p), "environment": "dry_test"}])
    with pytest.raises(ValueError, match="exceed"):
        record(ephemeral_db, p, [fill(p, quantity=3)])
    record(ephemeral_db, p, [fill(p)])
    with pytest.raises(ValueError, match="Conflicting execution"):
        record(ephemeral_db, p, [fill(p, price=3)])
    changed = copy.deepcopy(p)
    changed["premium"] += 1
    with pytest.raises(ValueError, match="different reviewed order"):
        record(ephemeral_db, changed, [fill(changed)])


def test_backfill_never_infers_legacy_strategy():
    rows = [{"id": 1, "symbol": "TEST", "options_proposal_id": None},
            {"id": 2, "symbol": "TEST", "options_proposal_id": "exact",
             "adjusted_params": {"options_evidence_ref": "doc-2", "options_fills": [{"price": 2}]}}]
    writes = []
    project = lambda r: writes.append(r["id"]) or {"ok": True, "idempotent_noop": True}
    dry = replay(lambda *a, **k: rows, project)
    assert dry["eligible"] == [2] and writes == []
    assert dry["review_required"][0]["manual_execution_id"] == 1
    applied = replay(lambda *a, **k: rows, project, apply=True)
    assert writes == [2] and len(applied["review_required"]) == 1


def test_monitoring_realized_pnl_uses_partial_close_evidence(ephemeral_db):
    from options_lifecycle_engine import persist_snapshot
    from options_lifecycle_model import strategy_with_legs
    conn = ephemeral_db
    cur = _build_all(conn)
    p = proposal()
    result = record(conn, p, [fill(p)])
    spid = result["strategy_position_id"]
    s = strategy_with_legs(cur, spid)
    eco = {"flags": [], "legs_json": [], "unrealized_pnl": 40}
    _, first = persist_snapshot(cur, conn, s, eco)
    assert first["realized_pnl"] is None
    leg = s["legs"][0]
    cur.execute("""INSERT INTO options_close_allocations
        (strategy_position_id,ticket_id,leg_id,occ_symbol,contracts,vwap,realized)
        VALUES (%s,101,%s,%s,1,2.5,50)""", (spid,leg["leg_id"],leg["occ_symbol"]))
    conn.commit()
    sid, second = persist_snapshot(cur, conn, s, eco)
    assert second["realized_pnl"] == 50
    cur.execute("SELECT realized_pnl,total_strategy_pnl FROM options_position_snapshots WHERE snapshot_id=%s", (sid,))
    assert tuple(map(float,cur.fetchone())) == (50,90)
    cur.execute("UPDATE options_close_allocations SET realized=NULL WHERE strategy_position_id=%s", (spid,))
    conn.commit()
    _, unknown = persist_snapshot(cur, conn, s, eco)
    assert unknown["realized_pnl"] is None
