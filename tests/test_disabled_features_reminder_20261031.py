"""A feature switched off on purpose carries a review date, and the reminder fires when it passes.

Operator 2026-10-31: "there needs to be a reminder to switch it back on. We just don't want to leave it off".
Firing test: scripts/check_disabled_features.py sends its P2 through an injected sender (never the real one).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts import check_disabled_features as chk
from scripts.lib import disabled_features as df
from scripts.lib import market_risk_projection as proj
from scripts.lib.market_risk import cio_context

COVERS = ["scripts/check_disabled_features.py"]

BLOCK = {
    "reason": "test reason",
    "disabled_at": "2026-10-31",
    "review_by": "2026-11-07",
    "owner": "coordinator",
    "reenable_plan": "review passes",
}


def _cfg(tmp_path: Path, name: str, blk: dict | None, *, json_file: bool = False) -> Path:
    d = tmp_path / "config"
    d.mkdir(exist_ok=True)
    body = {"schema": "X@v1", "enabled": True}
    if blk is not None:
        body["disabled_until"] = blk
    p = d / (name + (".json" if json_file else ".yaml"))
    p.write_text(json.dumps(body) if json_file else __import__("yaml").safe_dump(body), encoding="utf-8")
    return d


def test_curation_config_carries_the_reminder():
    e = df.entry_for(df.CONFIG_DIR / "market_risk_curation.yaml", today=date(2026, 10, 31))
    assert e and e["review_by"] == "2026-11-07" and e["owner"] == "coordinator" and not e.get("error")
    assert "BLUE/YELLOW/GREEN" in e["reenable_plan"]


def test_note_and_overdue_boundary():
    e = df.entry_for(df.CONFIG_DIR / "market_risk_curation.yaml", today=date(2026, 11, 7))
    assert df.note(e, "curation") == "curation: OFF — pending review, due 2026-11-07"
    late = df.entry_for(df.CONFIG_DIR / "market_risk_curation.yaml", today=date(2026, 11, 8))
    assert late["overdue"] and df.note(late, "curation").startswith("curation: OFF — OVERDUE since 2026-11-07")
    assert df.note(None, "curation") == "curation: ON"


def test_projection_and_ask_facts_show_the_status():
    mr = proj.build(None, None)
    assert mr["curation"]["state"] == "OFF" and "due 2026-11-07" in mr["curation"]["note"]
    facts = cio_context.ask_facts(mr)
    assert facts["curation"]["note"] == mr["curation"]["note"]


def test_scan_finds_yaml_and_json_and_flags_malformed(tmp_path):
    d = _cfg(tmp_path, "a_feature", BLOCK)
    _cfg(tmp_path, "b_feature", {**BLOCK, "review_by": "2026-10-01"}, json_file=True)
    _cfg(tmp_path, "c_broken", {"reason": "x"})
    _cfg(tmp_path, "d_plain", None)
    found = {e["name"]: e for e in df.scan(d, today=date(2026, 10, 31))}
    assert set(found) == {"a_feature", "b_feature", "c_broken"}
    assert not found["a_feature"]["overdue"] and found["b_feature"]["overdue"]
    assert found["c_broken"]["overdue"] and "missing" in found["c_broken"]["error"]


def test_firing_overdue_sends_one_p2_through_the_sender(tmp_path):
    d = _cfg(tmp_path, "late_feature", {**BLOCK, "review_by": "2026-10-01"})
    sent: list[tuple] = []

    def sender(msg, **kw):
        sent.append((msg, kw))
        return True

    rc = chk.run(apply=True, config_dir=d, today=date(2026, 10, 31), sender=sender)
    assert rc == 3 and len(sent) == 1
    msg, kw = sent[0]
    assert "Disabled feature overdue" in msg and "late_feature" in msg
    assert kw["priority"] == "P2" and kw["dedupe_minutes"] == 1440 and kw["producer"] == chk.PRODUCER


def test_nothing_overdue_sends_nothing(tmp_path):
    d = _cfg(tmp_path, "fine", BLOCK)
    sent = []
    assert chk.run(apply=True, config_dir=d, today=date(2026, 10, 31), sender=lambda m, **k: sent.append(m)) == 0
    assert sent == []


def test_dry_run_never_sends(tmp_path, monkeypatch):
    d = _cfg(tmp_path, "late", {**BLOCK, "review_by": "2026-10-01"})
    monkeypatch.setattr(chk, "deliver", lambda *a, **k: pytest.fail("dry run must not deliver"))
    assert chk.run(apply=False, config_dir=d, today=date(2026, 10, 31)) == 3


def test_harness_refuses_the_real_sender(monkeypatch):
    from scripts import telegram_alert as ta

    calls = []
    monkeypatch.setattr(ta, "send_telegram", lambda *a, **k: calls.append(a) or True)
    monkeypatch.setenv("TRADE_AI_CI", "1")
    assert chk.deliver("x") is False
    assert calls == [], "the real sender was reached under a test harness"
