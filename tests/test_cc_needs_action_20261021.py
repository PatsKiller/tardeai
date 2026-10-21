"""Command Center: hidden failures surfaced + the "Needs action" inbox (audit 2026-10-21).

The audit found real failures on pages nobody opens, or on none:
* the Communications strip said ``failed 0`` while Coordination → Events outbox showed ~149 telegram_outbox
  "failed" sends a day. Every one was a reports_archive row: ``report_capture.archive_message(suppressed=True)``
  stores ``ok = not suppressed``, so a message HELD for the digest was labelled a failed send. They are now
  ``held``; real Telegram failures are a separate figure on the strip;
* the overnight LLM queue (1,928 pending / 268 failed / 0 done) had no page;
* data plausibility had no API; the receipt carried no per-rule rows;
* pipeline_runs failures were behind 100 finviz successes, and /api/v2/pipeline-health ``stats`` was always ``{}``
  (the query filtered on ``run_type``; the column is ``run_label``).

GET /api/v2/needs-action probes every source independently; an unreadable source is an item, never omitted.
Hermetic: stub rows / fake cursors / tmp state roots. No database, no network, no systemctl, no send.
"""
from __future__ import annotations

import json
import sys
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import notification_outbox_projection as OP  # noqa: E402
from scripts.lib import needs_action as NA  # noqa: E402
from scripts.lib import data_plausibility_view as DPV  # noqa: E402
from scripts.lib import pipeline_failures as PF  # noqa: E402
from scripts import communications_portal as CP  # noqa: E402

NOW = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)


# ── A1: reports_archive holds are not failed sends ──────────────────────────────────────────────────────────────


def _outbox_rows(tg):
    def q(sql, params):
        if "GROUP BY" in sql:
            assert "reports_archive" in sql, "the SQL state must separate archive holds"
            b = Counter(OP.tg_state(r[5], r[6]) for r in tg)
            return [("telegram_outbox", st, n) for st, n in b.items()]
        return [] if sql.startswith("SELECT outbox_id") else tg
    return q


def test_archive_rows_are_held_not_failed_and_real_failures_stay_failed():
    tg = [(1, NOW - timedelta(minutes=1), "notification_intent_p3:process_reaper", "x", 139, False, "reports_archive"),
          (2, NOW - timedelta(minutes=2), "trade_critique", "y", 900, False, "reports_archive"),
          (3, NOW - timedelta(minutes=3), "alert", "z", 5000, False, "telegram"),
          (4, NOW - timedelta(minutes=4), "brief", "w", 100, True, "telegram")]
    m = OP.project_outbox(_outbox_rows(tg), hours=24, now=NOW)
    assert m["counts"]["telegram_outbox"] == {"held": 2, "failed": 1, "sent": 1}
    by_id = {i["id"]: i for i in m["items"]}
    assert by_id["1"]["state"] == "held" and "held for digest" in by_id["1"]["reason"]
    assert by_id["3"]["state"] == "failed" and by_id["3"]["reason"].startswith("ok=false")
    assert OP.tg_state(None, "reports_archive") == "unknown"
    # held is a known state: 20 held rows and nothing sent is still "silent senders" (not masked as unknown)
    many = [(i, NOW - timedelta(minutes=i), "p3", "t", 10, False, "reports_archive") for i in range(1, 22)]
    assert [f["item"] for f in OP.anomalies(OP.project_outbox(_outbox_rows(many), hours=24, now=NOW))] == ["silent_senders"]


class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)
        if "telegram_outbox" in sql:
            if self.conn.tg_error:
                raise RuntimeError("relation \"telegram_outbox\" does not exist")
            self._rows = self.conn.tg_rows
        else:
            self.description = [(c,) for c in ("unsettled", "failed", "reaped_unclaimed", "total",
                                               "oldest_unsettled_at", "as_of")]
            self._row = (0, 0, 6, 2015, None, NOW)

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, tg_rows=(), tg_error=False):
        self.tg_rows, self.tg_error, self.sql, self.rolled_back = list(tg_rows), tg_error, [], 0

    def cursor(self):
        return _Cur(self)

    def rollback(self):
        self.rolled_back += 1


def test_delivery_summary_carries_telegram_outbox_failures_as_their_own_figure(monkeypatch):
    conn = _Conn(tg_rows=[("reports_archive", 149, 0), ("telegram", 3, 18), ("telegram_document", 1, 2)])
    monkeypatch.setattr(CP, "_deliveries_db_conn", lambda: conn)
    s = CP.delivery_summary()
    assert s["status"] == "OK" and s["failed"] == 0          # the deliveries ledger is unchanged
    assert s["telegram_outbox_failed_24h"] == 4
    assert s["telegram_outbox_failed_24h_by_channel"] == {"telegram": 3, "telegram_document": 1}
    assert s["telegram_outbox_held_24h"] == 149 and s["telegram_outbox_sent_24h"] == 20


def test_unreadable_telegram_outbox_is_null_with_reason_never_zero(monkeypatch):
    conn = _Conn(tg_error=True)
    monkeypatch.setattr(CP, "_deliveries_db_conn", lambda: conn)
    s = CP.delivery_summary()
    assert s["status"] == "OK" and s["total"] == 2015       # the main summary survives
    assert s["telegram_outbox_failed_24h"] is None and "telegram_outbox" in s["telegram_outbox_error"]
    assert conn.rolled_back == 1
    monkeypatch.setattr(CP, "_deliveries_db_conn", lambda: None)
    assert CP.delivery_summary()["telegram_outbox_failed_24h"] is None


# ── A3: data plausibility ──────────────────────────────────────────────────────────────────────────────────────


def test_monitor_receipt_carries_violations_and_per_rule_rows():
    from scripts import data_plausibility_monitor as M
    results = [{"table": "t", "column": "a", "status": "VIOLATION", "severity": "BLOCK", "violations": 4, "total": 10,
                "detail": "pct > 100", "samples": [101.0]},
               {"table": "t", "column": "b", "status": "OK", "severity": "WARN", "violations": 0, "total": 10,
                "detail": "", "samples": []}]
    d = M.receipt_detail(results, [results[0]])
    assert d["blocking_items"] == ["t.a"] and d["violations"] == 1 and d["blocking"] == 1
    assert len(d["results"]) == 2 and "samples" not in d["results"][0]


def _write(root: Path, doc) -> None:
    p = root / DPV.RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)


def test_plausibility_view_states(tmp_path):
    assert DPV.load_view(tmp_path, now=NOW)["status"] == "NO_RECEIPT"
    _write(tmp_path, "{not json")
    assert DPV.load_view(tmp_path, now=NOW)["status"] == "UNAVAILABLE"
    _write(tmp_path, {"ran_at": (NOW - timedelta(hours=2)).isoformat(), "checked": 12, "off": 0, "blocking_items": []})
    old = DPV.load_view(tmp_path, now=NOW)
    assert old["status"] == "OK" and old["checked"] == 12 and old["blocking"] == 0 and old["rules"] is None
    assert "predates" in old["note"]
    _write(tmp_path, {"ran_at": (NOW - timedelta(hours=1)).isoformat(), "checked": 2, "off": 1, "blocking": 1,
                      "violations": 1, "blocking_items": ["t.a"],
                      "results": [{"table": "t", "column": "b", "status": "OK", "severity": "WARN"},
                                  {"table": "t", "column": "a", "status": "VIOLATION", "severity": "BLOCK"}]})
    v = DPV.load_view(tmp_path, now=NOW)
    assert v["status"] == "BLOCK" and v["rules"][0]["column"] == "a" and v["violations"] == 1
    _write(tmp_path, {"ran_at": (NOW - timedelta(hours=30)).isoformat(), "checked": 2, "off": 0})
    assert DPV.load_view(tmp_path, now=NOW)["status"] == "STALE"


# ── A4: pipeline failures ──────────────────────────────────────────────────────────────────────────────────────


def test_pipeline_failures_grouped_and_unreadable_is_unavailable():
    rows = [{"pipeline_key": "scalp_scan", "failed": 3, "last_failed_at": NOW, "last_error": "HTTP 429", "zombie_cleared": 0},
            ("eod_report", 1, NOW - timedelta(hours=3), None, 1)]
    m = PF.project(lambda s, p: rows, now=NOW)
    assert m["status"] == "OK" and m["pipelines_failing"] == 2 and m["failed_runs"] == 4
    assert m["pipelines"][0] == {"pipeline": "scalp_scan", "failed": 3, "last_failed_at": NOW.isoformat(),
                                 "last_error": "HTTP 429", "zombie_cleared": 0}
    assert m["pipelines"][1]["zombie_cleared"] == 1
    assert "NULLIF(NULLIF(summary->>'errors', '[]'), '')" in PF.SQL     # "[]" is no error text
    none = PF.project(lambda s, p: None, now=NOW)
    assert none["status"] == "UNAVAILABLE" and none["pipelines"] is None and none["failed_runs"] is None
    boom = PF.project(lambda s, p: (_ for _ in ()).throw(RuntimeError("down")), now=NOW)
    assert boom["status"] == "UNAVAILABLE" and "down" in boom["note"]
    assert PF.project(lambda s, p: [], now=NOW)["pipelines"] == []


def test_pipeline_health_stats_filter_on_existing_column():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    start = src.index("def _pipeline_health():")
    body = src[start:src.index("\ndef ", start + 10)]
    assert "run_type='retry'" not in body and "run_label='retry'" in body


# ── B: needs-action ───────────────────────────────────────────────────────────────────────────────────────────


GOOD = {
    "health": lambda: {"ok": True, "data": {"captured_at": NOW.isoformat(), "findings": [
        {"severity": "critical", "category": "risk_protection", "type": "orphaned_stops", "message": "1 orphaned stop",
         "cta": {"route": "/v3/risk"}},
        {"severity": "critical", "category": "pipeline_freshness", "type": "pipeline_failures", "message": "1 failure"},
        {"severity": "warning", "message": "ignored"}]}},
    "systemd": lambda: {"failed_units": [{"unit": "tradeai-portfolio-backup-cadence.service", "sub": "failed"}]},
    "n8n": lambda: {"status": "PARTIAL", "live_lane_states": {"identity-sweep-stage0": {"RUN_FAILED": 2},
                                                             "registry-runtime-truth": {"RUN_FAILED": 1, "RUN_DONE": 5}},
                    "failures": [{"lane": "identity-sweep-stage0", "mode": "live", "reason": "exit_1",
                                  "finished_at": NOW.isoformat(), "run_id": "d:x"}],
                    "relay": {"workflow_errors": [{"workflow_id": "tradeai-dispatcher", "at": f"2026-10-21T0{i}:00:00Z",
                                                   "node": "Stop And Error"} for i in range(4)]}},
    "approvals": lambda: {"status": "OK", "sources": {"packages": {"status": "OK"}},
                          "expiring": [{"kind": "grant", "id": "g1"}],
                          "items": [{"kind": "grant", "id": "g1", "scope": "release-write", "state": "ACTIVE", "ttl_min_left": 12},
                                    {"kind": "package", "id": "p1", "scope": "wave", "state": "OPEN", "items_pending": 2},
                                    {"kind": "grant", "id": "g0", "scope": "old", "state": "EXPIRED",
                                     "expires_at": (NOW - timedelta(days=20)).isoformat()}]},
    "queue": lambda: {"ok": True, "data": {"measured": True, "pending": 1928, "failed": 268, "done_today": 0,
                                           "cap_tonight": 100, "estimated_completion_nights": 19.3}},
    "data_plausibility": lambda: {"status": "BLOCK", "ran_at": NOW.isoformat(), "blocking_items": ["t.a"]},
    "data_sources": lambda: {"ok": True, "data": {"sources": [{"source": "Finnhub API", "status": "dead"},
                                                               {"source": "ledger:polygon", "status": "error", "last_error": "0 candidates"},
                                                               {"source": "fred", "status": "live"}]}},
    "comms": lambda: {"status": "OK", "failed": 0, "unsettled": 0, "telegram_outbox_failed_24h": 2,
                      "telegram_outbox_failed_24h_by_channel": {"telegram": 2}},
    "pipelines": lambda: {"status": "OK", "window_hours": 24,
                          "pipelines": [{"pipeline": "scalp_scan", "failed": 3, "last_error": "HTTP 429"}]},
}


def test_aggregate_every_source_answers():
    m = NA.aggregate(dict(GOOD), now=NOW)
    assert m["all_sources_answered"] is True and m["status"] == "OK"
    titles = [i["title"] for i in m["items"]]
    assert m["items"][0]["severity"] == "P0" and m["items"][0]["where"] == "/v3/risk"
    assert "n8n lane identity-sweep-stage0: every live run failed today (2/2)" in titles
    assert not any("registry-runtime-truth" in t for t in titles)          # it also succeeded: not "every run"
    assert "n8n workflow tradeai-dispatcher errored 4 times today" in titles
    assert any(t.startswith("grant release-write expires in 12 min") for t in titles)
    assert not any("old" in t and "expired" in t for t in titles)          # expired 20 days ago: history
    assert "Overnight LLM queue CRIT: 1928 pending, 268 failed" in titles
    assert "Implausible data: t.a" in titles
    assert "Data source ledger:polygon is error" in titles and "Data source fred is live" not in titles
    assert "2 Telegram sends failed in 24 h" in titles
    assert "Pipeline scalp_scan failed 3x in 24 h" in titles
    assert m["counts"] == {s: sum(1 for i in m["items"] if i["severity"] == s) for s in NA.SEVERITIES}
    assert sum(m["counts"].values()) == m["total"] == len(m["items"])
    for i in m["items"]:
        assert set(i) == {"severity", "title", "why", "where", "source", "since", "evidence"}
        assert i["where"].startswith("/v3")


def test_unavailable_source_is_an_item_never_omitted():
    probes = dict(GOOD)
    probes["queue"] = lambda: {"measured": False, "pending": 0}                # db_adapter returned None
    probes["pipelines"] = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    probes["comms"] = lambda: {"status": "UNAVAILABLE", "error": "communications DB unavailable"}
    m = NA.aggregate(probes, now=NOW)
    assert m["all_sources_answered"] is False and m["status"] == "PARTIAL"
    un = {i["source"]: i for i in m["items"] if i["title"].startswith("source ")}
    assert set(un) == {"queue", "pipelines", "comms"}
    assert "db down" in un["pipelines"]["why"] and un["comms"]["where"] == "/v3/communications"
    assert m["sources"]["queue"]["status"] == "UNAVAILABLE" and m["sources"]["health"]["status"] == "OK"


def test_a_hung_source_times_out_into_an_item():
    gate = threading.Event()
    probes = {"health": GOOD["health"], "systemd": lambda: gate.wait(5) and {"failed_units": []}}
    m = NA.aggregate(probes, now=NOW, timeout_s=0.3)
    gate.set()
    assert m["sources"]["systemd"]["status"] == "UNAVAILABLE" and "timed out" in m["sources"]["systemd"]["error"]
    assert any(i["title"] == "source systemd unavailable" for i in m["items"])
    assert m["all_sources_answered"] is False


def test_quiet_system_is_empty_only_when_all_answered():
    quiet = {
        "health": lambda: {"captured_at": NOW.isoformat(), "findings": []},
        "systemd": lambda: {"failed_units": []},
        "queue": lambda: {"measured": True, "pending": 10, "failed": 0, "done_today": 90, "estimated_completion_nights": 0.1},
        "comms": lambda: {"status": "OK", "failed": 0, "unsettled": 0, "telegram_outbox_failed_24h": 0},
    }
    m = NA.aggregate(quiet, now=NOW)
    assert m["items"] == [] and m["all_sources_answered"] is True and m["total"] == 0
    quiet["comms"] = lambda: {"status": "OK", "failed": 0, "unsettled": 0, "telegram_outbox_failed_24h": None}
    m2 = NA.aggregate(quiet, now=NOW)
    assert [i["title"] for i in m2["items"]] == ["source comms/telegram_outbox unavailable"]


def test_queue_thresholds_and_stale_health():
    assert NA.queue_level({"pending": 10, "failed": 0, "estimated_completion_nights": 0.1}) == "OK"
    assert NA.queue_level({"pending": 600, "failed": 0}) == "WARN"
    assert NA.queue_level({"pending": 100, "failed": 250}) == "CRIT"
    stale = NA.rule_health({"captured_at": (NOW - timedelta(hours=5)).isoformat(), "findings": []}, NOW)
    assert stale[0]["severity"] == "P2" and "5.0 h old" in stale[0]["title"]


def test_parse_failed_units_keeps_only_tradeai_units():
    text = ("tradeai-portfolio-backup-cadence.service loaded failed failed Portfolio backup cadence\n"
            "mcporter-token-refresh.service loaded failed failed Other app\n")
    assert NA.parse_failed_units(text) == [{"unit": "tradeai-portfolio-backup-cadence.service", "load": "loaded",
                                           "active": "failed", "sub": "failed",
                                           "description": "Portfolio backup cadence"}]

    class R:
        returncode, stdout, stderr = 1, "", "Failed to connect to bus"
    with pytest.raises(NA.SourceUnavailable):
        NA.probe_failed_units(run=lambda *a, **k: R())


def test_n8n_today_reports_live_lane_states(tmp_path):
    from scripts.lib.data_broker import n8n_today as nt
    d = tmp_path / "data" / "runtime" / "n8n_runs"
    d.mkdir(parents=True)
    for lane, slot, st in (("lane-a", "20261021T0800", "RUN_FAILED"), ("lane-a", "20261021T0900", "RUN_FAILED"),
                           ("lane-b", "20261021T0800", "RUN_DONE")):
        (d / f"d:{lane}:live:{slot}.json").write_text(json.dumps({"run_id": f"d:{lane}:live:{slot}", "mode": "live",
                                                                   "lane_id": lane, "state": st}))
    m = nt.build(tmp_path, now=NOW)
    assert m["live_lane_states"] == {"lane-a": {"RUN_FAILED": 2}, "lane-b": {"RUN_DONE": 1}}
    items = NA.rule_n8n(m, NOW)
    assert [i["title"] for i in items] == ["n8n lane lane-a: every live run failed today (2/2)"]


def test_needs_action_route_is_registered():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    for route in ("/api/v2/needs-action", "/api/v2/system/data-plausibility", "/api/v2/system/pipeline-failures"):
        assert f'"{route}":' in src
