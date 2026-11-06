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

#: A firing test below drives main --apply through the real structured Telegram outcome import path.
COVERS = ["scripts/nightly_security_scan.py"]
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
    def run(argv, cwd, **kwargs):
        tool = argv[0]
        if tool in missing:
            return 127, "", "not found"
        if argv[1:] == ["--version"]:
            return 0, f"{tool} 9.9.9\n", ""
        clean = {"semgrep": '{"results":[]}', "pip-audit": '{"dependencies":[]}', "npm": '{"vulnerabilities":{}}'}
        return 1, outputs.get(tool, clean[tool]), ""  # tools exit 1 when they FIND something
    return run


def test_new_findings_alert_once_then_dedupe(tmp_path):
    sent = []
    outs = {"semgrep": SEMGREP_ONE, "pip-audit": PIP_ONE, "npm": NPM_ONE}
    first = nss.run_scan(CONFIG, runner=runner(outs), state_dir=tmp_path,
                         send=lambda text, priority="P1": sent.append(text) or {"accepted": True, "delivered": True}, dry_run=False)
    assert len(first["new"]) == 3 and len(sent) == 1
    assert "semgrep:python.lang.security.audit.x:scripts/a.py:7" in sent[0]
    second = nss.run_scan(CONFIG, runner=runner(outs), state_dir=tmp_path,
                          send=lambda text, priority="P1": sent.append(text) or {"accepted": True, "delivered": True}, dry_run=False)
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


def test_a_missing_or_broken_ruff_fails_closed():
    """No JSON from ruff is not 'zero findings': the linter never ran, so the gate must refuse."""
    import pytest

    def missing(argv):
        return 2, ""

    with pytest.raises(RuntimeError):
        rsec.scan(runner=missing)

    def crashed(argv):
        return 1, ""

    with pytest.raises(RuntimeError):
        rsec.scan(runner=crashed)


def test_a_clean_scan_is_an_empty_json_list():
    assert rsec.scan(runner=lambda argv: (0, "[]")) == {}


# ---------------------------------------------------------------- review B (#2488)
def test_a_missing_tool_alerts_on_its_own_and_exits_non_zero(tmp_path, monkeypatch, capsys):
    import os, sys as _s, types
    sent = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram_outcome = lambda text, **kw: sent.append((text, kw)) or {"accepted": True, "delivered": True}
    monkeypatch.setitem(_s.modules, "telegram_alert", fake)
    monkeypatch.setattr(nss, "_default_runner", runner({}, missing=("semgrep",)))
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(dict(CONFIG, tools={**CONFIG["tools"], "pip-audit": {"enabled": False},
                                                  "npm-audit": {"enabled": False}})))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    rc = nss.main(["--apply", "--config", str(cfg), "--json"])
    assert rc == 1
    assert sent and "NOT INSTALLED" in sent[0][0]
    assert "pipx install semgrep" in sent[0][0]


def test_a_crashed_tool_carries_its_previous_findings_forward(tmp_path):
    outs = {"semgrep": SEMGREP_ONE}
    first = nss.run_scan(CONFIG, runner=runner(outs), state_dir=tmp_path, dry_run=False,
                         send=lambda *args, **kwargs: {"accepted": True, "delivered": True})
    assert len(first["findings"]) == 1

    def crash(argv, cwd):
        if argv[0] == "semgrep":
            return 2, "", "boom"
        clean = '{"dependencies":[]}' if argv[0] == "pip-audit" else '{"vulnerabilities":{}}'
        return (0, f"{argv[0]} 9.9.9\n", "") if argv[1:] == ["--version"] else (0, clean, "")

    second = nss.run_scan(CONFIG, runner=crash, state_dir=tmp_path, dry_run=False)
    assert second["tools"]["semgrep"]["status"] == "error"
    assert [f["id"] for f in second["findings"] if f.get("carried")] == [
        "semgrep:python.lang.security.audit.x:scripts/a.py:7"]
    # the next good night must not present the old finding as NEW again
    sent = []
    third = nss.run_scan(CONFIG, runner=runner(outs), state_dir=tmp_path,
                         send=lambda text, priority="P1": sent.append(text) or {"accepted": True, "delivered": True}, dry_run=False)
    assert third["new"] == [] and sent == []


def test_pip_audit_audits_the_project_lock_not_pipx():
    cfg = json.loads((ROOT / "config" / "nightly_security_scan.json").read_text())
    argv = cfg["tools"]["pip-audit"]["argv"]
    assert "-r" in argv and "requirements.lock.txt" in argv
