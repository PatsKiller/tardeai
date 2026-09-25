"""CIO options fluency — desk-supported strategies, goal lineage, BUY_READY packet.

Stage 1C / 1D for the Options Desk product contract (2026-09-24).

Rules (binding):
  * Catalog ONLY strategies the desk already generates — no new strategy types.
  * Never call create_goal. Lineage is LINKED or ABSENT; templates are proposals.
  * Never call live Schwab option_chain from Telegram / entry-render paths.
  * Read cached options_desk_latest / proposals only.
  * BUY_READY / ENTRY_NEAR options alt prefers capital-efficient directional
    structures (long_call / debit-class). covered_call on an already-held name
    is the WRONG class for "don't lay out full equity capital" — report
    OPTIONS_ALT_NONE with reason WRONG_STRATEGY_CLASS when that is all the cache
    has.
  * P8: PE/fundamentals grade thesis; IV/HV/ATR/expected-move/Greeks grade
    structure. PE never picks strikes.
  * Elevated ATR/HV vs distance-to-stop cites defined-risk options as preferred
    capital expression — still advisory; Path B 2FA.
  * MBI_BEHAVIOR = 0 — advisory text only; Path B pointer, never order language.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Desk-supported strategies (existing generators / slots). Do not invent.
DESK_STRATEGY_CATALOG: dict[str, dict[str, str]] = {
    "covered_call": {
        "family": "income",
        "cio_line": "Sell calls against ≥100 held shares for income; caps upside to strike.",
        "entry_alt_class": "income_on_held",  # not a stock-replacement for BUY_READY
    },
    "cash_secured_put": {
        "family": "income_entry",
        "cio_line": "Sell puts with cash reserved — get paid to potentially buy at strike.",
        "entry_alt_class": "willingness_to_own",
    },
    "protective_put": {
        "family": "hedge",
        "cio_line": "Buy puts to floor downside on shares already held.",
        "entry_alt_class": "hedge_held",
    },
    "credit_spread": {
        "family": "defined_risk_income",
        "cio_line": "Defined-risk credit (bull put / bear call) — limited loss, limited profit.",
        "entry_alt_class": "defined_risk_directional",
    },
    "long_call": {
        "family": "directional_debit",
        "cio_line": "Buy calls — defined risk (premium), leveraged upside vs buying shares.",
        "entry_alt_class": "stock_replacement_debit",
    },
    "long_put": {
        "family": "directional_debit",
        "cio_line": "Buy puts — defined-risk bearish / hedge expression.",
        "entry_alt_class": "directional_debit",
    },
    "debit_spread": {
        "family": "defined_risk_debit",
        "cio_line": "Debit vertical — defined risk, defined target; capital-efficient vs stock.",
        "entry_alt_class": "stock_replacement_debit",
    },
    "deep_itm_call": {
        "family": "paper_stock_replacement",
        "cio_line": "Deep ITM call as stock-replacement (paper / educational lane today).",
        "entry_alt_class": "stock_replacement_paper",
    },
}

#: Strategies that can stand in for laying out full equity on a BUY_READY thesis.
ENTRY_ALT_PREFERRED = frozenset({
    "long_call", "debit_spread", "deep_itm_call", "credit_spread",
})
#: Explicitly NOT capital-efficient stock replacement for a new entry.
ENTRY_ALT_WRONG_CLASS = frozenset({"covered_call", "protective_put"})

CIO_VERDICT_APPROVE = "APPROVE"
CIO_VERDICT_REJECT = "REJECT"
CIO_VERDICT_MODIFY = "MODIFY"

_OPTIONS_GOAL_RE = re.compile(
    r"(?i)\b(option|covered\s*call|\bCSP\b|cash[\s-]?secured|protective\s*put|"
    r"credit\s*spread|debit\s*spread|long\s*call|LEAP|wheel|IV\s*rank)\b"
)
_OPTIONS_ASK_RE = re.compile(
    r"(?i)\b(option\s*strateg|covered\s*call|cash[\s-]?secured\s*put|\bCSP\b|"
    r"protective\s*put|credit\s*spread|debit\s*spread|long\s*call|LEAP|"
    r"options?\s*play|defined[\s-]?risk\s*call|stock[\s-]?replacement)\b"
)

OPTIONS_DESK_RUNTIME_CANDIDATES = (
    PROJECT_ROOT / "data" / "runtime" / "options_desk_latest.json",
    Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/runtime/options_desk_latest.json"),
)
GOALS_PROJECTION_CANDIDATES = (
    PROJECT_ROOT / "data" / "cio" / "cio_goals_projection.json",
    Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio/cio_goals_projection.json"),
)
ENRICHMENT_CANDIDATES = (
    PROJECT_ROOT / "data" / "portfolios" / "state" / "ticker_enrichment_cache.json",
    Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/ticker_enrichment_cache.json"),
)

PATH_B_CHROME = (
    "Path B: Options Hub → View Chain → preflight → per-order 2FA when ARMED. "
    "Advisory only — nothing is placed from chat."
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def load_options_desk_summary(path: Optional[Path] = None) -> dict[str, Any]:
    if path is not None:
        data = _load_json(path)
        return data if isinstance(data, dict) else {}
    for p in OPTIONS_DESK_RUNTIME_CANDIDATES:
        data = _load_json(p)
        if isinstance(data, dict) and data.get("by_symbol") is not None:
            return data
    return {}


def load_cio_goals(path: Optional[Path] = None) -> list[dict[str, Any]]:
    if path is not None:
        data = _load_json(path)
    else:
        data = None
        for p in GOALS_PROJECTION_CANDIDATES:
            data = _load_json(p)
            if isinstance(data, dict):
                break
    if not isinstance(data, dict):
        return []
    goals = data.get("goals") or {}
    if isinstance(goals, dict):
        return [g for g in goals.values() if isinstance(g, dict)]
    if isinstance(goals, list):
        return [g for g in goals if isinstance(g, dict)]
    return []


def load_enrichment_row(symbol: str) -> dict[str, Any]:
    """House fundamentals for P8 thesis — cache only; never invent."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return {}
    for p in ENRICHMENT_CANDIDATES:
        data = _load_json(p)
        if isinstance(data, dict) and isinstance(data.get(sym), dict):
            return data[sym]
    return {}


def looks_like_options_strategy_ask(text: str) -> bool:
    return bool(_OPTIONS_ASK_RE.search(text or ""))


def catalog_for_cio() -> list[dict[str, str]]:
    """Every desk-supported strategy with the one-line CIO meaning."""
    out = []
    for sid, meta in DESK_STRATEGY_CATALOG.items():
        out.append({
            "strategy_id": sid,
            "family": meta["family"],
            "cio_line": meta["cio_line"],
            "entry_alt_class": meta["entry_alt_class"],
        })
    return out


def goal_lineage_for(
    symbol: str,
    strategy: str,
    *,
    goals: Optional[list[dict[str, Any]]] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
) -> dict[str, Any]:
    """LINKED only when an open goal names the symbol and options language.

    Never invents a goal_id. Stamps linked_sector / linked_industry / strategy_id
    when present on the goal or passed from the evidence row (additive lineage).
    """
    sym = (symbol or "").upper().strip()
    strat = (strategy or "").strip().lower()
    rows = goals if goals is not None else load_cio_goals()
    options_goals = []
    for g in rows:
        if str(g.get("status") or "open").lower() not in ("open", "active", ""):
            continue
        blob = " ".join(
            str(g.get(k) or "")
            for k in ("title", "description", "thesis_summary", "success_criteria")
        )
        if not _OPTIONS_GOAL_RE.search(blob):
            continue
        options_goals.append(g)
        linked = [str(s).upper() for s in (g.get("linked_symbols") or [])]
        if sym and sym in linked:
            g_sector = g.get("linked_sector") or g.get("sector") or sector
            g_industry = g.get("linked_industry") or g.get("industry") or industry
            g_strat = g.get("strategy_id") or g.get("strategy") or (strat or None)
            return {
                "status": "LINKED",
                "goal_id": g.get("goal_id"),
                "title": g.get("title"),
                "symbol": sym,
                "strategy": strat or None,
                "strategy_id": g_strat,
                "sector": g_sector,
                "industry": g_industry,
                "linked_sector": g_sector,
                "linked_industry": g_industry,
                "note": (
                    "linked_symbols match + options language in goal text"
                    + (f"; sector={g_sector}" if g_sector else "")
                    + (f"; industry={g_industry}" if g_industry else "")
                    + (f"; strategy_id={g_strat}" if g_strat else "")
                ),
            }
    return {
        "status": "ABSENT",
        "goal_id": None,
        "symbol": sym or None,
        "strategy": strat or None,
        "strategy_id": strat or None,
        "sector": sector,
        "industry": industry,
        "linked_sector": sector,
        "linked_industry": industry,
        "options_goals_open": len(options_goals),
        "note": (
            "no open cio_goals link this symbol to an options strategy "
            f"(options-ish open goals scanned: {len(options_goals)})"
        ),
    }


def gather_options_house_facts(
    symbols: Optional[list[str]] = None,
    *,
    desk: Optional[dict[str, Any]] = None,
    goals: Optional[list[dict[str, Any]]] = None,
    memory_outcomes: Optional[list[dict[str, Any]]] = None,
    memory_notes: Optional[list[dict[str, Any]]] = None,
    memory_flags: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """House facts for CIO replies — cache only, no live chain.

    When MEMORY_BEHAVIOR_INFLUENCE_OPTIONS=1, attaches a bounded memory
    envelope for the first symbol (Slice B). Fail-closed if empty.
    """
    desk = desk if desk is not None else load_options_desk_summary()
    by_sym = desk.get("by_symbol") if isinstance(desk.get("by_symbol"), dict) else {}
    syms = [str(s).upper() for s in (symbols or []) if str(s).strip()]
    per: dict[str, Any] = {}
    for sym in syms:
        rows = by_sym.get(sym) or []
        per[sym] = {
            "proposals": rows,
            "strategies": sorted({str(r.get("strategy") or "") for r in rows if r.get("strategy")}),
            "goal_lineage": goal_lineage_for(
                sym, (rows[0].get("strategy") if rows else ""), goals=goals,
            ),
        }
    out: dict[str, Any] = {
        "as_of": desk.get("generated_at"),
        "proposal_count": desk.get("proposal_count"),
        "strategy_counts": desk.get("strategy_counts") or {},
        "catalog": catalog_for_cio(),
        "by_symbol": per,
        "source": "options_desk_latest_cache",
        "live_chain": False,
    }
    # Slice B — scoped options memory (does not flip global MBI).
    if syms:
        try:
            from scripts.lib.options_memory_envelope import build_options_memory_envelope
        except ImportError:
            from lib.options_memory_envelope import build_options_memory_envelope  # type: ignore
        env = build_options_memory_envelope(
            syms[0],
            flags=memory_flags,
            outcomes=memory_outcomes,
            learning_notes=memory_notes,
        )
        out["memory_envelope"] = env
        if env.get("applied"):
            out["memory_sources"] = list(env.get("sources") or [])
    return out


def format_cio_options_opinion(
    facts: dict[str, Any],
    *,
    symbols: Optional[list[str]] = None,
    memory_envelope: Optional[dict[str, Any]] = None,
) -> str:
    """Plain CIO prose for finalize_operator_reply — not a specialist persona."""
    lines = [
        "Options desk (house facts — cached proposals, not a live Schwab pull):",
    ]
    counts = facts.get("strategy_counts") or {}
    if counts:
        bits = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        lines.append(f"Desk mix: {bits} (as_of {facts.get('as_of') or '—'}).")
    lines.append("Strategies this desk supports:")
    for row in (facts.get("catalog") or [])[:8]:
        lines.append(f"  · {row['strategy_id']}: {row['cio_line']}")
    for sym in [str(s).upper() for s in (symbols or []) if str(s).strip()][:3]:
        block = (facts.get("by_symbol") or {}).get(sym) or {}
        strats = block.get("strategies") or []
        lineage = block.get("goal_lineage") or {}
        if strats:
            lines.append(f"{sym} on desk: {', '.join(strats)}.")
        else:
            lines.append(f"{sym}: no cached options proposals — check Options Hub / Force scan.")
        lines.append(
            f"  Goal lineage: {lineage.get('status')} — {lineage.get('note') or ''}"
        )
        # Surface first-class GUIDs when stamped on cached proposals (Slice A).
        props = block.get("proposals") or []
        if props:
            first = props[0] if isinstance(props[0], dict) else {}
            sg = first.get("option_strategy_guid")
            cg = first.get("contract_guid")
            if sg or cg:
                lines.append(
                    "  Identity: "
                    + (f"strategy_guid={sg[:8]}…" if sg else "strategy_guid=—")
                    + " · "
                    + (f"contract_guid={cg[:8]}…" if cg else "contract_guid=—")
                )
    # Slice B — scoped memory envelope (flag-gated; fail-closed if empty).
    env = memory_envelope if isinstance(memory_envelope, dict) else facts.get("memory_envelope")
    if isinstance(env, dict) and env.get("applied") and env.get("prose"):
        lines.append("")
        lines.append(str(env["prose"]))
    lines.append(PATH_B_CHROME)
    return "\n".join(lines)


def build_thesis_indicators(
    symbol: str,
    *,
    ev: Optional[dict[str, Any]] = None,
    enrichment: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """P8 equity thesis stack — PE grades thesis; never used to pick strikes."""
    ev = ev or {}
    enr = enrichment if enrichment is not None else load_enrichment_row(symbol)
    pe = _f(ev.get("pe") if ev.get("pe") is not None else enr.get("pe") or enr.get("pe_ratio"))
    forward_pe = _f(
        ev.get("forward_pe") if ev.get("forward_pe") is not None else enr.get("forward_pe")
    )
    peg = _f(ev.get("peg") if ev.get("peg") is not None else enr.get("peg"))
    catalyst = ev.get("catalyst") or None
    sector = ev.get("sector") or enr.get("sector")
    industry = ev.get("industry") or enr.get("industry")
    drivers: list[str] = []
    if pe is not None:
        drivers.append(f"PE {pe:.2f} on file (thesis grade only — not a strike input)")
    else:
        drivers.append("PE MISSING — thesis PE not on house file")
    if forward_pe is not None:
        drivers.append(f"forward PE {forward_pe:.2f}")
    if peg is not None:
        drivers.append(f"PEG {peg:.2f}")
    if catalyst:
        drivers.append(f"catalyst: {str(catalyst)[:120]}")
    if sector:
        drivers.append(f"sector {sector}")
    return {
        "section": "thesis",
        "symbol": (symbol or "").upper(),
        "pe": pe,
        "pe_status": "PRESENT" if pe is not None else "MISSING",
        "forward_pe": forward_pe,
        "peg": peg,
        "catalyst": catalyst,
        "sector": sector,
        "industry": industry,
        "drivers": drivers,
        "note": "PE/fundamentals grade whether the bullish thesis is expressible; they do not pick strikes.",
    }


#: ATR ≥ this fraction of (price − stop) → prefer defined-risk options vs full equity (P8).
#: Shared by structure indicators and Hub Stage 1E entry_state conviction — do not fork.
ATR_VS_STOP_ELEVATED = 0.40


def atr_volatility_elevated(
    *,
    price: Any = None,
    stop: Any = None,
    atr: Any = None,
) -> tuple[bool, float | None, float | None]:
    """Pure ATR/stop preference rule used by P8 structure + Stage 1E Hub Ideas.

    Returns (volatility_elevated, atr_vs_distance_to_stop, distance_to_stop).
    """
    px = _f(price)
    st = _f(stop)
    atr_v = _f(atr)
    dist_stop = None
    if px is not None and st is not None and px > st:
        dist_stop = px - st
    atr_vs_stop = None
    vol_elevated = False
    if atr_v is not None and dist_stop is not None and dist_stop > 0:
        atr_vs_stop = round(atr_v / dist_stop, 2)
        vol_elevated = atr_vs_stop >= ATR_VS_STOP_ELEVATED
    return vol_elevated, atr_vs_stop, dist_stop


def build_structure_indicators(
    proposal: Optional[dict[str, Any]],
    *,
    price: Any = None,
    stop: Any = None,
    target: Any = None,
    atr: Any = None,
    enrichment: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """P8 options structure stack — IV/HV/ATR/expected-move/Greeks/OI."""
    p = proposal or {}
    enr = enrichment or {}
    px = _f(price)
    st = _f(stop)
    tg = _f(target)
    atr_v = _f(atr if atr is not None else enr.get("atr") or p.get("atr"))
    iv_rank = _f(p.get("iv_rank") if p.get("iv_rank") is not None else enr.get("iv_rank"))
    expected_move = _f(p.get("expected_move") or p.get("expected_move_pct"))
    delta = _f(p.get("delta"))
    gamma = _f(p.get("gamma"))
    theta = _f(p.get("theta"))
    vega = _f(p.get("vega"))
    oi = p.get("oi") or p.get("open_interest")
    volume = p.get("volume")
    dte = p.get("dte")
    vol_elevated, atr_vs_stop, dist_stop = atr_volatility_elevated(
        price=px, stop=st, atr=atr_v,
    )
    dist_target = None
    if px is not None and tg is not None and tg > px:
        dist_target = tg - px
    drivers: list[str] = []
    if iv_rank is not None:
        drivers.append(f"IV rank {iv_rank:.1f}")
    else:
        drivers.append("IV rank MISSING on cached proposal")
    if atr_v is not None:
        drivers.append(f"ATR {atr_v:.2f}")
        if atr_vs_stop is not None:
            drivers.append(
                f"ATR/distance-to-stop={atr_vs_stop:.2f}"
                + (" (elevated — favors defined-risk options over full equity)" if vol_elevated else "")
            )
    else:
        drivers.append("ATR/HV MISSING")
    if expected_move is not None:
        drivers.append(f"expected move {expected_move}")
    if delta is not None:
        drivers.append(f"delta {delta:.2f}")
    if oi is not None:
        drivers.append(f"OI {oi}")
    if dte is not None:
        drivers.append(f"DTE {dte}")
    return {
        "section": "structure",
        "iv_rank": iv_rank,
        "atr": atr_v,
        "atr_vs_distance_to_stop": atr_vs_stop,
        "volatility_elevated": vol_elevated,
        "expected_move": expected_move,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "oi": oi,
        "volume": volume,
        "dte": dte,
        "distance_to_stop": dist_stop,
        "distance_to_target": dist_target,
        "drivers": drivers,
        "note": "Structure indicators pick strike/expiry/strategy class — never PE.",
    }


def comparative_equity_vs_options(
    *,
    price: Any,
    entry_low: Any = None,
    entry_high: Any = None,
    stop: Any = None,
    target: Any = None,
    shares_hint: Any = None,  # accepted for old callers; ignored — never sized (MBI_BEHAVIOR=0)
    proposal: Optional[dict[str, Any]] = None,
    alternatives: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Stock vs options PER UNIT (per share / per contract) — never a position size.

    M5 09-24: this used to print "Equity capital hint (illustrative_100_shares): $36,675",
    a dollar size the MBI_BEHAVIOR=0 rail forbids. Rows are now per unit only.
    """
    del shares_hint
    px = _f(price)
    st = _f(stop)
    tg = _f(target)
    lo = _f(entry_low)
    hi = _f(entry_high)
    stock = None
    if px is not None and st is not None and tg is not None and px > st:
        risk = px - st
        worst = hi if hi is not None and hi > st else px
        stock = {
            "unit": "per share",
            "capital": round(px, 2),
            "max_loss_to_plan_stop": round(risk, 2),
            "breakeven": round(px, 2),
            "value_at_target": round(tg - px, 2),
            "return_at_target_pct": round(100.0 * (tg - px) / px, 2),
            "return_at_plan_stop_pct": round(-100.0 * risk / px, 2),
            "reward_risk_at_quote": round((tg - px) / risk, 2),
            "reward_risk_worst_in_zone": round((tg - worst) / (worst - st), 2) if worst > st else None,
            "zone": [lo, hi],
        }
    options_rows: list[dict[str, Any]] = []
    for a in ((alternatives or {}).get("alternatives") or [])[:4]:
        pc = a.get("per_contract") or {}
        options_rows.append({
            "unit": "per contract",
            "rank": a.get("rank"),
            "strategy": a.get("strategy"),
            "qualified": a.get("qualified"),
            "strikes": [leg.get("strike") for leg in a.get("legs") or []],
            "expiry": ((a.get("legs") or [{}])[0]).get("exp"),
            "capital": pc.get("capital"),
            "max_loss": pc.get("max_loss"),
            "breakeven": pc.get("breakeven"),
            "return_at_target_pct": pc.get("return_at_target_pct"),
            "return_at_plan_stop_pct": pc.get("return_at_plan_stop_pct"),
            "reward_risk": pc.get("reward_risk"),
        })
    if not options_rows and proposal:
        p = proposal
        prem = _f(p.get("premium_total") if p.get("premium_total") is not None else p.get("premium"))
        options_rows.append({
            "unit": "per contract (desk cache)",
            "strategy": str(p.get("strategy") or "").lower() or None,
            "strikes": [_f(p.get("strike"))],
            "capital": prem, "max_loss": prem, "breakeven": None,
            "numbers_incomplete": True,
        })
    return {
        "basis": "per_unit",
        "stock_per_share": stock,
        "options_per_contract": options_rows,
        "note": "Per-unit economics only; the operator decides any quantity.",
    }


def former_holding_context(ev: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Reentry / formerly-owned context for CIO opinion — never silent."""
    ev = ev or {}
    held = bool(ev.get("held"))
    plan_source = str(ev.get("plan_source") or "")
    reentry = plan_source == "reentry_desk" or bool(ev.get("reentry"))
    formerly = bool(ev.get("formerly_held") or ev.get("former_holding"))
    if not formerly and reentry and not held:
        formerly = True  # reentry desk row not currently held → former book context
    note_parts = []
    if formerly:
        note_parts.append("formerly held / re-entry book — fit vs prior book matters")
    if held:
        note_parts.append("currently held — entry would be an add")
    if reentry:
        note_parts.append(f"plan_source={plan_source or 'reentry_desk'}")
    return {
        "held": held,
        "formerly_held": formerly,
        "reentry": reentry,
        "plan_source": plan_source or None,
        "note": "; ".join(note_parts) if note_parts else "no former-holding flag on evidence",
    }


def select_entry_options_alternative(
    symbol: str,
    *,
    entry_low: Any = None,
    entry_high: Any = None,
    stop: Any = None,
    target: Any = None,
    atr: Any = None,
    desk: Optional[dict[str, Any]] = None,
    goals: Optional[list[dict[str, Any]]] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    structure: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Pick a capital-efficient options alt for BUY_READY/ENTRY_NEAR, or honest NONE."""
    sym = (symbol or "").upper().strip()
    desk = desk if desk is not None else load_options_desk_summary()
    by_sym = desk.get("by_symbol") if isinstance(desk.get("by_symbol"), dict) else {}
    rows = list(by_sym.get(sym) or [])
    preferred = [r for r in rows if str(r.get("strategy") or "").lower() in ENTRY_ALT_PREFERRED]
    wrong = [r for r in rows if str(r.get("strategy") or "").lower() in ENTRY_ALT_WRONG_CLASS]
    lineage = goal_lineage_for(
        sym, preferred[0].get("strategy") if preferred else "",
        goals=goals, sector=sector, industry=industry,
    )
    # Never borrow a wrong-class proposal's IV rank / DTE / greeks for the entry's
    # structure (M5 09-24: V showed the Roth covered call's IV rank 24.5 and DTE).
    struct = structure or build_structure_indicators(
        preferred[0] if preferred else None,
        price=entry_high or entry_low, stop=stop, target=target, atr=atr,
    )
    vol_pref = bool(struct.get("volatility_elevated"))

    if preferred:
        best = sorted(preferred, key=lambda r: -float(r.get("edge_score") or 0))[0]
        strat = str(best.get("strategy") or "")
        meta = DESK_STRATEGY_CATALOG.get(strat, {})
        paper = meta.get("entry_alt_class") == "stock_replacement_paper"
        return {
            "status": "OPTIONS_ALT_OK" if not paper else "OPTIONS_ALT_PAPER_ONLY",
            "symbol": sym,
            "strategy": strat,
            "proposal": best,
            "goal_lineage": lineage,
            "structure_indicators": struct,
            "volatility_prefers_options": vol_pref,
            "maps_to_plan": {
                "entry_low": entry_low,
                "entry_high": entry_high,
                "stop": stop,
                "target": target,
                "strike": best.get("strike"),
                "premium_total": best.get("premium_total"),
                "pop_pct": best.get("pop_pct"),
            },
            "reason": None,
            "path_b": PATH_B_CHROME,
            "preference_note": (
                "Elevated ATR/HV vs distance-to-stop — defined-risk options are the "
                "preferred capital-efficient expression of this thesis."
                if vol_pref else None
            ),
        }

    if wrong and not preferred:
        reason = "WRONG_STRATEGY_CLASS"
        detail = (
            f"desk cache has {[r.get('strategy') for r in wrong]} for {sym} — "
            "income/hedge on held shares, not a capital-efficient way to express "
            "a new equity entry (need long_call / debit / deep-ITM class)"
        )
        if vol_pref:
            detail += (
                "; ATR/HV elevated vs stop — options would be preferred if a "
                "directional debit idea were on cache (Force scan / Hub)"
            )
        return {
            "status": "OPTIONS_ALT_NONE",
            "symbol": sym,
            "strategy": None,
            "proposal": None,
            "goal_lineage": lineage,
            "structure_indicators": struct,
            "volatility_prefers_options": vol_pref,
            "reason": reason,
            "detail": detail,
            "path_b": PATH_B_CHROME,
        }

    detail = f"no cached options ideas for {sym}"
    if vol_pref:
        detail += (
            "; elevated ATR/HV vs stop favors a defined-risk options expression "
            "once Force scan surfaces a debit/spread idea"
        )
    return {
        "status": "OPTIONS_ALT_NONE",
        "symbol": sym,
        "strategy": None,
        "proposal": None,
        "goal_lineage": lineage,
        "structure_indicators": struct,
        "volatility_prefers_options": vol_pref,
        "reason": "NONE_ON_CACHE",
        "detail": detail,
        "path_b": PATH_B_CHROME,
    }


def _default_cio_verdict_core(packet: dict[str, Any]) -> dict[str, Any]:
    """Deterministic CIO chrome: APPROVE | REJECT | MODIFY_* — no specialist persona.

    Interactive Modify still goes through the real desk / finalize_operator_reply.
    This stamps the notice so the operator sees a structured verdict slot.
    """
    state = str((packet.get("equity") or {}).get("state") or "")
    alt = packet.get("options_alt") or {}
    thesis = packet.get("thesis_indicators") or {}
    struct = packet.get("structure_indicators") or {}
    former = packet.get("former_holding") or {}
    status = alt.get("status") or "OPTIONS_ALT_NONE"

    if state not in ("BUY_READY", "ENTRY_NEAR"):
        return {
            "verdict": f"{CIO_VERDICT_REJECT}_NOT_ACTIONABLE",
            "token": CIO_VERDICT_REJECT,
            "rationale": f"state {state or 'unknown'} is not an actionable entry",
        }

    if thesis.get("pe_status") == "MISSING" and not thesis.get("catalyst"):
        # Still may approve equity on zone/R:R alone — ask modify for thesis fill
        token = f"{CIO_VERDICT_MODIFY}_THESIS_DATA"
        return {
            "verdict": token,
            "token": CIO_VERDICT_MODIFY,
            "rationale": "zone actionable but PE and catalyst both thin — fill thesis before size-up",
        }

    if status in ("OPTIONS_ALT_OK", "OPTIONS_ALT_PAPER_ONLY"):
        if struct.get("volatility_elevated"):
            token = f"{CIO_VERDICT_APPROVE}_OPTIONS_PREFERRED"
            rationale = (
                "Equity zone valid; elevated ATR/HV vs stop — prefer defined-risk options "
                "alt for capital efficiency; equity remains confirmable"
            )
        else:
            token = f"{CIO_VERDICT_APPROVE}_BOTH"
            rationale = "Equity plan and capital-efficient options alt both reviewable"
        if former.get("formerly_held"):
            rationale += "; formerly held — weigh fit vs prior book"
        return {"verdict": token, "token": CIO_VERDICT_APPROVE, "rationale": rationale}

    reason = alt.get("reason") or "NONE"
    if reason == "WRONG_STRATEGY_CLASS":
        token = f"{CIO_VERDICT_MODIFY}_NEED_DIRECTIONAL_OPTIONS"
        return {
            "verdict": token,
            "token": CIO_VERDICT_MODIFY,
            "rationale": (
                "Equity confirm/refute stands; cached options are wrong class for new entry "
                "(e.g. covered_call). Force scan for long_call/debit or proceed equity-only via Path B."
            ),
        }

    token = f"{CIO_VERDICT_APPROVE}_EQUITY_ONLY"
    rationale = f"Equity plan reviewable; options unsuitable ({reason})"
    if struct.get("volatility_elevated"):
        token = f"{CIO_VERDICT_MODIFY}_OPTIONS_WANTED"
        rationale = (
            "Elevated ATR/HV vs stop argues for defined-risk options, but none suitable "
            f"on cache ({reason}) — modify: surface debit/spread or accept equity Path B"
        )
    if former.get("formerly_held"):
        rationale += "; formerly held — CIO should opine on re-entry fit"
    return {"verdict": token, "token": token.split("_")[0], "rationale": rationale}


def default_cio_verdict(packet: dict[str, Any]) -> dict[str, Any]:
    """Deterministic verdict + portfolio flags (facts only, never a size)."""
    v = dict(_default_cio_verdict_core(packet))
    port = packet.get("portfolio_risk") or {}
    flags = [f for f in (port.get("flags") or []) if f != "ADD_TO_EXISTING_POSITION"]
    if port.get("held"):
        bits = []
        if port.get("pct_of_total_book") is not None:
            bits.append(f"{port['pct_of_total_book']:.1f}% of book")
        if port.get("pct_of_invested_capital") is not None:
            bits.append(f"{port['pct_of_invested_capital']:.1f}% of invested")
        lim = (port.get("ips_limits") or {}).get("max_single_position_pct")
        if lim is not None:
            bits.append(f"IPS single-name limit {lim:g}%")
        v["rationale"] = (v.get("rationale") or "") + "; ADD to an existing position (" + ", ".join(bits) + ")"
        if flags:
            v["rationale"] += " — flags: " + ", ".join(flags)
    v["portfolio_flags"] = port.get("flags") or []
    return v


def _options_alt_from_alternatives(sym: str, alts: dict[str, Any], struct: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Map chain-ranked alternatives onto the options_alt slot (None → fall back to desk cache)."""
    status = alts.get("status")
    ranked = alts.get("alternatives") or []
    if status in (None, "NO_CHAIN", "DISABLED") and not ranked:
        return None
    vol_pref = bool(struct.get("volatility_elevated"))
    top = next((x for x in ranked if x.get("qualified")), None)
    if top:
        legs = top.get("legs") or []
        pc = top.get("per_contract") or {}
        return {
            "status": "OPTIONS_ALT_OK",
            "source": "chain",
            "symbol": sym,
            "strategy": top.get("strategy"),
            "proposal": None,
            "top": top,
            "maps_to_plan": {"strikes": [leg.get("strike") for leg in legs],
                             "expiry": legs[0].get("exp") if legs else None,
                             "capital_per_contract": pc.get("capital"), "breakeven": pc.get("breakeven"),
                             "pop_estimate": top.get("pop_estimate")},
            "volatility_prefers_options": vol_pref,
            "reason": None,
            "path_b": PATH_B_CHROME,
            "preference_note": (
                "Elevated ATR/HV vs distance-to-stop — defined-risk options are the "
                "preferred capital-efficient expression of this thesis." if vol_pref else None
            ),
        }
    reasons = sorted({r for x in ranked for r in (x.get("disqualified_by") or [])})
    return {
        "status": "OPTIONS_ALT_NONE",
        "source": "chain",
        "symbol": sym,
        "strategy": None,
        "proposal": None,
        "volatility_prefers_options": vol_pref,
        "reason": "NONE_QUALIFIED" if ranked else "NONE_IN_BANDS",
        "detail": "; ".join(reasons)[:240] if reasons else "no contract inside the delta/DTE bands",
        "path_b": PATH_B_CHROME,
    }


def _load_portfolio_facts(sym: str) -> dict[str, Any]:
    try:
        try:
            from scripts.lib.buy_ready_portfolio_facts import build_portfolio_facts  # noqa: PLC0415
        except ImportError:
            from lib.buy_ready_portfolio_facts import build_portfolio_facts  # type: ignore  # noqa: PLC0415
        return build_portfolio_facts(sym)
    except Exception as exc:  # noqa: BLE001 — a missing fact is reported, never invented
        return {"status": "UNAVAILABLE", "error": type(exc).__name__, "flags": [], "unknowns": ["portfolio facts"]}


def build_buy_ready_packet(
    result: dict[str, Any],
    ev: Optional[dict[str, Any]] = None,
    *,
    desk: Optional[dict[str, Any]] = None,
    goals: Optional[list[dict[str, Any]]] = None,
    enrichment: Optional[dict[str, Any]] = None,
    alternatives: Optional[dict[str, Any]] = None,
    portfolio: Optional[dict[str, Any]] = None,
    cio_review: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Institutional BUY_READY / ENTRY_NEAR packet (P6 + P8 + M5 09-24).

    ``alternatives`` (buy_ready_options_alternatives), ``portfolio``
    (buy_ready_portfolio_facts) and ``cio_review`` (buy_ready_cio_review) may be
    passed directly or on ``ev`` under options_alternatives / portfolio_facts /
    cio_review. Per-unit only; never a size (MBI_BEHAVIOR=0).
    """
    ev = ev or {}
    sym = str(result.get("symbol") or ev.get("symbol") or "").upper()
    enr = enrichment if enrichment is not None else load_enrichment_row(sym)
    thesis = build_thesis_indicators(sym, ev=ev, enrichment=enr)
    atr = result.get("atr") if result.get("atr") is not None else ev.get("atr") or enr.get("atr")
    alts = alternatives if alternatives is not None else ev.get("options_alternatives")
    struct = build_structure_indicators(
        None, price=result.get("price"), stop=result.get("stop"), target=result.get("target"),
        atr=atr, enrichment=enr,
    )
    alt = _options_alt_from_alternatives(sym, alts, struct) if isinstance(alts, dict) else None
    if alt is None:
        alt = select_entry_options_alternative(
            sym,
            entry_low=result.get("entry_low"),
            entry_high=result.get("entry_high"),
            stop=result.get("stop"),
            target=result.get("target"),
            atr=atr,
            desk=desk,
            goals=goals,
            sector=thesis.get("sector") or ev.get("sector"),
            industry=thesis.get("industry") or ev.get("industry"),
        )
        struct = alt.get("structure_indicators") or struct
    else:
        alt["goal_lineage"] = goal_lineage_for(sym, alt.get("strategy") or "", goals=goals,
                                               sector=thesis.get("sector"), industry=thesis.get("industry"))
        top = alt.get("top") or {}
        g = top.get("greeks_per_share") or {}
        legs = top.get("legs") or [{}]
        struct = dict(struct)
        struct.update({"delta": g.get("delta"), "gamma": g.get("gamma"), "theta": g.get("theta_per_day"),
                       "vega": g.get("vega_per_vol_pt"), "oi": legs[0].get("oi"), "volume": legs[0].get("volume"),
                       "dte": legs[0].get("dte")})
    ivc = (alts or {}).get("iv_context") if isinstance(alts, dict) else None
    struct = dict(struct)
    if ivc:
        struct["iv_rank"] = ivc.get("iv_rank")
        struct["iv_rank_source"] = ivc.get("iv_rank_source")
        struct["iv_percentile"] = ivc.get("iv_percentile")
        struct["iv_history_rows"] = ivc.get("history_rows")
        struct["drivers"] = [d for d in (struct.get("drivers") or []) if not str(d).startswith("IV rank")]
        if ivc.get("iv_rank") is not None:
            label = "" if ivc.get("iv_rank_source") == "history" else " (PROXY — thin IV history)"
            struct["drivers"].insert(0, f"IV rank {ivc['iv_rank']:.1f}{label}")
        else:
            struct["drivers"].insert(0, f"IV rank UNAVAILABLE ({ivc.get('history_rows', 0)} history rows)")
        if ivc.get("iv_percentile") is not None:
            struct["drivers"].insert(1, f"IV percentile {ivc['iv_percentile']:.1f}")
    else:
        struct.setdefault("iv_rank_source", "engine cache (history or proxy — not labelled upstream)"
                          if struct.get("iv_rank") is not None else "unavailable")
    compare = comparative_equity_vs_options(
        price=result.get("price"),
        entry_low=result.get("entry_low"),
        entry_high=result.get("entry_high"),
        stop=result.get("stop"),
        target=result.get("target"),
        proposal=alt.get("proposal"),
        alternatives=alts if isinstance(alts, dict) else None,
    )
    former = former_holding_context(ev)
    equity = {
        "symbol": sym,
        "state": result.get("state"),
        "price": result.get("price"),
        "quote_age_h": result.get("quote_age_h") if result.get("quote_age_h") is not None else ev.get("quote_age_h"),
        "entry_low": result.get("entry_low"),
        "entry_high": result.get("entry_high"),
        "stop": result.get("stop"),
        "target": result.get("target"),
        "rr": result.get("rr"),
        "plan_source": result.get("plan_source") or ev.get("plan_source"),
        "distance_pct": result.get("distance_pct"),
        "catalyst": result.get("catalyst") or ev.get("catalyst"),
    }
    port = portfolio if portfolio is not None else ev.get("portfolio_facts")
    if port is None:
        port = _load_portfolio_facts(sym)
    packet = {
        "schema": "BuyReadyInstitutionalPacket@v2",
        "symbol": sym,
        "equity": equity,
        "options_alt": alt,
        "options_alternatives": alts if isinstance(alts, dict) else None,
        "comparative": compare,
        "thesis_indicators": thesis,
        "structure_indicators": struct,
        "former_holding": former,
        "portfolio_risk": port,
        "path_b": PATH_B_CHROME,
        "cio_verdict": None,  # filled below
        "cio_review": cio_review if cio_review is not None else ev.get("cio_review"),
    }
    packet["cio_verdict"] = default_cio_verdict(packet)
    return packet


def format_buy_ready_packet_lines(
    packet: dict[str, Any],
    *,
    for_cio: bool = False,
    cap_label: Optional[str] = None,
) -> list[str]:
    """Multi-line institutional packet for Telegram / CIO desk."""
    eq = packet.get("equity") or {}
    alt = packet.get("options_alt") or {}
    cmp_ = packet.get("comparative") or {}
    thesis = packet.get("thesis_indicators") or {}
    struct = packet.get("structure_indicators") or {}
    former = packet.get("former_holding") or {}
    verdict = packet.get("cio_verdict") or {}
    sym = packet.get("symbol") or eq.get("symbol") or "?"
    state = eq.get("state") or "?"

    lines: list[str] = []
    if for_cio:
        cap_bit = f" ({cap_label})" if cap_label else ""
        lines.append(
            f"Entry state {state} for {sym}{cap_bit}: price {_money(eq.get('price'))}, "
            f"zone {_money(eq.get('entry_low'))}–{_money(eq.get('entry_high'))}, "
            f"stop {_money(eq.get('stop'))}, target {_money(eq.get('target'))}, "
            f"R:R {eq.get('rr')}. Plan source {eq.get('plan_source') or 'unknown'}."
        )
    else:
        lines.append(
            f"Equity: {_money(eq.get('price'))} · zone {_money(eq.get('entry_low'))}–"
            f"{_money(eq.get('entry_high'))} · stop {_money(eq.get('stop'))} · "
            f"target {_money(eq.get('target'))} · R:R {eq.get('rr')}"
        )

    # P8 thesis
    pe_bit = f"PE {thesis['pe']:.2f}" if thesis.get("pe") is not None else "PE MISSING"
    lines.append(
        f"Thesis: {pe_bit}"
        + (f" · fwd {_money(thesis['forward_pe']).replace('$', '')}" if thesis.get("forward_pe") is not None else "")
        + (f" · {thesis.get('sector')}" if thesis.get("sector") else "")
        + (f" · catalyst {str(thesis.get('catalyst'))[:80]}" if thesis.get("catalyst") else "")
    )

    # Options alternatives (chain-ranked, per contract) or the desk-cache fallback
    status = alt.get("status") or "OPTIONS_ALT_NONE"
    ranked = ((packet.get("options_alternatives") or {}).get("alternatives") or []) if alt.get("source") == "chain" else []
    if status == "OPTIONS_ALT_OK" and ranked:
        lines.append("Options alternatives (per contract, ranked):")
        for a in ranked[:3]:
            legs = a.get("legs") or []
            pc = a.get("per_contract") or {}
            strikes = "/".join(f"{leg.get('strike'):g}" for leg in legs if leg.get("strike") is not None)
            exp = legs[0].get("exp") if legs else None
            dte = legs[0].get("dte") if legs else None
            pop = a.get("pop_estimate")
            ret = pc.get("return_at_target_pct")
            flag = "" if a.get("qualified") else " ✗ " + "; ".join(a.get("disqualified_by") or [])[:80]
            lines.append(
                f"  {a.get('rank')}. {str(a.get('strategy')).replace('_', ' ')} {strikes} {exp} ({dte} DTE) · "
                f"{_money(pc.get('capital'))} · max loss {_money(pc.get('max_loss'))} · BE {_money(pc.get('breakeven'))}"
                + (f" · at target {ret:+.0f}%" if ret is not None else "")
                + (f" · POP≈{100 * pop:.0f}%" if pop is not None else "") + flag
            )
        top = ranked[0]
        if top.get("why_this_strike"):
            lines.append(f"  why #1: {str(top['why_this_strike'])[:150]}")
        if alt.get("preference_note"):
            lines.append(alt["preference_note"])
    elif status in ("OPTIONS_ALT_OK", "OPTIONS_ALT_PAPER_ONLY"):
        p = alt.get("proposal") or {}
        paper = " (paper/educational)" if status == "OPTIONS_ALT_PAPER_ONLY" else ""
        pop = p.get("pop_pct")
        pop_bit = f" · POP {pop}%" if pop is not None else ""
        lines.append(
            f"Options alt{paper}: {alt.get('strategy')} strike {_money(p.get('strike'))}"
            f" · debit/credit {_money(p.get('premium_total'))}{pop_bit} (desk cache)"
        )
        if alt.get("preference_note"):
            lines.append(alt["preference_note"])
    else:
        lines.append(
            f"Options alt: none suitable ({alt.get('reason') or 'NONE'})"
            f"{(' — ' + str(alt.get('detail') or '')) if alt.get('detail') else ''}"
        )

    # Structure drivers (P8)
    if struct.get("drivers"):
        lines.append("Structure: " + "; ".join(struct["drivers"][:5]))

    # Per-unit comparison (never a size)
    st_c = cmp_.get("stock_per_share") or {}
    op_rows = cmp_.get("options_per_contract") or []
    if st_c:
        worst = st_c.get("reward_risk_worst_in_zone")
        lines.append(
            f"Per unit — stock: {_money(st_c.get('capital'))}/share · risk to stop {_money(st_c.get('max_loss_to_plan_stop'))}"
            f" · at target {st_c.get('return_at_target_pct'):+.1f}% · R:R {st_c.get('reward_risk_at_quote')} at quote"
            + (f" ({worst} worst in zone)" if worst is not None else "")
        )
    if op_rows and op_rows[0].get("capital") is not None and not op_rows[0].get("numbers_incomplete"):
        o = op_rows[0]
        ret = o.get("return_at_target_pct")
        lines.append(
            f"  vs #{o.get('rank') or 1} {str(o.get('strategy')).replace('_', ' ')}: {_money(o.get('capital'))}/contract · "
            f"max loss {_money(o.get('max_loss'))} · BE {_money(o.get('breakeven'))}"
            + (f" · at target {ret:+.0f}%" if ret is not None else "")
        )

    # Portfolio facts (flags only)
    port = packet.get("portfolio_risk") or {}
    if port.get("status") == "OK":
        if port.get("held"):
            lim = (port.get("ips_limits") or {}).get("max_single_position_pct")
            lines.append(
                f"Book: already held ({port.get('held_units_total'):g} units) · {port.get('pct_of_total_book')}% of book"
                f" · {port.get('pct_of_invested_capital')}% of invested"
                + (f" · IPS single-name limit {lim:g}%" if lim is not None else "")
                + (" · flags " + ", ".join(f for f in port.get("flags") or [] if f != "ADD_TO_EXISTING_POSITION")
                   if [f for f in port.get("flags") or [] if f != "ADD_TO_EXISTING_POSITION"] else "")
            )
        else:
            lines.append("Book: not held — this would be a new position")
        ob = port.get("options_book") or {}
        if ob.get("leg_count") is not None:
            lines.append(f"  options book: {ob.get('leg_count')} open legs · net delta {ob.get('net_delta_shares')} sh-equiv"
                         f" · cash {str(port.get('cash_state') or '').split(' ')[0]}")
    else:
        lines.append("Book: portfolio facts unavailable")

    if former.get("note") and former.get("note") != "no former-holding flag on evidence":
        lines.append(f"Book context: {former['note']}")

    review = packet.get("cio_review")
    if review is not None:
        try:
            from scripts.lib.buy_ready_cio_review import format_review_lines  # noqa: PLC0415
        except ImportError:
            from lib.buy_ready_cio_review import format_review_lines  # type: ignore  # noqa: PLC0415
        lines.extend(format_review_lines(review))
    lines.append(
        f"House-rule verdict: {verdict.get('verdict') or '—'} — {verdict.get('rationale') or ''}"
    )
    lines.append(packet.get("path_b") or PATH_B_CHROME)
    return lines


def format_entry_options_alternative_block(alt: dict[str, Any]) -> str:
    """One/two lines for legacy callers; prefer format_buy_ready_packet_lines."""
    status = alt.get("status") or "OPTIONS_ALT_NONE"
    sym = alt.get("symbol") or "?"
    if status in ("OPTIONS_ALT_OK", "OPTIONS_ALT_PAPER_ONLY"):
        p = alt.get("proposal") or {}
        strat = alt.get("strategy") or p.get("strategy") or "option"
        strike = p.get("strike")
        prem = p.get("premium_total")
        pop = p.get("pop_pct")
        paper = " (paper/educational lane)" if status == "OPTIONS_ALT_PAPER_ONLY" else ""
        lineage = alt.get("goal_lineage") or {}
        goal_bit = (
            f" Goal {lineage.get('goal_id')}."
            if lineage.get("status") == "LINKED" and lineage.get("goal_id")
            else " Goal lineage ABSENT."
        )
        pref = f" {alt['preference_note']}" if alt.get("preference_note") else ""
        return (
            f"Options alternative{paper}: {strat} on {sym}"
            f"{f' strike {_money(strike)}' if strike is not None else ''}"
            f"{f' debit/credit {_money(prem)}' if prem is not None else ''}"
            f"{f' POP {pop}%' if pop is not None else ''} — defined risk vs full share capital."
            f"{pref} {alt.get('path_b') or PATH_B_CHROME}.{goal_bit} "
            f"Confirm or refute alongside the equity entry."
        )
    reason = alt.get("reason") or "NONE"
    detail = alt.get("detail") or ""
    return (
        f"Options alternative: none suitable ({reason})"
        f"{(' — ' + detail) if detail else ''}. "
        f"Equity plan remains primary. {alt.get('path_b') or PATH_B_CHROME}"
    ).strip()


def format_packet_for_render(result: dict[str, Any], ev: Optional[dict[str, Any]] = None, *, for_cio: bool = False) -> str:
    """Convenience: build + join packet lines for entry/reentry renders."""
    packet = build_buy_ready_packet(result, ev or {})
    return "\n".join(format_buy_ready_packet_lines(packet, for_cio=for_cio))


__all__ = [
    "ATR_VS_STOP_ELEVATED",
    "CIO_VERDICT_APPROVE",
    "CIO_VERDICT_MODIFY",
    "CIO_VERDICT_REJECT",
    "DESK_STRATEGY_CATALOG",
    "ENTRY_ALT_PREFERRED",
    "PATH_B_CHROME",
    "atr_volatility_elevated",
    "build_buy_ready_packet",
    "build_structure_indicators",
    "build_thesis_indicators",
    "catalog_for_cio",
    "comparative_equity_vs_options",
    "default_cio_verdict",
    "format_buy_ready_packet_lines",
    "format_cio_options_opinion",
    "format_entry_options_alternative_block",
    "format_packet_for_render",
    "former_holding_context",
    "gather_options_house_facts",
    "goal_lineage_for",
    "load_cio_goals",
    "load_enrichment_row",
    "load_options_desk_summary",
    "looks_like_options_strategy_ask",
    "select_entry_options_alternative",
]
