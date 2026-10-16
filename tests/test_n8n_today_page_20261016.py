"""What n8n did today — read model + API route + CC tab (operator 2026-10-16: "how do i know whats n8n did").

Temp state roots only: no network, no DB, no n8n, no send.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import n8n_today as nt  # noqa: E402

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)  # 11:00 ET


def _receipt(root: Path, lane: str, mode: str, slot: str, **doc) -> None:
    d = root / "data" / "runtime" / "n8n_runs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"d:{lane}:{mode}:{slot}.json").write_text(json.dumps({"run_id": f"d:{lane}:{mode}:{slot}", **doc}))


def _jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _fixture(root: Path) -> Path:
    _receipt(root, "heartbeat-watch", "live", "20261016T1000", state="RUN_DONE")
    _receipt(root, "heartbeat-watch", "live", "20261015T1000", state="RUN_DONE")  # yesterday: ignored
    _receipt(root, "hermes-momentum-catalyst-scalp", "live", "20261016T1025", state="RUN_SKIPPED_LOCK",
             reason="flock_held")
    _receipt(root, "hermes-momentum-catalyst-scalp", "live", "20261016T0925", state="RUN_SKIPPED_LOCK")
    _receipt(root, "daily-incubator-refresh", "live", "20261016T0815", state="RUN_FAILED", reason="exit_1",
             exit_code=1)
    _receipt(root, "trade-ai-scalp-live", "dry_run", "20261016T0935", state="RUN_DONE")
    _jsonl(root / "data/runtime/n8n_relay/relay_log.jsonl", [
        {"at": "2026-10-16T03:59:00+00:00", "state": "REQUESTED", "lane_id": "x"},  # before ET midnight
        {"at": "2026-10-16T04:10:00+00:00", "state": "REQUESTED", "lane_id": "heartbeat-watch"},
        {"at": "2026-10-16T12:00:00+00:00", "op": "event", "state": "ACCEPTED", "lane_id": "n8n-workflow-error",
         "workflow_id": "tradeai-dispatcher", "node": "Stop And Error", "execution_id": "1"},
    ])
    _jsonl(root / "data/runtime/n8n_diagnoses/diagnoses.jsonl", [
        {"at": "2026-10-15T20:00:00+00:00", "lane": "old", "event_type": "NO_OUTPUT", "decision": {"kind": "escalate"}},
        {"at": "2026-10-16T14:00:00+00:00", "lane": "finviz-screener-runner", "event_type": "NO_OUTPUT",
         "cause": "process_daily_cap", "decision": {"kind": "escalate", "priority": "P2"}},
        {"at": "2026-10-16T14:05:00+00:00", "lane": "heartbeat-watch", "event_type": "RUN_FAILED",
         "decision": {"kind": "retry"}, "remediation_run_id": "d:heartbeat-watch:live:20261016T1005"},
    ])
    cut = root / "data/runtime/n8n_cutover"
    cut.mkdir(parents=True)
    (cut / "research-insight-extractor-20261016T130000Z-cutover.json").write_text(json.dumps(
        {"lane_id": "research-insight-extractor", "action": "cutover", "applied": True,
         "at": "2026-10-16T13:00:00+00:00", "scheduler_before": {"kind": "cron"}}))
    (cut / "old-lane-20261013T130000Z-cutover.json").write_text(json.dumps(
        {"lane_id": "old-lane", "action": "cutover", "applied": True, "at": "2026-10-13T13:00:00+00:00"}))
    return root


def test_runs_failures_lock_skips(tmp_path):
    d = nt.build(_fixture(tmp_path), NOW)
    assert d["schema"] == "N8nToday@v1" and d["day"] == "2026-10-16" and d["status"] == "OK"
    assert d["runs"]["by_mode_state"]["live"] == {"RUN_DONE": 1, "RUN_SKIPPED_LOCK": 2, "RUN_FAILED": 1}
    assert d["runs"]["by_mode_state"]["dry_run"] == {"RUN_DONE": 1}
    assert d["failures"] == [{"lane": "daily-incubator-refresh", "mode": "live", "slot": "20261016T0815",
                              "state": "RUN_FAILED", "reason": "exit_1", "exit_code": 1, "finished_at": None,
                              "run_id": "d:daily-incubator-refresh:live:20261016T0815"}]
    assert d["lock_skips"] == [{"lane": "hermes-momentum-catalyst-scalp", "mode": "live", "count": 2}]


def test_relay_diagnoses_heals_today_only(tmp_path):
    d = nt.build(_fixture(tmp_path), NOW)
    assert d["relay"]["counts"] == {"run:REQUESTED": 1, "event:ACCEPTED": 1}
    assert d["relay"]["workflow_errors"][0]["workflow_id"] == "tradeai-dispatcher"
    assert d["diagnoses"]["total"] == 1 and d["diagnoses"]["by_lane"] == {"finviz-screener-runner": 1}
    assert [h["lane"] for h in d["heals"]] == ["heartbeat-watch"]


def test_cutovers_today(tmp_path):
    d = nt.build(_fixture(tmp_path), NOW)
    got = {(c["lane"], c["source"]) for c in d["cutovers_today"]}
    assert ("research-insight-extractor", "cutover_receipt") in got
    assert ("hermes-momentum-catalyst-scalp", "first_live_receipt_today") in got
    assert ("daily-incubator-refresh", "first_live_receipt_today") in got
    assert not any(c["lane"] in ("old-lane", "heartbeat-watch") for c in d["cutovers_today"])


def test_empty_root_is_honest(tmp_path):
    d = nt.build(tmp_path, NOW)
    assert d["status"] == "NO_RECEIPTS" and d["runs"]["totals"] == {"live": 0, "dry_run": 0}
    assert d["failures"] == [] and d["heals"] == [] and d["cutovers_today"] == []


def test_cache_hits_until_inputs_change(tmp_path):
    root = _fixture(tmp_path)
    assert nt.get_n8n_today(root, NOW)["cache"] == "MISS"
    assert nt.get_n8n_today(root, NOW)["cache"] == "HIT"
    assert nt.get_n8n_today(root, NOW, ttl_s=0)["cache"] == "MISS"


def test_tail_read_is_bounded(tmp_path):
    p = tmp_path / "log.jsonl"
    _jsonl(p, [{"at": f"2026-10-16T05:{i % 60:02d}:00+00:00", "pad": "x" * 200} for i in range(500)])
    rows, truncated = nt.tail_rows_since(p, datetime(2026, 10, 16, 4, tzinfo=timezone.utc), max_bytes=4096,
                                         block=1024)
    assert truncated and 0 < len(rows) < 500
    rows, truncated = nt.tail_rows_since(p, datetime(2026, 10, 16, 4, tzinfo=timezone.utc), block=1024)
    assert not truncated and len(rows) == 500


def test_api_route_is_read_only_and_wired():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    i = src.index('base_path == "/api/v2/coordination/n8n-today"')
    block = src[i:i + 700]
    assert "get_n8n_today" in block and '405, {"ok": False, "error": "read_only"}' in block


def test_cc_tab_wired():
    page = (ROOT / "apps/command-center-v3/src/pages/CoordinationPage.tsx").read_text()
    assert "import N8nToday from './N8nToday'" in page and "today: 'n8n today'" in page
    comp = (ROOT / "apps/command-center-v3/src/pages/N8nToday.tsx").read_text()
    assert "/api/v2/coordination/n8n-today" in comp and "designTokens" in comp
