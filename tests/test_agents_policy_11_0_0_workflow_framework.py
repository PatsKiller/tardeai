"""AGENTS.md 11.0.0 (ACTIVE since 2026-10-15, MAJOR) — §23.24 mandatory n8n workflow framework.

Operator 2026-10-14: n8n is the primary orchestration and automation layer, with "a mandatory standard framework for
every n8n workflow, contract, integration and automation" covering monitoring, alerting, logging, recovery, security
and AI/LLM governance. Pins, all hermetic (source text only; nothing imports or runs a lane, a workflow or n8n):

* the policy record: the header stays 10.0.0 ACTIVE until a ratifying edit (or, once it says 11.0.0, agrees with the
  row); one 11.0.0 version row awaiting APPROVE_AGENTS_POLICY_11_0_0; the banner; the state checker passes;
* §23.24: scope and class, every element the operator named in each of the six areas, each with a check marked
  existing (E) or proposed (P), the activation bar, and the pointers to the documents;
* §0, §2, §2A, §7A, §17, §22, §23.14 and §23.23 are byte-identical; the tool adapters carry nothing from 11.0.0;
* the documents §23.24 points at exist, and the gap assessment carries the 18-workflow compliance matrix
  (16 legacy + the 2 fabric workflows served in 5aa61048d, re-scored 2026-10-15).
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
from tests import test_agents_policy_10_0_0_n8n_fabric as T10  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TOKEN = "APPROVE_AGENTS_POLICY_11_0_0"
DIRECTIVE = "a mandatory standard framework for every n8n workflow, contract, integration and automation"
#: §23.23 (heading up to the next "## ", rstripped), measured on origin/main 57d8fc3ff before this amendment
#: (after the 10.0.0 ratifying edit, #1740, which changed §23.23's status lines; the a1b1c5c93 value was 12d4df6d…).
SECTION_23_23_SHA256 = "f5770e9bc578b1e96b1380f380b5b64821b9ee8965b7468b03d7e7347e469d4d"
DOCS = (
    "docs/implementation/n8n-maturity/N8N_CONFIGURATION.md",
    "docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md",
    "docs/implementation/n8n-maturity/N8N_MONITORING_AND_REMEDIATION_STANDARD.md",
    "docs/ALERT_INCIDENT_RESOLUTION.md",
    "docs/architecture/GOVERNED_MODEL_BRIDGE.md",
    "docs/runbooks/INCIDENT_RESPONSE.md",
    "docs/RESTORE_GUIDE.md",
    "docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md",
    "docs/implementation/n8n-maturity/N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md",
)
ACTIVE_WORKFLOWS = (
    "tradeai-dispatcher", "tradeai-event-router", "tradeai-digest-scheduler", "tradeai-heartbeat-watcher",
    "tradeai-incident-router", "tradeai-momentum-lifecycle-candidate", "n8n-incident-fanin", "n8n-pilot-dispatch",
    "n8n-research-intake-consumer", "crontab-snapshot-for-health-agent", "catalyst-calibration-monitor-shadow",
    "watch-directives-monitor-shadow", "source-attribution-monitor-shadow", "finviz-view-contracts-shadow",
    "generate-analyst-daily-digest-shadow", "lane-governance-packet-weekly-shadow",
    "tradeai-fabric-run-lane", "tradeai-fabric-error",
)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _row() -> re.Match:
    m = re.search(r"^\| 11\.0\.0 \| 2026-10-14 \| (PROPOSED|ACTIVE)[^|]* \| (MAJOR|MINOR) \|(.*)$", AGENTS, re.M)
    assert m, "no `| 11.0.0 | 2026-10-14 | PROPOSED|ACTIVE | MAJOR |` row"
    return m


def _s() -> str:
    return _flat(T10._sub23("23.24"))


# ------------------------------------------------------------------------------------------------ the record


def test_header_stays_until_ratification_and_row_waits_for_the_operator():
    status, _cls, rest = _row().groups()
    if _control("Policy-Version") == "11.0.0":
        assert _control("Status") == status
    else:
        assert _control("Status") == "ACTIVE" or (
            # 16.0.0 (2026-10-21) sets the header block to its PROPOSED version while the row waits for the token.
            tuple(int(x) for x in _control("Policy-Version").split(".")) >= (16, 0, 0)
            and _control("Status") == "PROPOSED" and _control("Effective-Date") == "PENDING"
        )
    if status == "PROPOSED":
        assert "PENDING" in rest and f"{TOKEN} <pr_number> <head_sha>" in rest
        assert not re.search(r"\brides?\b", rest, re.I)
    for frag in (DIRECTIVE, "§23.24", "tests/test_agents_policy_11_0_0_workflow_framework.py",
                 "§0, §2, §2A, §7A, §17, §22, §23.14 and §23.23 byte-identical", "Grants nothing",
                 "scripts/check_n8n_workflow_framework.py", "10.1.0"):
        assert frag in rest, frag


def test_one_row_per_version_and_state_checker_passes():
    assert len(re.findall(r"^\| 11\.0\.0 \|", AGENTS, re.M)) == 1
    assert STATE.check(AGENTS, on_main=False) == []
    assert STATE.check(AGENTS, on_main=True) == []


def test_banner_quotes_the_operator_and_states_the_class():
    start = AGENTS.index("**11.0.0 is ")
    end = AGENTS.index("\n\n**", start + 10)
    banner = _flat(AGENTS[start:end])
    # 2026-10-15 ratifying edit: ACTIVE, the operator's verbatim token, the header set to 11.0.0.
    for frag in ("ACTIVE (MAJOR)", DIRECTIVE, "Why MAJOR", "It grants nothing", "byte-identical",
                 "set the header block to 11.0.0 ACTIVE", f"{TOKEN} 1747 89fb642cd",
                 "PatsKiller 2026-10-15T11:51:39Z", "renumbers to 10.1.0"):
        assert frag in banner, frag


# ------------------------------------------------------------------------------------------------- §23.24


def test_23_24_is_active_and_scoped():
    s = _s()
    assert s.startswith("## 23.24 Mandatory n8n workflow framework (11.0.0, ACTIVE)")
    assert "PROPOSED: nothing here binds" not in s
    for frag in (DIRECTIVE, "**ACTIVE since 2026-10-15**", f"{TOKEN} 1747 89fb642cd",
                 "**Scope and class.**", "**business-critical**", "**resilience**", "**AI/LLM**",
                 "**monitoring/compliance**", "(E)", "(P)", "It adds obligations and grants nothing"):
        assert frag in s, frag


def test_23_24_names_every_element_the_operator_listed():
    s = _s()
    areas = {
        "**Monitoring.**": ("Success", "Failure", "Performance", "Capacity", "Dependency"),
        "**Alerting.**": ("Failure reaches", "SLA breach", "Performance degradation", "Integration failure",
                          "AI/LLM exception", "runbook_id"),
        "**Logging.**": ("Execution", "Error", "Audit", "Security", "Change"),
        "**Recovery.**": ("Retry has one owner", "Circuit breaker", "Fallback", "Dead-letter", "Manual recovery",
                          "Idempotency"),
        "**Security.**": ("AuthN", "AuthZ", "Secrets", "Data protection", "Audit trail"),
        "**AI/LLM governance**": ("Prompt management", "Model selection and fallback", "Cost and tokens",
                                  "Response validation", "Hallucination controls", "Output guardrails",
                                  "HITL escalation"),
    }
    for area, elements in areas.items():
        assert area in s, area
        start = s.index(area)
        nxt = min([s.index(a, start + 1) for a in list(areas) + ["**Activation bar.**"] if a in s[start + 1:]]
                  or [len(s)])
        block = s[start:nxt]
        for el in elements:
            assert el in block, (area, el)


def test_23_24_checks_name_real_artifacts():
    s = _s()
    for rel in ("config/n8n_health_contracts.json", "scripts/check_n8n_health_contracts.py",
                "config/n8n_retry_policies.json", "scripts/n8n_incident_fanin.py", "scripts/check_n8n_workflow_drift.py",
                "scripts/lib/n8n_due.py", "docs/ops/ROLLBACK_COMMANDS.md", "scripts/n8n_dlq.py",
                "scripts/check_n8n_activation_grants.py", "config/n8n_prompt_templates.json",
                "config/llm_process_registry.json", "config/llm_routing_policy.json",
                "config/schemas/n8n_model_job_outputs.json"):
        assert rel in s, rel
        assert (ROOT / rel).exists(), rel
    # The framework check is proposed, and says so.
    assert "`scripts/check_n8n_workflow_framework.py` (P)" in s


def test_23_24_activation_bar_and_independence():
    s = _s()
    for frag in ("**Activation bar.**", "no workflow is activated, re-activated or promoted a stage unless every "
                 "element above passes", "remediated or archived (never deleted, §0 rail 6) within 30 days",
                 "P0/P1 never depends on n8n", "comms gateway"):
        assert frag in s, frag


def test_23_24_points_at_documents_that_exist():
    s = _s()
    for rel in DOCS:
        assert rel in s, rel
        assert (ROOT / rel).exists(), rel


# ------------------------------------------------------------------------------------------- byte-identical


def test_rails_17_22_23_14_and_23_23_are_byte_identical():
    T10.test_rails_17_and_22_are_byte_identical()
    T10.test_23_14_is_byte_identical()
    block = T10._sub23("23.23").rstrip()
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == SECTION_23_23_SHA256, "§23.23 changed"
    assert "11.0.0" not in T10._sub23("23.14")


def test_adapters_carry_nothing_from_11_0_0():
    for rel in T10.ADAPTERS:
        p = ROOT / rel
        if p.exists():
            text = p.read_text(encoding="utf-8")
            assert "11.0.0" not in text and "§23.24" not in text, rel


# ----------------------------------------------------------------------------------------------- the docs


def test_gap_assessment_carries_the_compliance_matrix():
    text = (ROOT / DOCS[-1]).read_text(encoding="utf-8")
    assert re.search(r"^Status:\s+ACTIVE", text, re.M) and re.search(r"^Measured at:", text, re.M)
    matrix = text[text.index("## 4. Per-workflow framework compliance matrix"):text.index("## 5. Gaps by domain")]
    for wf in ACTIVE_WORKFLOWS:
        assert f"| {wf} |" in matrix, wf
    for area in ("Monitoring", "Alerting", "Logging", "Recovery", "Security", "AI/LLM gov."):
        assert area in matrix, area
    for label in ("LIVE", "MERGED-NOT-SERVED", "PR-OPEN", "BRANCH-ONLY", "PLANNED", "POLICY-ONLY"):
        assert f"**{label}**" in text, label
