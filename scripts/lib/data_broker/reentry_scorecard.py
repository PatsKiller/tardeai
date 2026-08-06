"""Re-Entry Scorecard — deterministic 8-stage checklist engine.

Computes per-symbol re-entry readiness using Data Broker enrichment providers.
Operator-driven: no cron, no silent DeepSeek calls. The operator presses a button.

Decision states:
  READY:        4+ confluences AND structure gate fired
  NEAR:         3+ confluences AND structure gate fired
  WAIT:         1-2 confluences OR 3+ but no structure
  SKIP:         0 confluences with viable data
  DISQUALIFIED: hard disqualifier hit
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# ── Gate result ──


@dataclass
class GateResult:
    stage: str          # "S0" through "S8"
    label: str          # "Gatekeeping", "Structure", "VWAP", etc.
    fired: bool
    value: Any = None
    detail: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    data_available: bool = True
    source: str = "none"


# ── Hard disqualifiers ──


def check_hard_disqualifiers(
    symbol: str,
    *,
    vwap_evidence: dict[str, Any] | None = None,
    macd_evidence: dict[str, Any] | None = None,
    rvol_ratio: float | None = None,
    attempt_number: int = 0,
    daily_loss_near_cap: bool = False,
    dilution_news: bool = False,
) -> str | None:
    """Return a disqualifier reason string, or None if none apply."""
    if attempt_number >= 3:
        return f"Attempt #{attempt_number} — max 2 re-entries per ticker per day"
    if daily_loss_near_cap:
        return "Daily loss near cap — no re-entry by policy"
    if dilution_news:
        return "Offering / ATM / dilution news — thesis compromised"

    # MACD below zero = trend dead
    if macd_evidence and macd_evidence.get("macd_signal") == "BEARISH" and macd_evidence.get("data_available"):
        return "5-min MACD crossed below zero — trend change detected"

    # RVOL decay
    if rvol_ratio is not None and rvol_ratio < 2.0:
        return f"RVOL {rvol_ratio:.1f}x below 2x threshold — catalyst decayed"

    # VWAP closed below with declining slope
    if vwap_evidence and vwap_evidence.get("data_available"):
        position = vwap_evidence.get("position")
        direction = vwap_evidence.get("direction")
        if position == "below" and direction in ("falling", "flat"):
            return "Closed below VWAP with VWAP declining — bearish structure"

    return None


# ── Stage 0: Gatekeeping ──


def compute_stage_0(
    symbol: str,
    *,
    db_query: Callable,
    stop_quality: dict[str, Any] | None = None,
    attempt_number: int = 0,
    daily_loss_near_cap: bool = False,
) -> GateResult:
    """Gatekeeping: thesis intact, stop quality, RVOL, attempt count, daily loss cap."""
    fired = True
    reasons = []

    # Load cached LLM insight
    thesis_intact = True
    stop_quality_text = None
    if stop_quality and stop_quality.get("analysis_parsed"):
        parsed = stop_quality["analysis_parsed"]
        sq = parsed.get("stop_quality", "unknown")
        rr_risk = parsed.get("reentry_risk", "unknown")
        stop_quality_text = sq
        if sq in ("structure_break", "poorly_managed"):
            thesis_intact = False
            reasons.append(f"Stop quality: {sq} — thesis may be compromised")
        else:
            reasons.append(f"Stop quality: {sq} (re-entry risk: {rr_risk})")

    if attempt_number >= 2:
        reasons.append(f"Attempt #{attempt_number}/{2} — last attempt for this ticker today")

    if daily_loss_near_cap:
        fired = False
        reasons.append("Daily loss near cap — blocked by policy")

    if not thesis_intact:
        fired = False

    return GateResult(
        stage="S0",
        label="Gatekeeping",
        fired=fired,
        value={"thesis_intact": thesis_intact, "stop_quality": stop_quality_text},
        detail={
            "thesis_intact": thesis_intact,
            "stop_quality": stop_quality_text,
            "attempt_number": attempt_number,
            "daily_loss_near_cap": daily_loss_near_cap,
        },
        reason="; ".join(reasons) if reasons else "Gatekeeping passed — thesis appears intact",
        data_available=True,
        source="reentry_llm_insight (cached)" if stop_quality else "none (no LLM insight)",
    )


# ── Scorecard builder ──


@dataclass
class ReEntryScorecard:
    symbol: str
    computed_at: str = ""
    gates: list[GateResult] = field(default_factory=list)
    confluence_count: int = 0
    has_structure_gate: bool = False
    decision_state: str = "WAIT"
    hard_disqualifier: str | None = None
    thesis: str | None = None
    provider_trace: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "computed_at": self.computed_at,
            "decision_state": self.decision_state,
            "hard_disqualifier": self.hard_disqualifier,
            "confluence_count": self.confluence_count,
            "has_structure_gate": self.has_structure_gate,
            "thesis": self.thesis,
            "gates": [
                {
                    "stage": g.stage,
                    "label": g.label,
                    "fired": g.fired,
                    "value": g.value,
                    "detail": g.detail,
                    "reason": g.reason,
                    "data_available": g.data_available,
                    "source": g.source,
                }
                for g in self.gates
            ],
            "provider_trace": self.provider_trace,
        }


def compute_scorecard(
    symbol: str,
    *,
    db_query: Callable,
    price: float | None = None,
    changepct: float | None = None,
    rsi: float | None = None,
    indicators: dict[str, Any] | None = None,
    entry_low: float | None = None,
    entry_high: float | None = None,
    stop_price: float | None = None,
    target_price: float | None = None,
    resistance: float | None = None,
    stop_quality: dict[str, Any] | None = None,
    attempt_number: int = 0,
    daily_loss_near_cap: bool = False,
    rvol_ratio: float | None = None,
    dilution_news: bool = False,
    thesis_text: str | None = None,
) -> ReEntryScorecard:
    """Compute the full 8-stage re-entry scorecard for one symbol.

    This is the single entry point. All enrichment calls happen here in order.
    """
    from lib.data_broker import reentry_enrichment as enrich

    now = datetime.now(timezone.utc).isoformat()
    gates: list[GateResult] = []
    provider_trace: dict[str, str] = {}

    # ── Stage 0: Gatekeeping ──
    g0 = compute_stage_0(
        symbol, db_query=db_query,
        stop_quality=stop_quality,
        attempt_number=attempt_number,
        daily_loss_near_cap=daily_loss_near_cap,
    )
    gates.append(g0)
    provider_trace["S0"] = g0.source

    # ── Early exit: hard disqualifiers ──
    # We must compute at least VWAP and MACD evidence to run disqualifier checks
    vwap_ev = enrich.get_vwap_evidence(db_query, symbol, price)
    macd_ev = enrich.get_macd_evidence(indicators)

    hard_disq = check_hard_disqualifiers(
        symbol,
        vwap_evidence=vwap_ev,
        macd_evidence=macd_ev,
        rvol_ratio=rvol_ratio,
        attempt_number=attempt_number,
        daily_loss_near_cap=daily_loss_near_cap,
        dilution_news=dilution_news,
    )

    if hard_disq:
        # Build remaining gates as "SKIPPED" for completeness
        for label, stage in [
            ("Structure", "S1"), ("VWAP", "S2"), ("Moving Averages", "S3"),
            ("MACD", "S4"), ("Fibonacci", "S5"), ("Volume & Tape", "S6"),
            ("Trigger Candle", "S7"), ("Risk", "S8"),
        ]:
            gates.append(GateResult(
                stage=stage, label=label, fired=False,
                reason=f"SKIPPED — hard disqualifier: {hard_disq}",
                data_available=False, source="none",
            ))
        return ReEntryScorecard(
            symbol=symbol, computed_at=now, gates=gates,
            confluence_count=0, has_structure_gate=False,
            decision_state="DISQUALIFIED", hard_disqualifier=hard_disq,
            provider_trace=provider_trace,
        )

    # ── Stage 1: Structure ──
    g1_data = enrich.get_structure_evidence(symbol, stop_price)
    g1 = GateResult(
        stage="S1", label="Structure",
        fired=g1_data["fired"],
        detail=g1_data,
        reason=g1_data["reason"],
        data_available=g1_data["data_available"],
        source=g1_data["source"],
    )
    gates.append(g1)
    provider_trace["S1"] = g1_data["source"]

    # ── Stage 2: VWAP ──
    g2 = GateResult(
        stage="S2", label="VWAP",
        fired=vwap_ev["fired"],
        detail=vwap_ev,
        reason=vwap_ev["reason"],
        data_available=vwap_ev["data_available"],
        source=vwap_ev["source"],
    )
    gates.append(g2)
    provider_trace["S2"] = vwap_ev["source"]

    # ── Stage 3: Moving Averages ──
    sma_ev = enrich.get_sma_evidence(indicators)
    g3 = GateResult(
        stage="S3", label="Moving Averages",
        fired=sma_ev["fired"],
        detail=sma_ev,
        reason=sma_ev["reason"],
        data_available=sma_ev["data_available"],
        source=sma_ev["source"],
    )
    gates.append(g3)
    provider_trace["S3"] = sma_ev["source"]

    # ── Stage 4: MACD ──
    g4 = GateResult(
        stage="S4", label="MACD",
        fired=macd_ev["fired"],
        detail=macd_ev,
        reason=macd_ev["reason"],
        data_available=macd_ev["data_available"],
        source=macd_ev["source"],
    )
    gates.append(g4)
    provider_trace["S4"] = macd_ev["source"]

    # ── Stage 5: Fibonacci ──
    fib_ev = enrich.get_fib_evidence(indicators)
    g5 = GateResult(
        stage="S5", label="Fibonacci",
        fired=fib_ev["fired"],
        detail=fib_ev,
        reason=fib_ev["reason"],
        data_available=fib_ev["data_available"],
        source=fib_ev["source"],
    )
    gates.append(g5)
    provider_trace["S5"] = fib_ev["source"]

    # ── Stage 6: Volume & Tape ──
    vol_ev = enrich.get_volume_evidence(db_query, symbol)
    g6 = GateResult(
        stage="S6", label="Volume & Tape",
        fired=vol_ev["fired"],
        detail=vol_ev,
        reason=vol_ev["reason"],
        data_available=vol_ev["data_available"],
        source=vol_ev["source"],
    )
    gates.append(g6)
    provider_trace["S6"] = vol_ev["source"]

    # ── Stage 7: Trigger Candle ──
    trig_ev = enrich.get_trigger_evidence(symbol)
    g7 = GateResult(
        stage="S7", label="Trigger Candle",
        fired=trig_ev["fired"],
        detail=trig_ev,
        reason=trig_ev["reason"],
        data_available=trig_ev["data_available"],
        source=trig_ev["source"],
    )
    gates.append(g7)
    provider_trace["S7"] = trig_ev["source"]

    # ── Stage 8: Risk ──
    risk_ev = enrich.get_risk_evidence(
        symbol, price=price, stop_price=stop_price,
        target_price=target_price, entry_low=entry_low,
        resistance=resistance, attempt_number=attempt_number,
    )
    g8 = GateResult(
        stage="S8", label="Risk",
        fired=risk_ev["fired"],
        detail=risk_ev,
        reason=risk_ev["reason"],
        data_available=risk_ev["data_available"],
        source=risk_ev["source"],
    )
    gates.append(g8)
    provider_trace["S8"] = risk_ev["source"]

    # ── Decision: count confluences ──
    structure_gates = [g1]
    all_scoring_gates = gates[1:]  # skip S0 gatekeeping
    confluences = [g for g in all_scoring_gates if g.fired]
    has_structure = any(g.fired for g in structure_gates)

    count = len(confluences)

    if count >= 4 and has_structure:
        state = "READY"
    elif count >= 3 and has_structure:
        state = "NEAR"
    elif count >= 1:
        state = "WAIT"
    elif count == 0 and any(g.data_available for g in all_scoring_gates):
        state = "SKIP"
    else:
        state = "WAIT"  # no data → wait for data

    return ReEntryScorecard(
        symbol=symbol,
        computed_at=now,
        gates=gates,
        confluence_count=count,
        has_structure_gate=has_structure,
        decision_state=state,
        thesis=thesis_text,
        provider_trace=provider_trace,
    )
