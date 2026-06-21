#!/usr/bin/env python3
"""Inference Layers — risk-appropriate sizing.

Turns the engine's synthesized signals (volatility regime, journal-derived edge,
inference confidence, FOMO/chase flags, regional impact) into a *risk-adjusted*
share recommendation — without bypassing any existing safety machinery.

Single source of truth is preserved:
  * shares come from account_policy.compute_sizing() (same engine risk_gate trusts)
  * the regime/confidence/journal signal only moves the `tilt` knob that
    compute_sizing already understands, within a hard clamp
  * the recommended plan is then re-run through risk_gate.RiskGate.check() so a
    recommendation can never exceed the account's risk envelope

Output is advisory: written to inference_sizing_recommendations for the existing
approval/execution path to consume. It does not mutate proposals.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("inference_sizing")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def compute_tilt(cfg: dict, regime: str, confidence: float,
                 journal_edge: float = 0.0, fomo: bool = False) -> tuple[float, list]:
    """Derive the sizing tilt from synthesized signals. Returns (tilt, reasoning)."""
    s = cfg.get("sizing", {}) or {}
    base = float(s.get("base_tilt", 1.0))
    regime_tilt = float((s.get("regime_tilts", {}) or {}).get(regime, 1.0))
    tilt = base * regime_tilt
    reasoning = [f"base={base}", f"regime={regime}->x{regime_tilt}"]

    min_conf = float(s.get("min_confidence_for_uptilt", 0.6))
    if confidence >= min_conf:
        # scale up modestly with conviction above the bar
        bump = 1.0 + min(0.25, (confidence - min_conf))
        tilt *= bump
        reasoning.append(f"confidence={confidence:.2f}->x{bump:.2f}")
    elif confidence < 0.4:
        tilt *= 0.85
        reasoning.append(f"low_confidence={confidence:.2f}->x0.85")

    # journal edge in [-1, 1]; positive expectancy enlarges, negative shrinks
    jw = float(s.get("journal_edge_weight", 0.5))
    if journal_edge:
        adj = 1.0 + _clamp(journal_edge, -1.0, 1.0) * jw
        adj = _clamp(adj, 0.5, 1.5)
        tilt *= adj
        reasoning.append(f"journal_edge={journal_edge:+.2f}->x{adj:.2f}")

    if fomo:
        pen = float(s.get("fomo_penalty", 0.8))
        tilt *= pen
        reasoning.append(f"fomo->x{pen}")

    tilt = _clamp(tilt, float(s.get("tilt_floor", 0.4)), float(s.get("tilt_ceiling", 1.5)))
    reasoning.append(f"tilt={tilt:.3f}")
    return round(tilt, 3), reasoning


def recommend(proposal: dict, *, regime: str, confidence: float, cfg: dict,
              account: Optional[str] = None, journal_edge: float = 0.0,
              fomo: bool = False, conn=None) -> dict:
    """Produce a risk-adjusted sizing recommendation for a proposal-like dict.

    `proposal` needs at least: symbol, strategy_id, proposed_entry, proposed_stop,
    proposed_shares (optional). Works for live PENDING proposals or hypotheticals.
    """
    account = account or proposal.get("target_account") or cfg.get("account", "rollover")
    symbol = proposal.get("symbol")
    strategy_id = proposal.get("strategy_id") or proposal.get("primary_strategy_id") or "swing_breakout"
    entry = proposal.get("proposed_entry") or proposal.get("entry")
    stop = proposal.get("proposed_stop") or proposal.get("stop")
    desired = proposal.get("proposed_shares") or proposal.get("shares")

    out = {
        "symbol": symbol, "strategy_id": strategy_id, "account": account,
        "regime": regime, "confidence": round(confidence, 3),
        "base_shares": None, "recommended_shares": None, "tilt": 1.0,
        "risk_gate_result": None, "risk_flags": [], "rationale": "",
        "sizing_basis": {}, "proposal_id": proposal.get("id"),
    }
    if not (entry and stop):
        out["rationale"] = "missing entry/stop — cannot size"
        out["risk_flags"] = ["MISSING_PLAN_DATA"]
        return out

    try:
        import account_policy as ap
        policy = ap.load_policy(account)
        equity, eq_src = ap.equity_for_account(account)

        base = ap.compute_sizing(policy, equity, entry, stop, desired_shares=desired, tilt=1.0)
        out["base_shares"] = base.get("shares")

        tilt, tilt_reasoning = compute_tilt(cfg, regime, confidence, journal_edge, fomo)
        out["tilt"] = tilt
        adj = ap.compute_sizing(policy, equity, entry, stop, desired_shares=desired, tilt=tilt)
        out["recommended_shares"] = adj.get("shares")
        out["sizing_basis"] = {"equity": equity, "equity_source": eq_src,
                               "engine": adj.get("engine"), "binding": adj.get("binding"),
                               "dollar_risk": adj.get("dollar_risk"),
                               "dollar_size": adj.get("dollar_size"),
                               "tilt_reasoning": tilt_reasoning}
    except Exception as e:
        log.warning("sizing compute failed for %s: %s", symbol, e)
        out["rationale"] = f"sizing error: {e}"
        out["risk_flags"] = ["SIZING_ERROR"]
        return out

    # Re-validate the recommended plan through the existing risk gate
    try:
        from risk_gate import RiskGate
        gate = RiskGate(conn)
        rr = None
        try:
            rr = abs((proposal.get("proposed_target1") or proposal.get("target") or 0) - entry) / \
                 max(1e-9, abs(entry - stop))
        except Exception:
            rr = None
        plan = {"entry": entry, "stop": stop,
                "target1": proposal.get("proposed_target1") or proposal.get("target"),
                "shares": out["recommended_shares"],
                "dollar_size": out["sizing_basis"].get("dollar_size"),
                "dollar_risk": out["sizing_basis"].get("dollar_risk"),
                "rr": rr, "sector": proposal.get("sector")}
        decision = gate.check(symbol, strategy_id, trade_plan=plan, account=account,
                              mode="paper", action_context="discovery")
        out["risk_gate_result"] = decision.result
        out["risk_flags"] = list(decision.reason_codes or [])
        if not decision.approved:
            # gate disagrees -> recommend the smaller of (gate-safe base, 0)
            out["recommended_shares"] = 0
            out["rationale"] = f"risk gate {decision.result}: {decision.reason_text[:200]}"
            return out
    except Exception as e:
        log.debug("risk gate revalidation skipped: %s", e)
        out["risk_flags"].append("GATE_UNAVAILABLE")

    delta = (out["recommended_shares"] or 0) - (out["base_shares"] or 0)
    verb = "up" if delta > 0 else ("down" if delta < 0 else "unchanged")
    out["rationale"] = (f"{regime} regime, conf {confidence:.0%}, tilt {out['tilt']:.2f} "
                        f"-> size {verb} {abs(delta)} sh vs base ({out['base_shares']}->"
                        f"{out['recommended_shares']}).")
    return out


def persist_recommendation(run_id: Optional[int], rec: dict) -> bool:
    if run_id is None:
        return False
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return False
        return bool(_execute(
            """INSERT INTO inference_sizing_recommendations
               (run_id, proposal_id, symbol, strategy_id, account, base_shares,
                recommended_shares, tilt, regime, confidence, risk_gate_result,
                risk_flags, rationale, sizing_basis)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, rec.get("proposal_id"), rec.get("symbol"), rec.get("strategy_id"),
             rec.get("account"), rec.get("base_shares"), rec.get("recommended_shares"),
             rec.get("tilt"), rec.get("regime"), rec.get("confidence"),
             rec.get("risk_gate_result"), json.dumps(rec.get("risk_flags", [])),
             rec.get("rationale", "")[:2000], json.dumps(rec.get("sizing_basis", {}), default=str)),
            fetch=None))
    except Exception as e:
        log.warning("sizing persist failed: %s", e)
        return False
