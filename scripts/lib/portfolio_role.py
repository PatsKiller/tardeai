"""Portfolio-role taxonomy for material symbols (READ_ONLY_ADVISORY).

Role is portfolio *context*, not financial truth or a BUY signal.
Operator declarations win over weak inferences.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]

ROLES = (
    "CORE_GROWTH",
    "GROWTH",
    "QUALITY_CORE",
    "INCOME",
    "DEFENSIVE",
    "CYCLICAL",
    "VALUE",
    "SATELLITE",
    "HEDGE",
    "SPECULATIVE",
    "CASH_ALTERNATIVE",
    "UNKNOWN",
)

# Operator-provided durable context (explicit handoff 2026-08-19).
# Not market truth. Not a recommendation.
OPERATOR_ROLE_OVERRIDES: dict[str, dict[str, Any]] = {
    "SCHG": {
        "portfolio_role": "GROWTH",
        "confidence": "HIGH",
        "source": "operator_declaration",
        "note": "Operator: SCHG represented growth exposure in the book.",
    },
}

# Weak ticker/sector heuristics — only used when no stronger evidence.
_TICKER_HINTS: dict[str, str] = {
    "SCHG": "GROWTH",
    "SCHD": "INCOME",
    "JEPI": "INCOME",
    "DIV": "INCOME",
    "DIVI": "INCOME",
    "PFLT": "INCOME",
    "CSWC": "INCOME",
    "BND": "DEFENSIVE",
    "XAR": "CYCLICAL",
    "XLI": "CYCLICAL",
    "XLB": "CYCLICAL",
    "NOC": "DEFENSIVE",
    "LDOS": "DEFENSIVE",
    "RTX": "DEFENSIVE",
    "BAH": "DEFENSIVE",
}


def _sym(s: str) -> str:
    return str(s or "").strip().upper()


def load_operator_overrides(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Merge code defaults with optional file override (worktree-local OK)."""
    root = Path(root or ROOT)
    out = dict(OPERATOR_ROLE_OVERRIDES)
    path = root / "config" / "operator_portfolio_roles.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            rows = data.get("roles") if isinstance(data, dict) else data
            if isinstance(rows, dict):
                for k, v in rows.items():
                    if isinstance(v, dict) and v.get("portfolio_role") in ROLES:
                        out[_sym(k)] = {
                            "portfolio_role": v["portfolio_role"],
                            "confidence": v.get("confidence") or "HIGH",
                            "source": v.get("source") or "operator_file",
                            "note": v.get("note") or "",
                        }
        except Exception:
            pass
    return out


def resolve_portfolio_role(
    symbol: str,
    *,
    universe_rec: Optional[dict[str, Any]] = None,
    thesis_rec: Optional[dict[str, Any]] = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return role resolution with provenance."""
    s = _sym(symbol)
    overrides = load_operator_overrides(root)

    if s in overrides:
        o = overrides[s]
        return {
            "symbol": s,
            "portfolio_role": o["portfolio_role"],
            "prior_portfolio_role": None,
            "confidence": o.get("confidence") or "HIGH",
            "source": o.get("source") or "operator_declaration",
            "evidence": [o.get("note") or "operator override"],
            "role_research_required": False,
            "authority": "READ_ONLY_ADVISORY",
        }

    evidence: list[str] = []
    role = "UNKNOWN"
    confidence = "LOW"
    source = "insufficient"

    # Thesis metadata (if symbol thesis already carries role)
    if thesis_rec:
        tr = thesis_rec.get("portfolio_role") or (thesis_rec.get("metadata") or {}).get("portfolio_role")
        if tr in ROLES and tr != "UNKNOWN":
            role = tr
            confidence = "MEDIUM"
            source = "symbol_thesis"
            evidence.append("role from symbol thesis metadata")

    # Former category mechanical hint (weak)
    former = (universe_rec or {}).get("former") or {}
    cat = str(former.get("category") or "").lower()
    if role == "UNKNOWN" and cat:
        mapping = {
            "long_term_compounder": "QUALITY_CORE",
            "position": "SATELLITE",
            "day_swing": "SPECULATIVE",
        }
        if cat in mapping:
            role = mapping[cat]
            confidence = "LOW"
            source = "former_holding_category"
            evidence.append(f"previously_traded category={cat}")

    # Company/sector string from reentry desk (weak)
    reentry = (universe_rec or {}).get("reentry") or {}
    # ticker hint last
    if role == "UNKNOWN" and s in _TICKER_HINTS:
        role = _TICKER_HINTS[s]
        confidence = "LOW"
        source = "ticker_hint"
        evidence.append(f"weak ticker hint → {role}")

    return {
        "symbol": s,
        "portfolio_role": role if role in ROLES else "UNKNOWN",
        "prior_portfolio_role": None,
        "confidence": confidence,
        "source": source,
        "evidence": evidence,
        "role_research_required": role == "UNKNOWN",
        "authority": "READ_ONLY_ADVISORY",
    }
