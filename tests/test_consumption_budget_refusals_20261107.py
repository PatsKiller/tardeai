"""CONSUMPTION_BUDGET_REFUSALS_20261107 (LQ-20261107-241): cap refusals are not provider failures."""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import llm_consumption as lc  # noqa: E402


@pytest.mark.parametrize("msg", [
    "ANTHROPIC_CREDIT_PROCESS_CAP: process cap reached",
    "ANTHROPIC_CREDIT_PER_CALL_CAP",
    "ANTHROPIC_CREDIT_PAUSED_TODAY",
    "COST_CAP_EXCEEDED: {'allow': False}",
])
def test_cap_refusals_are_budget_refusals(msg):
    assert lc.failure_class(False, msg) == "budget_refusal"


@pytest.mark.parametrize("msg", [
    "429 Client Error: Too Many Requests", "HTTP_402: policy=FAST", "ANTHROPIC_OUTPUT_INVALID",
    "ANTHROPIC_INPUT_LIMIT_EXCEEDED", "Read timed out", "", None,
])
def test_everything_else_is_a_provider_failure(msg):
    assert lc.failure_class(False, msg) == "provider_failure"


def test_success_has_no_class():
    assert lc.failure_class(True, None) is None
    assert lc.failure_class(True, "ANTHROPIC_CREDIT_PROCESS_CAP") is None


def test_sql_and_python_patterns_are_one_pattern():
    # The SQL predicate in overview() interpolates BUDGET_REFUSAL_RE, so SQL and row labels cannot drift apart.
    src = Path(lc.__file__).read_text()
    assert src.count("!~ '{BUDGET_REFUSAL_RE}'") == 1 and src.count("~ '{BUDGET_REFUSAL_RE}') AS budget_refusals") == 1
    assert "'" not in lc.BUDGET_REFUSAL_RE and "%" not in lc.BUDGET_REFUSAL_RE
    assert re.match(lc.BUDGET_REFUSAL_RE, "COST_CAP_EXCEEDED")
