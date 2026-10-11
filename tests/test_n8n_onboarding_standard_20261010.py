"""The n8n baseline documentation is the procedure, and it stays true to the code (2026-10-10).

Operator 2026-10-10 ~16:35 ET: "Make sure you totally update the documentation on this and the agents.md ... So when
new stuff is added to N8N, it follows the procedures." Then ~16:40 (monitoring / SIEM / LLM remediation per lane) and
~16:50 ("a separate document just for n8n configuration").

Pins: the three documents exist with a §14 header; each carries the rules the 2026-10-10 incidents produced; the
numbers they quote equal the code and config that implement them; the stale statements they replaced stay gone; the
configuration document names variables, never values. Static reads only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DOCS = ROOT / "docs" / "implementation" / "n8n-maturity"
ONBOARD = DOCS / "N8N_ONBOARDING_STANDARD.md"
MONITOR = DOCS / "N8N_MONITORING_AND_REMEDIATION_STANDARD.md"
CONFIG = DOCS / "N8N_CONFIGURATION.md"


def _flat(p: Path) -> str:
    return re.sub(r"\s+", " ", p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("doc", [ONBOARD, MONITOR, CONFIG])
def test_document_exists_with_a_header(doc):
    text = doc.read_text(encoding="utf-8")
    assert re.search(r"^Status:\s+ACTIVE", text, re.M), doc.name
    assert re.search(r"^as_of:\s+2026-10-1\d", text, re.M), doc.name
    assert re.search(r"^Measured at:", text, re.M), doc.name


def test_configuration_is_the_entry_point_and_links_the_standards():
    f = _flat(CONFIG)
    for target in (
        "N8N_ONBOARDING_STANDARD.md",
        "N8N_MONITORING_AND_REMEDIATION_STANDARD.md",
        "02-six-workflow-architecture.md",
        "cron-inventory/README.md",
        "config/n8n_health_contracts.json",
    ):
        assert target in f, target
    assert "N8N_CONFIGURATION.md" in _flat(ONBOARD) and "N8N_CONFIGURATION.md" in _flat(MONITOR)
    assert "N8N_MONITORING_AND_REMEDIATION_STANDARD.md" in _flat(ONBOARD)
    master = _flat(DOCS / "00-MASTER-PROGRAM.md")
    assert all(
        n in master
        for n in ("N8N_CONFIGURATION.md", "N8N_ONBOARDING_STANDARD.md", "N8N_MONITORING_AND_REMEDIATION_STANDARD.md")
    )


@pytest.mark.parametrize(
    "rule",
    [
        "`dispatcher`, never `tradeai-dispatcher`",
        "check_n8n_relay_contract.py",
        '"deletedAt" IS NULL',
        "TRADE_AI_CI=1",
        "LaneRunReceipt@v1",
        "adopted_from_generator",
        "retry_policy",
        "saveManualExecutions: false",
        "errorWorkflow = tradeai-incident-router",
        "One registry PR at a time",
        "write the workflow health contract",
        "--defer-in-process",
        "never delete",
        "re-send it",
    ],
)
def test_onboarding_standard_carries_the_rule(rule):
    assert rule.lower() in _flat(ONBOARD).lower(), rule


def test_onboarding_lessons_table_links_every_root_cause():
    f = _flat(ONBOARD)
    for i in range(1, 11):
        assert f"| RC{i} |" in f, f"RC{i}"


@pytest.mark.parametrize(
    "item",
    [
        "N8nHealthContract@v1",
        "LEARNED_PROVISIONAL",
        "CLASS_DEFAULT_PROVISIONAL",
        "DRAFT_AT_LIVE_STAGE",
        "DIAGNOSIS_EXCLUDED_LANES",
        "PEAK_DEFER_IN_PROCESS",
        "22:00–07:00",
        "R6",
        "n8n-selftest-fail",
        "Per-lane onboarding template",
        "n8n:<lane>",
        "L6",
    ],
)
def test_monitoring_standard_covers_the_operator_questions(item):
    assert item in _flat(MONITOR), item


# ----------------------------------------------------------------------------- the numbers equal the code


def test_relay_routes_quoted_equal_the_relay_table():
    import n8n_run_relay as R

    f = _flat(CONFIG)
    for method, path in R.ROUTES:
        assert f"{method} {path}" in f, (method, path)
    assert R.EVENT_LANE == "n8n-workflow-error"


def test_notifier_numbers_quoted_equal_its_defaults():
    import incident_notifier as N

    assert (N.DEFAULT_DAILY_CAP, N.DEFAULT_P2_BATCH_MIN, N.DEFAULT_QUIET_START, N.DEFAULT_QUIET_END) == (
        24,
        30,
        "22:00",
        "07:00",
    )
    f = _flat(MONITOR)
    assert "24 messages per ET day" in f and "every 30 min" in f


def test_diagnoser_caps_and_exclusion_quoted_equal_the_code():
    from scripts.lib import n8n_failure_diagnosis as D
    from scripts.lib import n8n_remediation_catalogue as CAT

    assert (D.PER_CALL_CAP_USD, D.DAILY_CAP_USD, D.CONFIDENCE_MIN) == (0.05, 0.10, 0.7)
    assert CAT.DIAGNOSIS_EXCLUDED_LANES == frozenset({"trade-ai-scalp-live"})
    cat = json.loads((ROOT / "config" / "n8n_remediation_catalogue.json").read_text(encoding="utf-8"))
    assert cat["summary"]["lanes"] == 80 and cat["summary"]["lanes_with_auto_rerun"] == 33


def test_class_caps_quoted_equal_the_retry_policies():
    caps = json.loads((ROOT / "config" / "n8n_retry_policies.json").read_text(encoding="utf-8"))["class_caps"]
    assert caps == {
        "global": 3,
        "reserved_priority_max": 1,
        "heavy": 1,
        "llm": 1,
        "ingest": 1,
        "send": 1,
        "pipeline": 2,
        "learn": 1,
    }
    assert "global 3, `heavy` 1, `llm` 1, `ingest` 1, `send` 1, `pipeline` 2, `learn` 1" in _flat(ONBOARD)


def test_dispatcher_naming_quoted_equals_the_gate():
    from scripts.lib import lane_dispatch as LD

    assert (LD.DISPATCHER_EXPRESSION, LD.DISPATCHER_WORKFLOW_ID) == ("dispatcher", "tradeai-dispatcher")
    assert LD.R1_SHADOW_SHAPE_STATUS == "ACTIVE"


def test_scripts_the_documents_name_exist():
    for rel in (
        "scripts/check_n8n_relay_contract.py",
        "scripts/check_n8n_health_contracts.py",
        "scripts/build_n8n_health_contracts.py",
        "scripts/build_remediation_catalogue.py",
        "scripts/n8n_siem_bridge.py",
        "scripts/n8n_failure_diagnosis.py",
        "scripts/incident_notifier.py",
        "scripts/n8n_selftest_fail.py",
        "scripts/check_n8n_activation_grants.py",
        "scripts/check_n8n_import_ready.py",
        "scripts/pipelines/cutover/_cutover.py",
        "scripts/lib/lane_stage_clamp.py",
        "scripts/lib/lane_last_receipt.py",
    ):
        assert (ROOT / rel).exists(), rel


# ------------------------------------------------------------------------------- stale statements stay gone


def test_stale_statements_are_corrected():
    d02 = _flat(DOCS / "02-six-workflow-architecture.md")
    assert "governs until 3.1.0 is ratified" not in d02
    assert "4.4.0" in d02 and "N8N_ONBOARDING_STANDARD.md" in d02
    deploy = _flat(ROOT / "docs" / "ops" / "FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md")
    assert "executor stays on the v1 serial drain" not in deploy and "10-executor-v2.conf" in deploy
    assert "10-executor-v2.conf" in _flat(ROOT / "docs" / "ops" / "ROLLBACK_COMMANDS.md")
    doc17 = (ROOT / "docs" / "implementation" / "n8n-parallel" / "17-n8n-operating-model-20261008.md").read_text(
        encoding="utf-8"
    )
    assert doc17.splitlines()[2].startswith("**Status:** SUPERSEDED BY")


def test_inventory_change_log_records_the_day():
    f = _flat(DOCS / "cron-inventory" / "README.md")
    for needle in (
        "Executor v2 enabled",
        "W0 rolled back",
        "`flock -n` added to crontab L318",
        "Gateway lane `n8n-workflow-error`",
        "Dispatch shadow wave 1",
        "waves 2+3",
    ):
        assert needle in f, needle


def test_configuration_names_variables_never_values():
    text = CONFIG.read_text(encoding="utf-8")
    assert not re.search(r"(?i)(password|secret|token|key)\s*[:=]\s*[A-Za-z0-9/+]{16,}", text)
    assert not re.search(r"\b[0-9a-f]{40,}\b", text)
    assert "EXECUTIONS_DATA_SAVE_ON_SUCCESS=none" in text


# ----------------------------------------------------------------------------------------- AGENTS.md pointer


def _agents() -> str:
    return (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def _section_23() -> str:
    m = re.search(r"^# 23 · .*?(?=^# Version history)", _agents(), re.M | re.S)
    assert m, "§23 not found"
    return re.sub(r"\s+", " ", m.group(0))


def test_agents_23_points_at_the_configuration_and_the_standards():
    s23 = _section_23()
    for doc in (
        "N8N_CONFIGURATION.md",
        "N8N_ONBOARDING_STANDARD.md",
        "N8N_MONITORING_AND_REMEDIATION_STANDARD.md",
        "config/n8n_health_contracts.json",
    ):
        assert doc in s23, doc


def test_agents_12_states_the_cron_wide_offpeak_arming():
    flat = re.sub(r"\s+", " ", _agents())
    assert "the crontab header sets `LLM_DEFER_OFFPEAK=1` for **every** cron-launched caller" in flat
    assert "set in exactly one place — the drop-in" not in flat
    assert "so no cron-launched caller inherits it**" not in flat


def test_claude_md_adapter_restates_no_n8n_rule():
    """CLAUDE.md is an adapter (AGENTS.md §19): it must not grow n8n rules of its own."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "n8n" not in text.lower()


# ------------------------------------------------------------------------------ AGENTS.md 4.5.0 (PROPOSED)


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", _agents(), re.M)
    assert m, key
    return m.group(1)


def _v() -> tuple[int, ...]:
    return tuple(int(x) for x in _control("Policy-Version").split("."))


def test_4_5_0_row_and_header_agree_and_wait_for_the_operator():
    assert _v() >= (4, 5, 0)
    m = re.search(r"^\| 4\.5\.0 \| 2026-10-10 \| (PROPOSED|ACTIVE)[^|]* \| MINOR \|(.*)$", _agents(), re.M)
    assert m, "no 4.5.0 MINOR row"
    if m.group(1) == "PROPOSED":
        assert "PENDING" in m.group(2) and "APPROVE_AGENTS_POLICY_4_5_0 <pr_number> <head_sha>" in m.group(2)
        assert not re.search(r"\brides?\b", m.group(2), re.I), "a PROPOSED 4.5.0 must not claim to ride a prior token"
        if _v() == (4, 5, 0):
            assert _control("Status") == "PROPOSED" and _control("Effective-Date") == "PENDING"
            assert "4.5.0 is PROPOSED (MINOR)" in re.sub(r"\s+", " ", _agents()[:6000])
    else:
        assert re.search(r"APPROVE_AGENTS_POLICY_4_5_0 \d+ [0-9a-f]{7,40}", m.group(2))


def test_4_4_1_patch_row_is_recorded():
    assert re.search(r"^\| 4\.4\.1 \| 2026-10-10 \| ACTIVE on merge \| PATCH \|", _agents(), re.M)


def test_23_19_makes_the_standard_mandatory_and_cites_its_causes():
    m = re.search(r"^## 23\.19 .*?(?=^---$)", _agents(), re.M | re.S)
    assert m, "§23.19 missing"
    body = re.sub(r"\s+", " ", m.group(0))
    assert "N8N_ONBOARDING_STANDARD.md`, and it is mandatory" in body
    assert "config/n8n_health_contracts.json" in body and "check_n8n_health_contracts.py" in body
    assert "check_n8n_relay_contract.py" in body and '"deletedAt" IS NULL' in body
    bullets = [b for b in re.split(r"\n- ", m.group(0))[1:]]
    assert len(bullets) == 3 and all("*Cause (§20):" in b for b in bullets)
    assert "grants nothing" in body
