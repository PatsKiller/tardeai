"""AGENTS.md 1.3.0 (PROPOSED) — the amendment must not act before it is ratified.

The failure this guards against: an authority-widening draft merged into AGENTS.md reads, to an
agent, exactly like a rule. So while 1.3.0 is PROPOSED the ACTIVE §0/§1/§2B wording must be
intact, the new text must be labelled NOT IN FORCE, and the promises the amendment makes
(no LLM live authority, Stage 14's separate start, push precedence) must be present.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
AMEND = (ROOT / "docs/governance/agent-standards/AUTHORITY_AMENDMENT_1_3_0.md").read_text(encoding="utf-8")
GRANT_DOC = (ROOT / "docs/governance/agent-standards/TRADING_SESSION_GRANT_CONTRACT.md").read_text(encoding="utf-8")
PROMPTS = ROOT / "docs/prompts"


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _section(title_prefix: str) -> str:
    m = re.search(rf"^# {re.escape(title_prefix)}.*?(?=^# )", AGENTS, re.M | re.S)
    assert m, title_prefix
    return m.group(0)


def test_1_3_0_is_proposed_and_undated():
    if _control("Policy-Version") == "1.3.0":
        assert _control("Status") == "PROPOSED"
        assert _control("Effective-Date") == "PENDING"


def test_active_broker_prohibition_is_untouched_while_proposed():
    """Negative authority test: the unratified draft must not have rewritten §0 rule 2."""
    if _control("Status") != "PROPOSED":
        return
    sec0 = _section("0 · If you read nothing else")
    assert "**The broker execution subsystem is out of scope.**" in sec0
    assert "never sizes, orders, stops, weights, or writes to a broker" in sec0
    assert "defined but not granted" in AGENTS
    assert "anything in the broker subsystem, credentials, or 2FA" in _section("17 · Operator-only")


def test_section_22_is_labelled_not_in_force():
    s22 = _section("22 · Proposed authority amendment 1.3.0")
    assert "NOT IN FORCE" in s22 and "Status: PROPOSED" in s22


def test_no_llm_ever_holds_live_or_order_authority():
    for text in (AGENTS, AMEND):
        assert "No LLM agent ever holds A4 or A5" in text


def test_five_authorities_are_distinct():
    for name in ("A1 Coding", "A2 Simulation", "A3 Deployment", "A4 Live activation", "A5 Broker order authority"):
        assert name in AMEND, name


def test_stage_14_keeps_its_separate_operator_start():
    for needle in ("exact reviewed SHA", "operator presence", "OPERATOR_DECISION_REQUIRED"):
        assert needle in AMEND, needle
    assert "Stage 14 keeps its own start" in AGENTS


def test_policy_approval_is_not_a_live_grant():
    assert "is not a live-session grant" in AMEND


def test_push_budget_outranks_the_implementation_program():
    v12 = (PROMPTS / "CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_2.md").read_text(encoding="utf-8")
    assert "8. branch pushed;" not in v12
    assert "GitHub push test" not in v12
    assert "one push per tranche" in v12
    v11 = (PROMPTS / "CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md").read_text(encoding="utf-8")
    assert v11.lstrip().startswith("> **SUPERSEDED by v1.2**")


def test_grant_contract_invents_no_risk_limit():
    """Every limit is an operator decision; the contract states no number for any of them."""
    table = GRANT_DOC.split("## 4. Values the operator must decide", 1)[1].split("## 5.", 1)[0]
    for limit in ("max_daily_loss", "max_risk_per_trade", "max_notional_per_trade"):
        assert limit in table
    assert not re.search(r"\$\s?\d", table), "a dollar figure appeared in the operator-decision table"


def test_codeowners_covers_the_authority_and_broker_paths():
    owners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    for path in (
        "/AGENTS.md",
        "/AI_WORK_POLICY.md",
        "/scripts/brokers/",
        "/scripts/lib/trading_session_grant.py",
        "/scripts/lib/cio_instrument_record.py",
    ):
        assert path in owners, path
