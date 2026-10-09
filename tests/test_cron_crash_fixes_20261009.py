"""Cron crash fixes from the 2026-10-09 cron + self-healing audits (operator: "fix the broken cron jobs").

- health_agent: failed --user units were invisible (systemctl asked only the system manager).
- schwab_econfirm_reconcile: cron PATH has no ~/.local/bin, so a bare "gog" raised FileNotFoundError.
- system_health_agent: a DISARMED retry was counted as "retried".
- hermes_llm_failover: the governed bridge's refusal code was dropped from 503 errors.
- lane registry: alert-quality was ACTIVE but never installed.
Fakes only: no systemd, no gog, no network, no database.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name):
    """Load scripts/<name>.py from THIS tree. health_agent puts the served release on sys.path when imported,
    so a plain import later in the session can resolve to the served copy instead of the code under test."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_t20261009_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_failed_units_checked_in_both_system_and_user_scope(monkeypatch):
    import health_agent as h

    calls = []

    def fake_run(argv, **k):
        calls.append(argv)
        out = ("tradeai-n8n-lab-watchdog.service loaded failed failed x\nxdg-desktop-portal.service loaded failed failed y\n"
               if "--user" in argv else "fancontrol.service loaded failed failed fan\n")
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr(h.subprocess, "run", fake_run)
    monkeypatch.setattr(h, "_POLICY", {"systemd_units": {"unit_prefixes": ["tradeai-", "fancontrol"]}})
    found = {(f["unit"], f["scope"]) for f in h.collect_failed_systemd_units()}
    assert found == {("fancontrol.service", "system"), ("tradeai-n8n-lab-watchdog.service", "user")}
    assert any("--user" in a for a in calls) and any("--user" not in a for a in calls)


def test_one_scope_unavailable_still_checks_the_other(monkeypatch):
    import health_agent as h

    def fake_run(argv, **k):
        if "--user" in argv:
            raise OSError("no bus")
        return subprocess.CompletedProcess(argv, 0, "tradeai-continuous.service loaded failed failed z\n", "")

    monkeypatch.setattr(h.subprocess, "run", fake_run)
    monkeypatch.setattr(h, "_POLICY", {"systemd_units": {"unit_prefixes": ["tradeai-"]}})
    kinds = sorted((f.get("type") or f.get("finding_type") or "", f.get("scope")) for f in h.collect_failed_systemd_units())
    assert ("systemd_check_unavailable", "user") in kinds
    assert ("systemd_unit_failed", "system") in kinds


def test_econfirm_resolves_gog_outside_cron_path(monkeypatch, tmp_path):
    e = _load("schwab_econfirm_reconcile")

    monkeypatch.setenv("GOG_BIN", "/opt/x/gog")
    assert e._gog_bin() == "/opt/x/gog"
    monkeypatch.delenv("GOG_BIN")
    home = tmp_path
    (home / ".local" / "bin").mkdir(parents=True)
    g = home / ".local" / "bin" / "gog"
    g.write_text("#!/bin/sh\n")
    g.chmod(0o755)
    monkeypatch.setattr(e.Path, "home", classmethod(lambda cls: home))
    assert e._gog_bin() == str(g)


def test_econfirm_missing_gog_is_a_surfaced_gmail_error(monkeypatch, tmp_path):
    e = _load("schwab_econfirm_reconcile")

    monkeypatch.setenv("GOG_BIN", str(tmp_path / "nope"))
    monkeypatch.setattr(e.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(e.GmailAccessError, match="gog not found"):
        e._gog("gmail", "search", "x")


def test_disarmed_retry_is_not_counted_as_retried(monkeypatch):
    s = _load("system_health_agent")

    monkeypatch.delenv("TRADEAI_HEALTH_AGENT_RETRY", raising=False)
    assert s._retry_armed() is False
    monkeypatch.setenv("TRADEAI_HEALTH_AGENT_RETRY", "1")
    assert s._retry_armed() is True
    src = (ROOT / "scripts/system_health_agent.py").read_text(encoding="utf-8")
    assert 'if comp.get("retry_cmd") and not _retry_armed():' in src
    assert 'report["summary"]["retry_disarmed"] += 1' in src
    assert '"retry_disarmed": 0' in src


def test_bridge_refusal_code_is_kept_in_the_error(monkeypatch):
    f = _load("hermes_llm_failover")

    body = json.dumps({"error": {"code": "BRIDGE_BUSY", "status": 503}}).encode()

    def boom(*a, **k):
        raise urllib.error.HTTPError("http://x", 503, "Service Unavailable", {}, io.BytesIO(body))

    monkeypatch.setattr(f, "_bridge_flash_chat", boom)
    with pytest.raises(f.HermesLlmError, match=r"HTTP Error 503: Service Unavailable:BRIDGE_BUSY"):
        f.chat_json("p")
    assert f._bridge_refusal_code(RuntimeError("x")) == ""


def test_alert_quality_registry_row_matches_reality():
    reg = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
    row = next(r for r in reg["lanes"] if r.get("lane_id") == "alert-quality")
    assert row["state"] == "NEVER_SCHEDULED" and row["reason_confidence"] == "ESTABLISHED"
