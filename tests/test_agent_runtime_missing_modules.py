"""Agent-runtime health monitor + trigger producer must import and exit 0.

No network required for dry-run producer. Health monitor may degrade but
must still write an observation and exit 0 when collection succeeds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_health_monitor_module_imports():
    from scripts.agent_runtime import health_monitor as hm
    assert callable(hm.collect)
    assert callable(hm.main)


def test_trigger_producer_dry_run_exits_zero(tmp_path, monkeypatch):
    from scripts.agent_runtime import trigger_producer as tp
    monkeypatch.delenv("AGENT_RUNTIME_DISPATCH_DSN", raising=False)
    rc = tp.main(["--dry-run", "--json", "--sources", ""])
    assert rc == 0


def test_trigger_producer_missing_dsn_fail_soft(monkeypatch):
    from scripts.agent_runtime import trigger_producer as tp
    monkeypatch.delenv("AGENT_RUNTIME_DISPATCH_DSN", raising=False)
    rc = tp.main(["--json"])
    assert rc == 0


def test_health_monitor_writes_observation_without_crashing(tmp_path, monkeypatch):
    from scripts.agent_runtime import health_monitor as hm

    def _boom(url: str):
        raise hm.URLError("down")

    monkeypatch.setattr(hm, "_get_json", lambda url: (_ for _ in ()).throw(hm.URLError("down")))
    state = tmp_path / "agent-runtime-health.json"
    monkeypatch.setattr(sys, "argv", ["health_monitor.py", "--state-file", str(state)])
    rc = hm.main()
    assert rc == 0
    payload = json.loads(state.read_text())
    assert payload["contract"] == "agent-runtime-health-v1"
    assert payload["authority"]["financial_action"] is False
