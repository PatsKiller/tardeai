"""Independent service ownership and honest completion (no DB/services/providers)."""

import importlib
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import pipeline_repair_handoff as handoff
import run_pipeline_repair as runner


def test_dry_run_has_no_service_calls(monkeypatch):
    monkeypatch.setattr(handoff.subprocess, "run", lambda *a, **k: pytest.fail("service call"))
    r = handoff.request_repair("enrichment", dry_run=True)
    assert r["dry_run"] and not r["accepted"] and not r["recovered"]
    assert r["command"][-1] == "tradeai-pipeline-repair@enrichment.service"


def test_missing_unit_never_falls_back_to_inline_work(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="not-found\n")

    monkeypatch.setattr(handoff.subprocess, "run", run)
    r = handoff.request_repair("orchestrator")
    assert r["outcome"] == "FAILED" and not r["accepted"]
    assert len(calls) == 1
    assert "--no-block" not in calls[0]


def test_acceptance_is_pending_not_recovered(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        assert not kw.get("shell")
        return subprocess.CompletedProcess(cmd, 0, stdout="loaded\n")

    monkeypatch.setattr(handoff.subprocess, "run", run)
    r = handoff.request_repair("orchestrator")
    assert r["accepted"] and r["outcome"] == "PENDING"
    assert not r["ok"] and not r["recovered"]
    assert calls[-1] == ["systemctl", "--user", "start", "--no-block", "tradeai-pipeline-repair@orchestrator.service"]


def test_unknown_kind_cannot_become_shell_text():
    with pytest.raises(ValueError):
        handoff.request_repair("orchestrator; echo bad")


def test_runner_dry_run_cannot_write_or_start(monkeypatch, capsys):
    monkeypatch.setattr(runner, "_receipt", lambda *a: pytest.fail("write"))
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("run"))
    assert runner.main(["enrichment", "--apply", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["budget_s"] == 240


def test_tick_cannot_execute_worker_directly(monkeypatch):
    monkeypatch.setenv("TRADEAI_PIPELINE_REPAIR_KIND", "enrichment")
    monkeypatch.setenv("HEALTH_TICK_STEP_TIMEOUT_S", "37")
    monkeypatch.setattr(runner, "_receipt", lambda *a: pytest.fail("write"))
    assert runner.main(["enrichment", "--apply"]) == 2


def test_worker_receipt_records_failed_children(monkeypatch):
    monkeypatch.setenv("TRADEAI_PIPELINE_REPAIR_KIND", "enrichment")
    monkeypatch.delenv("HEALTH_TICK_STEP_TIMEOUT_S", raising=False)
    monkeypatch.setattr(runner, "independently_owned", lambda kind: True)
    receipts = []
    monkeypatch.setattr(runner, "_receipt", lambda k, d: receipts.append(dict(d)))
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 1, stdout=json.dumps({"completed": 2, "failed": 13, "deferred": 0})
        ),
    )
    assert runner.main(["enrichment", "--apply"]) == 1
    assert receipts[-1]["failed"] == 13 and receipts[-1]["status"] == "failed"
    assert not receipts[-1]["recovered"]


def test_worker_receipt_never_claims_empty_completion(monkeypatch):
    monkeypatch.setenv("TRADEAI_PIPELINE_REPAIR_KIND", "enrichment")
    monkeypatch.delenv("HEALTH_TICK_STEP_TIMEOUT_S", raising=False)
    monkeypatch.setattr(runner, "independently_owned", lambda kind: True)
    receipts = []
    monkeypatch.setattr(runner, "_receipt", lambda k, d: receipts.append(dict(d)))
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, stdout=json.dumps({"completed": 0, "failed": 0, "deferred": 0})
        ),
    )
    assert runner.main(["enrichment", "--apply"]) == 0
    assert receipts[-1]["status"] == "no_work"


def test_independent_unit_keeps_cgroup_cleanup_and_enrichment_budget():
    unit = (ROOT / "config/systemd/user/tradeai-pipeline-repair@.service").read_text()
    assert "KillMode=control-group" in unit
    assert "UnsetEnvironment=HEALTH_TICK_STEP_TIMEOUT_S" in unit
    assert "EnvironmentFile=" not in unit
    dropin = ROOT / "config/systemd/user/tradeai-pipeline-repair@enrichment.service.d/timeout.conf"
    assert "TimeoutStartSec=270" in dropin.read_text()


def test_watchdog_handoff_does_not_run_ier_in_health_tick(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg2", types.ModuleType("psycopg2"))
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    sys.modules.pop("pipeline_watchdog", None)
    w = importlib.import_module("pipeline_watchdog")
    conn = types.SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(w.psycopg2, "connect", lambda **kw: conn, raising=False)
    order = []
    monkeypatch.setattr(w, "check_pipeline_execution", lambda c: order.append("pipeline") or [])
    monkeypatch.setattr(w, "check_go_coverage", lambda c: order.append("coverage") or 0)
    monkeypatch.setattr(w, "run_ier_engine", lambda *a: pytest.fail("inline enrichment"))
    monkeypatch.setattr(
        handoff, "request_repair", lambda k: order.append("handoff") or {"accepted": True, "outcome": "PENDING"}
    )
    monkeypatch.setattr(sys, "argv", ["watchdog", "--no-telegram"])
    monkeypatch.setenv("HEALTH_TICK_STEP_TIMEOUT_S", "37")
    assert w.main() == 0
    assert order == ["handoff", "pipeline", "coverage"]
    sys.modules.pop("pipeline_watchdog", None)


def test_failed_enrichment_releases_own_freshness_claim(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg2", types.ModuleType("psycopg2"))
    sys.modules.pop("pipeline_watchdog", None)
    w = importlib.import_module("pipeline_watchdog")
    statements = []

    class Cursor:
        def execute(self, sql, params=()):
            statements.append((sql, params))

        def fetchall(self):
            return [("ABC", "market", 42, "STALE", None)]

        def fetchone(self):
            return ("own-claim",)

    conn = types.SimpleNamespace(cursor=lambda: Cursor(), commit=lambda: None, rollback=lambda: None)
    monkeypatch.setattr(w, "was_alerted_recently", lambda *a, **k: False)
    monkeypatch.setattr(w, "log_action", lambda *a, **k: None)
    monkeypatch.setattr(w.subprocess, "Popen", lambda *a, **k: types.SimpleNamespace(returncode=1))
    from contextlib import contextmanager

    @contextmanager
    def supervise(*a, **k):
        yield

    monkeypatch.setattr(w, "_supervise_enrichment_batch", supervise)
    report = {}
    assert w.run_ier_engine(conn, report) == 0
    assert report == {"completed": 0, "failed": 1, "deferred": 0}
    resets = [p for sql, p in statements if "SET last_enriched=NULL" in sql]
    assert resets == [["ABC", "own-claim"]]
    sys.modules.pop("pipeline_watchdog", None)


def test_environment_marker_does_not_prove_service_ownership(monkeypatch):
    monkeypatch.setenv("TRADEAI_PIPELINE_REPAIR_KIND", "enrichment")
    monkeypatch.delenv("HEALTH_TICK_STEP_TIMEOUT_S", raising=False)
    monkeypatch.setattr(runner, "independently_owned", lambda kind: False)
    monkeypatch.setattr(runner, "_receipt", lambda *a: pytest.fail("write"))
    assert runner.main(["enrichment", "--apply"]) == 2


@pytest.mark.parametrize(
    "report,expected",
    [
        ({"completed": 2, "failed": 1, "deferred": 0}, 1),
        ({"completed": 1, "failed": 0, "deferred": 1}, 75),
        ({"completed": -1, "failed": 0, "deferred": 0}, 1),
    ],
)
def test_worker_reconciles_counts_with_zero_exit(monkeypatch, report, expected):
    monkeypatch.setenv("TRADEAI_PIPELINE_REPAIR_KIND", "enrichment")
    monkeypatch.delenv("HEALTH_TICK_STEP_TIMEOUT_S", raising=False)
    monkeypatch.setattr(runner, "independently_owned", lambda kind: True)
    receipts = []
    monkeypatch.setattr(runner, "_receipt", lambda k, d: receipts.append(dict(d)))
    monkeypatch.setattr(
        runner.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(report))
    )
    assert runner.main(["enrichment", "--apply"]) == expected
    assert receipts[-1]["status"] in ("failed", "deferred")


def test_cgroup_membership_is_exact_and_fail_closed(monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: "0::/user.slice/tradeai-health-tick.service\n")
    assert not runner.independently_owned("enrichment")
    monkeypatch.setattr(
        Path, "read_text", lambda *a, **k: "0::/user.slice/tradeai-pipeline-repair@enrichment.service\n"
    )
    assert runner.independently_owned("enrichment")
    assert not runner.independently_owned("orchestrator")
