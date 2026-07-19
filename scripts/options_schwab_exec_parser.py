#!/usr/bin/env python3
"""options_schwab_exec_parser.py — v1.2.3 P0-1: canonical Schwab execution parser.

Per-leg basis MUST come from execution-level evidence attributable to the exact
OCC leg. An order-level package net price is NEVER a valid per-leg basis; a
different leg's execution is NEVER a fallback. Ambiguity fails honestly.

resolve_leg_execution_basis(orders, occ_symbol) → {
  status: EXACT_EXECUTION_BASIS | PARTIAL_EXECUTION_BASIS |
          AMBIGUOUS_EXECUTION_MAPPING | PACKAGE_PRICE_ONLY_UNUSABLE |
          NO_MATCHING_EXECUTION | BROKER_DATA_UNAVAILABLE,
  contracts, vwap, fees, first_exec_at, last_exec_at,
  order_id, activity_ids, execution_ids, raw_provenance }

Only EXACT_EXECUTION_BASIS may promote a leg to broker-confirmed basis;
PARTIAL persists as incomplete evidence and never promotes the strategy to ok.

Fee policy (source-faithful, enforced): only fees explicitly attached to the
matching execution/leg are attributed; package-level fees are retained as
package_level_unallocated_fees (never divided among legs, never zeroed)."""
from __future__ import annotations


TERMINAL_ORDER_STATUSES = ("FILLED", "REPLACED", "PARTIALLY_FILLED", "CANCELED")


def _order_legs_for_occ(order: dict, occ: str) -> list[dict]:
    return [l for l in (order.get("orderLegCollection") or [])
            if ((l.get("instrument") or {}).get("symbol") or "").strip() == occ.strip()]


def _executions(order: dict) -> list[tuple[dict, dict]]:
    """(activity, executionLeg) pairs in stable order."""
    out = []
    for act in (order.get("orderActivityCollection") or []):
        for el in (act.get("executionLegs") or []):
            out.append((act, el))
    return out


def resolve_leg_execution_basis(orders: list[dict] | None, occ_symbol: str) -> dict:
    occ = occ_symbol.strip()
    if orders is None:
        return {"status": "BROKER_DATA_UNAVAILABLE"}
    best = None
    for order in orders:
        if str(order.get("status", "")).upper() not in TERMINAL_ORDER_STATUSES:
            continue
        legs = _order_legs_for_occ(order, occ)
        if not legs:
            continue
        if len(legs) > 1:
            # duplicate OCC legs inside one order: symbol-only mapping is ambiguous
            # unless executions carry a legId that uniquely resolves — check below
            leg_ids = {l.get("legId") for l in legs}
            if None in leg_ids or len(leg_ids) != len(legs):
                return {"status": "AMBIGUOUS_EXECUTION_MAPPING", "order_id": order.get("orderId"),
                        "reason": f"{len(legs)} order legs share OCC {occ} without unique legIds"}
        target_leg_ids = {l.get("legId") for l in legs if l.get("legId") is not None}
        ordered = int(sum(float(l.get("quantity") or 0) for l in legs))
        fills = []
        pkg_fees = 0.0
        for act, el in _executions(order):
            el_leg = el.get("legId")
            # associate by stable legId when present; else the ONLY leg with this OCC
            if el_leg is not None and target_leg_ids and el_leg not in target_leg_ids:
                continue
            if el_leg is None and len(legs) != 1:
                return {"status": "AMBIGUOUS_EXECUTION_MAPPING", "order_id": order.get("orderId"),
                        "reason": "execution leg lacks legId and OCC maps to multiple order legs"}
            # verify instrument identity when the execution carries it
            el_sym = ((el.get("instrument") or {}).get("symbol") or "").strip()
            if el_sym and el_sym != occ:
                continue
            px, qty = el.get("price"), el.get("quantity")
            if px is None or qty is None:
                continue
            fills.append({"px": float(px), "qty": float(qty),
                          "activity_id": act.get("activityId"),
                          "execution_id": el.get("executionId") or el.get("execution_id") or act.get("activityId"),
                          "time": el.get("time") or act.get("executionTime") or act.get("time"),
                          "fee": el.get("commission") or el.get("fee")})
        if not fills:
            # package price present but no per-leg executions → UNUSABLE, never a basis
            if order.get("price") is not None:
                cand = {"status": "PACKAGE_PRICE_ONLY_UNUSABLE", "order_id": order.get("orderId"),
                        "package_price_rejected": float(order["price"]),
                        "reason": "order-level net price is not a valid per-leg basis"}
                best = best or cand
            continue
        # dedupe repeated activities by (activity_id, execution_id, px, qty, time)
        seen, uniq = set(), []
        for f in fills:
            k = (f["activity_id"], f["execution_id"], f["px"], f["qty"], f["time"])
            if k not in seen:
                seen.add(k)
                uniq.append(f)
        filled = sum(f["qty"] for f in uniq)
        vwap = sum(f["px"] * f["qty"] for f in uniq) / filled
        leg_fees = sum(float(f["fee"]) for f in uniq if f.get("fee") is not None)
        has_leg_fees = any(f.get("fee") is not None for f in uniq)
        if order.get("orderFee") is not None or order.get("fees") is not None:
            pkg_fees = float(order.get("orderFee") or 0) or float(
                (order.get("fees") or {}).get("total", 0) if isinstance(order.get("fees"), dict)
                else order.get("fees") or 0)
        times = sorted(t for t in (f["time"] for f in uniq) if t)
        status = "EXACT_EXECUTION_BASIS" if abs(filled - ordered) < 1e-9 and ordered > 0 \
            else "PARTIAL_EXECUTION_BASIS"
        cand = {"status": status, "contracts": filled, "vwap": round(vwap, 6),
                "fees": round(leg_fees, 4) if has_leg_fees else None,
                "package_level_unallocated_fees": round(pkg_fees, 4) if pkg_fees else None,
                "first_exec_at": times[0] if times else None,
                "last_exec_at": times[-1] if times else None,
                "order_id": order.get("orderId"),
                "activity_ids": sorted({f["activity_id"] for f in uniq if f["activity_id"] is not None}),
                "execution_ids": sorted({str(f["execution_id"]) for f in uniq if f["execution_id"] is not None}),
                "raw_provenance": {"ordered_contracts": ordered, "fills": uniq}}
        # prefer EXACT over PARTIAL over unusable; corrected/replaced history:
        # a later EXACT candidate supersedes earlier PARTIAL
        if best is None or (best["status"] != "EXACT_EXECUTION_BASIS"
                            and cand["status"] == "EXACT_EXECUTION_BASIS"):
            best = cand
    return best or {"status": "NO_MATCHING_EXECUTION"}
