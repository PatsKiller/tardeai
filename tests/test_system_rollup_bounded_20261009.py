"""Storage audit 2026-10-09 #5: the nightly system rollup must stay bounded and never fail silently.

Hermetic: no database, no network, no Telegram. The real api_v2._system_rollup_trends and the real
system_rollup_snapshot.run are driven against an in-memory system_rollup_daily.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import system_rollup_payload as srp  # noqa: E402


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── in-memory system_rollup_daily + ai_reports ──────────────────────────────
class _Store:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.ai_reports: list[tuple] = []
        self.fail_snapshot: Exception | None = None

    def query(self, sql, params=None, fetch="all"):
        """Stands in for api_v2._db_query on the trends SELECT, honouring what it selects."""
        assert "system_rollup_daily" in sql
        days = sorted(self.rows, reverse=True)[:14]
        if "payload->'headlines'" in sql:
            return [{"day": d, "headlines": self.rows[d].get("headlines")} for d in days]
        return [{"day": d, "payload": self.rows[d]} for d in days]  # the pre-fix SELECT day, payload


class _Cur:
    def __init__(self, store: _Store):
        self.store = store
        self.rowcount = 0

    def execute(self, sql, params=None):
        if "INSERT INTO system_rollup_daily" in sql:
            if self.store.fail_snapshot is not None:
                raise self.store.fail_snapshot
            day, payload = params
            self.store.rows[str(day)] = json.loads(payload)
        elif "INSERT INTO ai_reports" in sql:
            self.store.ai_reports.append(params)
        else:  # pragma: no cover - any other statement is a test bug
            raise AssertionError(f"unexpected SQL {sql[:80]}")


class _Conn:
    def __init__(self, store):
        self.store = store
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cur(self.store)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


_STATIC_PANELS = {
    "pipelines": {"corpus": "pipeline_runs", "data": {"rows": [
        {"pipeline_key": "rag_indexer", "runs": 6, "successes": 5, "failures": 1}]}},
    "agents": {"corpus": "watchlist_agent_results", "data": {"rows": [{"agent": "maria", "analyses": 40}]}},
    "proposals": {"corpus": "proposals", "data": {"rows": [{"cnt": 3}]}},
    "alerts": {"corpus": "alerts", "data": {"rows": [{"n": 12}]}},
    "paper_trades": {"corpus": "paper", "data": {"closed": 2, "pnl": 14.5}},
    "research": {"corpus": "hermes", "data": {"hermes_items": 9}},
    "reports_generated": {"corpus": "reports", "data": {"rows": [{"n": 1}]}},
    "directives": {"corpus": "directives", "data": {"hits": 7}},
    "health": {"corpus": "health", "data": {"health_score": 81}},
}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    store = _Store()
    sent: list[str] = []

    # The REAL api_v2 trends function, with its _db_query pointed at the in-memory table.
    import api_v2 as real_api
    monkeypatch.setattr(real_api, "_db_query", store.query)

    def _system_rollup(window="24h"):
        panels = dict(_STATIC_PANELS)
        panels["trends"] = {"corpus": "system_rollup_daily snapshots", "data": real_api._system_rollup_trends()}
        return {"window": window, "panels": panels}

    monkeypatch.setattr(real_api, "_system_rollup", _system_rollup)

    tg = types.ModuleType("telegram_alert")
    tg.send_telegram = lambda msg, bypass_router=False, **k: sent.append(msg) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    hub = types.ModuleType("generate_reports_hub")
    hub.build_report_catalog = lambda root: None
    monkeypatch.setitem(sys.modules, "generate_reports_hub", hub)
    dba = types.ModuleType("db_adapter")
    conn = _Conn(store)
    dba._get_conn = lambda: conn
    monkeypatch.setitem(sys.modules, "db_adapter", dba)
    monkeypatch.setitem(sys.modules, "api_v2", real_api)

    snap = _load("system_rollup_snapshot_under_test", "system_rollup_snapshot.py")
    monkeypatch.setattr(snap, "REPORTS_DIR", tmp_path / "reports")
    (tmp_path / "reports").mkdir()
    receipts = tmp_path / "receipts.jsonl"
    monkeypatch.setenv(snap.RECEIPTS_ENV, str(receipts))
    monkeypatch.delenv(srp.MAX_PAYLOAD_ENV, raising=False)
    return types.SimpleNamespace(store=store, sent=sent, snap=snap, receipts=receipts, conn=conn,
                                 api=real_api, tmp=tmp_path)


def _receipts(h):
    return [json.loads(line) for line in h.receipts.read_text().splitlines()] if h.receipts.exists() else []


# ── the recursion is gone ───────────────────────────────────────────────────
def test_trends_panel_reads_headlines_only(harness):
    harness.store.rows["2026-07-31"] = {"headlines": {"pipelines_run": 5, "nested": {"x": 1}},
                                        "panels": {"trends": {"data": {"rows": ["huge"] * 1000}}}}
    out = harness.api._system_rollup_trends()
    assert out["days"] == 1 and out["shape"] == "headlines_only"
    row = out["rows"][0]
    assert set(row) == {"day", "payload"} and set(row["payload"]) == {"headlines"}
    assert row["payload"]["headlines"]["pipelines_run"] == 5
    assert "nested" not in row["payload"]["headlines"]
    assert "huge" not in json.dumps(out)


def test_payload_stays_bounded_across_30_simulated_days(harness):
    start = date(2026, 9, 1)
    sizes = []
    for i in range(30):
        code, receipt = harness.snap.run(today=start + timedelta(days=i))
        assert code == 0, receipt
        assert receipt["status"] == "ok" and receipt["steps"]["snapshot"]["status"] == "ok"
        sizes.append(receipt["payload_bytes"])
    stored = harness.store.rows
    assert len(stored) == 30
    for payload in stored.values():
        assert "trends" not in payload["panels"]
        assert payload["schema"] == srp.SCHEMA
        assert all(not isinstance(v, (dict, list)) for v in payload["headlines"].values())
    # bounded: day 30 is no bigger than day 1 (identical inputs), and far below the cap
    assert max(sizes) == min(sizes) and max(sizes) < 16_384
    # the page still gets 14 compact trend rows
    trends = harness.api._system_rollup_trends()
    assert trends["days"] == 14
    assert len(json.dumps(trends)) < 14 * 600
    assert len(harness.sent) == 30 and len(_receipts(harness)) == 30


def test_simulator_detects_the_old_recursion(harness, monkeypatch):
    """Control: with the pre-fix wiring (whole payloads selected, trends stored) the same 30-day
    simulation grows without bound, so the bounded test above can fail."""
    def old_trends():
        rows = harness.store.query("SELECT day, payload FROM system_rollup_daily ORDER BY day DESC LIMIT 14")
        return {"days": len(rows), "rows": [{"day": r["day"], "payload": r["payload"]} for r in rows]}

    monkeypatch.setattr(harness.api, "_system_rollup_trends", old_trends)
    monkeypatch.setattr(harness.snap, "build_stored_payload",
                        lambda hl, panels: {"headlines": hl, "panels": dict(panels)})
    monkeypatch.setenv(srp.MAX_PAYLOAD_ENV, str(10 * 1024 * 1024))
    sizes = []
    for i in range(12):
        code, receipt = harness.snap.run(today=date(2026, 7, 17) + timedelta(days=i))
        sizes.append(receipt["payload_bytes"])
        if code != 0:
            break
    assert sizes[-1] > 50 * sizes[0]


# ── typed refusal, receipts, non-zero exits ─────────────────────────────────
def test_size_cap_refusal_is_typed_receipted_and_nonzero(harness, monkeypatch):
    monkeypatch.setenv(srp.MAX_PAYLOAD_ENV, "500")
    code, receipt = harness.snap.run(today=date(2026, 10, 9))
    assert code == harness.snap.EXIT_PAYLOAD_REFUSED == 3
    assert receipt["status"] == "refused"
    snap_step = receipt["steps"]["snapshot"]
    assert snap_step["status"] == "refused" and snap_step["code"] == "ROLLUP_PAYLOAD_TOO_LARGE"
    assert snap_step["payload_bytes"] > snap_step["cap_bytes"] == 500
    assert harness.store.rows == {}                       # nothing stored
    assert harness.store.ai_reports                        # the digest still archived
    assert "REFUSED ROLLUP_PAYLOAD_TOO_LARGE" in harness.sent[-1]
    assert _receipts(harness)[-1]["status"] == "refused"
    md = (harness.tmp / "reports" / "system_digest_2026-10-09.md").read_text()
    assert "REFUSED ROLLUP_PAYLOAD_TOO_LARGE" in md


def test_serialize_with_cap_raises_typed_refusal():
    payload = srp.build_stored_payload({"pipelines_run": 1}, {"big": {"data": "x" * 5000}, "trends": {"x": 1}})
    assert "trends" not in payload["panels"]
    with pytest.raises(srp.RollupPayloadRefused) as ei:
        srp.serialize_with_cap(payload, 1000)
    assert ei.value.code == "ROLLUP_PAYLOAD_TOO_LARGE"
    assert ei.value.largest_panels[0][0] == "big"
    text, n = srp.serialize_with_cap(payload, 10_000)
    assert n == len(text.encode()) and n > 5000


def test_snapshot_insert_failure_exits_nonzero_with_receipt(harness):
    harness.store.fail_snapshot = RuntimeError("total size of jsonb array elements exceeds the maximum")
    code, receipt = harness.snap.run(today=date(2026, 10, 9))
    assert code == 1 and receipt["status"] == "failed"
    assert "snapshot" in receipt["failed_steps"]
    assert "jsonb" in receipt["steps"]["snapshot"]["error"]
    assert harness.conn.rollbacks >= 1
    assert harness.store.ai_reports                        # later steps still ran
    assert "FAILED steps: snapshot" in harness.sent[-1]
    assert _receipts(harness)[-1]["exit_code"] == 1


def test_rollup_failure_exits_nonzero_via_main(harness, monkeypatch):
    def boom(window="24h"):
        raise RuntimeError("db down")

    monkeypatch.setattr(harness.api, "_system_rollup", boom)
    assert harness.snap.main([]) == 1
    rec = _receipts(harness)[-1]
    assert rec["status"] == "failed" and rec["steps"]["rollup"]["status"] == "failed"
    assert harness.sent == []


def test_telegram_not_accepted_is_a_failure(harness, monkeypatch):
    sys.modules["telegram_alert"].send_telegram = lambda msg, bypass_router=False, **k: False
    code, receipt = harness.snap.run(today=date(2026, 10, 9))
    assert code == 1 and receipt["failed_steps"] == ["telegram"]


def test_dry_run_writes_nothing(harness):
    code, receipt = harness.snap.run(dry_run=True, today=date(2026, 10, 9))
    assert code == 0 and receipt["dry_run"] is True
    assert receipt["steps"]["snapshot"]["status"] == "would_write" and receipt["payload_bytes"] > 0
    assert harness.store.rows == {} and harness.store.ai_reports == []
    assert harness.sent == [] and not harness.receipts.exists()
    assert list((harness.tmp / "reports").iterdir()) == []


def test_max_payload_bytes_env_override():
    assert srp.max_payload_bytes({}) == srp.DEFAULT_MAX_PAYLOAD_BYTES
    assert srp.max_payload_bytes({srp.MAX_PAYLOAD_ENV: "2048"}) == 2048
    assert srp.max_payload_bytes({srp.MAX_PAYLOAD_ENV: "-1"}) == srp.DEFAULT_MAX_PAYLOAD_BYTES
    assert srp.max_payload_bytes({srp.MAX_PAYLOAD_ENV: "junk"}) == srp.DEFAULT_MAX_PAYLOAD_BYTES
