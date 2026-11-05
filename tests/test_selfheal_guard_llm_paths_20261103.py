"""The fixer's diff guard refuses the LLM policy and enforcement files the supervisor obeys.

cc2's whole-head review of #2509 (Ground 1b) reproduced these as OPEN to the shipped matcher:
the supervisor's model call is `default_model -> governed_cloud_generation.generate_cloud ->
llm_consumption.get_process_config`, which reads the allowed lane set and the token caps FROM THE
REGISTRY; `anthropic_routing` decides the model and the cost ceiling; and the supervisor pages
through `telegram_alert`. A `code_defect` fix PR could therefore raise its own token caps, widen the
allowed lanes or change the routing policy without tripping the guard that exists to stop it.

This test uses the REAL matcher (`lib.self_heal_fixer._match_any`, the same function the fixer calls),
not a string membership check, and pins a negative control so the assertion cannot pass by refusing
everything. Reverting any one of the seven entries makes it fail.

Hermetic: reads two repo files, no process, no network, no state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

REFUSED = (
    "config/llm_process_registry.json",
    "config/anthropic_credit_policy.json",
    "config/llm_routing_policy.json",
    "scripts/lib/governed_cloud_generation.py",
    "scripts/lib/llm_consumption.py",
    "scripts/lib/anthropic_routing.py",
    "scripts/telegram_alert.py",
    # cc2's completeness trace (second review, 2026-11-03): the rest of the model/spend/send path.
    "config/llm_lane_floors.json",
    "config/llm_model_registry.json",
    "scripts/lib/anthropic_transport.py",
    "scripts/lib/anthropic_credit.py",
    "scripts/llm_lane.py",
    "scripts/lib/llm_bridge_route.py",
    "scripts/lib/llm_lane_reservation.py",
    "scripts/lib/consumption_run_manual.py",
    "scripts/lib/bridge_agent_preconditions.py",
    "scripts/lib/governed_process_routes.py",
    "scripts/lib/model_chooser.py",
    "scripts/lib/oauth_lane_status.py",
    "scripts/lib/llm_model_registry.py",
    "scripts/lib/provider_cost/emit.py",
    # cc-deepseek-3's completeness finding (2026-11-05): a fix PR must not change
    # what a token costs or make the spend gate pass while emit.py stays closed.
    "scripts/lib/provider_cost/pricing.py",
    "scripts/lib/provider_cost/budget.py",
    "scripts/lib/provider_cost/__init__.py",
    "scripts/telegram_transport.py",
    "scripts/telegram_alert_router.py",
)

#: Entries that already protected the operator-only surface: the guard must not have shrunk to add these.
STILL_REFUSED = (
    "AGENTS.md",
    "config/self_heal_fixer.json",
    "scripts/lib/self_heal_fixer.py",
    "scripts/check_line_endings.py",
)


def _cfg() -> dict:
    return json.loads((ROOT / "config" / "self_heal_fixer.json").read_text(encoding="utf-8"))


def test_every_llm_policy_and_enforcement_file_is_refused_by_the_real_matcher():
    from lib import self_heal_fixer as F

    cfg = _cfg()
    patterns = cfg["diff_guard"]["refuse_paths"]
    for rel in REFUSED:
        hit = F._match_any(rel, patterns)
        assert hit is not None, f"{rel} is open to the fixer"
        why = F.lane_refusal("any-lane", rel, cfg)
        assert why and why.startswith("lane_refused:protected_script:"), (rel, why)


def test_the_guard_did_not_lose_the_rails_it_already_had():
    from lib import self_heal_fixer as F

    patterns = _cfg()["diff_guard"]["refuse_paths"]
    for rel in STILL_REFUSED:
        assert F._match_any(rel, patterns) is not None, rel


def test_the_guard_is_not_refusing_everything():
    """A negative control: an ordinary report script the fixer may still change stays open."""
    from lib import self_heal_fixer as F

    patterns = _cfg()["diff_guard"]["refuse_paths"]
    assert F._match_any("scripts/generate_weekly_docx.py", patterns) is None
