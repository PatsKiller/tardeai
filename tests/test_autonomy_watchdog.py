"""Program 4 — autonomous intelligence watchdog."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.autonomy_watchdog.engine import run_cycle
from scripts.lib.autonomy_watchdog.heartbeat import build_receipt, format_text, load_history, persist_receipt
from scripts.lib.autonomy_watchdog.model import (
    EXPECTED_IDLE,
    FAILED,
    HEALTHY,
    NOT_CONFIGURED,
    STALE,
    component,
    ny_date,
    ny_day_bounds,
    rollup,
)
from scripts.lib.autonomy_watchdog import telegram_system as TG
from scripts import api_v3_maturity as api


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "data" / "runtime" / "provider_cost").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("SYSTEM_TELEGRAM_INTERDICT", "1")
    return tmp_path


def test_rollup_never_promotes_idle_or_unconfigured():
    assert rollup([EXPECTED_IDLE]) == EXPECTED_IDLE
    assert rollup([NOT_CONFIGURED]) == NOT_CONFIGURED
    assert rollup([EXPECTED_IDLE, HEALTHY]) == HEALTHY
    assert rollup([EXPECTED_IDLE, FAILED]) == FAILED
    assert rollup([NOT_CONFIGURED, STALE]) == STALE


def test_component_schema():
    c = component("x", HEALTHY, reason="ok", source="t", last_success="2026-08-18T12:00:00+00:00")
    assert set(c) >= {"component", "status", "observed_at", "last_success", "last_failure", "age_seconds", "reason", "source", "consecutive_failures"}
    assert c["status"] == HEALTHY


def test_timezone_day_boundary():
    # 23:30 ET 17th is still 17th; 00:30 ET 18th is 18th
    late = datetime(2026, 8, 18, 3, 30, tzinfo=timezone.utc)  # 23:30 ET on 17th
    early = datetime(2026, 8, 18, 4, 30, tzinfo=timezone.utc)  # 00:30 ET on 18th
    assert ny_date(late) == "2026-08-17"
    assert ny_date(early) == "2026-08-18"
    start, end = ny_day_bounds("2026-08-18")
    assert start <= early < end
    assert not (start <= late < end)


def test_expected_idle_not_failed():
    c = component("learning", EXPECTED_IDLE, reason="no matured outcomes")
    assert c["status"] == EXPECTED_IDLE
    assert c["status"] != FAILED


def test_daily_identity_stable():
    now = datetime(2026, 8, 18, 13, 0, tzinfo=timezone.utc)
    assert TG.daily_identity(now) == "system-heartbeat:2026-08-18"
    assert TG.canary_identity(now) == "system-canary:2026-08-18"


def test_daily_window():
    before = datetime(2026, 8, 18, 11, 0, tzinfo=timezone.utc)  # 07:00 ET
    after = datetime(2026, 8, 18, 12, 20, tzinfo=timezone.utc)  # 08:20 ET
    assert TG.after_daily_window(before) is False
    assert TG.after_daily_window(after) is True


def test_persist_and_history_one_per_day(root: Path):
    rec = {
        "schema": "DailyIntelligenceHeartbeat@v1",
        "date": "2026-08-18",
        "generated_at": "2026-08-18T12:00:00+00:00",
        "overall": HEALTHY,
        "autonomy": {"wakes": 2},
    }
    persist_receipt(rec, root=root)
    rec2 = dict(rec)
    rec2["generated_at"] = "2026-08-18T13:00:00+00:00"
    rec2["autonomy"] = {"wakes": 5}
    persist_receipt(rec2, root=root)
    hist = load_history(root, 30)
    assert len(hist) == 1
    assert hist[0]["autonomy"]["wakes"] == 5


def test_telegram_dedupe(root: Path, monkeypatch: pytest.MonkeyPatch):
    env = {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "1", "SYSTEM_TELEGRAM_ENABLED": "1"}
    sent = {"n": 0}

    def fake_post(*a, **k):
        sent["n"] += 1
        class R:
            ok = True
            status_code = 200
            def json(self):
                return {"ok": True, "result": {"message_id": 99}}
        return R()

    monkeypatch.setattr("requests.post", fake_post)
    a = TG.send_system("hello", identity="system-heartbeat:2026-08-18", kind="daily_heartbeat", root=root, env=env)
    b = TG.send_system("hello", identity="system-heartbeat:2026-08-18", kind="daily_heartbeat", root=root, env=env)
    assert a["ok"] and a.get("message_id") == 99
    assert b.get("deduped") is True
    assert sent["n"] == 1


def test_ci_never_sends(root: Path):
    out = TG.send_system("x", identity="system-canary:2026-08-18", kind="canary", root=root)
    assert out["ok"] is False
    assert out["reason"] == "ci_or_interdict"


def test_format_has_no_trade_language():
    text = format_text({
        "release_sha": "98fffade53c5",
        "provenance_status": "AUTHORIZED_RELEASE",
        "autonomy": {"state": HEALTHY, "wakes": 4},
        "senses": {"state": HEALTHY, "receipts": 1},
        "learning": {"state": HEALTHY, "reflections": 1},
        "memory": {"state": HEALTHY, "retrievals": 2, "influence_mode": "SHADOW"},
        "cio": {"state": HEALTHY, "material_scans": 10, "immediate": 0, "suppressed": 10},
        "finops": {"state": HEALTHY, "events": 3},
        "health": {"operator_findings": 1},
    })
    assert "BUY" not in text and "SELL" not in text and "TRIM" not in text
    assert "DAILY INTELLIGENCE" in text


def test_authority_violation_failed(root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "1")
    out = run_cycle(root=root, dry_run=True, send_telegram=False)
    auth = [c for c in out["receipt"]["components"] if c["component"] == "authority"][0]
    assert auth["status"] == FAILED


def test_dry_run_does_not_persist(root: Path):
    run_cycle(root=root, dry_run=True, send_telegram=False)
    assert not (root / "data/cio/daily_intelligence_heartbeat.json").exists()


def test_cycle_persists(root: Path):
    out = run_cycle(root=root, dry_run=False, send_telegram=False)
    assert out["ok"] is True
    assert (root / "data/cio/daily_intelligence_heartbeat.json").is_file()
    assert out["receipt"]["authority"]["memory_behavior_influence"] in {"0", 0}
    assert out["financial_action"] is False


def test_api_heartbeat(root: Path):
    run_cycle(root=root, dry_run=False, send_telegram=False)
    code, body = api.handle_get("heartbeat")
    assert code == 200
    assert body["ok"] is True
    assert body["financial_action"] is False
    assert body["today"]["schema"] == "DailyIntelligenceHeartbeat@v1"
    code2, body2 = api.handle_get("dashboard")
    assert code2 == 200
    code3, body3 = api.handle_get("heartbeat/history")
    assert code3 == 200
    assert isinstance(body3["history"], list)


def test_cc_tab_present():
    health = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/HealthHub.tsx").read_text()
    assert "daily-intelligence" in health
    assert "DailyIntelligencePanel" in health
    panels = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/MaturityPanels.tsx").read_text()
    assert "daily-intelligence" in panels
    assert "No material immediate financial notification required" in panels


def test_no_broker_in_watchdog():
    root = Path(__file__).resolve().parent.parent / "scripts/lib/autonomy_watchdog"
    for p in root.glob("*.py"):
        text = p.read_text()
        for needle in ("place_order", "cancel_order", "broker.submit", "schwab_order"):
            assert needle not in text
