"""cio_decision_semantics.py — Phase 3 decision hygiene + Phase 8 identity (READ_ONLY_ADVISORY).

Canonical operator-facing decision semantics for Alex / Command Center / reports:

  * One stance per symbol (no HOLD + "Advisory TRIM" contradiction)
  * Aggregate split-account rows into one decision per symbol
  * Reject pseudo-sectors (e.g. Iwm−Spy spread pairs) outside GICS
  * Map internal enums to professional prose
  * Require ticker identity proof before a symbol enters CIO output
  * Stable decision_id so CIO NOW / report / Telegram share one identity

Pure and deterministic. No broker / order / stop / 2FA / Telegram side effects.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional
# ── Stance taxonomy (aligned with capital plan / opportunity queue) ──────────

STANCE_EXIT = "EXIT"
STANCE_TRIM = "TRIM"
STANCE_RE_ENTER = "RE_ENTER"
STANCE_ADD = "ADD"
STANCE_HOLD = "HOLD"
STANCE_REVIEW = "REVIEW"

ACTIONABLE_STANCES = frozenset({
    STANCE_EXIT, STANCE_TRIM, STANCE_RE_ENTER, STANCE_ADD,
})

# Higher = more decisive / overrides weaker desk noise.
STANCE_PRECEDENCE: dict[str, int] = {
    STANCE_EXIT: 50,
    STANCE_TRIM: 40,
    STANCE_RE_ENTER: 30,
    STANCE_ADD: 20,
    STANCE_REVIEW: 10,
    STANCE_HOLD: 0,
}

# Professional labels for operator surfaces (never leak SCREAMING_SNAKE enums).
STANCE_PROSE: dict[str, str] = {
    STANCE_EXIT: "Exit",
    STANCE_TRIM: "Trim",
    STANCE_RE_ENTER: "Re-enter",
    STANCE_ADD: "Add",
    STANCE_HOLD: "Hold",
    STANCE_REVIEW: "Review",
    "BUY": "Buy",
    "SELL": "Sell",
    "NO_ACTION": "No action",
    "DEFER": "Defer",
}

RECOMMENDATION_PROSE: dict[str, str] = {
    "NO_DEPLOYMENT": "No deployment",
    "STAGED_DEPLOYMENT": "Staged deployment",
    "RESEARCH_FIRST": "Research first",
    "WATCH_READY": "Watch ready",
    "NEEDS_RESEARCH": "Needs research",
    "TOO_EXTENDED": "Too extended",
    "UNKNOWN": "Unknown",
    "LEADING": "Leading",
    "IMPROVING": "Improving",
    "WEAKENING": "Weakening",
    "LAGGING": "Lagging",
}

# Canonical GICS set used by sector opportunity (import-safe duplicate for purity).
CANONICAL_GICS = frozenset({
    "Technology", "Financials", "Healthcare", "Energy", "Industrials",
    "Consumer Discretionary", "Consumer Staples", "Utilities", "Materials",
    "Real Estate", "Communications",
})

# Pseudo-sector patterns: relative-strength pairs, free-text spreads, non-GICS noise.
_PSEUDO_SECTOR_RE = re.compile(
    r"(?:"
    r"\b(?:iwm|spy|qqq|dia|rut|vix)\b"  # index/ETF pair tokens
    r"|[−\-–—/\\|]+"                   # dash/slash joiners in pair names
    r")",
    re.IGNORECASE,
)

# CUSIP-like / non-ticker identity (digits + alnum, length 8–9) needs a name proof.
_CUSIP_LIKE_RE = re.compile(r"^[0-9]{3}[A-Z0-9]{5,6}$", re.IGNORECASE)

# Tokens that are real tickers but easily confused with English — require name.
_AMBIGUOUS_TICKERS = frozenset({
    "YOU", "ALL", "NOW", "FOR", "ARE", "THE", "CAN", "OUT", "NEW", "ONE",
    "TWO", "BIG", "LOW", "USA", "CEO", "CFO", "GDP", "AI", "IT", "ON", "BE",
    "SO", "OR", "AN", "AT", "BY", "IF", "IN", "IS", "TO", "UP", "WE",
})

_NEUTRAL_WHY = "no new desk signal; hold"


def make_decision_id(
    symbol: Any,
    stance_code: Any,
    recommended_delta_usd: Any = 0.0,
    why_now: Any = None,
) -> str:
    """Stable, content-addressed decision id shared by CC / report / Telegram.

    Material fields only — not timestamps. Format: `dec_<16 hex>`.
    """
    body = {
        "symbol": str(symbol or "").upper().strip(),
        "stance": str(stance_code or "").upper().strip(),
        "delta": round(float(recommended_delta_usd or 0.0), 2),
        "why": str(why_now or "").strip()[:200],
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "dec_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def capital_plan_surface_digest(plan: Optional[dict[str, Any]]) -> str:
    """Digest of capital-plan dollars that must match across office home + report."""
    p = plan or {}
    src = p.get("capital_sources") or {}
    key = {
        "cash": round(float(p.get("cash_total_usd") or 0.0), 2),
        "reserve": round(float(p.get("cash_reserved_usd") or 0.0), 2),
        "investable": round(float(p.get("cash_investable_usd") or 0.0), 2),
        "earmark": round(float(
            p.get("cash_earmarked_redeploy_usd")
            or src.get("earmarked_redeploy_usd")
            or src.get("maturities_usd")
            or 0.0
        ), 2),
        "raise": round(float(
            p.get("net_recommended_raise_usd")
            or src.get("total_prospective_raise_usd")
            or src.get("total_raise_usd")
            or 0.0
        ), 2),
        "deploy": round(float(p.get("net_recommended_deploy_usd") or 0.0), 2),
        "post": round(float(p.get("post_plan_cash_usd") or 0.0), 2),
        "v": str(p.get("plan_version") or p.get("digest") or "")[:32],
    }
    # Prefer engine digest when present (stronger consistency)
    if p.get("digest"):
        return str(p["digest"])
    raw = json.dumps(key, sort_keys=True, separators=(",", ":"))
    return "cp_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def what_changes_the_call(stance_code: str, risk: Any = None, counter_thesis: Any = None) -> str:
    """CIO-speak condition that would reverse the call (not a state-machine code)."""
    stance = str(stance_code or "").upper()
    risk_s = str(risk or "")
    if "concentration" in risk_s.lower():
        return "Single-name weight falls back under the concentration cap, or the desk thesis invalidates the trim."
    if stance in ("TRIM", "EXIT"):
        return "Thesis re-validates on multi-desk evidence, or risk/reward reopens above the policy hurdle."
    if stance in ("ADD", "RE_ENTER", "BUY"):
        return "Setup breaks (price/structure), evidence quality drops below the gate, or cash policy requires reserve."
    if counter_thesis and "no Street" not in str(counter_thesis):
        return f"Counter-thesis resolves: {str(counter_thesis)[:120]}"
    return "Material new evidence arrives from multiple desks, or the cash/risk band forces a review."


def operator_action_affordances() -> list[dict[str, str]]:
    """Client-facing actions available on a CIO NOW card (no execution authority)."""
    return [
        {"code": "ACK", "label": "Acknowledge"},
        {"code": "DEFER", "label": "Defer"},
        {"code": "DONE", "label": "Mark done"},
        {"code": "REJECT", "label": "Reject"},
        {"code": "RATE", "label": "Rate"},
    ]


def professional_stance(stance: Any) -> str:
    """Map internal stance/enum to professional Title Case prose."""
    key = str(stance or "").strip().upper().replace("-", "_").replace(" ", "_")
    if key in STANCE_PROSE:
        return STANCE_PROSE[key]
    if not key:
        return "—"
    return key.replace("_", " ").title()


def professional_label(value: Any) -> str:
    """Map internal recommendation/state enums to professional prose."""
    key = str(value or "").strip().upper()
    if not key:
        return "—"
    if key in RECOMMENDATION_PROSE:
        return RECOMMENDATION_PROSE[key]
    if key in STANCE_PROSE:
        return STANCE_PROSE[key]
    # Already human prose?
    if " " in str(value) and str(value) == str(value).title():
        return str(value)
    return key.replace("_", " ").title()


def infer_stance_from_text(text: Any) -> Optional[str]:
    """Extract the strongest actionable stance keyword from free text / labels."""
    raw = str(text or "")
    if not raw:
        return None
    upper = raw.upper()
    # Order: most decisive first. RE_ENTER before ENTER; EXIT before TRIM.
    checks: list[tuple[str, str]] = [
        ("EXIT", STANCE_EXIT),
        ("SELL", STANCE_EXIT),
        ("RE_ENTER", STANCE_RE_ENTER),
        ("RE-ENTER", STANCE_RE_ENTER),
        ("REENTER", STANCE_RE_ENTER),
        ("TRIM", STANCE_TRIM),
        ("ADD", STANCE_ADD),
        ("BUY", STANCE_ADD),
        ("DEPLOY", STANCE_ADD),
    ]
    best: Optional[str] = None
    best_rank = -1
    for needle, stance in checks:
        if needle in upper:
            rank = STANCE_PRECEDENCE.get(stance, 0)
            if rank > best_rank:
                best, best_rank = stance, rank
    return best


def merge_stances(*stances: Optional[str]) -> str:
    """Pick highest-precedence non-empty stance; default HOLD."""
    best = STANCE_HOLD
    best_rank = STANCE_PRECEDENCE[STANCE_HOLD]
    for s in stances:
        if not s:
            continue
        key = str(s).strip().upper().replace("-", "_")
        if key == "REENTER":
            key = STANCE_RE_ENTER
        if key == "SELL":
            key = STANCE_EXIT
        if key == "BUY":
            key = STANCE_ADD
        rank = STANCE_PRECEDENCE.get(key, -1)
        if rank > best_rank:
            best, best_rank = key, rank
    return best


def stance_from_queue_item(item: Optional[dict[str, Any]]) -> str:
    """Stance for one queue item: explicit verdict > state > directive label."""
    if not item:
        return STANCE_HOLD
    verdict = str(item.get("verdict") or "").upper().strip() or None
    state = str(item.get("state") or "").upper().strip() or None
    label = item.get("directive_label") or item.get("label") or item.get("note")
    from_verdict = verdict if verdict in ACTIONABLE_STANCES else None
    from_state = None
    if state in {"READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW"}:
        from_state = STANCE_RE_ENTER
    from_label = infer_stance_from_text(label)
    return merge_stances(from_verdict, from_state, from_label)


def stance_for_symbol(symbol: str, queue: Optional[dict[str, Any]]) -> str:
    """Canonical stance across *all* queue items for a symbol (multi-desk).

    Precedence: EXIT > TRIM > RE_ENTER > ADD > HOLD. Labels like
    "Advisory TRIM — SCHD" count even when verdict is null.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return STANCE_HOLD
    items = (queue or {}).get("items") or (queue or {}).get("top") or []
    stances: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("symbol") or "").upper().strip() != sym:
            continue
        stances.append(stance_from_queue_item(it))
    return merge_stances(*stances) if stances else STANCE_HOLD


def resolve_display_stance(cio_stance: Any, why_now: Any = None) -> str:
    """Eliminate HOLD + TRIM contradictions for operator-facing stance.

    Prefer the more decisive of formal stance and stance inferred from why_now.
    """
    formal = str(cio_stance or "").upper().strip() or STANCE_HOLD
    from_why = infer_stance_from_text(why_now)
    return merge_stances(formal, from_why)


def is_pseudo_sector(name: Any) -> bool:
    """True when a sector label is a spread pair / non-GICS pseudo-sector."""
    raw = str(name or "").strip()
    if not raw:
        return True
    # Exact canonical GICS is fine
    if raw in CANONICAL_GICS:
        return False
    title = raw.title()
    if title in CANONICAL_GICS:
        return False
    # Pair / relative-strength pseudo-sectors: "Iwm−Spy", "IWM-SPY", "Spy/Qqq"
    compact = re.sub(r"\s+", "", raw)
    if re.search(r"[−\-–—/\\|]", compact) and _PSEUDO_SECTOR_RE.search(raw):
        return True
    # Two short ticker-like tokens joined
    if re.match(r"^[A-Za-z]{1,5}[−\-–—/\\|][A-Za-z]{1,5}$", raw):
        return True
    return False


def is_canonical_gics_sector(name: Any) -> bool:
    raw = str(name or "").strip()
    return raw in CANONICAL_GICS or raw.title() in CANONICAL_GICS


def filter_sector_opportunities(
    sectors: Optional[list[dict[str, Any]]],
    *,
    require_canonical_gics: bool = True,
    professionalize: bool = True,
) -> list[dict[str, Any]]:
    """Drop pseudo-sectors; optionally require GICS; map enums to prose."""
    out: list[dict[str, Any]] = []
    for o in sectors or []:
        if not isinstance(o, dict):
            continue
        sector = o.get("sector")
        if is_pseudo_sector(sector):
            continue
        if require_canonical_gics and not is_canonical_gics_sector(sector):
            continue
        row = dict(o)
        if professionalize:
            if row.get("recommendation") is not None:
                row["recommendation_code"] = row.get("recommendation")
                row["recommendation"] = professional_label(row.get("recommendation"))
            if row.get("state") is not None:
                row["state_code"] = row.get("state")
                row["state_display"] = professional_label(row.get("state"))
        out.append(row)
    return out


def symbol_identity_status(
    symbol: Any,
    *,
    name: Any = None,
    instrument_type: Any = None,
    exchange: Any = None,
) -> dict[str, Any]:
    """Prove (or refuse) that a ticker is a known security for CIO output.

    Returns:
      ok: bool — allowed into CIO operator surfaces
      reason: short code
      display_name: human name if known
    """
    sym = str(symbol or "").upper().strip()
    nm = str(name or "").strip()
    if not sym:
        return {"ok": False, "reason": "empty_symbol", "display_name": None, "symbol": sym}
    if sym in {"CASH", "USD", "USD$", "MONEYMARKET"}:
        return {"ok": False, "reason": "cash_not_security", "display_name": nm or None, "symbol": sym}
    # Pure CUSIP / SEDOL-like without a name: refuse
    if _CUSIP_LIKE_RE.match(sym) and not nm:
        return {"ok": False, "reason": "cusip_unproven", "display_name": None, "symbol": sym}
    if _CUSIP_LIKE_RE.match(sym) and nm:
        return {
            "ok": True, "reason": "cusip_named", "display_name": nm, "symbol": sym,
            "identity_note": f"{sym} is CUSIP/identifier for {nm}",
        }
    if sym in _AMBIGUOUS_TICKERS and not nm:
        return {"ok": False, "reason": "ambiguous_ticker_unproven", "display_name": None, "symbol": sym}
    if sym in _AMBIGUOUS_TICKERS and nm:
        return {
            "ok": True, "reason": "ambiguous_ticker_named", "display_name": nm, "symbol": sym,
            "identity_note": f"{sym} = {nm}",
        }
    # Ordinary ticker
    return {
        "ok": True,
        "reason": "ticker",
        "display_name": nm or None,
        "symbol": sym,
        "instrument_type": instrument_type,
        "exchange": exchange,
    }


def aggregate_position_decisions(
    rows: Optional[list[dict[str, Any]]],
    *,
    portfolio_value: float = 0.0,
) -> list[dict[str, Any]]:
    """Collapse split-account rows into one decision per symbol.

    Sums values, recomputes weight, keeps the decisive stance, joins accounts,
    and surfaces professional stance labels. Drops rows that fail identity proof
    unless they already carry a name.
    """
    by: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").upper().strip()
        if not sym:
            continue
        ident = symbol_identity_status(sym, name=r.get("name"))
        if not ident["ok"]:
            # Still allow if we have material book value and a name-like field
            if not r.get("name"):
                continue
        why = r.get("why_now")
        stance = resolve_display_stance(r.get("cio_stance"), why)
        value = float(r.get("current_value_usd") or 0.0)
        delta = float(r.get("recommended_delta_usd") or 0.0)
        acct = r.get("account")
        if sym not in by:
            by[sym] = {
                "symbol": sym,
                "name": r.get("name") or ident.get("display_name"),
                "accounts": [acct] if acct else [],
                "account": acct,  # primary (largest) filled later
                "current_value_usd": value,
                "recommended_delta_usd": delta,
                "cio_stance": stance,
                "why_now": why,
                "risk": r.get("risk"),
                "funding": r.get("funding"),
                "tax_account_constraint": r.get("tax_account_constraint"),
                "counter_thesis": r.get("counter_thesis"),
                "next_review": r.get("next_review"),
                "target_range_pct": r.get("target_range_pct"),
                "identity": ident,
                "_acct_values": {acct: value} if acct else {},
            }
            continue
        agg = by[sym]
        agg["current_value_usd"] = round(float(agg["current_value_usd"]) + value, 2)
        # Sum deltas when same direction; prefer larger-magnitude if conflicting
        prev_d = float(agg["recommended_delta_usd"] or 0.0)
        if (prev_d >= 0 and delta >= 0) or (prev_d <= 0 and delta <= 0):
            agg["recommended_delta_usd"] = round(prev_d + delta, 2)
        else:
            agg["recommended_delta_usd"] = prev_d if abs(prev_d) >= abs(delta) else delta
        agg["cio_stance"] = merge_stances(agg.get("cio_stance"), stance)
        if acct and acct not in agg["accounts"]:
            agg["accounts"].append(acct)
        if acct:
            agg["_acct_values"][acct] = round(
                float(agg["_acct_values"].get(acct, 0.0)) + value, 2)
        # Prefer non-neutral why_now
        if why and _NEUTRAL_WHY not in str(why).lower():
            if not agg.get("why_now") or _NEUTRAL_WHY in str(agg.get("why_now")).lower():
                agg["why_now"] = why
        if r.get("name") and not agg.get("name"):
            agg["name"] = r.get("name")
        # Escalate risk if any lot is over cap
        if "concentration >" in str(r.get("risk") or "").lower():
            agg["risk"] = r.get("risk")

    pv = max(0.0, float(portfolio_value or 0.0))
    out: list[dict[str, Any]] = []
    for sym, agg in by.items():
        # Primary account = largest value share
        acct_vals = agg.pop("_acct_values", {}) or {}
        if acct_vals:
            primary = max(acct_vals.items(), key=lambda kv: kv[1])[0]
            agg["account"] = primary
        value = float(agg["current_value_usd"] or 0.0)
        weight = round(value / pv * 100.0, 2) if pv > 0 else float(agg.get("current_weight_pct") or 0.0)
        stance = resolve_display_stance(agg.get("cio_stance"), agg.get("why_now"))
        agg["cio_stance"] = stance
        agg["stance"] = professional_stance(stance)  # operator-facing
        agg["stance_code"] = stance
        agg["current_weight_pct"] = weight
        agg["current_value_usd"] = round(value, 2)
        agg["recommended_delta_usd"] = round(float(agg.get("recommended_delta_usd") or 0.0), 2)
        agg["account_count"] = len(agg.get("accounts") or [])
        tr = agg.get("target_range_pct") or {}
        agg["target_weight_pct"] = tr.get("max") if isinstance(tr, dict) else None
        agg["decision_id"] = make_decision_id(
            sym, stance, agg["recommended_delta_usd"], agg.get("why_now"),
        )
        agg["what_changes_call"] = what_changes_the_call(
            stance, agg.get("risk"), agg.get("counter_thesis"),
        )
        out.append(agg)

    out.sort(key=lambda r: (-abs(float(r.get("recommended_delta_usd") or 0.0)),
                            -float(r.get("current_value_usd") or 0.0)))
    return out


def sanitize_decisions_now(
    rows: Optional[list[dict[str, Any]]],
    *,
    portfolio_value: float = 0.0,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Operator-facing decisions: aggregate, resolve stance, professional labels + IDs.

    Phase 8: every card carries a stable `decision_id` shared with CIO NOW / report.
    """
    aggregated = aggregate_position_decisions(rows, portfolio_value=portfolio_value)
    neutral = _NEUTRAL_WHY
    decisions: list[dict[str, Any]] = []
    for d in aggregated:
        why = d.get("why_now") or ""
        risk = d.get("risk") or ""
        delta = d.get("recommended_delta_usd") or 0.0
        has_delta = abs(float(delta)) > 0.005
        has_signal = bool(why) and neutral not in str(why).lower()
        has_breach = "concentration >" in str(risk).lower() or "breach" in str(risk).lower()
        if not (has_delta or has_signal or has_breach):
            continue
        stance_code = d.get("stance_code") or d.get("cio_stance")
        did = d.get("decision_id") or make_decision_id(
            d.get("symbol"), stance_code, delta, why,
        )
        tr = d.get("target_range_pct") or {}
        target_w = d.get("target_weight_pct")
        if target_w is None and isinstance(tr, dict):
            target_w = tr.get("max")
        decisions.append({
            "decision_id": did,
            "symbol": d.get("symbol"),
            "name": d.get("name"),
            "action": d.get("stance") or professional_stance(stance_code),
            "stance": d.get("stance") or professional_stance(stance_code),
            "stance_code": stance_code,
            "current_value_usd": d.get("current_value_usd"),
            "current_weight_pct": d.get("current_weight_pct"),
            "target_weight_pct": target_w,
            "recommended_delta_usd": d.get("recommended_delta_usd"),
            "why_now": why,
            "counter_thesis": d.get("counter_thesis") or "no Street/desk disagreement on record",
            "what_changes_call": d.get("what_changes_call") or what_changes_the_call(
                str(stance_code or ""), risk, d.get("counter_thesis"),
            ),
            "risk": risk,
            "next_review": d.get("next_review"),
            "accounts": d.get("accounts"),
            "account_count": d.get("account_count"),
            "operator_actions": operator_action_affordances(),
        })
    decisions.sort(
        key=lambda d: (
            -1 if "concentration >" in str(d.get("risk") or "").lower() else 0,
            -abs(float(d.get("recommended_delta_usd") or 0.0)),
            -float(d.get("current_value_usd") or 0.0),
        )
    )
    return decisions[:limit]


def allocation_weights_from_usd(
    allocation_usd: dict[str, Any],
) -> dict[str, float]:
    """Convert a class→USD map into class→weight_pct (sums to ~100)."""
    cleaned: dict[str, float] = {}
    for k, v in (allocation_usd or {}).items():
        try:
            cleaned[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    total = sum(max(0.0, v) for v in cleaned.values())
    if total <= 0:
        return {k: 0.0 for k in cleaned}
    return {k: round(max(0.0, v) / total * 100.0, 2) for k, v in cleaned.items()}


def looks_like_dollar_allocation(allocation: dict[str, Any]) -> bool:
    """Heuristic: any class value > 100 implies USD dollars, not weight %."""
    for v in (allocation or {}).values():
        try:
            if float(v) > 100.0:
                return True
        except (TypeError, ValueError):
            continue
    return False
