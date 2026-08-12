"""Shared multi-domain evidence spine for desk memo, enrich, and Telegram.

Assembles portfolio / cash / holdings / risk / catalyst / technicals /
hermes / thesis / learning / open plans into one stable structure.
READ_ONLY_ADVISORY — never invents numbers; missing → DATA_UNAVAILABLE.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _body(domains: dict[str, Any], name: str) -> dict[str, Any]:
    raw = domains.get(name) or {}
    if not isinstance(raw, dict):
        return {}
    d = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    return d if isinstance(d, dict) else {}


def _holding_meta(rows: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    sym = symbol.upper()
    matched = [r for r in rows if str(r.get("symbol") or "").upper() == sym]
    if not matched:
        return {"symbol": sym, "quality": "DATA_UNAVAILABLE"}
    lasts = [_f(r.get("last") or r.get("current_price") or r.get("mark")) for r in matched]
    lasts = [x for x in lasts if x is not None]
    bases = [
        _f(r.get("avg_cost") or r.get("basis") or r.get("avg_cost_per_share") or r.get("cost_basis_per_share"))
        for r in matched
    ]
    bases = [x for x in bases if x is not None and x > 0]
    mvs = [_f(r.get("market_value") or r.get("mv")) for r in matched]
    mvs = [x for x in mvs if x is not None]
    weights = [_f(r.get("weight_pct") or r.get("weight")) for r in matched]
    weights = [x for x in weights if x is not None]
    upls = [_f(r.get("unrealized_pnl_pct") or r.get("upl_pct") or r.get("pnl_pct")) for r in matched]
    upls = [x for x in upls if x is not None]
    last = lasts[0] if lasts else None
    basis = bases[0] if bases else None
    dd = None
    if basis and last is not None and basis > 0:
        dd = (basis - last) / basis * 100.0
    elif upls:
        # Negative UPL% ≈ drawdown from cost when basis row missing
        neg = [u for u in upls if u < 0]
        if neg:
            dd = abs(min(neg))
    return {
        "symbol": sym,
        "last": last,
        "basis": basis,
        "dd_from_basis_pct": dd,
        "upl_pct_min": min(upls) if upls else None,
        "market_value": sum(mvs) if mvs else None,
        "weight_pct": sum(weights) if weights else None,
        "quality": "OK" if last is not None or basis is not None or upls else "PARTIAL",
    }


def attach_broker_catalyst_technicals(
    symbols: list[str],
    *,
    max_symbols: int = 6,
) -> dict[str, Any]:
    """Fail-soft catalyst + technicals for focus symbols."""
    out: dict[str, Any] = {
        "catalyst_by_symbol": {},
        "technicals_by_symbol": {},
        "as_of": _now(),
        "gaps": [],
    }
    syms = [str(s).upper() for s in symbols if s][:max_symbols]
    if not syms:
        out["gaps"].append("no_symbols")
        return out

    # technicals
    try:
        try:
            from lib.data_broker.indicator_snapshot import get_indicator_snapshot
        except Exception:
            from scripts.lib.data_broker.indicator_snapshot import get_indicator_snapshot  # type: ignore
        ind = get_indicator_snapshot(syms) or {}
        by = ind.get("by_symbol") or {}
        for s in syms:
            row = by.get(s) or {}
            if isinstance(row, dict) and row:
                out["technicals_by_symbol"][s] = {
                    "rsi": row.get("rsi"),
                    "rsi_status": row.get("rsi_status"),
                    "sma_50": row.get("sma_50"),
                    "sma_200": row.get("sma_200"),
                    "macd_signal": row.get("macd_signal"),
                    "quality": "OK" if row.get("rsi") is not None else "PARTIAL",
                    "as_of": ind.get("as_of") or ind.get("computed_at"),
                }
            else:
                out["technicals_by_symbol"][s] = {
                    "quality": "DATA_UNAVAILABLE",
                    "gap_reason": "indicator_snapshot_empty",
                }
    except Exception as e:
        out["gaps"].append(f"technicals:{type(e).__name__}")
        for s in syms:
            out["technicals_by_symbol"][s] = {
                "quality": "DATA_UNAVAILABLE",
                "gap_reason": type(e).__name__,
            }

    # catalysts
    try:
        try:
            from db_adapter import _execute as _db_exec
        except Exception:
            from scripts.db_adapter import _execute as _db_exec  # type: ignore

        def _db(sql: str, params=None, fetch: str = "all"):
            return _db_exec(sql, params, fetch=fetch)

        try:
            from lib.data_broker.catalyst_record import get_catalyst_record
            from lib.catalyst_domain import pack_from_broker_record, unavailable_pack
        except Exception:
            from scripts.lib.data_broker.catalyst_record import get_catalyst_record  # type: ignore
            from scripts.lib.catalyst_domain import pack_from_broker_record, unavailable_pack  # type: ignore

        for s in syms:
            try:
                rec = get_catalyst_record(_db, s)
                if isinstance(rec, dict) and rec:
                    out["catalyst_by_symbol"][s] = pack_from_broker_record(rec, symbol=s)
                else:
                    out["catalyst_by_symbol"][s] = unavailable_pack(
                        symbol=s, gap_reason="no_catalyst_record",
                    )
            except Exception as e:
                out["catalyst_by_symbol"][s] = unavailable_pack(
                    symbol=s, gap_reason=type(e).__name__,
                )
    except Exception as e:
        out["gaps"].append(f"catalyst:{type(e).__name__}")
        for s in syms:
            out["catalyst_by_symbol"].setdefault(
                s,
                {
                    "domain": "catalyst",
                    "symbol": s,
                    "quality": "DATA_UNAVAILABLE",
                    "events": [],
                    "gap_reason": type(e).__name__,
                },
            )

    return out


def hermes_spine_for_plans(plan_ids: list[str]) -> dict[str, Any]:
    """Latest hermes findings / open jobs for plan ids."""
    out: dict[str, Any] = {"by_plan": {}, "gaps": []}
    try:
        try:
            from lib.cio_hermes_research import hermes_research_evidence_ref, latest_research_for_plan
        except Exception:
            from scripts.lib.cio_hermes_research import (  # type: ignore
                hermes_research_evidence_ref,
                latest_research_for_plan,
            )
        for pid in plan_ids[:12]:
            if not pid:
                continue
            try:
                out["by_plan"][pid] = {
                    "ref": hermes_research_evidence_ref(pid),
                    "latest": latest_research_for_plan(pid),
                }
            except Exception as e:
                out["by_plan"][pid] = {"gap": type(e).__name__}
    except Exception as e:
        out["gaps"].append(type(e).__name__)
    return out


def evidence_map_lines(spine: dict[str, Any]) -> list[str]:
    """Operator-facing evidence map rows."""
    lines: list[str] = []
    domains = spine.get("domains_present") or []
    as_of = str(spine.get("as_of") or "")[:19]
    lines.append(f"Spine as_of {as_of} · domains: {', '.join(domains) or 'none'}.")
    port = spine.get("portfolio") or {}
    lines.append(
        f"portfolio/cash: total={port.get('total_value')} cash_pct={port.get('cash_pct')} "
        f"quality={port.get('data_quality') or '—'}."
    )
    risk = spine.get("risk") or {}
    lines.append(
        f"risk: heat={risk.get('heat_pct')} stops_active={risk.get('stops_active')}."
    )
    for s, pack in (spine.get("catalyst_by_symbol") or {}).items():
        q = pack.get("quality") or pack.get("quality_state") or "—"
        ne = pack.get("next_event") or {}
        if isinstance(ne, dict) and ne.get("session_date"):
            lines.append(
                f"catalyst/{s}: {q} · next {ne.get('kind')} {ne.get('session_date')} "
                f"({ne.get('severity')})."
            )
        else:
            lines.append(f"catalyst/{s}: {q}" + (f" · {pack.get('gap_reason')}" if pack.get("gap_reason") else "."))
    for s, tech in (spine.get("technicals_by_symbol") or {}).items():
        if tech.get("rsi") is not None:
            lines.append(f"technicals/{s}: RSI={tech.get('rsi')} ({tech.get('rsi_status') or '—'}).")
        else:
            lines.append(
                f"technicals/{s}: {tech.get('quality') or 'DATA_UNAVAILABLE'}"
                + (f" · {tech.get('gap_reason')}" if tech.get("gap_reason") else ".")
            )
    for pid, h in (spine.get("hermes_by_plan") or {}).items():
        ref = (h or {}).get("ref") or {}
        lines.append(
            f"hermes/{pid}: {ref.get('quality_state') or '—'} "
            f"result={ref.get('result_id') or 'none'} open={ref.get('open_research_ids') or []}."
        )
    gaps = spine.get("gaps") or []
    if gaps:
        lines.append("Upstream gaps: " + "; ".join(str(g) for g in gaps[:6]) + ".")
    return lines


def build_evidence_spine(
    *,
    snapshot: Optional[dict[str, Any]] = None,
    thesis: Optional[dict[str, Any]] = None,
    pin: Optional[str] = None,
    material_plans: Optional[list[dict[str, Any]]] = None,
    learning: Optional[list[dict[str, Any]]] = None,
    focus_symbols: Optional[list[str]] = None,
    include_broker_enrich: bool = True,
) -> dict[str, Any]:
    """
    Canonical multi-domain spine for memo / enrich / telegram.

    When snapshot is None, caller should pass portfolio bodies already extracted.
    """
    domains = {}
    if isinstance(snapshot, dict):
        domains = snapshot.get("domains") or snapshot
        if not isinstance(domains, dict):
            domains = {}

    port = _body(domains, "portfolio")
    cash = _body(domains, "cash_buying_power")
    risk = _body(domains, "risk")
    hold = _body(domains, "holdings_detail")

    total_value = _f(port.get("total_value") or cash.get("total_value") or hold.get("total_value"))
    total_cash = _f(cash.get("total_cash"))
    cash_pct = _f(cash.get("cash_pct") or port.get("cash_pct") or cash.get("cash_weight_pct"))
    if cash_pct is None and total_value and total_cash is not None and total_value > 0:
        cash_pct = total_cash / total_value * 100.0

    rows = hold.get("holdings") or hold.get("positions") or hold.get("rows") or []
    if not isinstance(rows, list):
        rows = []

    materials = list(material_plans or [])
    focus = list(focus_symbols or [])
    if not focus:
        focus = ["SCHD", "SPCX"]
        for p in materials:
            for s in p.get("symbols") or []:
                su = str(s).upper()
                if su and su not in focus and su not in ("CASH", "BOOK"):
                    focus.append(su)
        focus = focus[:8]

    name_meta = {s: _holding_meta(rows, s) for s in focus}

    # Prefer aggregated weight from portfolio collection if weight_pct missing
    weights: dict[str, float] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        s = str(r.get("symbol") or "").upper()
        if not s or r.get("is_cash"):
            continue
        w = _f(r.get("weight_pct") or r.get("weight"))
        if w is None:
            mv = _f(r.get("market_value") or r.get("mv"))
            if total_value and mv is not None and total_value > 0:
                w = mv / total_value * 100.0
        if w is not None:
            weights[s] = weights.get(s, 0.0) + w
    for s, meta in name_meta.items():
        if meta.get("weight_pct") is None and s in weights:
            meta["weight_pct"] = weights[s]

    quality = "OK"
    if total_value is None or total_cash is None or cash_pct is None:
        quality = "PARTIAL"

    cat_tech: dict[str, Any] = {
        "catalyst_by_symbol": {},
        "technicals_by_symbol": {},
        "gaps": [],
    }
    if include_broker_enrich:
        cat_tech = attach_broker_catalyst_technicals(focus)

    plan_ids = [str(p.get("plan_id")) for p in materials if p.get("plan_id")]
    hermes = hermes_spine_for_plans(plan_ids)

    domains_present = []
    for name, body in (
        ("portfolio", port),
        ("cash_buying_power", cash),
        ("risk", risk),
        ("holdings_detail", hold),
    ):
        if body:
            domains_present.append(name)
    if cat_tech.get("catalyst_by_symbol"):
        domains_present.append("catalyst")
    if cat_tech.get("technicals_by_symbol"):
        domains_present.append("technicals")
    if hermes.get("by_plan"):
        domains_present.append("hermes_research")
    if thesis:
        domains_present.append("thesis")
    if learning:
        domains_present.append("learning_log")
    if materials:
        domains_present.append("open_plans")

    gaps = list(cat_tech.get("gaps") or []) + list(hermes.get("gaps") or [])

    return {
        "as_of": _now(),
        "pin": pin,
        "thesis": thesis or {},
        "learning": list(learning or []),
        "material_plans": materials,
        "focus_symbols": focus,
        "portfolio": {
            "total_value": total_value,
            "total_cash": total_cash,
            "cash_pct": cash_pct,
            "day_change_pct": _f(port.get("day_change_pct")),
            "holdings_count": port.get("holdings_count") or len(weights),
            "data_quality": quality,
        },
        "risk": {
            "heat_pct": _f(risk.get("portfolio_heat_pct")),
            "stops_active": risk.get("stops_active"),
        },
        "name_meta": name_meta,
        "symbol_weights": weights,
        "catalyst_by_symbol": cat_tech.get("catalyst_by_symbol") or {},
        "technicals_by_symbol": cat_tech.get("technicals_by_symbol") or {},
        "hermes_by_plan": hermes.get("by_plan") or {},
        "domains_present": domains_present,
        "gaps": gaps,
        "authority": "READ_ONLY_ADVISORY",
    }
