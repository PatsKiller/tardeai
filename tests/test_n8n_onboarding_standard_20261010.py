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
    for target in ("N8N_ONBOARDING_STANDARD.md", "N8N_MONITORING_AND_REMEDIATION_STANDARD.md",
                   "02-six-workflow-architecture.md", "cron-inventory/README.md", "config/n8n_health_contracts.json"):
        assert target in f, target
    assert "N8N_CONFIGURATION.md" in _flat(ONBOARD) and "N8N_CONFIGURATION.md" in _flat(MONITOR)
    assert "N8N_MONITORING_AND_REMEDIATION_STANDARD.md" in _flat(ONBOARD)
    master = _flat(DOCS / "00-MASTER-PROGRAM.md")
    assert all(n in master for n in ("N8N_CONFIGURATION.md", "N8N_ONBOARDING_STANDARD.md",
                                     "N8N_MONITORING_AND_REMEDIATION_STANDARD.md"))


@pytest.mark.parametrize("rule", [
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
])
def test_onboarding_standard_carries_the_rule(rule):
    assert rule.lower() in _flat(ONBOARD).lower(), rule


def test_onboarding_lessons_table_links_every_root_cause():
    f = _flat(ONBOARD)
    for i in range(1, 11):
        assert f"| RC{i} |" in f, f"RC{i}"


@pytest.mark.parametrize("item", [
    "N8nHealthContract@v1", "LEARNED_PROVISIONAL", "CLASS_DEFAULT_PROVISIONAL", "DRAFT_AT_LIVE_STAGE",
    "DIAGNOSIS_EXCLUDED_LANES", "PEAK_DEFER_IN_PROCESS", "22:00–07:00", "R6", "n8n-selftest-fail",
    "Per-lane onboarding template", "n8n:<lane>", "L6",
])
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
        24, 30, "22:00", "07:00")
    f = _flat(MONITOR)
    assert "24 messages per ET day" in f and "every 30 min" in f


def test_diagnoser_caps_and_exclusion_quoted_equal_the_code():
    from scripts.lib import n8n_failure_diagnosis as D
    from scripts.lib import n8n_remediation_catalogue as CAT

    assert (D.PER_CALL_CAP_USD, D.DAILY_CAP_USD, D.CONFIDENCE_MIN) == (0.05, 0.10, 0.7)
    assert CAT.DIAGNOSIS_EXCLUDED_LANES == frozenset({"trade-ai-scalp-live"})
    cat = json.loads((ROOT / "config" / "n8n_remediation_catalogue.json").read_text(encoding="utf-8"))
    assert cat["summary"]["lanes"] == 53 and cat["summary"]["lanes_with_auto_rerun"] == 8


def test_class_caps_quoted_equal_the_retry_policies():
    caps = json.loads((ROOT / "config" / "n8n_retry_policies.json").read_text(encoding="utf-8"))["class_caps"]
    assert caps == {"global": 3, "reserved_priority_max": 1, "heavy": 1, "llm": 1, "ingest": 1, "send": 1,
                    "pipeline": 2, "learn": 1}
    assert "global 3, `heavy` 1, `llm` 1, `ingest` 1, `send` 1, `pipeline` 2, `learn` 1" in _flat(ONBOARD)


def test_dispatcher_naming_quoted_equals_the_gate():
    from scripts.lib import lane_dispatch as LD

    assert (LD.DISPATCHER_EXPRESSION, LD.DISPATCHER_WORKFLOW_ID) == ("dispatcher", "tradeai-dispatcher")
    assert LD.R1_SHADOW_SHAPE_STATUS == "ACTIVE"


def test_scripts_the_documents_name_exist():
    for rel in ("scripts/check_n8n_relay_contract.py", "scripts/check_n8n_health_contracts.py",
                "scripts/build_n8n_health_contracts.py", "scripts/build_remediation_catalogue.py",
                "scripts/n8n_siem_bridge.py", "scripts/n8n_failure_diagnosis.py", "scripts/incident_notifier.py",
                "scripts/n8n_selftest_fail.py", "scripts/check_n8n_activation_grants.py",
                "scripts/check_n8n_import_ready.py", "scripts/pipelines/cutover/_cutover.py",
                "scripts/lib/lane_stage_clamp.py", "scripts/lib/lane_last_receipt.py"):
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
        encoding="utf-8")
    assert doc17.splitlines()[2].startswith("**Status:** SUPERSEDED BY")


def test_inventory_change_log_records_the_day():
    f = _flat(DOCS / "cron-inventory" / "README.md")
    for needle in ("Executor v2 enabled", "W0 rolled back", "`flock -n` added to crontab L318",
                   "Gateway lane `n8n-workflow-error`", "Dispatch shadow wave 1", "waves 2+3"):
        assert needle in f, needle


def test_configuration_names_variables_never_values():
    text = CONFIG.read_text(encoding="utf-8")
    assert not re.search(r"(?i)(password|secret|token|key)\s*[:=]\s*[A-Za-z0-9/+]{16,}", text)
    assert not re.search(r"\b[0-9a-f]{40,}\b", text)
    assert "EXECUTIONS_DATA_SAVE_ON_SUCCESS=none" in text
