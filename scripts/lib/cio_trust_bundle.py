"""CIO trust bundle — operator TRUST HIGH | DEGRADED from deterministic gates.

High means dual lane agree (buy-side) + fresh Street evidence + QA/safety.
Does not claim LLMs are ground truth; fails closed when evidence is thin.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

BUY_SIDE = frozenset({"BUY", "STRONG_BUY", "ADD", "ADD_ON_PULLBACK", "ACCUMULATE"})
SELL_SIDE = frozenset({"SELL", "AVOID", "IGNORE", "TRIM", "REBALANCE_TRIM", "UNDERPERFORM"})
STREET_SELL = frozenset({"sell", "underperform", "strong_sell"})
STREET_BUY = frozenset({"buy", "strong_buy", "outperform", "overweight"})

# Policy knobs (hours / counts)
SYNTHESIS_MAX_AGE_H = 24 * 7  # matches decision_qa stale_analysis
STREET_MAX_AGE_H = 48
STREET_MIN_N = 5
SPECIALIST_MAX_AGE_H = 72


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _age_hours(ts: Any) -> float | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    else:
        s = str(ts).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0)


def _rec(v: Any) -> str:
    return str(v or "").strip().upper().replace(" ", "_")


def is_buy_side(rec: str) -> bool:
    return _rec(rec) in BUY_SIDE


def narrative_conflicts_recommendation(narrative: str | None, recommendation: str | None) -> bool:
    """True when narrative lean opposes the one-word recommendation."""
    text = (narrative or "").lower()
    rec = _rec(recommendation)
    if not text or not rec:
        return False
    sellish = bool(re.search(r"\b(sell|avoid|trim|exit|underperform)\b", text))
    buyish = bool(re.search(r"\b(buy|add|accumulate|overweight|strong buy)\b", text))
    if is_buy_side(rec) and sellish and not buyish:
        return True
    if rec in SELL_SIDE and buyish and not sellish:
        return True
    return False


def compute_cio_trust_bundle(
    *,
    recommendation: str | None = None,
    synthesis_updated_at: Any = None,
    models_agree: bool | None = None,
    dual_consensus: dict | None = None,
    model_used: str | None = None,
    decision_quality_status: str | None = None,
    decision_safety: str | None = None,
    actionable: bool | None = None,
    street_rec: str | None = None,
    street_n: int | None = None,
    street_as_of: Any = None,
    street_divergence: str | None = None,
    instrument_type: str | None = None,
    evidence: list | None = None,
    synthesis_narrative: str | None = None,
    on_main: bool = False,
) -> dict[str, Any]:
    """Return trust level + gate list for UI / QA."""
    dual = dual_consensus if isinstance(dual_consensus, dict) else {}
    grok = dual.get("grok") if isinstance(dual.get("grok"), dict) else None
    chatgpt = dual.get("chatgpt") if isinstance(dual.get("chatgpt"), dict) else None
    agree = models_agree if models_agree is not None else dual.get("agree")
    model = str(model_used or dual.get("model") or "").lower()
    local_only = bool(model) and ("gemma" in model or "ollama" in model or model in ("local",)) and "grok" not in model and "chatgpt" not in model and "gpt" not in model and "deepseek" not in model

    gates: list[dict[str, Any]] = []
    failed: list[str] = []

    synth_age = _age_hours(synthesis_updated_at)
    synth_ok = synth_age is not None and synth_age <= SYNTHESIS_MAX_AGE_H
    gates.append({
        "id": "synthesis_fresh",
        "pass": synth_ok,
        "label": "CIO synthesis fresh",
        "detail": f"{synth_age:.0f}h old" if synth_age is not None else "no synthesis timestamp",
    })
    if not synth_ok:
        failed.append("synthesis_fresh")

    both_lanes = bool(grok and grok.get("recommendation") and chatgpt and chatgpt.get("recommendation"))
    # Legacy rows may only stamp models_agree without nested lane objects
    if not both_lanes and agree is True and not local_only:
        both_lanes = True
    dual_mode = "AGREE" if agree is True else ("SPLIT" if agree is False else ("SINGLE" if (grok or chatgpt) else ("LOCAL" if local_only else "MISSING")))
    buy = is_buy_side(recommendation or dual.get("consensus") or "")

    if buy:
        dual_pass = both_lanes and agree is True and not local_only
        detail = (
            f"{dual_mode} — buy-side requires both OAuth lanes AGREE"
            if not dual_pass else "Dual lane consensus (AGREE)"
        )
    else:
        # Non-buy: AGREE (or cautious single) OK; SPLIT never HIGH
        dual_pass = both_lanes and agree is True and not local_only
        detail = f"{dual_mode}"
    gates.append({"id": "dual", "pass": dual_pass, "label": "Dual consensus", "detail": detail})
    if not dual_pass:
        failed.append("dual")

    # Narrative consistency
    narr_ok = not narrative_conflicts_recommendation(synthesis_narrative, recommendation)
    gates.append({
        "id": "narrative_consistency",
        "pass": narr_ok,
        "label": "Narrative ↔ recommendation",
        "detail": "aligned" if narr_ok else "narrative opposes recommendation",
    })
    if not narr_ok:
        failed.append("narrative_consistency")

    # Evidence present (soft for HIGH when buy-side)
    ev = evidence if isinstance(evidence, list) else (dual.get("structured_evidence") or [])
    ev_ok = bool(ev) or not buy  # require evidence tags for buy-side HIGH
    if buy and not ev:
        ev_ok = False
    gates.append({
        "id": "evidence",
        "pass": ev_ok,
        "label": "Evidence refs",
        "detail": f"{len(ev)} evidence items" if ev else "no structured evidence",
    })
    if not ev_ok:
        failed.append("evidence")

    # Street
    inst = str(instrument_type or "").lower()
    is_fund = any(x in inst for x in ("etf", "fund", "mutual"))
    street_age = _age_hours(street_as_of)
    street_rec_l = str(street_rec or "").lower().replace(" ", "_")
    n = int(street_n or 0)

    if is_fund:
        street_pass = True
        street_detail = "N/A — fund/ETF (no equity analyst panel required)"
        street_label = "Street N/A (fund)"
    else:
        fresh = street_age is not None and street_age <= STREET_MAX_AGE_H
        covered = n >= STREET_MIN_N and street_rec_l not in ("", "no_coverage", "none", "unavailable")
        street_pass = fresh and covered
        street_detail = (
            f"{street_rec_l or '—'} · n={n} · "
            + (f"{street_age:.0f}h" if street_age is not None else "age unknown")
        )
        street_label = "Street evidence"
        if buy and street_rec_l in STREET_SELL:
            street_pass = False
            street_detail += " · CIO buy vs Street sell"
        if str(street_divergence or "").lower() == "divergent" and buy and street_rec_l not in STREET_BUY:
            street_pass = False
            street_detail += " · divergent"
    gates.append({"id": "street", "pass": street_pass, "label": street_label, "detail": street_detail})
    if not street_pass:
        failed.append("street")

    # QA / safety
    dq = str(decision_quality_status or "").lower()
    safety = str(decision_safety or "").lower()
    qa_pass = dq in ("", "actionable") and safety not in ("unsafe", "blocked")
    if actionable is False and dq not in ("", "actionable"):
        qa_pass = False
    if safety in ("unsafe", "blocked"):
        qa_pass = False
    gates.append({
        "id": "qa_safety",
        "pass": qa_pass,
        "label": "QA / safety",
        "detail": f"quality={dq or '—'} · safety={safety or '—'}",
    })
    if not qa_pass:
        failed.append("qa_safety")

    # Local-only on MAIN is always degraded
    if on_main and local_only:
        failed.append("local_fallback")
        gates.append({
            "id": "local_fallback",
            "pass": False,
            "label": "MAIN OAuth lanes",
            "detail": "local fallback — not HIGH on MAIN",
        })

    level = "HIGH" if not failed else "DEGRADED"
    return {
        "level": level,
        "trust_high": level == "HIGH",
        "failed_gates": failed,
        "gates": gates,
        "ages": {
            "synthesis_age_h": round(synth_age, 1) if synth_age is not None else None,
            "street_age_h": round(street_age, 1) if street_age is not None else None,
        },
        "dual_mode": dual_mode,
        "models_agree": agree,
        "street_n": n if not is_fund else None,
        "street_rec": street_rec_l or None,
        "recommendation": _rec(recommendation) or None,
        "on_main": on_main,
    }


def apply_trust_to_qa(qa: dict, trust: dict) -> dict:
    """Downgrade QA actionable when buy-side CIO is TRUST DEGRADED on dual/street."""
    out = dict(qa)
    rec = _rec(trust.get("recommendation") or qa.get("recommendation"))
    if not is_buy_side(rec):
        out["cio_trust"] = trust
        return out
    if trust.get("level") == "HIGH":
        out["cio_trust"] = trust
        return out
    # Fail-close buy-side actionable when dual/street/narrative failed
    hard = set(trust.get("failed_gates") or {}) & {"dual", "street", "narrative_consistency", "local_fallback"}
    if hard and out.get("actionable"):
        out["actionable"] = False
        dq = out.get("decision_quality_status") or out.get("status")
        if dq == "actionable":
            out["decision_quality_status"] = "cio_trust_degraded"
            out["status"] = "cio_trust_degraded"
        reasons = list(out.get("gating_reasons") or [])
        reasons.append(f"CIO TRUST DEGRADED: {', '.join(sorted(hard))}")
        out["gating_reasons"] = reasons
        out["needs_human_review"] = True
        out["human_review_required"] = True
    out["cio_trust"] = trust
    return out
