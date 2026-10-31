"""Pre-market stack dead-man (DSN-20261031-market-risk-engine-P0-T4).

Fixture = the morning of 2026-10-30: the premarket pipeline receipt is still 10-29's (ENOSPC at 05:45) and no
morning brief event exists (API dead at 07:30). Pins: silent before the deadlines; P1 after them; one page then
repeats every repeat_minutes up to max_repeats; dry-run sends nothing and writes no state; weekend silent;
unknown ledger is reported as unknown, never as zero; a fresh receipt + brief row = no finding (positive control).
Hermetic: tmp state root, telegram_alert and db_adapter stubbed via sys.modules, TRADE_AI_CI=1.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_premarket_delivery as cpd  # noqa: E402

ET = ZoneInfo("America/New_York")
CFG = cpd.load_config()


def _et(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=ET)


RECEIPT_1029 = {
    "schema": "PipelineRun@v1",
    "pipeline": "premarket",
    "stage": "premarket",
    "run_ts_utc": "2026-10-29T10:10:11Z",
    "started_at": "2026-10-29T09:45:02Z",
    "overall_status": "degraded",
    "receipt_complete": True,
    "step_count": 37,
    "expected_step_count": 37,
}
RECEIPT_1030 = dict(RECEIPT_1029, run_ts_utc="2026-10-30T10:12:00Z", started_at="2026-10-30T09:45:01Z")


def test_config_carries_every_threshold():
    for k in (
        "pipeline_due_et",
        "brief_due_et",
        "brief_match",
        "window_end_et",
        "repeat_minutes",
        "max_repeats",
        "pipeline_receipt_rel",
        "state_rel",
        "lane_id",
    ):
        assert k in CFG, k


def test_silent_before_the_pipeline_deadline():
    assert cpd.evaluate(_et("2026-10-30T06:40:00"), RECEIPT_1029, 0, CFG) == []


def test_the_1030_morning_pages_pipeline_then_brief():
    at_0650 = cpd.evaluate(_et("2026-10-30T06:50:00"), RECEIPT_1029, 0, CFG)
    assert [f["key"] for f in at_0650] == ["PREMARKET_PIPELINE_MISSING"]
    assert at_0650[0]["priority"] == "P1" and "2026-10-29" in at_0650[0]["detail"]
    at_0750 = cpd.evaluate(_et("2026-10-30T07:50:00"), RECEIPT_1029, 0, CFG)
    assert [f["key"] for f in at_0750] == ["PREMARKET_PIPELINE_MISSING", "MORNING_BRIEF_NOT_DELIVERED"]
    assert all(f["priority"] == "P1" for f in at_0750)


def test_a_failed_receipt_is_a_finding_but_degraded_is_not():
    failed = dict(RECEIPT_1030, overall_status="failed")
    assert [f["key"] for f in cpd.evaluate(_et("2026-10-30T07:00:00"), failed, 0, CFG)] == ["PREMARKET_PIPELINE_FAILED"]
    assert cpd.evaluate(_et("2026-10-30T07:00:00"), RECEIPT_1030, 0, CFG) == []


def test_positive_control_fresh_receipt_and_brief_row_is_quiet():
    assert cpd.evaluate(_et("2026-10-30T08:00:00"), RECEIPT_1030, 1, CFG) == []


def test_unknown_ledger_is_reported_as_unknown_not_zero():
    out = cpd.evaluate(_et("2026-10-30T08:00:00"), RECEIPT_1030, None, CFG)
    assert [f["key"] for f in out] == ["MORNING_BRIEF_CHECK_UNAVAILABLE"] and out[0]["priority"] == "P2"


def test_silent_after_the_window_closes():
    assert cpd.evaluate(_et("2026-10-30T12:05:00"), RECEIPT_1029, 0, CFG) == []


def test_repeat_cadence_and_cap():
    f = {"key": "PREMARKET_PIPELINE_MISSING", "priority": "P1", "detail": "x"}
    state: dict = {}
    t0 = _et("2026-10-30T06:50:00")
    assert cpd.due_to_send(f, state, t0, CFG)
    cpd.mark_sent(f, state, t0)
    assert not cpd.due_to_send(f, state, _et("2026-10-30T07:20:00"), CFG), "inside repeat_minutes: no resend"
    t = t0
    for i in range(int(CFG["max_repeats"])):
        t = t.replace(hour=t.hour + 1)
        assert cpd.due_to_send(f, state, t, CFG), f"repeat {i + 1} due"
        cpd.mark_sent(f, state, t)
    t = t.replace(hour=t.hour + 1)
    assert not cpd.due_to_send(f, state, t, CFG), "max_repeats reached"


@pytest.fixture
def stubs(monkeypatch, tmp_path):
    sent = []
    tg = types.ModuleType("telegram_alert")
    tg.send_telegram = lambda msg, **k: sent.append({"msg": msg, **k}) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    ms = types.ModuleType("market_session")
    ms.is_trading_day = lambda now=None: now.weekday() < 5
    monkeypatch.setitem(sys.modules, "market_session", ms)
    db = types.ModuleType("db_adapter")
    db._execute = lambda sql, params=None, fetch=None: [{"n": 0}]
    monkeypatch.setitem(sys.modules, "db_adapter", db)
    receipts = []
    llr = types.ModuleType("lib.lane_last_receipt")
    llr.write_lane_receipt = lambda lane_id, **k: receipts.append({"lane_id": lane_id, **k})
    monkeypatch.setitem(sys.modules, "lib.lane_last_receipt", llr)
    root = tmp_path / "persistent"
    (root / "data" / "runtime").mkdir(parents=True)
    (root / CFG["pipeline_receipt_rel"]).write_text(json.dumps(RECEIPT_1029))
    return {"sent": sent, "root": root, "receipts": receipts}


def test_main_pages_p1_once_then_holds_and_writes_the_receipt(stubs):
    rc = cpd.main(["--now", "2026-10-30T07:50:00", "--state-root", str(stubs["root"]), "--json"])
    assert rc == 3
    assert len(stubs["sent"]) == 1
    call = stubs["sent"][0]
    assert call["priority"] == "P1" and call["dedupe_minutes"] == 0 and call["producer"] == "check_premarket_delivery"
    assert "PREMARKET_PIPELINE_MISSING" in call["msg"] and "MORNING_BRIEF_NOT_DELIVERED" in call["msg"]
    state = json.loads((stubs["root"] / CFG["state_rel"]).read_text())
    assert set(state) == {"2026-10-30:PREMARKET_PIPELINE_MISSING", "2026-10-30:MORNING_BRIEF_NOT_DELIVERED"}
    rc2 = cpd.main(["--now", "2026-10-30T08:05:00", "--state-root", str(stubs["root"])])
    assert rc2 == 3 and len(stubs["sent"]) == 1, "still a finding, but no resend inside repeat_minutes"
    assert (
        stubs["receipts"] and stubs["receipts"][-1]["lane_id"] == CFG["lane_id"] and stubs["receipts"][-1]["ok"] is True
    )


def test_dry_run_sends_nothing_and_writes_no_state(stubs, capsys):
    rc = cpd.main(["--now", "2026-10-30T07:50:00", "--state-root", str(stubs["root"]), "--dry-run"])
    assert rc == 3
    assert stubs["sent"] == [] and stubs["receipts"] == []
    assert not (stubs["root"] / CFG["state_rel"]).exists()
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "PREMARKET_PIPELINE_MISSING" in out


def test_weekend_is_silent(stubs):
    rc = cpd.main(["--now", "2026-11-01T08:00:00", "--state-root", str(stubs["root"])])  # Sunday
    assert rc == 0 and stubs["sent"] == []


def test_delivery_failure_lands_on_the_receipt(stubs, monkeypatch):
    def boom(msg, **k):
        raise RuntimeError("transport down")

    sys.modules["telegram_alert"].send_telegram = boom
    rc = cpd.main(["--now", "2026-10-30T07:50:00", "--state-root", str(stubs["root"])])
    assert rc == 3
    rec = stubs["receipts"][-1]
    assert rec["ok"] is False and "transport down" in rec["summary"]["delivery_error"]
    assert not (stubs["root"] / CFG["state_rel"]).exists(), "an undelivered page is not marked sent"
