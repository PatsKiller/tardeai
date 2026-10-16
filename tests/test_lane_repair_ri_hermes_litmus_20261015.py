"""Lane repair 2026-10-15: three lanes the lane-disposition audit found broken, turned on and wired for n8n SHADOW.

COVERS = ["scripts/topic_ingestion.py", "scripts/run_research_intelligence_overnight.sh",
          "scripts/research_intelligence_narrative_enrich.py", "scripts/topic_research_synthesizer.py",
          "scripts/completion_compound_receipt.py", "scripts/lib/lane_last_receipt.py",
          "scripts/research_critique_pipeline.py", "scripts/source_litmus_vs_yahoo.py",
          "config/llm_process_registry.json", "config/llm_routing_policy.json", "config/lane_registry.json",
          "config/n8n_run_allowlist.json", "config/n8n_effect_keys.json", "config/n8n_health_contracts.json"]

1. run-research-intelligence-overnight: the ingest step exited 124 every night (331 serial ~11 s OAuth rating calls,
   one per search result, no per-run bound, `timeout 30m`), the narrative step was refused PROCESS_NOT_REGISTERED
   for every row, and topic_research_synthesizer called the model with no process_id (no gate, no cap).
2. hermes-coordinator: research_curator exited 1 every tick on a ForeignKeyViolation in retention_purge (archived
   watch_directives still referenced by strategy_watchpool), so the coordinator receipt read completed:false.
3. source-litmus-vs-yahoo: a BLOCK finding wrote a failed lane receipt; one sub-penny tick (SRNE 0.0003 vs 0.0002)
   and one 13% micro-cap row each BLOCKed a whole source.

Hermetic: no DB, no network, no model call; receipts go to tmp_path (TRADEAI_STATE_ROOT); the shell dry run is offline.
"""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import types
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: The scripts under test import ``lib.X`` (their own spelling); this module imports ``scripts.lib.X``. Both are
#: dropped again at module teardown so no later test sees one module under two names (DualImportIdentityError).
_MODULES_BEFORE = frozenset(sys.modules)

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_last_receipt as LR  # noqa: E402


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ti = _load("topic_ingestion_lane_repair_under_test", "scripts/topic_ingestion.py")
ccr = _load("completion_compound_receipt_under_test", "scripts/completion_compound_receipt.py")
lit = _load("source_litmus_lane_repair_under_test", "scripts/source_litmus_vs_yahoo.py")
rcp = _load("research_critique_pipeline_lane_repair_under_test", "scripts/research_critique_pipeline.py")

REGISTRY = {r["lane_id"]: r for r in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]}
ALLOW_DOC = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())
ALLOW = {e["lane_id"]: e for e in ALLOW_DOC["lanes"]}
LLM_REG = {p["id"]: p for p in json.loads((ROOT / "config/llm_process_registry.json").read_text())["processes"]}
ROUTING = json.loads((ROOT / "config/llm_routing_policy.json").read_text())["policies"]["default"]["processes"]
EFFECTS = json.loads((ROOT / "config/n8n_effect_keys.json").read_text())["lanes"]
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]}
RI, LIT, HC = "run-research-intelligence-overnight", "source-litmus-vs-yahoo", "hermes-coordinator"
NEW_PROCESSES = ("topic_ingestion", "ri_narrative_enrich", "topic_research_synthesizer")


@pytest.fixture(autouse=True, scope="module")
def _drop_dual_spelled_modules():
    yield
    for name in [n for n in sys.modules if n not in _MODULES_BEFORE]:
        if name == "lib" or name.startswith("lib."):
            del sys.modules[name]


@pytest.fixture(autouse=True)
def _state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    for k in [k for k in os.environ if k.startswith(("DB_", "PG"))]:
        monkeypatch.delenv(k, raising=False)
    yield


# ── 1. topic_ingestion: bounded work, pre-model skip, resumable, receipt even when killed ─────────────────────────


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_run_budget_caps_items_and_stops_on_the_clock():
    clk = Clock()
    b = ti.RunBudget(budget_s=100, max_items_per_topic=2, clock=clk)
    b.start_topic()
    assert [b.admit(), b.admit(), b.admit()] == [None, None, "item_cap"]
    b.start_topic()
    assert b.admit() is None and b.attempted == 3
    clk.t = 100
    assert b.exhausted() and b.admit() == "budget_exhausted" and b.topic_cut
    unbounded = ti.RunBudget()
    unbounded.start_topic()
    assert all(unbounded.admit() is None for _ in range(500)) and not unbounded.exhausted()


def _stub_topic_world(monkeypatch, *, stored: set, news: int = 6, clock=None, budget=0, cap=0):
    rated = []
    monkeypatch.setattr(ti, "_RUN", ti.RunBudget(budget, cap, clock=clock or Clock()))
    monkeypatch.setattr(ti, "search_saved_urls", lambda conn, topic: [])
    monkeypatch.setattr(ti, "search_youtube", lambda *a, **k: [])
    monkeypatch.setattr(
        ti,
        "search_google_news",
        lambda *a, **k: [
            {"title": f"t{i}", "url": f"https://x/{i}", "description": "d", "source": "google_news_rss"}
            for i in range(news)
        ],
    )
    for fn in ("search_yahoo_news", "search_brave_news", "search_duckduckgo"):
        monkeypatch.setattr(ti, fn, lambda *a, **k: [])
    monkeypatch.setattr(ti, "_log_gap_fill", lambda *a, **k: None)
    monkeypatch.setattr(ti, "_is_blocked", lambda conn, kind, cid: False)
    monkeypatch.setattr(ti, "_already_stored", lambda conn, topic, item: item["url"] in stored)

    def rate(title, *a, **k):
        rated.append(title)
        return {"rag_status": "approved", "rag_reason": "", "summary": "s"}

    monkeypatch.setattr(ti, "_llm_rate_quality", rate)
    return rated


TOPIC = {"topic_id": "roth_conv", "display_name": "Roth conversion", "search_queries": ["q"], "video_queries": ["v"]}


def test_already_stored_results_skip_before_the_model_call(monkeypatch):
    rated = _stub_topic_world(monkeypatch, stored={"https://x/0", "https://x/1", "https://x/2"})
    out = ti.process_topic(object(), dict(TOPIC), dry_run=True, use_llm=True)
    assert rated == ["t3", "t4", "t5"]  # the three stored results never reached the model
    assert ti._RUN.skipped == {"already_stored": 3} and ti._RUN.attempted == 3 and out["complete"] is True


def test_item_cap_bounds_model_calls_per_topic(monkeypatch):
    rated = _stub_topic_world(monkeypatch, stored=set(), news=40, cap=12)
    ti.process_topic(object(), dict(TOPIC), dry_run=True, use_llm=True)
    assert len(rated) == 12 and ti._RUN.skipped == {"item_cap": 28}


def test_a_spent_budget_cuts_the_topic_so_it_resumes_first(monkeypatch):
    clk = Clock()
    rated = _stub_topic_world(monkeypatch, stored=set(), news=5, clock=clk, budget=10)
    orig = ti._llm_rate_quality

    def slow(*a, **k):
        clk.t += 6  # each model call costs 6 s of a 10 s budget
        return orig(*a, **k)

    monkeypatch.setattr(ti, "_llm_rate_quality", slow)
    out = ti.process_topic(object(), dict(TOPIC), dry_run=True, use_llm=True)
    assert len(rated) == 2 and out["complete"] is False
    assert ti._RUN.skipped["budget_exhausted"] == 3
    assert any(k.startswith("search_skipped_budget:") for k in ti._RUN.skipped)  # no new network work either


class _FakeConn:
    exhausted = False

    def __init__(self, topics):
        self.topics = topics
        self.updated = []
        self.closed = False

    def cursor(self):
        conn = self

        class C:
            description = [("topic_id",), ("display_name",), ("search_queries",), ("video_queries",)]

            def execute(self, sql, params=None):
                self.sql = sql
                if "UPDATE topic_monitor" in sql:
                    conn.updated.append(params[1])

            def fetchall(self):
                return [
                    (t["topic_id"], t["display_name"], t["search_queries"], t["video_queries"]) for t in conn.topics
                ]

        return C()

    def commit(self):
        pass

    def close(self):
        self.closed = True


def test_batch_run_writes_output_fields_and_does_not_mark_a_cut_topic(tmp_path, monkeypatch):
    topics = [dict(TOPIC, topic_id=f"t{i}", display_name=f"T{i}") for i in range(3)]
    conn = _FakeConn(topics)
    monkeypatch.setattr(ti, "_get_run_conn", lambda: conn)
    monkeypatch.setattr(ti, "_check_existing_count", lambda *a: 0)
    monkeypatch.setattr(ti, "_interval_gate_ok", lambda: True)
    monkeypatch.setattr(ti, "BATCH_LOCK_PATH", str(tmp_path / "batch.lock"))
    monkeypatch.setattr(ti, "RUN_RECEIPT", tmp_path / "topic_ingestion_run_latest.json")
    calls = {"n": 0}

    def fake_process(conn_, topic, **kw):
        calls["n"] += 1
        ti._RUN.start_topic()
        ti._RUN.admit()
        if calls["n"] == 2:
            ti._RUN._t0 -= 10_000  # the budget runs out inside topic 2
            ti._RUN.admit()
        return {
            "articles": 1,
            "transcripts": 0,
            "found": 3,
            "blocked": 0,
            "sources_used": [],
            "complete": not ti._RUN.topic_cut,
        }

    monkeypatch.setattr(ti, "process_topic", fake_process)
    rc = ti.main(
        [
            "--use-llm-queries",
            "--max-topics",
            "20",
            "--budget-s",
            "1500",
            "--max-items-per-topic",
            "12",
            "--no-auto-curate",
        ]
    )
    rec = json.loads((tmp_path / "topic_ingestion_run_latest.json").read_text())
    assert rc == 0 and rec["status"] == "ok"
    assert conn.updated == ["t0"]  # t1 was cut: its last_searched stays old, so the next run resumes it first
    assert rec["topics_cut"] == 1 and rec["topics_deferred"] == 1
    assert rec["produced_count"] == 2 and rec["attempted_count"] == 2 and rec["budget_exhausted"] is True
    assert rec["skipped_reasons"]["topic_deferred_budget"] == 1


def test_a_second_batch_run_skips_on_the_lock_with_a_receipt(tmp_path, monkeypatch):
    lock = tmp_path / "batch.lock"
    monkeypatch.setattr(ti, "BATCH_LOCK_PATH", str(lock))
    monkeypatch.setattr(ti, "RUN_RECEIPT", tmp_path / "r.json")
    with open(lock, "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc = ti.main(["--use-llm-queries"])
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rc == ti.EXIT_LOCK_BUSY == 75
    assert rec["status"] == "skipped" and rec["reason"] == "lock_busy" and rec["empty_reason"] == "lock_busy"


def test_sigterm_unwinds_through_the_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(ti, "BATCH_LOCK_PATH", str(tmp_path / "batch.lock"))
    monkeypatch.setattr(ti, "RUN_RECEIPT", tmp_path / "r.json")

    def killed(args, receipt):
        ti._on_sigterm(15, None)

    monkeypatch.setattr(ti, "_run", killed)
    with pytest.raises(SystemExit) as e:
        ti.main(["--use-llm-queries"])
    rec = json.loads((tmp_path / "r.json").read_text())
    assert e.value.code == 143 and rec["status"] == "failed" and rec["error"].startswith("SystemExit")
    src = (ROOT / "scripts/topic_ingestion.py").read_text()
    assert "signal.signal(signal.SIGTERM, _on_sigterm)" in src and "line_buffering=True" in src


# ── 1b. receipts: v2 output fields on the v1 document; compound aggregation ──────────────────────────────────────


def test_lane_receipt_output_fields_are_additive_and_validated(tmp_path):
    p = LR.write_lane_receipt(
        "x-lane",
        ok=True,
        exit_code=0,
        path=tmp_path / "x.json",
        output={
            "produced_count": "3",
            "attempted_count": -2,
            "skipped_reasons": {"a": 2, "b": "x"},
            "empty_reason": "",
            "output_evidence": [{"kind": "file"}, "junk"],
        },
    )
    doc = json.loads(p.read_text())
    assert doc["schema"] == "LaneRunReceipt@v1" and doc["status"] == "ok"
    assert doc["produced_count"] == 3 and doc["attempted_count"] == 0 and doc["skipped_reasons"] == {"a": 2}
    assert doc["empty_reason"] is None and doc["output_evidence"] == [{"kind": "file"}]
    assert doc["output_fields"] == "LaneRunReceipt@v2"
    plain = json.loads(LR.write_lane_receipt("y", ok=True, path=tmp_path / "y.json").read_text())
    assert "produced_count" not in plain  # no output given -> a v1 document exactly as before


def test_compound_receipt_counts_only_this_runs_step_receipts(tmp_path):
    fresh = tmp_path / "topic_ingestion_run_latest.json"
    fresh.write_text(
        json.dumps(
            {
                "finished_at": "2026-10-15T01:20:00+00:00",
                "produced_count": 7,
                "attempted_count": 30,
                "skipped_reasons": {"already_stored": 9},
            }
        )
    )
    stale = tmp_path / "old.json"
    stale.write_text(json.dumps({"finished_at": "2026-10-13T01:20:00+00:00", "produced_count": 99}))
    LR.write_lane_receipt("ri-narrative-enrich", ok=True, output={"produced_count": 4, "attempted_count": 5})
    out = ccr.aggregate_outputs(
        [str(fresh), str(stale), str(tmp_path / "missing.json"), "lane:ri-narrative-enrich"],
        "2026-10-15T00:30:00+00:00",
    )
    assert out["produced_count"] == 11 and out["attempted_count"] == 35
    assert out["skipped_reasons"] == {
        "topic_ingestion_run_latest:already_stored": 9,
        "step_receipt_stale:old": 1,
        "step_receipt_missing:missing": 1,
    }
    assert (
        ccr.main(["--lane", RI, "--exit", "0", "--since", "2026-10-15T00:30:00+00:00", "--output-receipt", str(fresh)])
        == 0
    )
    doc = json.loads(LR.receipt_path(RI).read_text())
    assert doc["status"] == "ok" and doc["produced_count"] == 7 and doc["started_at"] == "2026-10-15T00:30:00+00:00"


# ── 1c. the governed LLM path: registered, capped, no manual_trigger claim, no ungoverned call ──────────────────────


def test_the_three_processes_are_registered_capped_and_oauth_only():
    for pid in NEW_PROCESSES:
        p = LLM_REG[pid]
        assert p["default_mode"] == "automated" and p["allowed_lanes"] == ["grok", "chatgpt"], pid
        assert p["daily_soft_cap"] > 0 and 0 < p["daily_cost_cap_usd"] <= 0.25, pid
        assert set(ROUTING[pid]) >= {"primary", "secondary", "fallback", "cost_ceiling_usd"}, pid
    narr = (ROOT / "scripts/research_intelligence_narrative_enrich.py").read_text()
    assert 'PROCESS_ID = "ri_narrative_enrich"' in narr  # no manual_trigger: pinned by the behaviour test below
    syn = (ROOT / "scripts/topic_research_synthesizer.py").read_text()
    assert "llm_lane.generate(" not in syn and 'PROCESS_ID = "topic_research_synthesizer"' in syn


def test_synthesizer_calls_through_the_governed_helper_with_its_process_id(monkeypatch):
    seen = []
    fake = types.ModuleType("lib.governed_cloud_generation")

    def generate_cloud(prompt, **kw):
        seen.append(kw)
        raise RuntimeError("CLOUD_GENERATION_FAILED_CLOSED")

    fake.generate_cloud = generate_cloud
    monkeypatch.setitem(sys.modules, "lib.governed_cloud_generation", fake)
    syn = _load("topic_research_synthesizer_lane_repair_under_test", "scripts/topic_research_synthesizer.py")
    assert syn._synthesize("Roth conversion", "ctx") is None
    assert [k["lanes"] for k in seen] == [("grok",), ("chatgpt",)]
    assert {k["process_id"] for k in seen} == {"topic_research_synthesizer"}


def _narrative_world(monkeypatch, n_rows: int, gen):
    rows = [
        {
            "id": i,
            "topic": f"topic {i}",
            "summary": "s" * 50,
            "thesis": "",
            "symbol": None,
            "research_type": "x",
            "evidence_json": None,
        }
        for i in range(n_rows)
    ]
    db = types.ModuleType("db_adapter")
    db.USE_DB = True
    db._execute = lambda *a, **k: rows
    monkeypatch.setitem(sys.modules, "db_adapter", db)
    ri_mod = types.ModuleType("lib.research_intelligence")
    ri_mod.classify_text = lambda *a, **k: ["general"]
    monkeypatch.setitem(sys.modules, "lib.research_intelligence", ri_mod)
    writes = []
    w = types.ModuleType("lib.writers.hermes_research_writer")
    w.set_fields_by_id = lambda *a, **k: writes.append(k["ids"])
    monkeypatch.setitem(sys.modules, "lib.writers.hermes_research_writer", w)
    lane = types.ModuleType("llm_lane")
    lane.calls = []
    lane.available = lambda name: name in ("grok", "chatgpt")

    def generate(prompt, **kw):
        lane.calls.append(kw)
        return gen(kw)

    lane.generate = generate
    monkeypatch.setitem(sys.modules, "llm_lane", lane)
    mod = _load("narrative_enrich_lane_repair_under_test", "scripts/research_intelligence_narrative_enrich.py")
    return mod, lane, writes


def test_narrative_stops_at_the_first_governance_refusal(monkeypatch):
    def refuse(kw):
        raise RuntimeError("PROCESS_NOT_REGISTERED")

    mod, lane, writes = _narrative_world(monkeypatch, 25, refuse)
    assert mod.main(["--apply", "--limit", "25"]) == 1
    assert len(lane.calls) == 1 and writes == []  # was 25 rows x 2 lanes = 50 refused calls per run
    assert "manual_trigger" not in lane.calls[0] and lane.calls[0]["process_id"] == "ri_narrative_enrich"
    rec = json.loads(LR.receipt_path("ri-narrative-enrich").read_text())
    assert rec["status"] == "failed" and rec["skipped_reasons"] == {"governance_refused": 25}
    assert rec["produced_count"] == 0


def test_narrative_writes_and_counts(monkeypatch):
    good = json.dumps({"lede": "Lede", "executive_summary": "a\n\nb", "key_takeaways": ["k"]})
    mod, lane, writes = _narrative_world(monkeypatch, 3, lambda kw: good)
    assert mod.main(["--apply", "--limit", "3", "--budget-s", "600"]) == 0
    rec = json.loads(LR.receipt_path("ri-narrative-enrich").read_text())
    assert writes == [[0], [1], [2]] and rec["produced_count"] == 3 and rec["status"] == "ok"
    assert mod._lane_chain("auto") == ["grok", "chatgpt"] and "local" not in mod._lane_chain("local")


# ── 1d. the cron wrapper: bounded, one log copy, offline dry run ─────────────────────────────────────────────────


def test_overnight_wrapper_dry_run_is_offline_and_shows_the_bound(tmp_path):
    sh = ROOT / "scripts/run_research_intelligence_overnight.sh"
    assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0
    before = sorted(p.name for p in (ROOT / "logs").glob("*")) if (ROOT / "logs").is_dir() else []
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "PG"))}
    r = subprocess.run(
        ["bash", str(sh), "--phase", "full", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=30,
    )
    assert r.returncode == 0 and r.stdout.startswith("DRY-RUN run-research-intelligence-overnight phase=full")
    assert "budget 1500s inside timeout 30m" in r.stdout and "items/topic 12" in r.stdout
    assert "llm process ri_narrative_enrich" in r.stdout and not list((tmp_path / "state").rglob("*"))
    after = sorted(p.name for p in (ROOT / "logs").glob("*")) if (ROOT / "logs").is_dir() else []
    assert after == before
    src = sh.read_text()
    assert "| tee -a" not in src  # the cron redirect + tee wrote every line twice
    assert '--budget-s "$RI_INGEST_BUDGET_S"' in src and '--budget-s "$RI_NARRATIVE_BUDGET_S"' in src
    assert '--max-items-per-topic "$RI_INGEST_MAX_ITEMS_PER_TOPIC"' in src
    assert (
        'RI_INGEST_BUDGET_S="${RI_INGEST_BUDGET_S:-1500}"' in src
        and 'RI_INGEST_TIMEOUT="${RI_INGEST_TIMEOUT:-30m}"' in src
    )


# ── 2. hermes-coordinator: the purge skips FK-referenced rows and is bounded per pass ────────────────────────────


def test_retention_purge_never_deletes_a_row_a_foreign_key_still_points_at(monkeypatch):
    seen = []

    def managed_purge(conn, **kw):
        seen.append(kw)
        return {"eligible": 1, "deleted": 0}

    fake = types.ModuleType("lib.retention_archive")
    fake.managed_purge = managed_purge
    monkeypatch.setitem(sys.modules, "lib.retention_archive", fake)

    class Cur:
        rowcount = 0

        def execute(self, *a, **k):
            pass

    conn = types.SimpleNamespace(cursor=lambda: Cur(), commit=lambda: None)
    rcp.retention_purge(conn, apply=False)
    by_table = {kw["table"]: kw for kw in seen}
    w = by_table["watch_directives"]["where_sql"]
    assert "NOT EXISTS (SELECT 1 FROM strategy_watchpool c WHERE c.directive_id = t.id)" in w
    assert "NOT EXISTS (SELECT 1 FROM watchlist_items c WHERE c.directive_id = t.id)" in w
    h = by_table["hermes_research_intelligence"]["where_sql"]
    for child, col in (
        ("hermes_alerts", "related_research_id"),
        ("hermes_embedding_queue", "source_research_id"),
        ("hermes_memory_events", "related_research_id"),
    ):
        assert f"NOT EXISTS (SELECT 1 FROM {child} c WHERE c.{col} = t.id)" in h
    assert all(kw["max_rows"] == rcp.RETENTION_MAX_ROWS_PER_PASS == 2000 for kw in seen)
    assert "watch_directive_hits" not in json.dumps(rcp.PURGE_FK_CHILDREN)  # ON DELETE CASCADE: no guard needed


# ── 3. source litmus: a finding is not a failure; one tick or one noisy row does not BLOCK a source ──────────────


def test_one_tick_is_a_match_and_one_moderate_row_warns_not_blocks():
    out = lit.evaluate([("SRNE", "holdings", 0.0003)], {"SRNE": 0.0002})
    assert out["sources"]["holdings"]["within"] == 1 and out["block"] == []
    samples = [("XCUR", "finviz", 1.05)] + [(f"F{i}", "finviz", 10.0) for i in range(39)]
    ref = {"XCUR": 1.21, **{f"F{i}": 10.0 for i in range(39)}}
    out = lit.evaluate(samples, ref)
    assert out["block"] == [] and out["warn"] and out["warn"][0].startswith("finviz: 1/40")


def test_two_bad_rows_or_one_gross_row_still_block():
    samples = [("A", "market_quotes", 0.5652), ("B", "market_quotes", 23.39), ("C", "market_quotes", 4.09)] + [
        (f"M{i}", "market_quotes", 10.0) for i in range(111)
    ]
    ref = {"A": 0.07, "B": 20.42, "C": 4.7, **{f"M{i}": 10.0 for i in range(111)}}
    assert lit.evaluate(samples, ref)["block"][0].startswith("market_quotes: 3/114")  # the real 2026-10-14 finding
    gross = lit.evaluate([("XLI", "portfolio_repricer", 7.51)], {"XLI": 172.37})  # 2026-09-14 incident class
    assert gross["block"] and gross["warn"] == []


def _litmus_world(monkeypatch, tmp_path, samples, ref):
    class Conn:
        def cursor(self):
            return None

        def close(self):
            pass

    monkeypatch.setattr(lit, "_db", lambda: Conn())
    monkeypatch.setattr(lit, "_last_session", lambda cur: date(2026, 10, 14))
    monkeypatch.setattr(lit, "_sample", lambda cur, session, seed: samples)
    monkeypatch.setattr(lit, "_weekend_rows", lambda cur: [])
    monkeypatch.setattr(lit, "_yahoo_closes", lambda syms, session: ref)
    monkeypatch.setattr(lit, "RECEIPT", tmp_path / "source_litmus_last_run.json")


def test_a_block_finding_writes_an_ok_receipt_with_the_verdict(tmp_path, monkeypatch):
    samples = [("A", "market_quotes", 1.0), ("B", "market_quotes", 1.0), ("C", "market_quotes", 10.0)]
    _litmus_world(monkeypatch, tmp_path, samples, {"A": 2.0, "B": 2.0, "C": 10.0})
    assert lit.main([]) == 1  # systemd contract unchanged: SuccessExitStatus=0 1
    rec = json.loads(LR.receipt_path(LIT).read_text())
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["verdict"] == "BLOCK"
    assert rec["produced_count"] == 3 and rec["attempted_count"] == 3
    assert lit.main(["--exit-zero-on-block"]) == 0


def test_nothing_compared_is_not_nothing_wrong(tmp_path, monkeypatch):
    _litmus_world(monkeypatch, tmp_path, [("A", "market_quotes", 1.0)], {"A": 1.0})
    monkeypatch.setattr(lit, "_yahoo_closes", lambda syms, session: {"A": None})
    assert lit.main([]) == 0  # the typed soft skip
    rec = json.loads(LR.receipt_path(LIT).read_text())
    assert rec["status"] == "failed" and rec["produced_count"] == 0 and rec["empty_reason"] == "reference_unavailable"


# ── n8n SHADOW wiring (AGENTS 23.11/23.18/23.23; audit 2026-10-15: shadow only, no new LIVE cutover) ─────────────


def test_litmus_is_a_shadow_row_with_a_dry_run_only_entry():
    row, e = REGISTRY[LIT], ALLOW[LIT]
    assert row["scheduler"]["stage"] == "shadow" and row["dispatch"]["mode"] == "dry_run"
    assert row["dispatch"]["class"] == "monitor" and row["dispatch"]["cron"] == ["45 7 * * 2-6"]
    assert row["output_signal"] == {"kind": "json_key", "path": f"data/runtime/{LIT}_last.json", "key": "ok_at"}
    assert (
        e["live_arg"] is None
        and e["dry_run_arg"] == ["--dry-run"]
        and e["output_signal"] == row["output_signal"]["path"]
    )
    assert X.validate_entry(e) is None and LD.validate_dispatch_block(row) == []
    assert LD.r1_class_admission(row, e) == (True, "pre_r1_class")
    assert LIT not in ALLOW_DOC["blocked_reasons"] and LIT not in EFFECTS  # read-only: no append/send/llm effect
    assert not any(LIT in v for v in ALLOW_DOC["pending_tranches"].values() if isinstance(v, list))


def test_ri_is_staged_shadow_and_blocked_until_its_bridge_route_exists():
    row = REGISTRY[RI]
    pend = row["r1_pending"]
    assert pend["scheduler"]["stage"] == "shadow" and pend["dispatch"]["mode"] == "dry_run"
    assert pend["dispatch"]["class"] == "llm" and pend["output_signal"]["path"] == f"data/runtime/{RI}_last.json"
    assert "dispatch" not in row and RI not in ALLOW  # nothing fires until activation
    reason = ALLOW_DOC["blocked_reasons"][RI]
    assert "llm_process_route_not_registered" in reason and "live_arg null" in reason
    # the blocker is real: the entry the activation PR would add is refused by the executor today
    planned = {
        "lane_id": RI,
        "command": ["bash", "scripts/run_research_intelligence_overnight.sh", "--phase", "full"],
        "lock": "/tmp/ri_overnight_full.lock",
        "lock_kind": "flock",
        "timeout_s": 5400,
        "dry_run_arg": ["--dry-run"],
        "live_arg": None,
        "env_names": ["DB_HOST"],
        "env_allowlist_mode": "report",
        "env_report_reason": "x",
        "output_signal": f"data/runtime/{RI}_last.json",
        "llm_route": {"via": "cio-governed-bridge", "process_id": "topic_ingestion"},
    }
    assert X.validate_entry(planned) == "llm_process_route_not_registered"
    activated = dict(
        row,
        scheduler={**row["scheduler"], **pend["scheduler"]},
        output_signal=pend["output_signal"],
        dispatch=pend["dispatch"],
    )
    ok, why = LD.r1_class_admission(activated, planned, process_ids=NEW_PROCESSES)
    assert ok and why == "r1_admitted:llm"  # every other R1 condition already holds
    fx = EFFECTS[RI]
    assert set(fx["effects"]) == {"append", "llm"} and fx["cron_claim"] is False and fx["n8n_claim"] is False


def test_hermes_coordinator_is_excluded_with_its_reason():
    reason = ALLOW_DOC["blocked_reasons"][HC]
    assert "telegram_transport" in reason and "schwab_transport" in reason and HC not in ALLOW
    assert "dispatch" not in REGISTRY[HC]


@pytest.mark.parametrize("lane", [RI, LIT])
def test_contracts_are_reviewed_with_an_expected_output_rule(lane):
    c = CONTRACTS[lane]
    eo = c["expected_output"]
    assert c["status"] == "REVIEWED" and c["stage"] == "shadow" and "UNKNOWN" not in json.dumps(c)
    assert eo["schema"] == "N8nExpectedOutput@v1" and eo["produced_field"] == "produced_count"
    assert eo["rule"] in ("min_produced", "per_window") and eo["min_produced"] >= 1
    assert eo["on_violation"]["run_state"] == "RUN_FAILED" and eo["on_violation"]["reason"] == "empty_output"
    assert {"output_produced"} <= {h["check"] for h in c["healthy"]}
    assert {"empty_output"} <= {f["check"] for f in c["failed"]}


def test_lane_scripts_reach_no_sender_and_no_broker():
    from scripts.lib import advisory_lane_guard as G

    for entry in (
        "scripts/topic_ingestion.py",
        "scripts/research_intelligence_narrative_enrich.py",
        "scripts/topic_research_synthesizer.py",
        "scripts/source_litmus_vs_yahoo.py",
        "scripts/completion_compound_receipt.py",
    ):
        rep = G.scan_entry(entry)
        assert rep.problems() == [] and not rep.sends and not rep.direct_sends, (entry, rep.problems())
    coord = G.scan_entry("scripts/hermes_coordinator.py")
    assert coord.direct_sends and coord.problems()  # why it is excluded: pinned so a closure cut shows up here


def test_litmus_offline_dry_run_writes_nothing(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "PG"))}
    env["TRADEAI_STATE_ROOT"] = str(tmp_path / "state")
    r = subprocess.run(
        [sys.executable, "scripts/source_litmus_vs_yahoo.py", "--dry-run"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0 and r.stdout.startswith("DRY-RUN source-litmus-vs-yahoo")
    assert not (tmp_path / "state").exists()


def test_packet_candidate_changes_two_exact_lines_and_reverts_byte_identically():
    """C1+C2 only: C3/C4 (bound the standalone topic-ingestion lines) were absorbed by the C1 B-families
    consolidation, which retired those lines; the bound now lives in family_slot_jobs B2 (served code)."""
    pkt = _load(
        "lane_repair_candidate_under_test",
        "docs/ops/packets/lane-repair-run-research-intelligence-overnight-20261015/candidate.py",
    )
    assert [cid for cid, _old, _new in pkt.CHANGES] == ["C1", "C2"] and pkt.DROPPED == ("C3", "C4")
    assert not any("topic_ingestion" in old or "topic_ingestion" in new for _cid, old, new in pkt.CHANGES)
    live = ["# header", "PY=/x/python"] + [old for _cid, old, _new in pkt.CHANGES] + ["0 1 * * * true"]
    cand, problems = pkt.build(live)
    assert problems == [] and sum(a != b for a, b in zip(live, cand)) == 2
    assert cand[2].startswith("15 0 * * * ") and "run_with_deepseek_offpeak" not in cand[3]
    back, problems = pkt.build(cand, revert=True)
    assert problems == [] and back == live
    drifted, problems = pkt.build(live[:2] + live[3:])  # one target line missing -> refused, never half-applied
    assert problems and problems[0].startswith("C1:")


def test_topic_ingestion_bound_lives_in_the_family_job():
    """Where C3/C4's bound went: both topic-ingestion family modes carry it (served code, no crontab change)."""
    from scripts.lib import family_slot_jobs as fsj

    for mode in fsj.family("topic-ingestion").modes:
        assert mode.command.endswith("--max-topics 14 --budget-s 1500 --max-items-per-topic 12")
