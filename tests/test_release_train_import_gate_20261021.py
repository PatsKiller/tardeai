"""Release train arming finding 2 (ANCHOR RELEASE_TRAIN_IMPORT_GATE_20261021): the §23.24 import gate and
``tradeai-fabric-release-train``.

What is pinned here:

* every WORKFLOW-level §23.24 element passes (no FAIL, no critical PARTIAL; error workflow, retry owner, idempotency
  key, health contract, runbook, receipts); the gate refuses only on the six PLATFORM facts (FW-P1..P6, true of every
  fabric workflow, the already-imported ones included) and on runtime obligations that need host-signed evidence;
* the runtime obligations are recorded as PENDING in ``framework_pending_evidence.json``, generated from and equal to
  the checker's own obligation list (so it cannot drift); it is not evidence and not an exception;
* the gate is not weakened: it still refuses today, exceptions are still unaccepted, and the arming script's step F
  runs the activation gate with ``--runtime-evidence`` (packet pattern) and refuses ``--apply`` without it.

Hermetic: the real checkers on committed files; the arming sandbox under $TMPDIR. No n8n, DB, relay or network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_release_train_arming_20261021 import Sandbox  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WF = "docs/implementation/n8n-maturity/workflows/fabric/tradeai-fabric-release-train.json"
PENDING = ROOT / "docs/ops/packets/release-train-arming-20261021/framework_pending_evidence.json"


def _framework():
    p = subprocess.run([sys.executable, "scripts/check_n8n_workflow_framework.py", "--workflow", WF, "--json"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    return json.loads(p.stdout)


def _gate():
    p = subprocess.run([sys.executable, "scripts/check_n8n_import_ready.py", WF, "--relay-url",
                        "http://172.19.0.1:18092", "--known-id", "tradeai-fabric-error", "--framework-gate",
                        "activation", "--json"], cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    return p.returncode, json.loads(p.stdout)


@pytest.fixture(scope="module")
def fw():
    return _framework()


def test_every_workflow_element_passes(fw):
    import check_n8n_workflow_framework as F  # noqa: PLC0415

    w = fw["workflows"][0]
    assert w["failing"] == []
    bad = {k: v["status"] for k, v in w["elements"].items() if v["status"] == "fail"
           or (v["status"] == "partial" and k in F.CRITICAL_ELEMENTS)}
    assert bad == {}
    for k in ("FW-M2", "FW-A1", "FW-R1", "FW-R2", "FW-R6", "FW-C3", "FW-A6", "FW-L1", "FW-L2", "FW-M6"):
        assert w["elements"][k]["status"] == "pass", k
    # the one non-critical partial: no cron-line fallback exists for an n8n-only lane (manual release is the fallback)
    assert {k for k, v in w["elements"].items() if v["status"] == "partial"} <= {"FW-R3"}


def test_the_gate_still_refuses_only_on_platform_and_runtime():
    rc, out = _gate()
    assert rc != 0 and out["refused"] == 1
    blocking = out["files"][0]["framework_gate"]["blocking"]
    assert blocking and all(b.startswith(("platform FW-P", "runtime 23.24-")) for b in blocking), blocking


def test_pending_evidence_equals_the_checkers_obligations(fw):
    doc = json.loads(PENDING.read_text(encoding="utf-8"))
    w = fw["workflows"][0]
    assert doc["schema"] == "N8nFrameworkPendingEvidence@v1" and doc["status"] == "PENDING"
    assert doc["workflow_id"] == w["id"] == "tradeai-fabric-release-train"
    assert [(o["id"], o["evidence_required"]) for o in doc["runtime_pending"]] == \
        [(o["id"], o["evidence_required"]) for o in w["runtime"]]
    assert all(o["collect_at"] for o in doc["runtime_pending"])
    assert set(doc["platform_blocking"]) == {k for k, v in fw["platform"].items() if v["status"] != "pass"}
    assert doc["static_elements"]["failing"] == []
    assert "not an exception" in doc["note"].lower() or "not evidence and not an exception" in doc["note"].lower()


def test_pending_evidence_is_not_accepted_by_the_gate_as_evidence():
    p = subprocess.run([sys.executable, "scripts/check_n8n_import_ready.py", WF, "--relay-url",
                        "http://172.19.0.1:18092", "--known-id", "tradeai-fabric-error", "--framework-gate",
                        "activation", "--runtime-evidence", str(PENDING), "--json"], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=300)
    assert p.returncode != 0                                              # never a pass, never an exception


def test_no_gate_exception_or_weakening_was_added():
    src = (ROOT / "scripts/check_n8n_workflow_framework.py").read_text(encoding="utf-8")
    assert "def _excused(exceptions: Iterable[Mapping], wid: str, item: str, today: str) -> bool:" in src
    assert "tradeai-fabric-release-train" not in src
    assert "tradeai-fabric-release-train" not in (ROOT / "scripts/check_n8n_import_ready.py").read_text()
    facts = json.loads((ROOT / "docs/implementation/n8n-maturity/data/n8n_platform_facts_20261015.json").read_text())
    assert facts["facts"]["host_dead_man_outside_n8n"]["value"] is not True    # unchanged platform facts


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path)


def test_step_f_runs_the_activation_gate_and_names_what_is_pending(sb):
    r = sb.run("F")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "runtime evidence: NOT SUPPLIED" in r.stdout and "runtime obligations pending 18" in r.stdout
    assert "WOULD REFUSE --apply" in r.stdout


def test_step_f_apply_refuses_without_runtime_evidence(sb):
    r = sb.apply("F")
    assert r.returncode == 2 and "framework evidence unavailable (AGENTS §23.24)" in r.stdout
    assert not any("import:workflow" in c for c in sb.calls())


def test_step_f_apply_with_evidence_still_meets_the_real_gate(sb, tmp_path):
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps({"schema": "N8nFrameworkRuntimeEvidence@v2", "workflows": {}}))
    r = sb.apply("F", N8N_FRAMEWORK_RUNTIME_EVIDENCE=str(ev))
    assert r.returncode == 2 and "§23.24" in r.stdout and "not routed around" in r.stdout
    assert not any("import:workflow" in c or "publish:workflow" in c for c in sb.calls())


def test_packet_finding_2_records_the_result():
    text = (ROOT / "docs/ops/packets/release-train-arming-20261021/README.md").read_text(encoding="utf-8")
    seg = text[text.index("2. **F is blocked by AGENTS §23.24.**"):]
    assert "**Status: WORKFLOW CONFORMS; STILL BLOCKED (platform + runtime)**" in seg[:2600]


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_train_import_gate_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_IMPORT_GATE_20261021"
    assert "tests/test_release_train_import_gate_20261021.py" in doc["files"]
