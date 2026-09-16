"""A declared vector chain that never runs is no chain. This monitor measures the
receipts against the gaps, and this file proves the monitor fires.

Three findings, each pure so it runs with no host state:

    OPEN_NO_ATTEMPT   a gap queued/registered >2h ago with no receipt
    VECTOR_FAILING    a vector with >=3 error receipts today
    RETIRED_RAN       a receipt whose provider is retired and did not refuse

RETIRED_RAN must be 0: the catalyst chain fell through four dead slots for seven
weeks because nothing reported that a retired provider was being called.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_gap_resolution as cgr  # noqa: E402

# Declares to the C1 alarm gate that this file's send_telegram site is exercised.
COVERS = ["scripts/check_gap_resolution.py"]

NOW = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
RETIRED = frozenset({"fmp", "finnhub", "polygon", "newsapi"})


def _ago(h: float) -> str:
    return (NOW - timedelta(hours=h)).isoformat()


# ── the findings ──────────────────────────────────────────────────────────────


def test_a_gap_open_more_than_two_hours_with_no_receipt_is_reported():
    queue = [{"gap_id": "g1", "domain": "quote_price", "subject": "WMT", "ts": _ago(3), "status": "open"}]
    out = cgr.open_gaps(queue, [], [], now=NOW)
    assert [g["gap_id"] for g in out] == ["g1"]
    assert out[0]["age_hours"] == 3.0 and out[0]["origin"] == "gap_queue"


def test_a_gap_with_a_receipt_is_not_reported_whatever_the_outcome():
    queue = [{"gap_id": "g1", "domain": "quote_price", "subject": "WMT", "ts": _ago(3), "status": "open"}]
    receipts = [{"gap_id": "g1", "vector": "refresh_producer", "outcome": "no_answer"}]
    assert cgr.open_gaps(queue, [], receipts, now=NOW) == []


def test_a_young_gap_is_not_reported_yet():
    queue = [{"gap_id": "g1", "domain": "quote_price", "subject": "WMT", "ts": _ago(1.5), "status": "open"}]
    assert cgr.open_gaps(queue, [], [], now=NOW) == []


def test_an_open_research_gap_counts_too_and_a_resolved_one_does_not():
    research = [
        {"gap_id": "r1", "symbol": "WMT", "status": "OPEN", "created_at": _ago(5)},
        {"gap_id": "r2", "symbol": "TGT", "status": "RESOLVED_FREE", "created_at": _ago(5)},
    ]
    out = cgr.open_gaps([], research, [], now=NOW)
    assert [g["gap_id"] for g in out] == ["r1"] and out[0]["origin"] == "research_gaps"


def test_a_vector_with_three_errors_today_is_failing_and_two_is_not():
    rows = [{"vector": "governed_search", "outcome": "error", "started": _ago(i)} for i in range(3)]
    rows += [{"vector": "backup_provider", "outcome": "error", "started": _ago(1)}] * 2
    rows += [{"vector": "hermes_research", "outcome": "no_answer", "started": _ago(1)}] * 5
    out = cgr.failing_vectors(rows, now=NOW)
    assert out == [{"vector": "governed_search", "errors_today": 3}]


def test_yesterdays_errors_do_not_count():
    rows = [{"vector": "v", "outcome": "error", "started": _ago(30)}] * 5
    assert cgr.failing_vectors(rows, now=NOW) == []


def test_a_retired_provider_that_ran_is_reported_and_a_refusal_is_not():
    receipts = [
        {"gap_id": "g", "vector": "backup_provider", "provider": "fmp", "outcome": "retired_skipped", "started": _ago(1)},
        {"gap_id": "g", "vector": "backup_provider", "provider": "fmp", "outcome": "answered", "started": _ago(1)},
        {"gap_id": "g", "vector": "refresh_producer", "provider": "yahoo", "outcome": "answered", "started": _ago(1)},
    ]
    out = cgr.retired_ran(receipts, RETIRED)
    assert len(out) == 1 and out[0]["provider"] == "fmp" and out[0]["outcome"] == "answered"


def test_collect_reads_injected_ledgers_and_counts(tmp_path):
    r = tmp_path / "receipts.jsonl"
    q = tmp_path / "queue.jsonl"
    g = tmp_path / "gaps.jsonl"
    r.write_text(json.dumps({"gap_id": "g1", "vector": "backup_provider", "provider": "polygon",
                             "outcome": "no_answer", "started": _ago(1)}) + "\n")
    q.write_text(json.dumps({"gap_id": "g2", "domain": "d", "subject": "S", "ts": _ago(4), "status": "open"}) + "\n")
    g.write_text("")
    # denials=[] for the same reason the other three ledgers are injected: an
    # un-injected ledger falls back to the PRODUCTION one, and this test's exact
    # counts would then depend on the real machine's refusals on the real date.
    rep = cgr.collect(now=NOW, receipts_path=r, queue_path=q, research_path=g,
                      retired=RETIRED, denials=[])
    assert rep["schema"] == cgr.SCHEMA
    assert rep["receipts"] == 1 and rep["queued_gaps"] == 1
    assert rep["finding_count"] == 2
    assert rep["findings"]["RETIRED_RAN"][0]["provider"] == "polygon"
    assert rep["findings"]["OPEN_NO_ATTEMPT"][0]["gap_id"] == "g2"


def test_missing_ledgers_are_an_empty_report_not_a_crash(tmp_path):
    rep = cgr.collect(now=NOW, receipts_path=tmp_path / "a", queue_path=tmp_path / "b",
                      research_path=tmp_path / "c", retired=RETIRED, denials=[])
    assert rep["finding_count"] == 0


# ── the alarm ─────────────────────────────────────────────────────────────────


class _Captured:
    def __init__(self):
        self.sent = []

    def send_telegram(self, message, **kwargs):
        self.sent.append(message)
        return True


@pytest.fixture
def wired(monkeypatch, tmp_path):
    cap = _Captured()
    mod = type(sys)("telegram_alert")
    mod.send_telegram = cap.send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(cgr, "STATE_PATH", tmp_path / "state.json")
    return cap


def _report(**findings):
    f = {"OPEN_NO_ATTEMPT": [], "VECTOR_FAILING": [], "RETIRED_RAN": []}
    f.update(findings)
    return {"schema": cgr.SCHEMA, "findings": f, "finding_count": sum(len(v) for v in f.values())}


def test_alarm_fires_names_the_retired_provider_and_routes_as_an_interrupt(wired):
    cgr._alert(_report(RETIRED_RAN=[{"gap_id": "g", "vector": "backup_provider", "provider": "fmp",
                                      "outcome": "answered", "started": _ago(1)}]))
    assert len(wired.sent) == 1
    body = wired.sent[0]
    assert "RETIRED provider RAN" in body and "fmp" in body and "backup_provider" in body
    assert body.startswith(cgr.SENTINEL), "the sentinel routes this, not the wording"

    from telegram_alert_router import classify_alert

    assert classify_alert(body) == "P0_INTERRUPT"


def test_alarm_names_unattended_gaps_and_failing_vectors(wired):
    cgr._alert(_report(
        OPEN_NO_ATTEMPT=[{"gap_id": "g", "domain": "quote_price", "subject": "WMT", "age_hours": 3.0, "origin": "gap_queue"}],
        VECTOR_FAILING=[{"vector": "governed_search", "errors_today": 4}],
    ))
    body = wired.sent[0]
    assert "quote_price:WMT" in body and "governed_search: 4 errors" in body


def test_an_unchanged_finding_set_stays_silent(wired):
    rep = _report(VECTOR_FAILING=[{"vector": "v", "errors_today": 3}])
    cgr.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cgr.STATE_PATH.write_text(json.dumps({"fingerprint": cgr.fingerprint(rep)}))
    cgr._alert(rep)
    assert wired.sent == []


def test_recovery_is_reported_once(wired):
    cgr.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cgr.STATE_PATH.write_text(json.dumps({"fingerprint": {"vector:v": "VECTOR_FAILING"}}))
    cgr._alert(_report())
    assert len(wired.sent) == 1 and "✅" in wired.sent[0] and wired.sent[0].startswith(cgr.SENTINEL)
    cgr._alert(_report())
    assert len(wired.sent) == 1


def test_a_send_failure_does_not_advance_state(monkeypatch, tmp_path, capsys):
    mod = type(sys)("telegram_alert")

    def _boom(message, **kwargs):
        raise RuntimeError("unreachable")

    mod.send_telegram = _boom
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(cgr, "STATE_PATH", tmp_path / "s.json")
    cgr._alert(_report(VECTOR_FAILING=[{"vector": "v", "errors_today": 3}]))
    assert "FAILED to send" in capsys.readouterr().err
    assert not cgr.STATE_PATH.exists()


# ── the schedule is declared, not installed ───────────────────────────────────


def test_unit_files_exist_and_carry_the_required_settings():
    svc = (ROOT / "config/systemd/user/tradeai-gap-resolution.service").read_text()
    tmr = (ROOT / "config/systemd/user/tradeai-gap-resolution.timer").read_text()
    assert "scripts/check_gap_resolution.py --alert" in svc
    assert "SuccessExitStatus=0 1" in svc
    assert "WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild" in svc
    assert "OnCalendar=*-*-* *:07,37:00" in tmr
    assert "Persistent=true" in tmr


def test_lane_registry_declares_the_lane_with_a_durable_output_signal():
    reg = json.loads((ROOT / "config/lane_registry.json").read_text())
    lane = next(l for l in reg["lanes"] if l["lane_id"] == "gap-resolution-audit")
    assert lane["scheduler"] == {"kind": "systemd", "expression": "tradeai-gap-resolution.timer"}
    assert lane["output_signal"] == {"kind": "file_mtime", "path": f"data/runtime/{cgr.RECEIPT_NAME}"}
    assert lane["expected_cadence_hours"] == 0.5 and lane["state"] == "ACTIVE"


def test_the_monitor_declares_its_scheduler_for_the_dark_contract_gate():
    assert "tradeai-gap-resolution.timer" in cgr.SCHEDULED_ENTRYPOINT
