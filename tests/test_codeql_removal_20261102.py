"""CodeQL is gone; the promote gate and the merge windows say so (2026-11-02).

Operator: "remove CodeQL completely... the password/personal-data scan stays" and "Merge in batches at
noon and 5:30". The promote gate must accept a head whose every remaining check is green, and a
historical cancelled CodeQL run must never block it, while every test workflow stays required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import release_grant_preflight as rgp  # noqa: E402

SHA = "a" * 40


def _run(path, *, conclusion="success", status="completed", number=1):
    return {"head_sha": SHA, "event": "push", "head_branch": "main", "path": path,
            "workflow_id": 1, "id": number, "run_number": number, "status": status,
            "conclusion": conclusion, "name": path.split("/")[-1]}


def test_the_codeql_workflow_is_gone():
    assert not (ROOT / ".github" / "workflows" / "codeql.yml").exists()


def test_a_cancelled_codeql_run_never_blocks_a_promote():
    runs = [_run(p, number=i) for i, p in enumerate(sorted(rgp.REQUIRED_PUSH_WORKFLOWS), start=1)]
    runs.append(_run(".github/workflows/codeql.yml", conclusion="cancelled", number=9))
    ev = rgp.evaluate_push_checks(SHA, runs)
    assert ev["ok"] is True, ev["errors"]
    codeql = next(c for c in ev["checks"] if c["path"].endswith("codeql.yml"))
    assert codeql["gating"] is False


def test_any_other_test_workflow_still_blocks():
    runs = [_run(p, number=i) for i, p in enumerate(sorted(rgp.REQUIRED_PUSH_WORKFLOWS), start=1)]
    runs.append(_run(".github/workflows/provider-cost-ci.yml", conclusion="failure", number=9))
    ev = rgp.evaluate_push_checks(SHA, runs)
    assert ev["ok"] is False
    assert any(e.endswith("provider-cost-ci.yml") for e in ev["errors"])


def test_the_promote_gate_still_requires_secret_scan_when_it_ran_red():
    runs = [_run(p, number=i) for i, p in enumerate(sorted(rgp.REQUIRED_PUSH_WORKFLOWS), start=1)]
    runs.append(_run(".github/workflows/secret-scan.yml", conclusion="failure", number=9))
    assert rgp.evaluate_push_checks(SHA, runs)["ok"] is False


def test_mergify_merges_in_two_windows():
    cfg = yaml.safe_load((ROOT / ".mergify.yml").read_text())
    blocks = 0
    for rule in cfg["pull_request_rules"]:
        if "queue" in (rule.get("actions") or {}):
            flat = json.dumps(rule.get("conditions"))
            assert "Mon-Fri 12:00-12:30[America/New_York]" in flat, rule["name"]
            assert "Mon-Fri 17:30-18:30[America/New_York]" in flat, rule["name"]
            blocks += 1
    for rule in cfg["queue_rules"]:
        flat = json.dumps(rule.get("merge_conditions"))
        assert "Mon-Fri 12:00-12:30[America/New_York]" in flat, rule["name"]
        assert "Mon-Fri 17:30-18:30[America/New_York]" in flat, rule["name"]
        blocks += 1
    assert blocks == 4


def test_autoheal_no_longer_watches_codeql():
    cfg = json.loads((ROOT / "config" / "main_red_autoheal.json").read_text())
    assert "CodeQL" not in cfg["required_workflows"]
    assert "secret-scan" in cfg["required_workflows"]
