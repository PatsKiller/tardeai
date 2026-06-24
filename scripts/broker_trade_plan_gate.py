#!/usr/bin/env python3
"""broker_trade_plan_gate.py — Block live broker routes without an authoritative trade plan.

Watchlist bridge rows must not promote with entry + 2×risk geometry alone (gambling).
Same standard as Proposals tab: trade_plans → strategy card → confluence, not generic R:R.
"""
from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from typing import Any

REQUIRE_TRADE_PLAN = os.getenv("BROKER_REQUIRE_TRADE_PLAN", "1") == "1"

AUTHORITATIVE_SOURCES = frozenset({
    "trade_plans",
    "watchlist_strategy_card",
    "strategy_card",
    "confluence",
    "watchlist_entry_plan",
})

GENERIC_SOURCE_MARKERS = (
    "generic fallback",
    ":1 r:r policy",
    "r:r policy",
    "5% below entry",
)

RR_TOLERANCE = float(os.getenv("BROKER_TRADE_PLAN_RR_TOLERANCE", "0.03"))


def _f(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_basis(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _norm_sources(sources: list | None) -> list[str]:
    return [str(s).strip().lower() for s in (sources or []) if s]


def is_rr_only_target(
    entry: float,
    stop: float,
    target: float,
    *,
    target_rr: float = 2.0,
    tolerance: float | None = None,
) -> bool:
    """True when target is pure R:R math with no technical anchor."""
    tol = RR_TOLERANCE if tolerance is None else tolerance
    if not entry or not stop or not target or entry <= stop or target <= entry:
        return False
    risk = entry - stop
    if risk <= 0:
        return False
    expected = round(entry + risk * float(target_rr), 2)
    return abs(target - expected) <= max(0.02, tol * risk)


def _sources_are_generic_only(sources: list[str]) -> bool:
    if not sources:
        return True
    technical = (
        "trade plan",
        "strategy card",
        "watchlist strategy card",
        "confluence",
        "support",
        "resistance",
        "entry plan",
        "entry from watchlist",
        "stop from watchlist",
        "target from watchlist",
        "level_based",
        "fundamental",
    )
    has_technical = any(any(t in s for t in technical) for s in sources)
    if has_technical:
        return False
    return any(m in s for s in sources for m in GENERIC_SOURCE_MARKERS)


def _load_proposal_row(conn, proposal_id: int) -> dict | None:
    cur = conn.cursor()
    cur.execute(
        """SELECT id, symbol, strategy_id, origin, discovery_source,
                  proposed_entry, proposed_stop, proposed_target1, proposed_rr,
                  sizing_basis
           FROM paper_trade_proposals WHERE id=%s""",
        (proposal_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _find_trade_plan(conn, symbol: str) -> dict | None:
    from strategy_signal_sync import find_trade_plan
    return find_trade_plan(conn, str(symbol).upper())


def _find_watchlist_card(conn, symbol: str) -> dict | None:
    cur = conn.cursor()
    cur.execute(
        """SELECT ideal_entry, stop_loss, target_price, support, resistance, risk_reward
           FROM watchlist_strategy_cards
           WHERE symbol = %s
           ORDER BY updated_at DESC NULLS LAST LIMIT 1""",
        (str(symbol).upper(),),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _find_confluence(conn, symbol: str) -> dict | None:
    try:
        from backfill_trade_plans_for_signals import find_confluence
        return find_confluence(conn, str(symbol).upper())
    except Exception:
        return None


def _card_has_anchor(card: dict) -> bool:
    stop = _f(card.get("stop_loss"))
    target = _f(card.get("target_price"))
    support = _f(card.get("support"))
    resistance = _f(card.get("resistance"))
    if stop and target:
        return True
    if stop and support:
        return True
    if target and resistance:
        return True
    return bool(support and resistance)


def resolve_authoritative_levels(
    conn,
    symbol: str,
    *,
    candidate: dict | None = None,
    quote_cache: dict | None = None,
) -> dict | None:
    """Resolve entry/stop/target from authoritative sources only. None if gambling geometry."""
    import broker_strategy_resolver as bsr

    sym = str(symbol or "").upper().strip()
    c = candidate or {}
    sources: list[str] = []
    plan_source = None

    tp = _find_trade_plan(conn, sym)
    if tp:
        entry = _f(tp.get("entry_high")) or _f(tp.get("entry_low"))
        stop = _f(tp.get("stop_loss"))
        target = _f(tp.get("target_1"))
        if entry and stop and target and entry > stop and target > entry:
            strategy_id = str(tp.get("strategy_id") or "")
            resolved = bsr.resolve_executable_strategy(sym, strategy_id)
            return {
                "entry": round(entry, 2),
                "stop": round(stop, 2),
                "target": round(target, 2),
                "strategy_id": resolved["strategy_id"],
                "plan_source": "trade_plans",
                "authoritative": True,
                "exit_rationale": {
                    "strategy_id": resolved["strategy_id"],
                    "sources": [f"trade_plans #{tp.get('id')}"],
                    "resolve": resolved,
                },
            }

    card = _find_watchlist_card(conn, sym)
    if card:
        c = {**c, **{
            "card_entry": card.get("ideal_entry"),
            "card_stop": card.get("stop_loss"),
            "card_target": card.get("target_price"),
            "card_support": card.get("support"),
            "card_resistance": card.get("resistance"),
        }}

    entry = _f(c.get("limit_price")) or _f(c.get("card_entry"))
    if not entry and c.get("entry_zone_high"):
        entry = _f(c["entry_zone_high"])
    if not entry and quote_cache is not None:
        entry = _f(quote_cache.get(sym))
    if not entry or entry <= 0:
        return None

    stop = _f(c.get("card_stop"))
    target = _f(c.get("card_target"))
    support = _f(c.get("card_support"))
    resistance = _f(c.get("card_resistance"))

    if c.get("entry_zone_low"):
        zl = _f(c["entry_zone_low"])
        if zl and zl < entry and (not stop or stop > zl * 0.98):
            stop = round(zl * 0.98, 2)
            sources.append("stop from watchlist entry zone")

    has_card_anchor = _card_has_anchor(card or {})
    if _f(c.get("card_stop")):
        sources.append("stop from watchlist strategy card")
    if _f(c.get("card_target")):
        sources.append("target from watchlist strategy card")
    if _f(c.get("limit_price")) or _f(c.get("card_entry")):
        sources.append("entry from watchlist entry plan / card")

    conf = _find_confluence(conn, sym)
    if conf:
        cs = _f(conf.get("stop_price"))
        ct = _f(conf.get("target_price"))
        if cs and (not stop or stop <= 0):
            stop = cs
            sources.append("stop from confluence cache")
            plan_source = plan_source or "confluence"
        if ct and (not target or target <= entry):
            target = ct
            sources.append("target from confluence cache")
            plan_source = plan_source or "confluence"

    if not has_card_anchor and not (stop and target):
        return None

    sleeve = str(c.get("wl_strategy") or "")
    resolved = bsr.resolve_executable_strategy(sym, sleeve)
    strategy_id = resolved["strategy_id"]

    entry, stop, target, exit_rationale = bsr.apply_strategy_exit_plan(
        entry, stop, target, strategy_id,
        support=support, resistance=resistance,
    )
    exit_rationale["resolve"] = resolved
    merged_sources = sources + list(exit_rationale.get("sources") or [])
    exit_rationale["sources"] = merged_sources

    if _sources_are_generic_only(_norm_sources(merged_sources)):
        return None

    target_rr = float((exit_rationale.get("target_rr_policy") or 2.0))
    if is_rr_only_target(entry, stop, target, target_rr=target_rr):
        if not any(
            k in " ".join(_norm_sources(merged_sources))
            for k in ("resistance", "support", "strategy card", "confluence", "trade plan")
        ):
            return None

    plan_source = plan_source or ("watchlist_strategy_card" if has_card_anchor else "watchlist_entry_plan")
    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "strategy_id": strategy_id,
        "plan_source": plan_source,
        "authoritative": True,
        "exit_rationale": exit_rationale,
    }


def assess_broker_trade_plan(
    entry: float,
    stop: float,
    target: float,
    strategy_id: str,
    *,
    proposal_id: int | None = None,
    proposal_row: dict | None = None,
    sizing_basis: dict | None = None,
    conn=None,
) -> dict:
    """PASS | WARN | BLOCK — authoritative plan required for live routes."""
    if not REQUIRE_TRADE_PLAN:
        return {
            "status": "PASS",
            "allowed": True,
            "violations": [],
            "warnings": [],
            "required": False,
            "plan_source": "disabled",
            "authoritative": True,
        }

    violations: list[str] = []
    warnings: list[str] = []
    plan_source = None
    authoritative = False

    entry = _f(entry) or 0.0
    stop = _f(stop) or 0.0
    target = _f(target) or 0.0

    row = proposal_row
    basis = sizing_basis or {}
    if row:
        basis = basis or _parse_basis(row.get("sizing_basis"))
        entry = entry or _f(row.get("proposed_entry")) or 0.0
        stop = stop or _f(row.get("proposed_stop")) or 0.0
        target = target or _f(row.get("proposed_target1")) or 0.0
        strategy_id = strategy_id or str(row.get("strategy_id") or "")

    exit_rationale = basis.get("exit_rationale") if isinstance(basis.get("exit_rationale"), dict) else {}
    sources = _norm_sources(exit_rationale.get("sources"))
    plan_source = basis.get("plan_source") or exit_rationale.get("plan_source")

    if entry <= 0 or stop <= 0 or target <= 0:
        violations.append("No authoritative trade plan — entry/stop/target incomplete (live route blocked)")
    elif entry <= stop:
        violations.append("Invalid long plan — entry must be above stop")
    elif target <= entry:
        violations.append("Invalid long plan — target must be above entry")

    import broker_strategy_resolver as bsr
    if bsr.is_watchlist_sleeve(strategy_id):
        violations.append(
            f"Strategy still a watchlist sleeve ({strategy_id}) — reconcile to YAML strategy before live route"
        )

    if sources:
        if _sources_are_generic_only(sources):
            violations.append(
                "No authoritative trade plan — stop/target are generic R:R fallback only (gambling blocked)"
            )
        elif any(m in s for s in sources for m in GENERIC_SOURCE_MARKERS):
            if not any(
                k in " ".join(sources)
                for k in ("resistance", "support", "strategy card", "confluence", "trade plan", "entry plan")
            ):
                violations.append(
                    "No authoritative trade plan — levels lack technical anchor (gambling blocked)"
                )
    elif proposal_id or row:
        if conn is None:
            from db_adapter import _get_conn
            conn = _get_conn()
        sym = str((row or {}).get("symbol") or "").upper()
        if sym:
            auth = resolve_authoritative_levels(conn, sym)
            if auth:
                plan_source = auth.get("plan_source")
                authoritative = True
                ae, ast, atg = auth["entry"], auth["stop"], auth["target"]
                if abs(entry - ae) > 0.05 or abs(stop - ast) > 0.05 or abs(target - atg) > 0.05:
                    warnings.append(
                        f"Stored plan differs from authoritative {plan_source} — refresh bridge before route"
                    )
            else:
                violations.append(
                    "No authoritative trade plan — cannot derive levels from trade_plans/cards/confluence (gambling blocked)"
                )

    target_rr = float(exit_rationale.get("target_rr_policy") or 2.0)
    if not violations and is_rr_only_target(entry, stop, target, target_rr=target_rr):
        if _sources_are_generic_only(sources) or not sources:
            violations.append(
                f"No authoritative trade plan — target is {target_rr:.1f}:1 R:R math only (gambling blocked)"
            )

    if plan_source in AUTHORITATIVE_SOURCES or authoritative:
        if not violations:
            authoritative = True

    if violations:
        status = "BLOCK"
        allowed = False
    elif warnings:
        status = "WARN"
        allowed = True
    else:
        status = "PASS"
        allowed = True

    return {
        "status": status,
        "allowed": allowed,
        "violations": violations,
        "warnings": warnings,
        "required": True,
        "plan_source": plan_source,
        "authoritative": authoritative,
        "exit_rationale": exit_rationale,
        "is_rr_only": is_rr_only_target(entry, stop, target, target_rr=target_rr) if entry and stop and target else False,
    }


def assess_proposal_trade_plan(proposal_id: int, conn=None) -> dict:
    """Assess trade-plan gate for a broker proposal row."""
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()
    row = _load_proposal_row(conn, proposal_id)
    if not row:
        return {
            "status": "BLOCK",
            "allowed": False,
            "violations": [f"proposal #{proposal_id} not found"],
            "warnings": [],
            "required": REQUIRE_TRADE_PLAN,
        }
    return assess_broker_trade_plan(
        _f(row.get("proposed_entry")) or 0,
        _f(row.get("proposed_stop")) or 0,
        _f(row.get("proposed_target1")) or 0,
        str(row.get("strategy_id") or ""),
        proposal_id=proposal_id,
        proposal_row=row,
        conn=conn,
    )