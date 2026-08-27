"""Semantic health gates: broker proof and Morning ownership."""
import json
from datetime import datetime, timezone
from pathlib import Path

import scripts.system_health_agent as health


def _write_holdings(root: Path, **meta):
    state = root / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    doc = {"holdings": [], "last_repriced": "2026-08-27 10:58:17 ET"}
    doc.update(meta)
    (state / "holdings.json").write_text(json.dumps(doc), encoding="utf-8")


def test_semantic_portfolio_requires_applied_sync_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "PROJECT_ROOT", tmp_path)
    _write_holdings(tmp_path, broker_as_of="2026-08-27 10:00:00 ET")
    result = health._semantic_portfolio_health(
        datetime(2026, 8, 27, 14, 5, tzinfo=timezone.utc))
    assert result["status"] in {"STALE_PORTFOLIO", "DATA_INTEGRITY_BLOCKED"}
    assert result["applied_sync"] is False
    assert any("applied broker-sync" in a for a in result["alerts"])


def test_semantic_portfolio_current_only_with_apply_and_id(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "PROJECT_ROOT", tmp_path)
    _write_holdings(tmp_path, broker_as_of="2026-08-27 10:00:00 ET",
                    portfolio_snapshot_id="snap-1",
                    _canonical_reconcile={"applied": True})
    result = health._semantic_portfolio_health(
        datetime(2026, 8, 27, 14, 5, tzinfo=timezone.utc))
    assert result["status"] == "OK"
    assert result["data_quality"] == "CURRENT"
    assert result["snapshot_id"] == "snap-1"


def test_morning_producer_health_flags_multiple_enabled_capabilities(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "PROJECT_ROOT", tmp_path)
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "morning.cron").write_text("send_morning_brief.py\n", encoding="utf-8")
    (cfg / "legacy.cron").write_text("morning_command_digest.py\n", encoding="utf-8")
    result = health._morning_producer_health()
    assert result["status"] == "DUPLICATE_PRODUCER"
    assert result["producer_count"] >= 2


def test_morning_producer_health_does_not_call_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "PROJECT_ROOT", tmp_path)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "canonical_operator_brief.py").write_text("def deliver_morning(): pass\n", encoding="utf-8")
    result = health._morning_producer_health()
    # Source capability alone is not an enabled scheduled producer.
    assert result["producer_count"] == 0

