"""The path classes the canonical merge evaluator refuses without an operator decision.

ONE source for three callers that must agree:

* ``pr_merge_delegation`` raises these codes (``Refused``) when it evaluates a merge request;
* ``agent_dispatch``'s Ready-to-merge projection reports the same refusal as the one step a PR needs;
* reviewers and operators read the same names.

Why this module exists (2026-11-06): the projection said Ready=1 for ``config/portfolio_positions.yaml`` and
``scripts/schwab_synthetic.py`` while the evaluator refuses both on the path alone — a merge-ready light that said
yes about a path the gate would refuse. Restating the lists in a second place would let them drift again, so they
live here and both callers import them.

Nothing here reads a store, a broker or a file: pure constants and one pure predicate.
"""
from __future__ import annotations

import fnmatch

# Ratification and the delegation verifier/classification controls stay operator-owned.
# Other hook, CI and merge/deploy engineering uses the held two-review path.
DELEGATION_CONTROL_PATHS = (
    # This module IS the gate's definition now. It must refuse itself, or one ordinary one-review PR could edit the
    # lists that decide refusals — weakening the merge gate and the Ready-to-merge projection in the same keystroke
    # while keeping the two in agreement (cc-deepseek-6 F1 on #2650, 2026-11-06).
    "scripts/lib/merge_path_classes.py",
    "scripts/lib/pr_merge_delegation.py",
    "scripts/lib/pr_all_checks_green.py",
    "scripts/lib/merge_hold_paths.py",
    "config/merge_hold_paths.json",
    ".cursor/hooks/guard_standing_policy.py",
    "tests/test_pr_merge_delegation_20261102.py",
    "tests/test_pr_all_checks_standing_20261102.py",
    "tests/test_guard_standing_policy_20261102.py",
)
RESERVED = (
    "AGENTS.md", "*/AGENTS.md", "AI_WORK_POLICY.md", "CLAUDE.md", "GEMINI.md", ".goosehints",
    ".cursor/rules/*", ".github/copilot-instructions.md", "config/agent_standing_authority.json",
) + DELEGATION_CONTROL_PATHS
OPERATOR_ONLY = (
    "scripts/brokers/*", "scripts/active_trader/*", "scripts/moomoo/*", "scripts/schwab_*",
    "scripts/lib/schwab_*", "scripts/broker_*", "scripts/lib/broker*", "scripts/*order_intent*",
    "scripts/lib/*order_intent*", "scripts/*execution_guard*", "scripts/lib/*execution_guard*",
    "scripts/alpaca_*stop*", "scripts/defense_execution.py", "apps/broker-admin/*",
    "config/active_trader*", "config/secret_registry.yaml", ".env", ".env.*", "*/.env", "*/.env.*",
    "config/*branch*protection*", ".github/settings*", "scripts/*branch*protection*",
    "scripts/lib/*branch*protection*",
    "scripts/lib/trading_lock.py", "scripts/lib/trading_session_grant.py",
    "scripts/validate_schwab_write_policy.py", "scripts/lib/cio_instrument_record.py",
)
DECISION_PATHS = (
    "config/lane_registry.json", "config/data_source_authority.json", "config/n8n_relay_live*.json",
    "config/n8n_live*.json", "config/*access_mode*", "config/*kill_switch*", "config/*risk_policy*",
    "config/operator_alert_policy.yaml", "config/portfolio_positions.yaml",
    "config/search_routing_policy.json", "config/conflict_rulebook.json", "config/systemd/*",
    "config/disk_hygiene_rules.json", "config/anthropic_credit_policy.json",
)

OPERATOR_ONLY_REFUSAL = "operator_only_or_delegation_definition_path"
DECISION_REFUSAL = "applicable_section17_decision_required"


def hits(path: str, patterns) -> bool:
    """fnmatch over a pattern list, case-sensitively — the evaluator's own matcher."""
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def path_refusal(paths, *, operator_only_extra=()) -> str | None:
    """None, or the canonical evaluator's refusal code for these paths.

    ``operator_only_extra`` carries the deployment's own exclusion globs (the evaluator's snapshot), which are
    operator-only for the same reason. The operator-only class is checked first, as the evaluator does.
    """
    files = [str(p) for p in paths]
    operator_only = (*RESERVED, *OPERATOR_ONLY, *tuple(operator_only_extra))
    if any(hits(p, operator_only) for p in files):
        return OPERATOR_ONLY_REFUSAL
    if any(hits(p, DECISION_PATHS) for p in files):
        return DECISION_REFUSAL
    return None
