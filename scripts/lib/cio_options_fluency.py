"""CIO options fluency — desk-supported strategies, goal lineage, entry alts.

Stage 1C / 1D for the Options Desk product contract (2026-09-24).

Rules (binding):
  * Catalog ONLY strategies the desk already generates — no new strategy types.
  * Never call create_goal. Lineage is LINKED or ABSENT; templates are proposals.
  * Never call live Schwab option_chain from Telegram / entry-render paths.
  * Read cached options_desk_latest / proposals only.
  * BUY_READY options alt prefers capital-efficient directional structures
    (long_call / debit-class). covered_call on an already-held name is the
    WRONG class for "don't lay out full equity capital" — report OPTIONS_ALT_NONE
    with reason WRONG_STRATEGY_CLASS when that is all the cache has.
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


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
) -> dict[str, Any]:
    """LINKED only when an open goal names the symbol and options language.

    Never invents a goal_id. Sector/industry are not on the goal schema today —
    returned as None with note until Stage 2G operator mint + optional schema.
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
            return {
                "status": "LINKED",
                "goal_id": g.get("goal_id"),
                "title": g.get("title"),
                "symbol": sym,
                "strategy": strat or None,
                "sector": None,
                "industry": None,
                "note": "linked_symbols match + options language in goal text; "
                        "sector/industry not first-class on cio_goals schema yet",
            }
    return {
        "status": "ABSENT",
        "goal_id": None,
        "symbol": sym or None,
        "strategy": strat or None,
        "sector": None,
        "industry": None,
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
) -> dict[str, Any]:
    """House facts for CIO replies — cache only, no live chain."""
    desk = desk if desk is not None else load_options_desk_summary()
    by_sym = desk.get("by_symbol") if isinstance(desk.get("by_symbol"), dict) else {}
    syms = [str(s).upper() for s in (symbols or []) if str(s).strip()]
    per: dict[str, Any] = {}
    for sym in syms:
        rows = by_sym.get(sym) or []
        per[sym] = {
            "proposals": rows,
            "strategies": sorted({str(r.get("strategy") or "") for r in rows if r.get("strategy")}),
            "goal_lineage": goal_lineage_for(sym, (rows[0].get("strategy") if rows else ""), goals=goals),
        }
    return {
        "as_of": desk.get("generated_at"),
        "proposal_count": desk.get("proposal_count"),
        "strategy_counts": desk.get("strategy_counts") or {},
        "catalog": catalog_for_cio(),
        "by_symbol": per,
        "source": "options_desk_latest_cache",
        "live_chain": False,
    }


def format_cio_options_opinion(facts: dict[str, Any], *, symbols: Optional[list[str]] = None) -> str:
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
    lines.append(
        "Execution stays Path B (View Chain → preflight → per-order 2FA when ARMED). "
        "Advisory only — nothing is placed from chat."
    )
    return "\n".join(lines)


def _money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def select_entry_options_alternative(
    symbol: str,
    *,
    entry_low: Any = None,
    entry_high: Any = None,
    stop: Any = None,
    target: Any = None,
    desk: Optional[dict[str, Any]] = None,
    goals: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Pick a capital-efficient options alt for BUY_READY, or honest NONE."""
    sym = (symbol or "").upper().strip()
    desk = desk if desk is not None else load_options_desk_summary()
    by_sym = desk.get("by_symbol") if isinstance(desk.get("by_symbol"), dict) else {}
    rows = list(by_sym.get(sym) or [])
    preferred = [r for r in rows if str(r.get("strategy") or "").lower() in ENTRY_ALT_PREFERRED]
    wrong = [r for r in rows if str(r.get("strategy") or "").lower() in ENTRY_ALT_WRONG_CLASS]
    lineage = goal_lineage_for(sym, preferred[0].get("strategy") if preferred else "", goals=goals)

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
            "path_b": "Options Hub → View Chain → preflight → 2FA when ARMED",
        }

    if wrong and not preferred:
        return {
            "status": "OPTIONS_ALT_NONE",
            "symbol": sym,
            "strategy": None,
            "proposal": None,
            "goal_lineage": lineage,
            "reason": "WRONG_STRATEGY_CLASS",
            "detail": (
                f"desk cache has {[r.get('strategy') for r in wrong]} for {sym} — "
                "income/hedge on held shares, not a capital-efficient way to express "
                "a new BUY_READY equity entry (need long_call / debit / deep-ITM class)"
            ),
            "path_b": "Options Hub Force scan may surface directional ideas; Path B unchanged",
        }

    return {
        "status": "OPTIONS_ALT_NONE",
        "symbol": sym,
        "strategy": None,
        "proposal": None,
        "goal_lineage": lineage,
        "reason": "NONE_ON_CACHE",
        "detail": f"no cached options ideas for {sym}",
        "path_b": "Options Hub → Force scan / View Chain; still no auto-submit",
    }


def format_entry_options_alternative_block(alt: dict[str, Any]) -> str:
    """One/two lines for render_cio / render_operator."""
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
        return (
            f"Options alternative{paper}: {strat} on {sym}"
            f"{f' strike {_money(strike)}' if strike is not None else ''}"
            f"{f' debit/credit {_money(prem)}' if prem is not None else ''}"
            f"{f' POP {pop}%' if pop is not None else ''} — defined risk vs full share capital. "
            f"{alt.get('path_b')}.{goal_bit} Confirm or refute alongside the equity entry."
        )
    reason = alt.get("reason") or "NONE"
    detail = alt.get("detail") or ""
    return (
        f"Options alternative: none suitable ({reason})"
        f"{(' — ' + detail) if detail else ''}. "
        f"Equity plan remains primary. {alt.get('path_b') or ''}"
    ).strip()


__all__ = [
    "DESK_STRATEGY_CATALOG",
    "ENTRY_ALT_PREFERRED",
    "catalog_for_cio",
    "format_cio_options_opinion",
    "format_entry_options_alternative_block",
    "gather_options_house_facts",
    "goal_lineage_for",
    "load_cio_goals",
    "load_options_desk_summary",
    "looks_like_options_strategy_ask",
    "select_entry_options_alternative",
]
