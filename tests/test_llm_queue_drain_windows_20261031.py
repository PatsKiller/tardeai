"""Deep overnight LLM queue drain: operator windows, lane chain, triage, and a dry run that writes nothing.

Operator 2026-10-31: weekends + market holidays drain all day; trading days 21:00-04:00 ET; budget ceilings stay;
DeepSeek only outside its billing peak. Live finding the same day: run_deep_overnight_llm_queue.py --dry-run ran
recover_stale_running (an UPDATE) and committed before reaching the dry-run branch. Hermetic: no DB, no network.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import llm_queue_drain_policy as dp  # noqa: E402

POLICY = dp.load_policy()
TRADING = lambda now: now.astimezone(dp.ET).weekday() < 5  # noqa: E731 - weekday calendar for the tests


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "now,expected,reason",
    [
        (_utc(2026, 10, 31, 18), True, "non_trading_day"),  # Sat 14:00 ET
        (_utc(2026, 11, 2, 20), False, "trading_day_hours"),  # Mon 15:00 EST
        (_utc(2026, 11, 3, 3), True, "night_21-04_et"),  # Mon 22:00 EST
        (_utc(2026, 11, 3, 8, 30), True, "night_21-04_et"),  # Tue 03:30 EST
        (_utc(2026, 11, 3, 9), False, "trading_day_hours"),  # Tue 04:00 EST - window closed
        (_utc(2026, 11, 3, 1, 59), False, "trading_day_hours"),  # Mon 20:59 EST
    ],
)
def test_window_state(now, expected, reason):
    ws = dp.window_state(now, POLICY, is_trading_day=TRADING)
    assert ws == {"unrestricted": expected, "reason": reason}


def test_market_holiday_is_unrestricted_all_day():
    ws = dp.window_state(_utc(2026, 11, 26, 17), POLICY, is_trading_day=lambda n: False)  # Thanksgiving noon
    assert ws["unrestricted"] is True and ws["reason"] == "non_trading_day"


def test_chain_drops_deepseek_inside_its_peak_only():
    peak = dp.provider_chain(_utc(2026, 11, 2, 2), POLICY)  # Mon 02:00 UTC: DeepSeek peak
    off = dp.provider_chain(_utc(2026, 11, 2, 12), POLICY)  # Mon 12:00 UTC: off-peak
    weekend = dp.provider_chain(_utc(2026, 10, 31, 2), POLICY)  # Sat: no peak at all
    assert peak == ["anthropic", "grok", "chatgpt"]
    assert off == weekend == ["anthropic", "grok", "chatgpt", "deepseek-flash"]


def test_triage_keeps_only_strategy_classification_on_symbols_still_tracked():
    sql, params = dp.triage_filter_sql(POLICY)
    assert "ticker_snapshot_daily" in sql and params == ["strategy_classification", 14]


import run_deep_overnight_llm_queue as w  # noqa: E402


class _Res:
    text, lane = "ok", "grok"

    def provenance_line(self):
        return "served by grok (substituted)"


def test_call_cloud_routes_through_the_budget_gated_chain(monkeypatch):
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw)
        return _Res()

    text, _rt, model = w.call_cloud("p", POLICY, fallback=fake, now=_utc(2026, 11, 2, 2))
    assert (text, model) == ("ok", "cloud:grok")
    assert seen["lane"] == "anthropic" and seen["extra_lanes"] == ["grok", "chatgpt"]
    assert seen["allow_paid"] is False and seen["process_id"] == "deep_overnight_llm_drain"
    w.call_cloud("p", POLICY, fallback=fake, now=_utc(2026, 11, 2, 12))
    assert seen["allow_paid"] is True and seen["extra_lanes"][-1] == "deepseek-flash"


def test_call_cloud_failure_is_a_failed_job_not_a_crash():
    def boom(prompt, **kw):
        raise RuntimeError("COST_CAP_EXCEEDED: process cap")

    assert w.call_cloud("p", POLICY, fallback=boom, now=_utc(2026, 10, 31, 18))[0] is None


class _Cur:
    def __init__(self, log):
        self.log, self.description = (
            log,
            [
                ("id",),
                ("job_type",),
                ("symbol",),
                ("trade_id",),
                ("journal_id",),
                ("priority_tier",),
                ("priority_score",),
                ("reason_codes",),
            ],
        )

    def execute(self, sql, params=None):
        self.log.append(sql.strip().split()[0].upper())

    def fetchall(self):
        return [(1, "strategy_classification", "AAPL", None, None, "P1", 50, ["x"])]


class _Conn:
    def __init__(self, log):
        self.log = log

    def cursor(self):
        return _Cur(self.log)

    def commit(self):
        self.log.append("COMMIT")

    def close(self):
        pass


def test_dry_run_writes_nothing(monkeypatch):
    log: list[str] = []
    monkeypatch.setattr(w, "get_db_connection", lambda: _Conn(log))
    monkeypatch.setattr(w, "log", lambda m: None)
    monkeypatch.setattr(sys, "argv", ["x", "--dry-run", "--triaged", "--limit", "5"])
    w.main()
    assert log == ["SELECT"]  # no UPDATE (recover_stale_running), no COMMIT


def test_drain_window_refuses_outside_the_window_before_touching_the_db(monkeypatch):
    monkeypatch.setattr(w, "get_db_connection", lambda: pytest.fail("connected outside the window"))
    monkeypatch.setattr(w, "log", lambda m: None)
    monkeypatch.setattr(dp, "window_state", lambda now=None, policy=None, **k: {"unrestricted": False, "reason": "t"})
    monkeypatch.setattr(sys, "argv", ["x", "--drain-window", "--route", "cloud"])
    w.main()
