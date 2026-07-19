"""v1.2.3 P0-1 — Schwab execution-level basis parser fixture matrix (pure)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from options_schwab_exec_parser import resolve_leg_execution_basis as R

OCC_C = "CSCO  260918C00120000"
OCC_P = "CSCO  260918P00100000"
OCC_P2 = "CSCO  260918P00095000"


def leg(occ, qty, leg_id=None):
    return {"instrument": {"symbol": occ}, "quantity": qty,
            **({"legId": leg_id} if leg_id is not None else {})}


def act(aid, execs):
    return {"activityId": aid,
            "executionLegs": [{"legId": e.get("legId"), "price": e["px"], "quantity": e["qty"],
                               "time": e.get("t", "2026-07-18T14:30:00Z"),
                               **({"commission": e["fee"]} if "fee" in e else {}),
                               **({"instrument": {"symbol": e["sym"]}} if "sym" in e else {}),
                               "executionId": e.get("eid")} for e in execs]}


def order(oid, legs, acts, status="FILLED", price=None, orderFee=None):
    o = {"orderId": oid, "status": status, "orderLegCollection": legs,
         "orderActivityCollection": acts}
    if price is not None:
        o["price"] = price
    if orderFee is not None:
        o["orderFee"] = orderFee
    return o


def test_single_leg_multi_execution_vwap():
    o = order("o1", [leg(OCC_C, 3, 1)],
              [act("a1", [{"legId": 1, "px": 2.00, "qty": 1, "eid": "e1"}]),
               act("a2", [{"legId": 1, "px": 2.10, "qty": 2, "eid": "e2"}])])
    r = R([o], OCC_C)
    assert r["status"] == "EXACT_EXECUTION_BASIS"
    assert abs(r["vwap"] - (2.00 + 2.10 * 2) / 3) < 1e-5
    assert r["contracts"] == 3 and r["order_id"] == "o1"
    assert set(r["execution_ids"]) == {"e1", "e2"}


def test_two_leg_spread_each_leg_own_vwap_never_package():
    legs = [leg(OCC_P, 2, 1), leg(OCC_P2, 2, 2)]
    acts = [act("a1", [{"legId": 1, "px": 1.50, "qty": 2, "eid": "e1"},
                       {"legId": 2, "px": 0.70, "qty": 2, "eid": "e2"}])]
    o = order("o2", legs, acts, price=0.80)   # package NET credit present
    r1, r2 = R([o], OCC_P), R([o], OCC_P2)
    assert r1["status"] == r2["status"] == "EXACT_EXECUTION_BASIS"
    assert r1["vwap"] == 1.50 and r2["vwap"] == 0.70
    assert r1["vwap"] != 0.80 and r2["vwap"] != 0.80   # package price NEVER a leg basis


def test_debit_and_credit_spread_symmetry():
    legs = [leg(OCC_P, 1, 1), leg(OCC_P2, 1, 2)]
    o = order("o3", legs, [act("a1", [{"legId": 1, "px": 2.20, "qty": 1, "eid": "x1"},
                                      {"legId": 2, "px": 1.10, "qty": 1, "eid": "x2"}])])
    assert R([o], OCC_P)["vwap"] == 2.20
    assert R([o], OCC_P2)["vwap"] == 1.10


def test_four_leg_iron_condor_per_leg():
    occs = ["IC    260918P00090000", "IC    260918P00095000",
            "IC    260918C00110000", "IC    260918C00115000"]
    legs = [leg(occs[i], 1, i + 1) for i in range(4)]
    execs = [{"legId": i + 1, "px": 0.50 + i * 0.25, "qty": 1, "eid": f"e{i}"} for i in range(4)]
    o = order("o4", legs, [act("a1", execs)], price=0.10)
    for i, occ in enumerate(occs):
        r = R([o], occ)
        assert r["status"] == "EXACT_EXECUTION_BASIS" and r["vwap"] == 0.50 + i * 0.25


def test_partial_execution_one_leg_only():
    legs = [leg(OCC_P, 2, 1), leg(OCC_P2, 2, 2)]
    o = order("o5", legs, [act("a1", [{"legId": 1, "px": 1.50, "qty": 1, "eid": "e1"}])],
              status="PARTIALLY_FILLED")
    r = R([o], OCC_P)
    assert r["status"] == "PARTIAL_EXECUTION_BASIS" and r["contracts"] == 1
    assert R([o], OCC_P2)["status"] in ("NO_MATCHING_EXECUTION", "PACKAGE_PRICE_ONLY_UNUSABLE")


def test_repeated_activities_deduped():
    e = {"legId": 1, "px": 2.00, "qty": 1, "eid": "e1", "t": "T1"}
    o = order("o6", [leg(OCC_C, 1, 1)], [act("a1", [e]), act("a1", [e])])
    r = R([o], OCC_C)
    assert r["contracts"] == 1                       # duplicate ingest changed nothing


def test_replaced_order_and_canceled_remainder():
    o_old = order("o7", [leg(OCC_C, 2, 1)],
                  [act("a1", [{"legId": 1, "px": 2.00, "qty": 1, "eid": "e1"}])], status="REPLACED")
    o_new = order("o8", [leg(OCC_C, 1, 1)],
                  [act("a2", [{"legId": 1, "px": 2.05, "qty": 1, "eid": "e2"}])], status="FILLED")
    r = R([o_old, o_new], OCC_C)
    assert r["status"] == "EXACT_EXECUTION_BASIS" and r["order_id"] == "o8"
    o_can = order("o9", [leg(OCC_C, 3, 1)],
                  [act("a3", [{"legId": 1, "px": 2.10, "qty": 2, "eid": "e3"}])], status="CANCELED")
    rc = R([o_can], OCC_C)
    assert rc["status"] == "PARTIAL_EXECUTION_BASIS" and rc["contracts"] == 2


def test_out_of_order_execution_ids_and_times():
    o = order("oA", [leg(OCC_C, 2, 1)],
              [act("a2", [{"legId": 1, "px": 2.10, "qty": 1, "eid": "e9", "t": "2026-07-18T15:00:00Z"}]),
               act("a1", [{"legId": 1, "px": 2.00, "qty": 1, "eid": "e1", "t": "2026-07-18T14:00:00Z"}])])
    r = R([o], OCC_C)
    assert r["first_exec_at"].endswith("14:00:00Z") and r["last_exec_at"].endswith("15:00:00Z")


def test_missing_legid_but_unique_occ_ok():
    o = order("oB", [leg(OCC_C, 1)],   # no legId; only ONE leg with this OCC
              [act("a1", [{"px": 2.00, "qty": 1, "eid": "e1"}])])
    assert R([o], OCC_C)["status"] == "EXACT_EXECUTION_BASIS"


def test_duplicate_occ_legs_ambiguous():
    o = order("oC", [leg(OCC_C, 1), leg(OCC_C, 1)],   # two legs, same OCC, no legIds
              [act("a1", [{"px": 2.00, "qty": 1, "eid": "e1"}])])
    assert R([o], OCC_C)["status"] == "AMBIGUOUS_EXECUTION_MAPPING"


def test_package_price_only_unusable():
    o = order("oD", [leg(OCC_P, 1, 1), leg(OCC_P2, 1, 2)], [], price=0.80)
    r = R([o], OCC_P)
    assert r["status"] == "PACKAGE_PRICE_ONLY_UNUSABLE"
    assert r["package_price_rejected"] == 0.80
    assert "vwap" not in r                           # nothing usable as basis


def test_package_fees_stay_unallocated():
    o = order("oE", [leg(OCC_C, 1, 1)],
              [act("a1", [{"legId": 1, "px": 2.00, "qty": 1, "eid": "e1"}])], orderFee=1.30)
    r = R([o], OCC_C)
    assert r["fees"] is None                          # unknown leg fees stay NULL, never zeroed
    assert r["package_level_unallocated_fees"] == 1.30


def test_leg_attached_fees_used_when_present():
    o = order("oF", [leg(OCC_C, 1, 1)],
              [act("a1", [{"legId": 1, "px": 2.00, "qty": 1, "eid": "e1", "fee": 0.65}])])
    assert R([o], OCC_C)["fees"] == 0.65


def test_wrong_instrument_execution_never_fallback():
    o = order("oG", [leg(OCC_C, 1, 1)],
              [act("a1", [{"legId": 1, "px": 9.99, "qty": 1, "eid": "e1", "sym": OCC_P}])])
    assert R([o], OCC_C)["status"] in ("NO_MATCHING_EXECUTION", "PACKAGE_PRICE_ONLY_UNUSABLE")


def test_broker_data_unavailable_and_no_match():
    assert R(None, OCC_C)["status"] == "BROKER_DATA_UNAVAILABLE"
    assert R([], OCC_C)["status"] == "NO_MATCHING_EXECUTION"


def test_corrected_history_supersedes_partial():
    o_part = order("oH", [leg(OCC_C, 2, 1)],
                   [act("a1", [{"legId": 1, "px": 2.00, "qty": 1, "eid": "e1"}])],
                   status="PARTIALLY_FILLED")
    o_full = order("oH", [leg(OCC_C, 2, 1)],
                   [act("a1", [{"legId": 1, "px": 2.00, "qty": 1, "eid": "e1"}]),
                    act("a2", [{"legId": 1, "px": 2.06, "qty": 1, "eid": "e2"}])], status="FILLED")
    r = R([o_part, o_full], OCC_C)
    assert r["status"] == "EXACT_EXECUTION_BASIS" and abs(r["vwap"] - 2.03) < 1e-9
