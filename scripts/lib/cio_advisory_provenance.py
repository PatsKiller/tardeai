"""cio_advisory_provenance.py — Phase 8 Advisory Desk data-quality repair.

Build compact provenance blocks so expanded cards never force the operator
to reverse-engineer conflicting prices/targets.
"""
from __future__ import annotations

from typing import Any, Optional

from scripts.lib.cio_financial_truth_gate import (
    analyst_upside_vs_canonical,
    classify_price_fields,
    dollar_tol,
)

ADVISORY_PROVENANCE_VERSION = "advisory_provenance_1.0.0"


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def build_expanded_row_provenance(row: dict[str, Any]) -> dict[str, Any]:
    """Ordered provenance for one advisory/holdings expanded row."""
    shares = _f(row.get("shares") if row.get("shares") is not None else row.get("quantity"))
    price_info = classify_price_fields(row)
    px = price_info.get("canonical_price")
    mv = _f(row.get("market_value"))
    basis = _f(row.get("cost_basis") or row.get("average_cost"))
    implied = (shares * px) if (shares is not None and px is not None) else None
    upl = (mv - basis) if (mv is not None and basis is not None) else None
    upl_pct = (upl / basis * 100.0) if (upl is not None and basis and basis > 0) else None

    analyst_target = _f(row.get("analyst_target") or row.get("target_price") or row.get("consensus_target"))
    analyst_as_of = row.get("analyst_as_of") or row.get("target_as_of")
    analyst_snap_px = _f(row.get("analyst_snapshot_price") or row.get("provider_ref_price"))
    upside = analyst_upside_vs_canonical(
        analyst_target=analyst_target,
        canonical_price=px,
        analyst_snapshot_price=analyst_snap_px,
    )

    conflicts: list[str] = []
    if price_info.get("conflicted"):
        conflicts.append(
            f"Dual price fields disagree: {price_info.get('prices')}"
        )
    if implied is not None and mv is not None:
        if abs(implied - mv) > dollar_tol(mv):
            conflicts.append(
                f"shares×price ({implied:.2f}) ≠ market_value ({mv:.2f})"
            )
    if upside.get("quality") == "CONFLICTED":
        conflicts.append(
            "Analyst upside uses a different denominator than canonical current price"
        )

    # Deterministic vs desk synthesis
    det = str(row.get("deterministic_stance") or row.get("stance_code") or row.get("cio_stance") or "")
    maria = str(row.get("maria_stance") or row.get("fundamental_stance") or "")
    guardian = str(row.get("guardian_stance") or row.get("risk_stance") or "")
    synthesis = None
    if det.upper() == "TRIM" and (
        maria.upper() in ("HOLD", "") or guardian.upper() in ("HOLD", "")
    ):
        synthesis = (
            "Fundamental desks remain HOLD. The trim signal is portfolio-risk driven, "
            "not thesis deterioration."
        )

    facts = [
        {
            "label": "Current price",
            "value": px,
            "display": f"${px:,.2f}" if px is not None else "—",
            "as_of": row.get("updated_at") or row.get("as_of") or row.get("price_as_of"),
            "source": row.get("price_source") or price_info.get("canonical_price_key") or "quote",
        },
        {
            "label": "Position value",
            "value": mv,
            "display": f"${mv:,.0f}" if mv is not None else "—",
            "as_of": row.get("updated_at") or row.get("as_of"),
            "source": (
                f"calculated from {shares:g} × ${px:.2f}" if shares and px else "holdings.market_value"
            ),
        },
        {
            "label": "Cost basis",
            "value": basis,
            "display": f"${basis:,.0f}" if basis is not None else "—",
            "as_of": row.get("basis_as_of") or row.get("last_reconciled_at"),
            "source": row.get("cost_basis_source") or "broker/lots",
        },
        {
            "label": "Unrealized gain",
            "value": upl,
            "display": (
                f"${upl:,.0f} / {upl_pct:+.2f}%" if upl is not None and upl_pct is not None else "—"
            ),
            "source": "market_value − cost_basis",
        },
        {
            "label": "Analyst target",
            "value": analyst_target,
            "display": f"${analyst_target:,.2f}" if analyst_target is not None else "—",
            "as_of": analyst_as_of,
            "source": "analyst_consensus",
        },
        {
            "label": upside.get("label") or "Upside",
            "value": upside.get("upside_pct"),
            "display": (
                f"{upside['upside_pct']:+.2f}%" if upside.get("upside_pct") is not None else "—"
            ),
            "source": f"target vs {upside.get('denominator_price')}",
            "quality": upside.get("quality"),
            "note": upside.get("note"),
        },
    ]

    return {
        "version": ADVISORY_PROVENANCE_VERSION,
        "symbol": row.get("symbol"),
        "order": [
            "decision",
            "current_financial_facts",
            "portfolio_role",
            "price_trend",
            "analyst_research",
            "specialist_opinions",
            "conflicts",
            "evidence_provenance",
            "operator_actions",
        ],
        "current_financial_facts": facts,
        "conflicts": conflicts,
        "opinion_synthesis": synthesis,
        "specialist_opinions": {
            "deterministic": det or None,
            "maria_or_fundamental": maria or None,
            "guardian_or_risk": guardian or None,
        },
        "price_fields": price_info.get("prices") or {},
        "authority": "READ_ONLY_ADVISORY",
    }
