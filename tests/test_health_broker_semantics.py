from datetime import datetime, timezone
import sys
import types

# The health daemon's optional dotenv dependency is not required for its pure
# semantic validator; keep this unit test dependency-clean.
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))
from scripts.system_health_agent import evaluate_broker_snapshot


def _snapshot(ts: str, *, sync_mode: str = "APPLIED") -> dict:
    return {
        "portfolio_snapshot_id": "snap-1",
        "sync_mode": sync_mode,
        "holdings": [{"symbol": "SCHD", "broker_position_as_of": ts}],
    }


def test_broker_snapshot_requires_fresh_applied_positions():
    now = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)
    fresh = "2026-08-27T13:50:00+00:00"
    assert evaluate_broker_snapshot(_snapshot(fresh), now=now)["status"] == "CURRENT"
    stale = evaluate_broker_snapshot(_snapshot("2026-08-27T12:00:00+00:00"), now=now)
    assert stale["status"] == "STALE_PORTFOLIO"
    assert any("stale" in reason for reason in stale["reasons"])


def test_dry_run_cannot_claim_current_and_missing_timestamp_is_explicit():
    now = datetime.now(timezone.utc)
    dry = evaluate_broker_snapshot(_snapshot(now.isoformat(), sync_mode="DRY_RUN"), now=now)
    assert dry["status"] == "STALE_PORTFOLIO"
    assert "sync_not_applied" in dry["reasons"]
    missing = evaluate_broker_snapshot({"holdings": [{"symbol": "SCHD"}]}, now=now)
    assert missing["status"] == "STALE_PORTFOLIO"
    assert "missing_broker_timestamp:SCHD" in missing["reasons"]
