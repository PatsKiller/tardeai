"""Unit tests for Operator Inbox plain-language curation (homeLabels.inboxDetailPlain)."""
from __future__ import annotations

# Lightweight mirror of the TypeScript rules so CI can lock examples without a TS runner.
# Keep in sync with apps/command-center-v3/src/lib/homeLabels.ts → inboxDetailPlain.

STATE = {
    "HUMAN_REVIEW": "needs your review",
    "ROTATION_REVIEW": "rotation review",
    "ADD_ON_PULLBACK": "add on a pullback",
    "HOLD": "hold",
    "dividend_growth_compounder": "dividend growth",
    "high_yield_income_bdc": "high-yield income BDC",
    "core_index": "core index",
    "defense_thesis": "defense thesis",
    "REBALANCE": "rebalance",
}


def inbox_detail_plain(raw: str) -> str:
    import re
    s = (raw or "").strip()
    if not s:
        return "Review required"
    head = re.match(r"^([A-Z_]+)\s*[·•|]\s*(.+)$", s)
    decision_raw, rest = (head.group(1), head.group(2)) if head else ("", s)
    strat_act = re.match(r"^([a-z][a-z0-9_]*)\s+([A-Z][A-Z0-9_]+)\b", rest)
    strategy_raw = action_raw = ""
    if strat_act:
        strategy_raw, action_raw = strat_act.group(1), strat_act.group(2)
        rest = rest[len(strat_act.group(0)):].lstrip(". ")
    signal_m = re.search(r"Signal\s*=\s*([0-9.]+)\s*(?:\(([^)]+)\))?", rest, re.I)
    weight_m = re.search(r"Weight\s*=\s*([0-9.]+)", rest, re.I)
    parts = []
    decision = STATE.get(decision_raw, decision_raw.replace("_", " ").lower() if decision_raw else "")
    if decision:
        parts.append(decision[:1].upper() + decision[1:])
    strategy = STATE.get(strategy_raw, strategy_raw.replace("_", " ") if strategy_raw else "")
    action = STATE.get(action_raw, action_raw.replace("_", " ").lower() if action_raw else "")
    if strategy and action:
        parts.append(f"{strategy} — {action}")
    elif strategy:
        parts.append(strategy)
    elif action:
        parts.append(action)
    if signal_m:
        lvl = (signal_m.group(2) or "").lower()
        n = float(signal_m.group(1))
        parts.append(f"signal {lvl} ({n:.2f})" if lvl else f"signal {n:.2f}")
    if weight_m:
        w = float(weight_m.group(1))
        parts.append("not in book (0% weight)" if w == 0 else f"book weight {w:.1f}%")
    return ". ".join(parts) + "." if parts else s


def test_human_review_dividend_pullback():
    raw = "HUMAN_REVIEW · dividend_growth_compounder ADD_ON_PULLBACK. Signal=0.10 (low). Weight=0.0%. Inco"
    out = inbox_detail_plain(raw)
    assert "needs your review" in out.lower()
    assert "dividend growth" in out.lower()
    assert "add on a pullback" in out.lower()
    assert "0.10" in out
    assert "HUMAN_REVIEW" not in out
    assert "ADD_ON_PULLBACK" not in out


def test_rotation_defense_hold():
    raw = "ROTATION_REVIEW · defense_thesis HOLD. Signal=0.62 (critical). Weight=0.0%. Income=0%. Synthesis=H"
    out = inbox_detail_plain(raw)
    assert "rotation review" in out.lower()
    assert "defense thesis" in out.lower()
    assert "hold" in out.lower()
    assert "critical" in out.lower()


def test_core_index_rebalance_language():
    raw = "HUMAN_REVIEW · core_index HOLD. Signal=0.07 (low). Weight=0.0%. Income=17%. Synthesis=REBALANCE"
    out = inbox_detail_plain(raw)
    assert "core index" in out.lower()
    assert "HUMAN_REVIEW" not in out
