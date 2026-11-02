"""The free scanners that replace CodeQL (2026-11-02).

Per change: ruff's flake8-bandit rules with a baseline (a test file's own `assert` is not a security
finding, so tests are excluded and a new test file never fails on its assertions). Nightly: semgrep
OSS + pip-audit + npm audit, alerting only on findings absent from the previous receipt, with a
missing tool recorded rather than skipped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_ruff_security as rsec  # noqa: E402
import nightly_security_scan as nss  # noqa: E402

CONFIG = {
    "alert_priority": "P1",
    "tools": {
        "semgrep": {"enabled": True, "argv": ["semgrep", "scan", "."], "install": "pipx install semgrep"},
        "pip-audit": {"enabled": True, "argv": ["pip-audit", "-f", "json"]},
        "npm-audit": {"enabled": True, "argv": ["npm", "audit", "--json"]},
    },
}

SEMGREP_ONE = json.dumps({"results": [{"check_id": "python.lang.security.audit.x", "path": "scripts/a.py",
                                       "start": {"line": 7},
                                       "extra": {"severity": "ERROR", "message": "bad thing"}}]})
PIP_ONE = json.dumps({"dependencies": [{"name": "demo", "version": "1.0",
                                        "vulns": [{"id": "GHSA-1", "fix_versions": ["1.1"]}]}]})
NPM_ONE = json.dumps({"vulnerabilities": {"pkg": {"severity": "high", "via": [{"title": "proto pollution"}]}}})


def runner(outputs, *, missing=()):
    def run(argv, cwd):
        tool = argv[0]
        if tool in missing:
            return 127, "", "not found"
        if argv[1:] == ["--version"]:
            return 0, f"{tool} 9.9.9\n", ""
        return 1, outputs.get(tool, "{}"), ""  # tools exit 1 when they FIND something
    return run


def test_new_findings_alert_once_then_dedupe(tmp_path):
    sent = []
    outs = {"semgrep": SEMGREP_ONE, "pip-audit": PIP_ONE, "npm": NPM_ONE}
    first = nss.run_scan(CONFIG, runner=runner(outs), state_dir=tmp_path,
                         send=lambda text, priority="P1": sent.append(text), dry_run=False)
    assert len(first["new"]) == 3 and len(sent) == 1
    assert "semgrep:python.lang.security.audit.x:scripts/a.py:7" in sent[0]
    second = nss.run_scan(CONFIG, runner=runner(outs), state_dir=tmp_path,
                          send=lambda text, priority="P1": sent.append(text), dry_run=False)
    assert second["new"] == [] and len(sent) == 1  # nothing new, nothing sent


def test_a_missing_tool_is_recorded_not_skipped(tmp_path):
    receipt = nss.run_scan(CONFIG, runner=runner({}, missing=("semgrep",)), state_dir=tmp_path, dry_run=False)
    assert receipt["tools"]["semgrep"]["status"] == "tool_missing"
    assert receipt["tools"]["semgrep"]["install"] == "pipx install semgrep"
    assert receipt["tools"]["pip-audit"]["status"] == "ran"


def test_a_dry_run_writes_no_receipt(tmp_path):
    nss.run_scan(CONFIG, runner=runner({}), state_dir=tmp_path, dry_run=True)
    assert not (tmp_path / "last.json").exists()


def test_ruff_security_baseline_has_no_new_findings():
    result = rsec.compare(rsec.scan(), rsec.load_baseline())
    assert result["ok"], result["new"][:10]


def test_a_new_security_finding_is_new_and_a_paid_one_is_stale():
    current = {"scripts/a.py": {"S105": 2}}
    baseline = {"scripts/a.py": {"S105": 1, "S603": 4}}
    result = rsec.compare(current, baseline)
    assert result["ok"] is False
    assert any("S105" in line for line in result["new"])
    assert any("S603" in line for line in result["stale"])
