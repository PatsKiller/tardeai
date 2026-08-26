"""R16 golden generators — outcome quality, lookahead, lessons."""
from __future__ import annotations

from scripts.lib.cio_institutional_learning import DECISION_CLASSES, QUALITY_AXES, HORIZONS, FEEDBACK_TAXONOMY


def outcome_goldens() -> list[dict]:
    cases = []
    recs = list(DECISION_CLASSES)
    for i in range(100):
        rec = recs[i % len(recs)]
        cases.append({
            "id": f"O-{i:03d}",
            "recommendation": rec,
            "pnl_up": i % 3 == 0,
            "risk_warning": rec in {"TRIM", "EXIT", "RISK_CRITIQUE", "HOLD_CASH"},
            "evidence": i % 2 == 0,
            "horizon": HORIZONS[i % len(HORIZONS)],
            "expect_pnl_not_grade": True,
        })
    return cases


def lookahead_goldens() -> list[dict]:
    cases = []
    for i in range(75):
        if i % 5 == 0:
            ctx = {"future_price": 12.0}
            allow = False
        elif i % 5 == 1:
            ctx = {"evidence": [{"id": f"e{i}", "as_of": "2026-09-01T00:00:00+00:00"}]}
            allow = False
        elif i % 5 == 2:
            ctx = {"later_thesis": "v9"}
            allow = False
        elif i % 5 == 3:
            ctx = {"evidence": [{"id": f"e{i}", "as_of": "2026-01-01T00:00:00+00:00"}]}
            allow = True
        else:
            ctx = {"evidence": []}
            allow = True
        cases.append({"id": f"L-{i:03d}", "as_of": "2026-08-01T00:00:00+00:00", "context": ctx, "allow": allow})
    return cases


def specialist_model_goldens() -> list[dict]:
    agents = ["maria", "steph", "guardian", "ledger"]
    tasks = ["extraction", "classification", "research_curation", "contradiction_reconciliation",
             "risk_critique", "tax_critique", "portfolio_synthesis", "operator_explanation",
             "notification_rendering", "deep_invalidation"]
    cases = []
    for i in range(100):
        cases.append({
            "id": f"S-{i:03d}",
            "agent": agents[i % 4],
            "task": tasks[i % 10],
            "agree_with_cio": i % 2 == 0,
            "unique_evidence": i % 3 == 0,
            "score_on_agreement": False,
        })
    return cases
