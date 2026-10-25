"""Market-session-aware freshness (live audit 2026-10-25: weekend data shown STALE / overdue).

Synthetic dates only. The case table is shared with the TypeScript mirror
(apps/command-center-v3/src/lib/marketSessionFreshness.test.ts).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import session_freshness as sf
from scripts.lib.buy_ready_packets_index import index_packets
from scripts.lib.watch_canonical_quote import compose_quote_artifact, derive_freshness

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/session_freshness/cases_20261025.json").read_text(encoding="utf-8"))
SUNDAY = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)


def _t(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.parametrize("case", CASES["phrases"], ids=lambda c: c["why"])
def test_closed_phrase(case):
    assert sf.closed_phrase(_t(case["now"])) == case["phrase"]


@pytest.mark.parametrize("case", CASES["evaluate"], ids=lambda c: c["why"])
def test_evaluate(case):
    out = sf.evaluate(case["as_of"], _t(case["now"]), max_age_h=case["max_age_h"],
                      closed_max_age_h=case.get("closed_max_age_h"), grace_minutes=case.get("grace_minutes", 0))
    assert out["state"] == case["state"], out
    assert out["stale"] is (case["state"] in ("stale", "unknown"))
    if case["state"] == "latest_close":
        assert out["phrase"].startswith("Market closed · last close")


@pytest.mark.parametrize("case", CASES["trading_age"], ids=lambda c: c["why"])
def test_trading_age(case):
    assert sf.trading_age_hours(case["as_of"], _t(case["now"])) == pytest.approx(case["hours"], abs=0.01)


def test_quote_friday_close_print_is_not_stale_on_sunday():
    state, session = derive_freshness("2026-10-23T19:46:00+00:00", now=SUNDAY, hold_last_close=True)
    assert state == "AFTER_HOURS_CURRENT" and session == "regular"


def test_quote_friday_morning_print_stays_stale_on_sunday():
    state, _ = derive_freshness("2026-10-23T13:15:00+00:00", now=SUNDAY, hold_last_close=True)
    assert state == "STALE"


def test_quote_friday_close_print_still_held_monday_premarket():
    # Beyond the old 48 h weekend cap: Friday close is still the latest regular print.
    state, _ = derive_freshness("2026-10-23T19:50:00+00:00", now=datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc), hold_last_close=True)
    assert state == "AFTER_HOURS_CURRENT"


def test_quote_rth_rule_unchanged_while_open():
    now = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)  # Mon 12:00 ET
    assert derive_freshness("2026-10-26T15:30:00+00:00", now=now, hold_last_close=True)[0] == "CURRENT"
    assert derive_freshness("2026-10-23T19:50:00+00:00", now=now, hold_last_close=True)[0] == "STALE"


def test_quote_default_callers_unchanged():
    # decision_integrity / watch_alerts_eval apply their own closed-market hold.
    assert derive_freshness("2026-10-23T19:46:00+00:00", now=SUNDAY)[0] == "STALE"


def test_compose_quote_artifact_holds_friday_close_on_sunday():
    art = compose_quote_artifact(symbol="SYM001", mq_id=1, mq_price=10.0, mq_fetched_at="2026-10-23T19:50:00+00:00",
                                 mq_source="synthetic", mq_day_change_pct=0.1, wi_id=None, wi_price=None,
                                 wi_last_enriched_at=None, wi_change_pct=None, now=SUNDAY)
    assert art["freshness_state"] == "AFTER_HOURS_CURRENT"


def _packet(tmp_path: Path, sym: str, saved_at: str) -> None:
    (tmp_path / f"{sym}.json").write_text(json.dumps({"symbol": sym, "state": "BUY_READY", "saved_at": saved_at}), encoding="utf-8")


def test_ready_now_keeps_friday_packets_over_the_weekend(tmp_path):
    _packet(tmp_path, "SYM001", "2026-10-23T14:00:00+00:00")   # Fri 10:00 ET
    _packet(tmp_path, "SYM002", "2026-10-21T14:00:00+00:00")   # Wed 10:00 ET: 54 trading hours
    out = index_packets(tmp_path, now=SUNDAY)
    assert [r["symbol"] for r in out["rows"]] == ["SYM001"]
    assert [r["symbol"] for r in out["stale"]] == ["SYM002"]
    assert out["max_age_basis"] == "trading_days"
    assert "weekends and exchange holidays" in out["max_age_label"]


def test_ready_now_still_expires_after_48_trading_hours(tmp_path):
    _packet(tmp_path, "SYM001", "2026-10-23T14:00:00+00:00")
    out = index_packets(tmp_path, now=datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc))  # Tue 11:00 ET
    assert out["rows"] == [] and out["stale"][0]["symbol"] == "SYM001"
