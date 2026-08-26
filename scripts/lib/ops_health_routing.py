"""Route machine telemetry away from investment intelligence."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

CHANNELS = (
    "INVESTMENT_DECISION",
    "CIO_BRIEF",
    "RISK_ALERT",
    "RESEARCH_INTELLIGENCE",
    "OPS_HEALTH",
)

OPS_PATTERNS = (
    r"zero_non_error_24h",
    r"COST_CONFIGURATION_INVALID",
    r"RAW-store health",
    r"hermes_rank_surge",
    r"deepseek",
    r"lane health",
    r"provider.?cost",
    r"scheduler mismatch",
)

RESEARCH_PATTERNS = (
    r"hermes.*(thesis|finding|material)",
    r"research completed",
    r"catalyst confirmed",
)


def looks_like_raw_json(text: str) -> bool:
    t = (text or "").strip()
    if t.startswith("{") and t.endswith("}") and ("schema" in t or "\"error\"" in t or "COST_CONFIGURATION" in t):
        return True
    if t.startswith("[") and '"symbol"' in t and ("rationale" in t or "recommended_action" in t):
        return True
    return False


def classify_message(text: str) -> dict[str, Any]:
    t = text or ""
    if looks_like_raw_json(t):
        return {
            "channel": "OPS_HEALTH",
            "is_investment_intelligence": False,
            "operator_alert": "suppressed_raw_json",
            "human": "Machine telemetry was suppressed. Raw JSON is available via detail/API, not Telegram.",
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "financial_action": False,
        }
    ops = any(re.search(p, t, re.I) for p in OPS_PATTERNS)
    if ops:
        degraded = bool(re.search(r"COST_CONFIGURATION_INVALID|zero_non_error", t, re.I))
        return {
            "channel": "OPS_HEALTH",
            "is_investment_intelligence": False,
            "cio_capability_degraded": degraded,
            "operator_alert": "only_if_cio_capability_degraded",
            "human": (
                "CIO DATA DEGRADATION — research enrichment unavailable. "
                "Existing portfolio facts remain available. No investment decision "
                "is being changed because of this failure. Action: none; system repair required."
            ) if degraded else (
                "Operations telemetry — not an investment recommendation."
            ),
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "financial_action": False,
        }
    if any(re.search(p, t, re.I) for p in RESEARCH_PATTERNS):
        return {
            "channel": "RESEARCH_INTELLIGENCE",
            "is_investment_intelligence": True,
            "authority": AUTHORITY,
            "financial_action": False,
        }
    if re.search(r"\[CIO DECISION\]|CIO OPERATOR PRODUCT|MORNING CIO BRIEF|EOD CIO BRIEF", t):
        return {
            "channel": "CIO_BRIEF" if "BRIEF" in t.upper() else "INVESTMENT_DECISION",
            "is_investment_intelligence": True,
            "authority": AUTHORITY,
            "financial_action": False,
        }
    return {
        "channel": "CIO_INTELLIGENCE",
        "is_investment_intelligence": True,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def cio_capability_impact(health_dir: Path) -> dict[str, Any] | None:
    """Ops health enters the CIO product only when a material decision needs missing data."""
    if not health_dir.exists():
        return None
    hits = []
    try:
        for p in list(health_dir.rglob("*"))[:40]:
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            if re.search(r"COST_CONFIGURATION_INVALID|zero_non_error_24h", text, re.I):
                hits.append(p.name)
    except OSError:
        return None
    if not hits:
        return None
    return {
        "affects_investment_reliability": True,
        "prose": (
            "Research provider unavailable. Decisions that require that research "
            "are labelled CIO DATA GAP. Existing holdings facts remain last-known-good. "
            f"Sources: {', '.join(hits[:4])}."
        ),
        "channel": "OPS_HEALTH",
        "authority": AUTHORITY,
        "financial_action": False,
    }
