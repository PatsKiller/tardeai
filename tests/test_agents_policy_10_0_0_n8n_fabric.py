"""AGENTS.md 10.0.0 (PROPOSED, MAJOR) — §23.23 n8n is the automation fabric: n8n owns flow, the host owns authority.

Operator 2026-10-14, verbatim: n8n is "a centralized, intelligent automation fabric that provides: Workflow
orchestration, Dependency management, Observability, Alerting, Human approvals, Agent coordination, LLM integration,
Event-driven automation, Operational visibility, Auditability, Governance, Centralized controls." and "Do not tell me
whether cron is a better scheduler. Tell me whether we are building the right platform." Pins, all hermetic (source
text only; nothing imports or runs a lane, a workflow or n8n):

* the policy record: the header stays 7.0.0 ACTIVE until the ratifying edit (or, once it says 10.0.0, agrees with the
  row); one 10.0.0 version row awaiting APPROVE_AGENTS_POLICY_10_0_0 that quotes the operator; the banner; the state
  checker passes on a branch and on main;
* §23.23: flow vs authority, broker, LLM steps, agents, workflow governance, node enablement, independence, the
  migration freeze and the money preconditions, each by its text markers;
* the superseded sections: §23.1, §23.11 and §24.1 keep every original sentence (never delete) and carry an explicit
  "Superseded by §23.23 once ACTIVE" note; §23.3 keeps its trigger path and gains one route note;
* §0, §2, §2A, §7A, §17, §22 and §23.14 are byte-identical (§23.14 read through the 8.0.0 one-clause reversal when that
  amendment is present); the tool adapters carry nothing from 10.0.0.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_agents_policy_state as STATE  # noqa: E402
from tests import test_agents_policy_5_2_0_validation as P520  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
# AGENTS.md 20.0.0 (§28.7): once 20.0.0 is ACTIVE its eight clause edits are undone before the pins below are
# checked (and before any 19.0.0 undo); tests/test_agents_policy_20_0_0_agent_operations.py pins those edits and
# the post-ratification digests. While 20.0.0 is PROPOSED the text is unchanged.
from tests.test_agents_policy_20_0_0_agent_operations import pre_20_0_0  # noqa: E402

AGENTS = pre_20_0_0(AGENTS)
# AGENTS.md 19.0.0 (§27.5): once 19.0.0 is ACTIVE its four clause edits in §17, §23.14 and §25.4 are undone before
# the pins below are checked; tests/test_agents_policy_19_0_0_broker_read_controls.py pins those edits and the
# post-ratification digests. While 19.0.0 is PROPOSED the text is unchanged.
from tests.test_agents_policy_19_0_0_broker_read_controls import pre_19_0_0  # noqa: E402

AGENTS = pre_19_0_0(AGENTS)
TOKEN = "APPROVE_AGENTS_POLICY_10_0_0"
DIRECTIVE = (
    'n8n is "a centralized, intelligent automation fabric that provides: Workflow orchestration, Dependency '
    "management, Observability, Alerting, Human approvals, Agent coordination, LLM integration, Event-driven "
    'automation, Operational visibility, Auditability, Governance, Centralized controls."'
)
PLATFORM = "Do not tell me whether cron is a better scheduler. Tell me whether we are building the right platform."
#: §22 ("# 22 · " up to "# 23 · "), measured on origin/main 07cf2e027 before this amendment.
SECTION_22_SHA256 = "81f1646a64e38047882c7375ab18739111ba8349471fbaa0351fc1069f9717e9"
SUPERSEDED_NOTE = "Superseded by §23.23 (10.0.0, ACTIVE)"
ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _row() -> re.Match:
    m = re.search(r"^\| 10\.0\.0 \| 2026-10-14 \| (PROPOSED|ACTIVE)[^|]* \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no `| 10.0.0 | 2026-10-14 | PROPOSED|ACTIVE | MAJOR |` row"
    return m


def _sub23(num: str) -> str:
    sec = re.search(r"^# 23 · .*?(?=^# 24 · |^# Version history)", AGENTS, re.M | re.S)
    assert sec
    m = re.search(rf"^## {re.escape(num)} .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    assert m, num
    return m.group(0)


def _sub24(num: str) -> str:
    sec = re.search(r"^# 24 · .*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert sec
    m = re.search(rf"^## {re.escape(num)} .*?(?=^## |^---$|^# |\Z)", sec.group(0), re.M | re.S)
    assert m, num
    return m.group(0)


# ------------------------------------------------------------------------------------------------ the record


def test_header_stays_until_ratification_and_row_waits_for_the_operator():
    status, rest = _row().groups()
    if _control("Policy-Version") == "10.0.0":
        assert _control("Status") == status
        if status == "PROPOSED":
            assert _control("Effective-Date") == "PENDING"
    else:
        # Until the ratifying edit the header is the last ACTIVE version (7.0.0 when this was written), or a later
        # version's PROPOSED header block (16.0.0 onward).
        assert _control("Status") == "ACTIVE" or (
            # 16.0.0 (2026-10-21) sets the header block to its PROPOSED version while the row waits for the token.
            tuple(int(x) for x in _control("Policy-Version").split(".")) >= (16, 0, 0)
            and _control("Status") == "PROPOSED" and _control("Effective-Date") == "PENDING"
        )
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I)
    for frag in (DIRECTIVE, PLATFORM, "§23.23", "tests/test_agents_policy_10_0_0_n8n_fabric.py",
                 "§0, §2, §2A, §7A, §17, §22 and §23.14 byte-identical", "FROZEN", "Run Lane sub-workflow",
                 "§23.1", "§23.11", "§24.1"):
        assert frag in rest, frag


def test_state_checker_passes_on_branch_and_on_main():
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_banner_quotes_the_operator_and_states_the_class():
    start = AGENTS.index("**10.0.0 is ")
    end = AGENTS.index("\n\n**", start + 10)
    banner = _flat(AGENTS[start:end])
    for frag in ("ACTIVE (MAJOR)", DIRECTIVE, PLATFORM, "Why MAJOR", "n8n owns flow",
                 "The host keeps authority, execution and evidence", "an n8n approval is a request",
                 "byte-identical", "Ratification activates no node, workflow, route or credential", "#1697", "#1727",
                 "n8nmat/schwab-read-lanes-20261014", "set the header block to 10.0.0 ACTIVE",
                 f"{TOKEN} 1736 7f275d279", "PatsKiller 2026-10-14T23:25:56Z", "`3e9dc5e14`"):
        assert frag in banner, frag


# ------------------------------------------------------------------------------------------------- §23.23


def test_23_23_is_active_and_names_what_it_supersedes():
    s = _flat(_sub23("23.23"))
    assert s.startswith("## 23.23 n8n is the automation fabric — n8n owns flow, the host owns authority (10.0.0, ACTIVE)")
    for frag in (DIRECTIVE, PLATFORM, "**ACTIVE:**", f"{TOKEN} 1736 7f275d279", "PatsKiller 2026-10-14T23:25:56Z",
                 "supersedes the restrictive parts of §23.1", "§23.11", "§24.1", "not deleted (§0 rail 6)",
                 "WS9_THREAT_MODEL.md", "WS1b_N8N_TARGET_ARCHITECTURE.md", "DECISIONS_FOR_OPERATOR.md"):
        assert frag in s, frag


def test_23_23_flow_and_authority():
    s = _flat(_sub23("23.23"))
    for frag in (
        "**n8n owns FLOW.**", "Sequencing and dependencies", "event triggers",
        "retries, backoff and dead-letter decisions, made through one Run Lane sub-workflow", "error workflows",
        "approval TIMELINES (Wait nodes", "escalation timers", "invoking LLM judgment steps",
        "**The host owns AUTHORITY, EXECUTION and EVIDENCE.**", "The allowlist", "live/dry authority",
        "idempotency keys", "every secret", "the ledger as the audit of record", "the comms chokepoint for every send",
        "n8n requests a send through a host intent API", "**n8n never holds a bot token**",
    ):
        assert frag in s, frag


def test_23_23_broker_and_llm_and_agents():
    s = _flat(_sub23("23.23"))
    for frag in (
        "**n8n never holds broker credentials** and never calls a broker route or an order route",
        "Broker reads go only through the broker gateway (§23.22)",
        "Broker writes go only through the execution service, behind the trading lock, with a per-order operator "
        "hardware-key or TOTP assertion over the intent hash",
        "**An n8n approval is a REQUEST; authority is the host record**",
        "Only through the governed bridge (§23.4)", "A closed output schema; n8n branches on enumerated fields only",
        "The host re-checks the recommended action", "A bounded tool list, read-only tools by default",
        "Prompt, response and decision are audited in one row joined by `run_id` ↔ `execution_id`",
        "LLM output never selects an unlisted action", "Ingested text (news, social, transcripts, PR bodies) is data",
        "**Agents are judgment functions invoked by workflows.**",
        "No agent holds a side-effecting tool without an approval gate in front of it",
        "Long-running agent loops are retired into event-triggered workflows over time",
        "Invoking an agent is a workflow step — a bridge call, not a dispatcher lane — so §23.14 does not bar it",
        "§23.8–§23.10 still bind every n8n Agent node",
    ):
        assert frag in s, frag


def test_23_23_governance_nodes_independence():
    s = _flat(_sub23("23.23"))
    for frag in (
        "**they are never edited in the n8n UI.**", "Workflows are generated from git",
        "Any git-vs-live drift pages **P1**", "Successful executions are saved, with `run_id`",
        "Every workflow has an error workflow", "Policy refusals (`RUN_REFUSED`, already `RUNNING`) are recorded as data, "
        "not as n8n errors", "Community nodes stay off", "The n8n DB role is not superuser",
        "The `NODES_EXCLUDE` / `N8N_DISABLED_MODULES` relaxation is allowed only for the nodes the target needs",
        "Execute Workflow and sub-workflows", "Wait;", "Form or webhook-resume for approvals", "Switch, Merge and If",
        "Error Trigger", "the AI Agent node restricted to the bridge-backed credential",
        "**Each enablement is a separate reviewed PR**", "Messaging nodes with their own credentials",
        "stay excluded", "The P0/P1 dead-man and P0/P1 pages never depend on n8n",
    ):
        assert frag in s, frag


def test_23_23_migration_freeze_and_money_preconditions():
    s = _flat(_sub23("23.23"))
    for frag in (
        "**Timer-only leaf-lane cutovers are FROZEN** until three things exist: the Run Lane sub-workflow, the async "
        "run-outcome callback", "and this amendment ACTIVE",
        "progress is measured as business processes owned by n8n and orchestration owners retired, not lanes moved",
        "Consolidate before migrating", "WS2_family_decisions.csv", "§23.21 cutover standard",
        "a fenced single-owner switch",
        "**Preconditions before any money-touching flow.**", "Command Center auth", "the read-only trading lock merged "
        "and served", "uid separation for execution", "the DB role split", "signed guard grants",
        "the signed unlock of the trading lock",
        "C1", "C2", "C3", "C10",
        "§0, §2, §2A, §7A, §17 and §22 are byte-identical", "§23.14 is byte-identical",
    ):
        assert frag in s, frag


# ------------------------------------------------------------------------------- superseded, never deleted


def test_23_1_keeps_its_text_and_is_marked_superseded():
    s = _flat(_sub23("23.1"))
    assert "**n8n is a scheduler and a requester, never an authority.**" in s
    assert "Evidence is the `RunReceipt@v1` and the lane's `output_signal`, both written on the host." in s
    assert s.count(SUPERSEDED_NOTE) == 1
    assert '"Never an authority" and every evidence sentence above stay in force' in s


def test_23_11_keeps_its_text_and_is_marked_superseded():
    s = _flat(_sub23("23.11"))
    for frag in ("**Six generic workflows, activated once.**", "**The other five send nothing and decide nothing.**",
                 "**The approval router never mints, approves or extends a grant.**"):
        assert frag in s, frag
    assert s.count(SUPERSEDED_NOTE) == 1
    assert '"Send nothing" stays: a send is a request to the host intent route' in s


def test_24_1_keeps_its_text_and_is_marked_superseded():
    s = _flat(_sub24("24.1"))
    for frag in ('**"n8n orchestrates" means it fires host lanes and decides nothing.**',
                 "**The host communications gateway is the only sender.**",
                 "**The P1 path does not depend on n8n.**"):
        assert frag in s, frag
    assert s.count(SUPERSEDED_NOTE) == 1
    assert "never holds a bot token" in s


def test_23_3_keeps_the_trigger_path_and_gains_one_route_note():
    s = _flat(_sub23("23.3"))
    assert "No other port, route, socket, SSH, `docker exec`, file drop or webhook is a trigger path." in s
    assert "**No sends from n8n.**" in s
    assert s.count("**Route note for §23.23 (10.0.0, ACTIVE).**") == 1
    for frag in ("a send-intent route", "an approval-request route", "the async run-outcome callback",
                 "None of them runs a command, and none is a broker or order route"):
        assert frag in s, frag
    # The note is not a §23.3 lane exception (tests/test_agents_policy_4_0_0_scalp_lane.py counts those).
    assert "**Exception (10.0.0" not in s


# ------------------------------------------------------------------------------------------- byte-identical


def test_rails_17_and_22_are_byte_identical():
    for name, (start, end, digest) in P520.PINNED_SECTIONS.items():
        block = P520._section(AGENTS, start, end)
        assert hashlib.sha256(block.encode("utf-8")).hexdigest() == digest, f"{name} changed"
    s = re.search(r"^# 22 · ", AGENTS, re.M).start()
    e = re.search(r"^# 23 · ", AGENTS, re.M).start()
    assert hashlib.sha256(AGENTS[s:e].encode("utf-8")).hexdigest() == SECTION_22_SHA256, "§22 changed"


def test_23_14_is_byte_identical():
    block = _sub23("23.14").rstrip("\n").rstrip("-").rstrip("\n")
    # 8.0.0 (PR #1727) changes §23.14 by exactly one clause and publishes the pair on the 5.2.0 test; reverse it if
    # present, so this pin holds whichever of 8.0.0 and 10.0.0 merges first.
    new, old = getattr(P520, "CLAUSE_23_14_8_0_0", None), getattr(P520, "CLAUSE_23_14_PRE_8_0_0", None)
    if new and old and new in block:
        block = block.replace(new, old)
    # 16.0.0 (ratified 2026-10-21, #1911) replaced one §23.14 clause; reversed the same way (pinned in 16.0.0's test).
    block = block.replace(P520.CLAUSE_23_14_16_0_0, P520.CLAUSE_23_14_PRE_16_0_0)
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == P520.SECTION_23_14_SHA256
    assert "10.0.0" not in block and "§23.23" not in block


def test_adapters_carry_nothing_from_10_0_0():
    for rel in ADAPTERS:
        p = ROOT / rel
        if p.exists():
            text = p.read_text(encoding="utf-8")
            assert "10.0.0" not in text and "§23.23" not in text, rel
