"""Refactor wave 2 (cron -> n8n, 2026-10-10), bucket V4: topic curation lanes.

- scripts/topic_curator.py (cron L300): --dry-run opens a READ ONLY session and runs SELECT counts only;
  no LLM lane, writer, subprocess (rag_indexer / topic_ingestion) or file write is reachable. A real run
  writes topic-curator_last.json (ok_at only on success); a failed RAG re-index now exits 1.
- scripts/hermes_topic_monitor_bridge.py (cron L420): --dry-run wins over --apply; the reconcile UPDATE is
  replaced by a read-only SELECT count; an --apply run with an insert error exits 1.
- scripts/hermes_entity_spike_discovery.py (cron L683): real runs leave a receipt; dry runs do not.
Hermetic: fake connections, TRADEAI_STATE_ROOT = tmp, every write path patched to raise.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_entity_spike_discovery as hesd  # noqa: E402
import hermes_topic_monitor_bridge as htb  # noqa: E402
import topic_curator as tc  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402

_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "TRUNCATE")


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rowcount, self.description = conn, 1, None
        self._one, self._all = (0,), []

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.conn.sql.append(norm)
        if self.conn.fail_on and self.conn.fail_on in norm:
            raise RuntimeError("db failure")
        res = (self.conn.responder(norm, params) if self.conn.responder else None) or {}
        self.description = res.get("description")
        self._one, self._all = res.get("one", (0,)), res.get("all", [])
        self.rowcount = res.get("rowcount", 1)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._all)

    def close(self):
        pass


class FakeConn:
    def __init__(self, responder=None, fail_on=None):
        self.responder, self.fail_on = responder, fail_on
        self.sql, self.commits, self.readonly, self.closed = [], 0, None, False

    def cursor(self, *a, **k):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def set_session(self, readonly=None, **k):
        self.readonly = readonly

    def close(self):
        self.closed = True

    def writes(self):
        return [s for s in self.sql if s.split()[0].upper() in _WRITE_VERBS]


def _boom(*a, **k):
    raise AssertionError("dry run reached a write / LLM / subprocess path")


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


def _receipt(state, lane):
    return json.loads((state / "data" / "runtime" / f"{lane}_last.json").read_text())


def _dry_line(text):
    line = next(ln for ln in text.splitlines() if ln.startswith("DRY-RUN "))
    return json.loads(line[len("DRY-RUN ") :])


# ── topic_curator ────────────────────────────────────────────────────────────────────────────────────
def _curator_counts(counts):
    seq = iter(counts)
    return lambda sql, params: {"one": (next(seq),)} if sql.startswith("SELECT count(*)") else None


def test_curator_dry_run_reaches_no_write_llm_or_subprocess(monkeypatch, capsys, _state):
    conn = FakeConn(_curator_counts([7, 3, 2, 5, 4]))
    monkeypatch.setattr(tc, "_get_conn", lambda: conn)
    for name in (
        "rate_pending_content",
        "extract_and_link_entities",
        "improve_queries",
        "trigger_rag_reindex",
        "update_agent_context",
        "_write_desk_projection",
        "ensemble_rescue",
        "_free_lane_gen",
        "_promote_discovery_ticker",
        "_write_ensemble_receipt",
    ):
        monkeypatch.setattr(tc, name, _boom)
    import subprocess

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    monkeypatch.setattr(sys, "argv", ["topic_curator.py", "--dry-run", "--ensemble", "--improve-queries"])
    assert tc.main() == 0
    assert conn.readonly is True and conn.commits == 0 and conn.writes() == []
    assert all(s.startswith("SELECT") for s in conn.sql)
    rep = _dry_line(capsys.readouterr().out)
    assert rep["lane_id"] == "topic-curator"
    assert rep["summary"]["would_auto_approve"] == 7
    assert rep["summary"]["would_llm_rate_articles"] == 3
    assert rep["summary"]["would_enqueue_agent_events"] == 4
    assert any("topic_ingestion.py" in w for w in rep["would_write"])
    assert not (_state / "data" / "runtime").exists()


def test_curator_dry_run_report_follows_the_data(monkeypatch, capsys):
    """Mutation test (AGENTS.md §6): change the store, the report changes with it."""
    for counts in ([0, 0, 0, 0, 0], [11, 250, 9, 400, 2]):
        conn = FakeConn(_curator_counts(counts))
        monkeypatch.setattr(tc, "_get_conn", lambda c=conn: c)
        monkeypatch.setattr(sys, "argv", ["topic_curator.py", "--dry-run"])
        assert tc.main() == 0
        rep = _dry_line(capsys.readouterr().out)["summary"]
        assert rep["would_auto_approve"] == counts[0]
        assert rep["would_llm_rate_articles"] == min(counts[1], 200)
        assert rep["would_extract_entities_from"] == min(counts[3], 100)


def test_curator_dry_branch_precedes_the_real_run_in_source():
    src = inspect.getsource(tc.main)
    assert src.index("if args.dry_run") < src.index("_curate(")
    dry = inspect.getsource(tc._dry_run) + inspect.getsource(tc.preview)
    for forbidden in (
        "rate_pending_content(",
        "set_rag_status",
        "subprocess.run",
        "import subprocess",
        "_write_desk_projection(",
        "write_lane_receipt",
        "_free_lane_gen(",
        "commit(",
    ):
        assert forbidden not in dry, forbidden


def _patch_curator_steps(monkeypatch, *, rag="ok", rated=3):
    monkeypatch.setattr(tc, "_get_conn", lambda: FakeConn())
    monkeypatch.setattr(tc, "rate_pending_content", lambda conn, topic=None: (rated, 1, 0))
    monkeypatch.setattr(tc, "extract_and_link_entities", lambda conn, topic=None: 2)
    monkeypatch.setattr(tc, "update_agent_context", lambda conn, topic=None: 1)
    monkeypatch.setattr(tc, "trigger_rag_reindex", lambda conn: rag)
    monkeypatch.setattr(sys, "argv", ["topic_curator.py"])


def test_curator_real_run_writes_receipt_and_desk_projection_to_state_root(monkeypatch, _state):
    _patch_curator_steps(monkeypatch)
    assert tc.main() == 0
    rec = _receipt(_state, "topic-curator")
    assert rec["status"] == "ok" and rec["ok_at"] == rec["finished_at"] and rec["exit"] == 0
    assert rec["summary"]["entity_links"] == 2 and rec["summary"]["rag_reindex"] == "ok"
    proj = json.loads((_state / "data" / "runtime" / "topic_curator_latest.json").read_text())
    assert proj["rated"] == 3 and proj["agent_events"] == 1


def test_curator_failed_rag_reindex_exits_1_and_keeps_previous_ok_at(monkeypatch, _state):
    _patch_curator_steps(monkeypatch)
    assert tc.main() == 0
    ok_at = _receipt(_state, "topic-curator")["ok_at"]
    _patch_curator_steps(monkeypatch, rag="failed rc=1")
    assert tc.main() == 1
    rec = _receipt(_state, "topic-curator")
    assert rec["status"] == "failed" and rec["exit"] == 1 and rec["ok_at"] == ok_at


def test_curator_crash_leaves_failed_receipt(monkeypatch, _state):
    _patch_curator_steps(monkeypatch)

    def crash(conn, topic=None):
        raise RuntimeError("SSL connection has been closed unexpectedly")

    monkeypatch.setattr(tc, "extract_and_link_entities", crash)
    with pytest.raises(RuntimeError):
        tc.main()
    rec = _receipt(_state, "topic-curator")
    assert rec["status"] == "failed" and rec["ok_at"] is None and rec["error"] == "RuntimeError"


def test_rag_reindex_reports_its_status(monkeypatch, tmp_path):
    import subprocess

    class R:
        def __init__(self, rc):
            self.returncode = rc

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or R(1))
    assert tc.trigger_rag_reindex(None) == "failed rc=1" and len(calls) == 2

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("rag", 180)

    monkeypatch.setattr(subprocess, "run", timeout)
    assert tc.trigger_rag_reindex(None) == "error TimeoutExpired"


# ── hermes_topic_monitor_bridge ──────────────────────────────────────────────────────────────────────
def _bridge_responder(sql, params):
    if sql.startswith("SELECT count(*) FROM topic_monitor tm"):
        return {"one": (6,)}
    if sql.startswith("SELECT topic_id"):
        return {
            "description": [
                ("topic_id",),
                ("display_name",),
                ("owner",),
                ("search_queries",),
                ("video_queries",),
                ("priority",),
                ("max_age_days",),
            ],
            "all": [("t1", "Topic One", "hermes", ["q"], [], 1, 7)],
        }
    return None


@pytest.mark.parametrize("argv", [[], ["--apply", "--dry-run"], ["--dry-run", "--json", "--apply"]])
def test_bridge_dry_run_is_read_only(monkeypatch, capsys, argv):
    conn = FakeConn(_bridge_responder)
    monkeypatch.setattr(htb, "load_env", lambda: None)
    monkeypatch.setattr(htb, "db", lambda: conn)
    import lib.writers.hermes_research_writer as hrw

    monkeypatch.setattr(hrw, "write_research_rows", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert htb.main(argv) == 0
    assert conn.readonly is True and conn.commits == 0 and conn.writes() == []
    cap = capsys.readouterr()
    rep = _dry_line(cap.err if "--json" in argv else cap.out)
    assert rep["summary"] == {"reconciled": 6, "candidates": 1}
    if "--json" in argv:
        assert json.loads(cap.out)["applied"] is False  # stdout stays parseable JSON


def test_bridge_apply_writes_receipt_and_insert_error_exits_1(monkeypatch, _state):
    class RC:
        def __init__(self, ids):
            self.ids, self.rows_rejected = ids, 0

    conn = FakeConn(_bridge_responder)
    monkeypatch.setattr(htb, "load_env", lambda: None)
    monkeypatch.setattr(htb, "db", lambda: conn)
    import lib.writers.hermes_research_writer as hrw

    monkeypatch.setattr(hrw, "write_research_rows", lambda cur, rows, producer: RC([42]))
    assert htb.main(["--apply", "--max-rows", "40"]) == 0
    assert any(s.startswith("UPDATE topic_monitor") for s in conn.writes())
    rec = _receipt(_state, "hermes-topic-monitor-bridge")
    assert rec["status"] == "ok" and rec["summary"]["enqueued"] == 1

    monkeypatch.setattr(hrw, "write_research_rows", lambda cur, rows, producer: RC([]))
    assert htb.main(["--apply"]) == 1
    rec2 = _receipt(_state, "hermes-topic-monitor-bridge")
    assert rec2["status"] == "failed" and rec2["summary"]["insert_errors"] == 1 and rec2["ok_at"] == rec["ok_at"]


# ── hermes_entity_spike_discovery ────────────────────────────────────────────────────────────────────
def _spike_report(dry_run, **k):
    return {
        "dry_run": dry_run,
        "scanned_terms": 12,
        "spikes_detected": 2,
        "upserted": 0 if dry_run else 2,
        "would_upsert": 2 if dry_run else None,
        "thresholds": {},
        "by_type": {},
        "by_domain": {},
        "skipped_reasons": {},
        "notes": [],
        "candidates": [],
    }


def test_spike_dry_run_passes_dry_and_writes_no_receipt(monkeypatch, capsys, _state):
    seen = {}

    def fake(dry_run, limit, window_hours):
        seen["dry_run"] = dry_run
        return _spike_report(dry_run)

    monkeypatch.setattr(hesd.entity_spikes, "run_discovery", fake)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    monkeypatch.setattr(sys, "argv", ["x", "--run", "--dry-run", "--json"])
    assert hesd.main() == 0
    cap = capsys.readouterr()
    assert seen["dry_run"] is True and json.loads(cap.out)["would_upsert"] == 2
    assert _dry_line(cap.err)["summary"]["spikes_detected"] == 2


def test_spike_dry_run_never_calls_the_inbox_writer(monkeypatch):
    es = hesd.entity_spikes
    monkeypatch.setattr(es.inbox, "upsert_candidate", _boom)
    monkeypatch.setattr(es, "collect_entity_counts", lambda wh, notes: ([], {}))
    monkeypatch.setattr(es, "collect_topic_counts", lambda wh, notes: ([], {}))
    monkeypatch.setattr(es, "covered_keys", lambda notes: set())
    monkeypatch.setattr(es, "relevant_symbols", lambda notes: set())
    monkeypatch.setattr(es, "compute_spikes", lambda *a, **k: [{"x": 1}])
    payload = {
        "candidate_type": "TOPIC_CANDIDATE",
        "label": "l",
        "meta": {"spike": {}},
        "signals": {"trend_momentum": 0.5},
    }
    monkeypatch.setattr(es, "build_payloads", lambda *a, **k: [payload])
    rep = es.run_discovery(dry_run=True)
    assert rep["would_upsert"] == 1 and rep["upserted"] == 0


def test_spike_real_run_receipt_and_crash(monkeypatch, _state):
    monkeypatch.setattr(
        hesd.entity_spikes, "run_discovery", lambda dry_run, limit, window_hours: _spike_report(dry_run)
    )
    monkeypatch.setattr(sys, "argv", ["x", "--run", "--json"])
    assert hesd.main() == 0
    rec = _receipt(_state, "hermes-entity-spike-discovery")
    assert rec["status"] == "ok" and rec["summary"] == {"scanned_terms": 12, "spikes_detected": 2, "upserted": 2}

    def crash(**k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(hesd.entity_spikes, "run_discovery", crash)
    with pytest.raises(RuntimeError):
        hesd.main()
    rec2 = _receipt(_state, "hermes-entity-spike-discovery")
    assert rec2["status"] == "failed" and rec2["ok_at"] == rec["ok_at"]
