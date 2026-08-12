"""CIO desk synthesis v1 — portfolio-grade advisory note under live desk@vN.

READ_ONLY_ADVISORY. Combines thesis + Data Broker snapshot + material plans +
operator learning into one operator-facing desk note (Telegram + /v3/cio).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _body(domains: dict[str, Any], name: str) -> dict[str, Any]:
    raw = domains.get(name) or {}
    if not isinstance(raw, dict):
        return {}
    d = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    return d if isinstance(d, dict) else {}


def _f(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _fmt_usd(n: Optional[float]) -> str:
    if n is None:
        return "DATA_UNAVAILABLE"
    abs_n = abs(n)
    if abs_n >= 1e6:
        return f"${n/1e6:.2f}M"
    if abs_n >= 1e3:
        return f"${n/1e3:.1f}K"
    return f"${n:.0f}"


def _fmt_pct(n: Optional[float], signed: bool = False) -> str:
    if n is None:
        return "DATA_UNAVAILABLE"
    if signed:
        return f"{n:+.2f}%"
    return f"{n:.2f}%"


def _import_cio():
    """Import CIO libs whether PYTHONPATH is repo root or scripts/."""
    try:
        from lib.cio_theses import (  # type: ignore
            safe_current_pin,
            safe_context_block,
            recent_operator_learning,
        )
        from lib.cio_plans import CIOPlanStore  # type: ignore
        from lib.cio_plan_enrichment import is_material_plan  # type: ignore
        return safe_current_pin, safe_context_block, recent_operator_learning, CIOPlanStore, is_material_plan
    except Exception:
        from scripts.lib.cio_theses import (
            safe_current_pin,
            safe_context_block,
            recent_operator_learning,
        )
        from scripts.lib.cio_plans import CIOPlanStore
        from scripts.lib.cio_plan_enrichment import is_material_plan
        return safe_current_pin, safe_context_block, recent_operator_learning, CIOPlanStore, is_material_plan


def collect_desk_inputs() -> dict[str, Any]:
    """Live desk@vN + portfolio + material plans + learning (fail-soft)."""
    (
        safe_current_pin,
        safe_context_block,
        recent_operator_learning,
        CIOPlanStore,
        is_material_plan,
    ) = _import_cio()

    pin = safe_current_pin("desk")
    try:
        thesis = safe_context_block("desk", full=True) or {}
    except TypeError:
        thesis = safe_context_block("desk") or {}

    domains: dict[str, Any] = {}
    try:
        try:
            from lib.data_broker.cio_portfolio import get_cio_snapshot  # type: ignore
        except Exception:
            from scripts.lib.data_broker.cio_portfolio import get_cio_snapshot
        snap = get_cio_snapshot(max_age_s=60) or {}
        domains = snap.get("domains") or snap or {}
        if not isinstance(domains, dict):
            domains = {}
    except Exception:
        domains = {}

    port = _body(domains, "portfolio")
    cash = _body(domains, "cash_buying_power")
    risk = _body(domains, "risk")
    hold = _body(domains, "holdings_detail")

    total_value = _f(port.get("total_value") or cash.get("total_value"))
    total_cash = _f(cash.get("total_cash"))
    cash_pct = _f(cash.get("cash_pct") or port.get("cash_pct") or cash.get("cash_weight_pct"))
    if cash_pct is None and total_value and total_cash is not None and total_value > 0:
        cash_pct = total_cash / total_value * 100.0

    rows = hold.get("holdings") or hold.get("positions") or hold.get("rows") or []
    if not isinstance(rows, list):
        rows = []
    agg: dict[str, float] = defaultdict(float)
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or r.get("ticker") or "").upper()
        if not sym or r.get("is_cash"):
            continue
        w = _f(r.get("weight_pct") or r.get("weight"))
        if w is None:
            mv = _f(r.get("market_value") or r.get("mv"))
            if total_value and mv is not None and total_value > 0:
                w = mv / total_value * 100.0
        if w is not None:
            agg[sym] += w
        by_sym[sym].append(r)
    top = sorted(agg.items(), key=lambda x: -x[1])[:12]

    rps = thesis.get("risk_posture_structured") or {}
    cash_band = _f(rps.get("cash_band_min_pct")) or 20.0
    conc_fire = _f(rps.get("concentration_fire_pct")) or 16.5
    max_name = _f(rps.get("max_single_name_weight_pct")) or 12.0
    deep_dd = _f(rps.get("deep_dd_threshold_pct")) or 25.0

    store = CIOPlanStore()
    materials: list[dict[str, Any]] = []
    for p in store.list_open_plans(limit=80):
        fr = p.get("fire_reasons") or (p.get("extra") or {}).get("fire_reasons") or []
        pp = {**p, "fire_reasons": fr}
        if is_material_plan(pp):
            materials.append(pp)

    # Prefer book-level material (S5, SCHD S6, SPCX S1); demote account-scoped oddities
    def _prio(p: dict[str, Any]) -> tuple:
        st = str(p.get("situation_type") or "")
        syms = [str(s).upper() for s in (p.get("symbols") or [])]
        order = {
            "S5_CASH_DEPLOYMENT": 0,
            "S6_CONCENTRATION_OR_DISPOSITION": 1,
            "S1_POSITION_LIFECYCLE": 2,
            "S8_DEFENSIVE_REGIME": 3,
        }.get(st, 9)
        # demote pure CASH / fixture noise
        demote = 1 if (syms == ["CASH"] or "SPACEX_TEST" in syms or "TEST" in "".join(syms)) else 0
        return (demote, order, str(p.get("plan_id")))

    materials = sorted(materials, key=_prio)

    learning = recent_operator_learning(limit=10)

    return {
        "as_of": _now(),
        "pin": pin,
        "thesis": thesis,
        "thresholds": {
            "cash_band_min_pct": cash_band,
            "max_single_name_weight_pct": max_name,
            "concentration_fire_pct": conc_fire,
            "deep_dd_threshold_pct": deep_dd,
        },
        "portfolio": {
            "total_value": total_value,
            "total_cash": total_cash,
            "cash_pct": cash_pct,
            "day_change_pct": _f(port.get("day_change_pct")),
            "holdings_count": port.get("holdings_count") or len(agg),
            "heat_pct": _f(risk.get("portfolio_heat_pct")),
            "stops_active": risk.get("stops_active"),
            "top_weights": [{"symbol": s, "weight_pct": w} for s, w in top],
            "by_symbol_rows": {k: v for k, v in list(by_sym.items())[:30]},
        },
        "material_plans": materials,
        "learning": learning,
        "authority": "READ_ONLY_ADVISORY",
    }


def render_desk_note(data: Optional[dict[str, Any]] = None, *, telegram: bool = True) -> str:
    """Render operator-facing desk note (Markdown-ish for Telegram)."""
    d = data or collect_desk_inputs()
    pin = d.get("pin") or "desk@?"
    th = d.get("thesis") or {}
    thr = d.get("thresholds") or {}
    port = d.get("portfolio") or {}
    materials: list[dict[str, Any]] = d.get("material_plans") or []
    learning: list[dict[str, Any]] = d.get("learning") or []

    stance = th.get("stance") or "unknown"
    rps = th.get("risk_posture_structured") or thr
    cash_band = thr.get("cash_band_min_pct") or rps.get("cash_band_min_pct") or 20
    max_name = thr.get("max_single_name_weight_pct") or rps.get("max_single_name_weight_pct") or 12
    conc_fire = thr.get("concentration_fire_pct") or rps.get("concentration_fire_pct") or 16.5
    deep_dd = thr.get("deep_dd_threshold_pct") or rps.get("deep_dd_threshold_pct") or 25

    cash_pct = port.get("cash_pct")
    total_value = port.get("total_value")
    total_cash = port.get("total_cash")
    heat = port.get("heat_pct")
    day = port.get("day_change_pct")
    top = port.get("top_weights") or []

    cash_gap = None
    if cash_pct is not None:
        cash_gap = cash_pct - float(cash_band)

    lines: list[str] = []
    if telegram:
        lines.append(f"🏦 *CIO desk note* · READ_ONLY · `{pin}`")
        lines.append(f"stance: *{stance}* · as_of {str(d.get('as_of') or '')[:19]}Z")
    else:
        lines.append(f"# CIO desk note · {pin}")
        lines.append(f"stance: {stance} · as_of {d.get('as_of')}")
    lines.append("────────────────")

    # 1 Thesis header
    lines.append("🎯 *1. Thesis header*")
    lines.append((th.get("summary") or "")[:320] or "(no thesis summary)")
    lines.append(
        f"Risk posture: max_name≥{max_name}% · cash_band≥{cash_band}% · "
        f"deep_DD≥{deep_dd}% · concentration_fire≈{conc_fire}%"
    )
    principles = th.get("principles") or []
    if principles:
        lines.append("Principles: " + "; ".join(str(p) for p in principles[:3]))
    lines.append("")

    # 2 Portfolio snapshot
    lines.append("📊 *2. Portfolio snapshot*")
    lines.append(
        f"Book {_fmt_usd(total_value)} · day {_fmt_pct(day, signed=True)} · "
        f"holdings {port.get('holdings_count') or '—'}"
    )
    lines.append(
        f"Cash {_fmt_usd(total_cash)} ({_fmt_pct(cash_pct)}) vs band {cash_band}% "
        + (f"→ gap {_fmt_pct(cash_gap, signed=True)}" if cash_gap is not None else "")
    )
    lines.append(
        f"Heat {_fmt_pct(heat)} · stops_active {port.get('stops_active') if port.get('stops_active') is not None else '—'}"
    )
    if top:
        top_s = ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in top[:6])
        lines.append(f"Top weights (book): {top_s}")
    lines.append("")

    # 3 Material situations
    lines.append("📍 *3. Material situations* (desk-filtered)")
    # Focus set for operator: S5, SCHD S6, SPCX S1, optionally top real S6
    focus: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for p in materials:
        st = str(p.get("situation_type") or "")
        syms = [str(s).upper() for s in (p.get("symbols") or [])]
        if "TEST" in "".join(syms) or "SPACEX_TEST" in syms:
            continue
        key = f"{st}:{','.join(syms)}"
        if key in seen_keys:
            continue
        # skip account-level CASH concentration noise if book cash already in S5
        if st.startswith("S6") and syms == ["CASH"]:
            continue
        # demote account-scoped extreme weights that disagree with book top_weights
        if st.startswith("S6") and syms:
            book_w = next((t["weight_pct"] for t in top if t["symbol"] == syms[0]), None)
            fire = " ".join(str(x) for x in (p.get("fire_reasons") or []))
            # extract claimed weight from fire like weight_70.2pct
            claimed = None
            for tok in fire.replace(",", " ").split():
                if tok.startswith("weight_") and "pct" in tok:
                    try:
                        claimed = float(tok.replace("weight_", "").replace("pct", ""))
                    except Exception:
                        pass
            # account-scoped if claimed ≫ book weight
            if claimed is not None and claimed >= 25:
                if book_w is None or book_w < float(max_name) * 0.5:
                    continue
            if book_w is not None and book_w < 5 and claimed and claimed >= 30:
                continue
        if st in ("S5_CASH_DEPLOYMENT", "S6_CONCENTRATION_OR_DISPOSITION", "S1_POSITION_LIFECYCLE"):
            focus.append(p)
            seen_keys.add(key)
        if len(focus) >= 5:
            break

    if not focus:
        lines.append("_No open material plans after desk filters._")
    for p in focus:
        st = (p.get("situation_type") or "").replace("_", " ")
        syms = ",".join(p.get("symbols") or []) or "book"
        pid = p.get("plan_id")
        fire = ", ".join(str(x) for x in (p.get("fire_reasons") or [])[:3])
        lines.append(f"• *{st}* · {syms}")
        lines.append(f"  fire: {fire or '—'}")
        rec = (p.get("recommendation") or "").strip()
        # one-line rec
        rec1 = rec.split("\n")[0][:200]
        lines.append(f"  rec: {rec1}")
        ta = (p.get("thesis_alignment") or "").strip()
        if ta:
            lines.append(f"  thesis fit: {ta[:180]}")
        md = (p.get("multi_domain_summary") or "").strip()
        if md:
            lines.append(f"  multi-domain: {md[:180]}")
        lines.append(f"  plan: `{pid}` · pin `{p.get('thesis_version') or pin}`")
    lines.append("")

    # 4 Cross-position
    lines.append("🔗 *4. Cross-position view*")
    # concentration cluster: names near max_name / fire
    near = [t for t in top if t["weight_pct"] >= float(max_name)]
    watch = [t for t in top if float(max_name) * 0.7 <= t["weight_pct"] < float(max_name)]
    if near:
        lines.append(
            "Concentration cluster (book ≥ max_name): "
            + ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in near)
        )
    else:
        lines.append(f"No book names ≥ max_name {max_name}% besides filtered noise.")
    if watch:
        lines.append(
            "Approaching band: "
            + ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in watch[:5])
        )
    # cash runway
    if cash_pct is not None:
        if cash_pct >= float(cash_band) + 15:
            runway = "elevated — multi-quarter optionality; stage only with complete totals"
        elif cash_pct >= float(cash_band):
            runway = "above band — dry powder intentional under defensive_observe"
        else:
            runway = "inside/below band — less buffer"
        lines.append(f"Cash runway: {_fmt_pct(cash_pct)} ({runway})")
    # correlated sleeve hint: ARKX/XAR/XLI industrials/aero
    sleeve = [t for t in top if t["symbol"] in ("ARKX", "XAR", "XLI", "SPCX", "XLB")]
    if sleeve:
        lines.append(
            "Industrial/aero sleeve: "
            + ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in sleeve)
            + " — correlated risk if space/industrials re-rate together"
        )
    # heat
    if heat is not None:
        lines.append(
            f"Portfolio heat {_fmt_pct(heat)} with {port.get('stops_active')} stops marked active — "
            "low heat supports observe; does not authorize new risk from chat."
        )
    lines.append("")

    # 5 Recommendations
    lines.append("✅ *5. Desk recommendations* (under " + f"`{pin}`" + ")")
    # Cash
    if cash_pct is not None and cash_pct >= float(cash_band):
        lines.append(
            f"1. *HOLD / STAGE cash* — {_fmt_pct(cash_pct)} ≫ band {cash_band}%. "
            f"Under {pin} cash is a feature; do not force deploy while totals quality is partial. "
            "Stage only when total_cash/total_value support a sized plan."
        )
    # SCHD
    schd_w = next((t["weight_pct"] for t in top if t["symbol"] == "SCHD"), None)
    if schd_w is not None and schd_w >= float(max_name):
        lines.append(
            f"2. *HOLD SCHD with buffer watch* — book weight {_fmt_pct(schd_w)} "
            f"(fire≈{conc_fire}%). Operator already *deferred* SCHD concentration "
            f"('wait for price buffer') — honor that learning; re-escalate only if weight "
            f"breaks fire or thesis on SCHD changes."
        )
    # SPCX deep DD
    spcx_plan = next(
        (
            p
            for p in materials
            if p.get("situation_type") == "S1_POSITION_LIFECYCLE"
            and "SPCX" in [str(s).upper() for s in (p.get("symbols") or [])]
        ),
        None,
    )
    if spcx_plan:
        lines.append(
            f"3. *HOLD SPCX (lifecycle)* — deep DD from basis is material but book weight "
            f"is small (~2%). Fit with {pin}: escalate awareness, not forced trim; "
            "review hold vs stop-above-BE only as operator action, never auto-stop."
        )
    lines.append(
        f"4. *ESCALATE to operator* any new single-name book weight ≥{max_name}% or "
        f"cash regime change ≥3pp — do not treat account-scoped 40% CASH rows as book concentration."
    )
    lines.append("All actions: READ_ONLY_ADVISORY — no orders/stops from desk note.")
    lines.append("")

    # 6 Learning log
    lines.append("🧠 *6. Learning log* (biases this note)")
    if not learning:
        lines.append("_No recent operator dispositions recorded._")
    else:
        for L in learning[:6]:
            lines.append(
                f"• {L.get('disposition')} · {L.get('situation_type')} · "
                f"{','.join(L.get('symbols') or []) or '—'} · "
                f"{(L.get('note') or '')[:80]} · pin {L.get('thesis_version') or '—'}"
            )
    lines.append("")

    # 7 Revisit + plan ids
    lines.append("🔄 *7. Revisit + ack*")
    plan_ids = [p.get("plan_id") for p in focus if p.get("plan_id")]
    if plan_ids:
        lines.append("Plans: " + " · ".join(f"`{x}`" for x in plan_ids[:6]))
        lines.append("Ack: `/cio ack <plan_id>` or reply `ack` on Telegram thread")
    else:
        lines.append("No material plan_ids in focus set.")
    lines.append(
        f"Revisit: 24h or earlier if cash moves ≥3pp, SCHD weight ≥{conc_fire}%, "
        f"or SPCX makes new lows vs basis."
    )
    lines.append(f"Thesis: `/cio thesis` ({pin})")
    lines.append("No orders/stops from chat · READ_ONLY_ADVISORY")
    return "\n".join(lines)


def render_situation_card_contrast(plan: dict[str, Any]) -> str:
    """Short current-style situation card for side-by-side quality contrast."""
    st = (plan.get("situation_type") or "").replace("_", " ")
    syms = ",".join(plan.get("symbols") or []) or "—"
    fire = ", ".join(str(x) for x in (plan.get("fire_reasons") or [])[:3])
    return "\n".join(
        [
            f"📍 Situation card (legacy thin): {st} · {syms}",
            f"Why: {fire or '—'}",
            f"Summary: {(plan.get('summary') or '')[:160]}",
            f"Rec: {(plan.get('recommendation') or '')[:120]}",
            f"plan_id: `{plan.get('plan_id')}`",
            "_(single-situation, little portfolio context)_",
        ]
    )


def generate_desk_synthesis_v1() -> dict[str, Any]:
    """Return structured payload + rendered note + contrast sample."""
    data = collect_desk_inputs()
    note = render_desk_note(data, telegram=True)
    # pick SCHD S6 or S5 for contrast
    sample = None
    for p in data.get("material_plans") or []:
        if p.get("plan_id") == "plan_79fe9e72f2d4":
            sample = p
            break
    if sample is None and data.get("material_plans"):
        sample = data["material_plans"][0]
    contrast = render_situation_card_contrast(sample) if sample else "(no plan)"
    return {
        "ok": True,
        "as_of": data.get("as_of"),
        "thesis_version": data.get("pin"),
        "note": note,
        "contrast_card": contrast,
        "material_plan_ids": [p.get("plan_id") for p in (data.get("material_plans") or [])][:12],
        "authority": "READ_ONLY_ADVISORY",
    }


if __name__ == "__main__":
    out = generate_desk_synthesis_v1()
    print(out["note"])
    print("\n======== CONTRAST ========\n")
    print(out["contrast_card"])
