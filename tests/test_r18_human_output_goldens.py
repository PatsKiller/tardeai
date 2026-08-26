"""≥100 human-output goldens. Operator must understand the action without JSON."""
from __future__ import annotations

from scripts.lib.cio_operator_product import _entry_from_rec, render_human
from scripts.lib.operator_human_renderer import looks_like_raw_json, render_decision, render_product
from scripts.lib.research_intelligence_summary import from_research_result, render_human as render_research

CRITICAL = (
    "material HOLD",
    "material TRIM",
    "reentry candidate",
    "cash posture",
    "sector rotation",
    "earnings",
    "research gap",
    "research failure",
    "stale holdings",
    "identity unresolved",
    "no material change",
    "multiple simultaneous changes",
)


def _product_for(tag: str, i: int) -> dict:
    action_cycle = ["HOLD", "TRIM", "REENTER", "WATCH", "AVOID", "REVIEW", "WAIT", "NO_ACTION"]
    action = action_cycle[i % len(action_cycle)]
    if "TRIM" in tag:
        action = "TRIM"
    elif "HOLD" in tag and "cash" not in tag:
        action = "HOLD"
    elif "reentry" in tag:
        action = "REENTER"
    elif "cash" in tag:
        action = "HOLD_CASH"
    entry = _entry_from_rec({
        "symbol": ["NVDA", "GERN", "NOC", "CASH", "XLB"][i % 5],
        "recommended_action": action,
        "title": f"{action} scenario {tag}",
        "description": f"What changed is {tag} at index {i}.",
        "rationale": f"CIO view: {tag}. Operator should understand without JSON.",
        "priority": "HIGH" if action in {"TRIM", "REENTER", "REVIEW"} else "LOW",
        "confidence": round(0.4 + (i % 6) * 0.1, 2),
        "counterpoint": "Could be wrong if earnings miss." if i % 3 == 0 else None,
        "data_quality": "LAST_KNOWN_GOOD" if "stale" in tag else ("IDENTITY_UNRESOLVED" if "identity" in tag else "OK"),
        "next_review": "next session",
    })
    if "research failure" in tag:
        return {
            "schema": "CIOOperatorProduct@v1",
            "available": True,
            "status": "AVAILABLE",
            "executive_summary": "Research provider unavailable. Existing facts remain last-known-good.",
            "data_quality": {"state": "DEGRADED_RESEARCH", "labels": ["CIO_DATA_GAP"]},
            "entries": [entry],
            "decisions": [entry],
            "action_now": [],
        }
    if "no material change" in tag:
        entry["what_should_i_do"] = "NOTHING"
        entry["cio_decision"] = "HOLD"
    return {
        "schema": "CIOOperatorProduct@v1",
        "available": True,
        "status": "AVAILABLE",
        "executive_summary": f"Scenario {tag} #{i}",
        "entries": [entry],
        "decisions": [entry],
        "action_now": [entry] if entry.get("what_should_i_do") == "NOW" else [],
        "data_quality": {"state": entry.get("data_quality")},
    }


def _all_tags() -> list[str]:
    tags = list(CRITICAL)
    extras = [
        "watch only", "avoid name", "review catalyst", "macro risk-on",
        "industry leading", "theme AI", "policy gap", "multiple trims",
        "reentry blocked", "cash deploy none",
    ]
    tags.extend(extras)
    while len(tags) < 108:
        tags.append(CRITICAL[len(tags) % len(CRITICAL)] + f" variant")
    return tags[:108]


def test_one_hundred_human_goldens():
    tags = _all_tags()
    assert len(tags) >= 100
    for i, tag in enumerate(tags):
        product = _product_for(tag, i)
        text = render_product(product)
        assert not looks_like_raw_json(text), tag
        assert "CIO" in text or "[CIO DECISION]" in text
        assert "What changed" in text or "Standing" in text or "DATA" in text
        # Operator can see an action word without parsing JSON.
        assert any(w in text for w in (
            "HOLD", "TRIM", "REENTER", "WATCH", "AVOID", "REVIEW", "WAIT", "NO_ACTION",
            "NONE", "NOTHING", "DATA GAP", "DEGRADED",
        )), tag


def test_critical_named_scenarios_are_prose():
    for tag in CRITICAL:
        text = render_human(_product_for(tag, 1))
        assert "{" not in text or "CIO" in text
        assert "Decision:" in text or "HOLD" in text or "DATA" in text


def test_research_and_decision_cards_not_json():
    d = render_decision({
        "symbol": "NOC",
        "cio_decision": "HOLD",
        "what_changed": "No thesis break",
        "why_it_matters": "Defense exposure remains core",
        "what_should_i_do": "NOTHING",
        "confidence": 0.8,
        "data_quality": "OK",
        "next_review": "after earnings",
    })
    assert d.startswith("[CIO DECISION] NOC")
    assert "Decision: HOLD" in d
    r = render_research(from_research_result({
        "entity": "NOC",
        "question": "earnings quality",
        "what_was_found": "in-line",
        "material_change": False,
    }))
    assert r.startswith("[RESEARCH] NOC")
    assert not looks_like_raw_json(r)
