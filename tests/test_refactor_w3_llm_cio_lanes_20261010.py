"""Refactor wave 3 (cron -> n8n, 2026-10-10), bucket X4: LLM, learning and CIO hygiene lanes.

- scripts/llm_intelligence_enrichment.py (cron L184/L185/L186, lane llm-intelligence-enrichment)
- scripts/feedback_loop_processor.py (cron L197, lane feedback-loop-processor)
- scripts/rag_indexer.py (cron L252, lane rag-indexer)
- scripts/journal_review_builder.py (cron L457, lane journal-review-builder)
- scripts/backfill_subject_identity.py (cron L926 ``--all --apply``, lane identity-sweep-stage0)
- scripts/drain_cio_stance_classification.py (cron L982 ``--apply``, lane cio-stance-classification-drain)
- scripts/cio_draft_plan_hygiene.py (cron L908 ``--apply``, lane cio-draft-plan-hygiene)

For each: --dry-run reaches no write and no model/embedding call (the writer / LLM is patched to raise),
prints a DRY-RUN report that varies with the input, writes no receipt; --dry-run wins over --apply; a
real run writes LaneRunReceipt@v1 with ok_at; the failure path exits non-zero (or re-raises) with a
failed receipt that keeps the previous ok_at; and the guard ordering is asserted in the source.
Hermetic: fake connections and modules, TRADEAI_STATE_ROOT = tmp. No DB, network or LLM.
"""

from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the
# real driver is absent, so the dry-run safety tests still run instead of being skipped.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
    import psycopg2.extras  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

# rag_retrieval imports numpy; rag_indexer only needs embed_text, which every test replaces.
try:  # pragma: no cover - depends on the environment
    import rag_retrieval  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _rr = types.ModuleType("rag_retrieval")
    _rr.embed_text = lambda _t: None
    sys.modules.setdefault("rag_retrieval", _rr)

import backfill_subject_identity as bsi  # noqa: E402
import cio_draft_plan_hygiene as hyg  # noqa: E402
import drain_cio_stance_classification as drain  # noqa: E402
import feedback_loop_processor as flp  # noqa: E402
import journal_review_builder as jrb  # noqa: E402
import llm_intelligence_enrichment as lie  # noqa: E402
import rag_indexer as rag  # noqa: E402

_DRAIN_RUN = drain.run  # the real drain; tests re-wire drain.run around it
_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "TRUNCATE")


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rowcount, self.description = conn, 1, None
        self._one, self._all = (0,), []

    def execute(self, sql, params=None):
        norm = " ".join(str(sql).split())
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
    raise AssertionError("dry run reached a write / LLM / embedding path")


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


def _receipt_file(state, lane):
    return state / "data" / "runtime" / f"{lane}_last.json"


def _receipt(state, lane):
    return json.loads(_receipt_file(state, lane).read_text())


def _dry_line(text):
    line = next(ln for ln in text.splitlines() if ln.startswith("DRY-RUN "))
    return json.loads(line[len("DRY-RUN ") :])


def _seed_ok(state, lane, ok_at="2026-10-09T00:00:00+00:00"):
    p = _receipt_file(state, lane)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": "LaneRunReceipt@v1", "lane_id": lane, "ok_at": ok_at}))
    return ok_at


# ── llm_intelligence_enrichment ─────────────────────────────────────────────


def _lie_setup(monkeypatch, tmp_path, prospects=0, conn=None):
    state = tmp_path / "pstate"
    state.mkdir(exist_ok=True)
    (state / "holdings.json").write_text(
        json.dumps({"holdings": [{"symbol": "AAA", "market_value": 5000}, {"symbol": "BBB", "market_value": 3000}]})
    )
    monkeypatch.setattr(lie, "STATE_DIR", state)
    monkeypatch.setattr(lie.time, "sleep", lambda *_: None)

    def responder(sql, params):
        if "FROM trade_ai_scans" in sql:
            return {"all": [(f"S{i}", 50, "GO", 10.0, "cat", "Tech", "Soft") for i in range(prospects)]}
        return {"all": [], "one": None}

    c = conn or FakeConn(responder)
    monkeypatch.setattr(lie, "_get_conn", lambda: c)
    return c


def test_lie_dry_run_reaches_no_llm_no_write_no_receipt(monkeypatch, tmp_path, capsys, _state):
    conn = _lie_setup(monkeypatch, tmp_path, prospects=2)
    monkeypatch.setattr(lie, "_llm_generate", _boom)
    monkeypatch.setattr(lie, "_save_cache", _boom)
    monkeypatch.setattr(lie, "ensure_cache_table", _boom)
    assert lie.main(["--dry-run"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["lane_id"] == "llm-intelligence-enrichment"
    s = rep["summary"]
    assert set(s["would_call_llm"]) == {
        "portfolio_risk",
        "rebalance_suggestions",
        "morning_synthesis",
        "prospect_narratives",
    }
    assert s["no_input"] == ["recovery_analysis"] and s["errors"] == {}
    assert s["plan"]["prospect_narratives"]["prospects"] == 2
    assert conn.readonly is True and conn.writes() == [] and conn.commits == 0
    assert not _receipt_file(_state, "llm-intelligence-enrichment").exists()


def test_lie_dry_run_report_varies_with_state(monkeypatch, tmp_path, capsys):
    _lie_setup(monkeypatch, tmp_path, prospects=0)
    monkeypatch.setattr(lie, "_llm_generate", _boom)
    lie.main(["--dry-run"])
    s0 = _dry_line(capsys.readouterr().out)["summary"]
    _lie_setup(monkeypatch, tmp_path, prospects=3)
    lie.main(["--dry-run"])
    s3 = _dry_line(capsys.readouterr().out)["summary"]
    assert "prospect_narratives" in s0["no_input"] and "prospect_narratives" not in s0["would_call_llm"]
    assert s3["plan"]["prospect_narratives"]["prospects"] == 3


def test_lie_real_run_writes_receipt(monkeypatch, tmp_path, _state):
    conn = _lie_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(lie, "is_valid_prose", lambda *a, **k: True)
    monkeypatch.setattr(lie, "extract_prose", lambda t: t)
    monkeypatch.setattr(lie, "_llm_generate", lambda *a, **k: "A concise and specific paragraph.")
    assert lie.main([]) == 0
    r = _receipt(_state, "llm-intelligence-enrichment")
    assert r["status"] == "ok" and r["ok_at"] and r["exit"] == 0
    assert "portfolio_risk" in r["summary"]["saved"]
    assert any(w.startswith("INSERT INTO llm_intelligence_cache") for w in conn.writes())


def test_lie_every_llm_section_failing_exits_1_and_keeps_ok_at(monkeypatch, tmp_path, _state):
    _lie_setup(monkeypatch, tmp_path)
    prev = _seed_ok(_state, "llm-intelligence-enrichment")

    def down(*a, **k):
        raise RuntimeError("CLOUD_GENERATION_FAILED_CLOSED: no governed cloud lane available")

    monkeypatch.setattr(lie, "_llm_generate", down)
    assert lie.main([]) == 1
    r = _receipt(_state, "llm-intelligence-enrichment")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["exit"] == 1
    assert set(r["summary"]["errors"]) == {"portfolio_risk", "rebalance_suggestions", "morning_synthesis"}


def test_lie_one_section_failing_is_not_a_run_failure(monkeypatch, tmp_path, _state):
    _lie_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(lie, "is_valid_prose", lambda *a, **k: True)
    monkeypatch.setattr(lie, "extract_prose", lambda t: t)

    def gen(prompt, timeout=120):
        if "risk analyst" in prompt:
            raise RuntimeError("CLOUD_GENERATION_FAILED_CLOSED")
        return "A concise and specific paragraph."

    monkeypatch.setattr(lie, "_llm_generate", gen)
    assert lie.main([]) == 0
    r = _receipt(_state, "llm-intelligence-enrichment")
    assert r["status"] == "ok" and r["summary"]["errors"] == {"portfolio_risk": "RuntimeError"}


def test_lie_db_down_exits_1_with_failed_receipt_and_unknown_section_is_usage(monkeypatch, _state):
    def no_db():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(lie, "_get_conn", no_db)
    assert lie.main(["--section", "nope"]) == 2
    assert not _receipt_file(_state, "llm-intelligence-enrichment").exists()
    assert lie.main(["--dry-run"]) == 1
    assert not _receipt_file(_state, "llm-intelligence-enrichment").exists()
    assert lie.main([]) == 1
    assert _receipt(_state, "llm-intelligence-enrichment")["status"] == "failed"


def test_lie_section_run_uses_its_own_lane_id(monkeypatch, tmp_path, _state):
    """cron L600 runs --section X; its receipt is lane llm-intelligence-enrichment-section, not the full lane's."""
    _lie_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(lie, "is_valid_prose", lambda *a, **k: True)
    monkeypatch.setattr(lie, "extract_prose", lambda t: t)
    monkeypatch.setattr(lie, "_llm_generate", lambda *a, **k: "A concise and specific paragraph.")
    assert lie.main(["--section", "morning_synthesis"]) == 0
    assert _receipt(_state, "llm-intelligence-enrichment-section")["summary"]["saved"] == ["morning_synthesis"]
    assert not _receipt_file(_state, "llm-intelligence-enrichment").exists()


def test_lie_source_order_dry_run_returns_before_llm():
    for fn in (
        lie.generate_portfolio_risk,
        lie.generate_rebalance_suggestions,
        lie.generate_recovery_analysis,
        lie.generate_morning_synthesis,
        lie.generate_prospect_narratives,
    ):
        src = inspect.getsource(fn)
        assert src.index("if dry_run:") < src.index("_llm_generate(") < src.index("_save_cache(")
        guard = src[src.index("if dry_run:") : src.index("_llm_generate(")]
        assert "return" in guard
    main_src = inspect.getsource(lie.main)
    assert main_src.index("enforce_readonly(conn)") < main_src.index("ensure_cache_table(conn)")
    assert main_src.index("if args.dry_run:\n        # AGENTS") < main_src.index("ensure_cache_table(conn)")


# ── feedback_loop_processor ─────────────────────────────────────────────────


def _flp_conn(n_props=2, fail_on=None):
    def responder(sql, params):
        if "FROM paper_trade_proposals p" in sql:
            return {
                "all": [
                    {
                        "id": i,
                        "symbol": f"S{i}",
                        "strategy_id": "x",
                        "status": "REJECTED",
                        "proposed_by": "a",
                        "created_at": "2026-10-01",
                    }
                    for i in range(n_props)
                ]
            }
        if "information_schema.columns" in sql:
            return {"one": None}
        if "FROM paper_trades" in sql:
            return {"one": None}
        return {"all": [], "one": None}

    return FakeConn(responder, fail_on=fail_on)


def test_flp_dry_run_no_write_report_varies_no_receipt(monkeypatch, capsys, _state):
    c2 = _flp_conn(2)
    monkeypatch.setattr(flp, "_get_conn", lambda: c2)
    assert flp.main(["--dry-run"]) == 0
    s2 = _dry_line(capsys.readouterr().out)["summary"]
    c5 = _flp_conn(5)
    monkeypatch.setattr(flp, "_get_conn", lambda: c5)
    assert flp.main(["--dry-run"]) == 0
    s5 = _dry_line(capsys.readouterr().out)["summary"]
    assert s2["proposal_chains_linked"] == 2 and s5["proposal_chains_linked"] == 5
    for c in (c2, c5):
        assert c.readonly is True and c.writes() == [] and c.commits == 0
    assert not _receipt_file(_state, "feedback-loop-processor").exists()


def test_flp_real_run_writes_receipt(monkeypatch, _state):
    c = _flp_conn(3)
    monkeypatch.setattr(flp, "_get_conn", lambda: c)
    assert flp.main([]) == 0
    r = _receipt(_state, "feedback-loop-processor")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["proposal_chains_linked"] == 3
    assert sum(1 for w in c.writes() if w.startswith("INSERT INTO proposal_outcome_chain")) == 3


def test_flp_step_failure_raises_with_failed_receipt_keeping_ok_at(monkeypatch, _state):
    prev = _seed_ok(_state, "feedback-loop-processor")
    c = _flp_conn(1, fail_on="FROM notification_log")
    monkeypatch.setattr(flp, "_get_conn", lambda: c)
    with pytest.raises(RuntimeError):
        flp.main([])
    r = _receipt(_state, "feedback-loop-processor")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["exit"] == 1
    assert r["summary"]["proposal_chains_linked"] == 1 and r["error"] == "RuntimeError"


def test_flp_dry_run_failure_exits_1_without_receipt(monkeypatch, _state):
    c = _flp_conn(1, fail_on="FROM notification_log")
    monkeypatch.setattr(flp, "_get_conn", lambda: c)
    assert flp.main(["--dry-run"]) == 1
    assert not _receipt_file(_state, "feedback-loop-processor").exists()


def test_flp_source_order_readonly_before_steps_and_writes_guarded():
    src = inspect.getsource(flp.main)
    assert src.index("enforce_readonly(conn)") < src.index("for key, label, fn in STEPS")
    for _, _, fn in flp.STEPS:
        body = inspect.getsource(fn)
        for verb in ("INSERT INTO", "UPDATE proposal_outcome_chain"):
            pos = body.find(verb)
            if pos >= 0:
                assert body.rfind("if not dry_run:", 0, pos) >= 0


# ── rag_indexer ─────────────────────────────────────────────────────────────


def _rag_conn(n_news=2, fail_on=None):
    def responder(sql, params):
        if "FROM news_articles" in sql and sql.startswith("SELECT sub.id"):
            return {"all": [(i, f"title {i} AAPL", f"title {i}", "2026-10-10") for i in range(n_news)]}
        return {"all": [], "one": (0,)}

    return FakeConn(responder, fail_on=fail_on)


def test_rag_dry_run_no_embed_no_write_report_varies(monkeypatch, capsys, _state):
    monkeypatch.setattr(rag, "embed_text", _boom)
    for n in (2, 4):
        c = _rag_conn(n)
        monkeypatch.setattr(rag, "_get_conn", lambda c=c: c)
        assert rag.main(["--source", "news,youtube", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert '"dry_run": true' in out.split("RAG_INDEXER_SUMMARY ", 1)[1].splitlines()[0]
        s = _dry_line(out)["summary"]
        assert s["would_index"] == n and s["sources"]["news"]["selected"] == n
        assert c.readonly is True and c.writes() == []
    assert not _receipt_file(_state, "rag-indexer").exists()


def test_rag_real_run_writes_receipt_from_summary(monkeypatch, _state):
    c = _rag_conn(3)
    monkeypatch.setattr(rag, "_get_conn", lambda: c)
    monkeypatch.setattr(rag, "embed_text", lambda t: [0.1, 0.2])
    monkeypatch.setitem(
        sys.modules, "intelligence_entity_manager", types.SimpleNamespace(upsert_entity=lambda *a, **k: None)
    )
    assert rag.main(["--source", "news"]) == 0
    r = _receipt(_state, "rag-indexer")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["total"] == 3
    assert r["summary"]["sources"]["news"]["indexed"] == 3
    assert sum(1 for w in c.writes() if w.startswith("INSERT INTO content_embeddings")) == 3


def test_rag_embedder_down_with_work_exits_1_keeping_ok_at(monkeypatch, _state):
    prev = _seed_ok(_state, "rag-indexer")
    c = _rag_conn(2)
    monkeypatch.setattr(rag, "_get_conn", lambda: c)
    monkeypatch.setattr(rag, "embed_text", lambda t: None)
    assert rag.main(["--source", "news"]) == 1
    r = _receipt(_state, "rag-indexer")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["summary"]["sources"]["news"]["embed_failed"] == 2


def test_rag_every_source_erroring_exits_1_nothing_to_do_exits_0(monkeypatch, _state):
    c = _rag_conn(0, fail_on="SELECT sub.id")
    monkeypatch.setattr(rag, "_get_conn", lambda: c)
    monkeypatch.setattr(rag, "embed_text", _boom)
    assert rag.main(["--source", "news,youtube"]) == 1
    assert _receipt(_state, "rag-indexer")["summary"]["source_errors"] == ["news", "youtube"]
    c0 = _rag_conn(0)
    monkeypatch.setattr(rag, "_get_conn", lambda: c0)
    assert rag.main(["--source", "news"]) == 0
    assert rag.main(["--source", "bogus"]) == 2


def test_rag_source_order_dry_run_continues_before_embed():
    src = inspect.getsource(rag.index_source)
    assert src.index("if dry_run:") < src.index("embed_text(") < src.index("INSERT INTO content_embeddings")
    main_src = inspect.getsource(rag.main)
    assert main_src.index("enforce_readonly(conn)") < main_src.index("index_source(")


# ── journal_review_builder ──────────────────────────────────────────────────


def _jrb_conn(n=2, reviewed=()):
    def responder(sql, params):
        if "FROM trades WHERE" in sql:
            cols = [
                "symbol",
                "account",
                "cd",
                "strategy_id",
                "entry_price",
                "exit_price",
                "shares",
                "pnl",
                "exit_reason",
            ]
            return {
                "description": [(c,) for c in cols],
                "all": [(f"S{i}", "paper", "2026-10-0%d" % (i + 1), "x", 10, 11, 5, 5, "target") for i in range(n)],
            }
        if "FROM journal_trade_reviews" in sql:
            return {"one": (1,) if params and params[0] in reviewed else None}
        return {}

    return FakeConn(responder)


def _fake_llm_lane(monkeypatch, generate):
    mod = types.ModuleType("llm_lane")
    mod.available = lambda lane: True
    mod.generate = generate
    monkeypatch.setitem(sys.modules, "llm_lane", mod)
    return mod


def test_jrb_dry_run_no_llm_no_write_report_varies(monkeypatch, capsys, _state):
    trap = types.ModuleType("llm_lane")
    trap.available = _boom
    trap.generate = _boom
    monkeypatch.setitem(sys.modules, "llm_lane", trap)
    c = _jrb_conn(3, reviewed={"S0:paper:2026-10-01"})
    monkeypatch.setattr(jrb, "_conn", lambda: c)
    assert jrb.main(["--dry-run"]) == 0
    s = _dry_line(capsys.readouterr().out)["summary"]
    assert s["would_review"] == 2 and s["skipped_existing"] == 1 and s["candidates"] == 3
    assert c.readonly is True and c.writes() == [] and c.commits == 0
    c5 = _jrb_conn(5)
    monkeypatch.setattr(jrb, "_conn", lambda: c5)
    assert jrb.main(["--dry-run"]) == 0
    assert _dry_line(capsys.readouterr().out)["summary"]["would_review"] == 5
    assert not _receipt_file(_state, "journal-review-builder").exists()


def test_jrb_real_run_writes_receipt(monkeypatch, _state):
    reply = json.dumps(
        {"setup": "s", "entry_grade": "B", "exit_grade": "A", "lesson": "l", "strengths": [], "mistakes": []}
    )
    _fake_llm_lane(monkeypatch, lambda *a, **k: reply)
    c = _jrb_conn(2)
    monkeypatch.setattr(jrb, "_conn", lambda: c)
    assert jrb.main([]) == 0
    r = _receipt(_state, "journal-review-builder")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["reviewed"] == 2
    assert sum(1 for w in c.writes() if w.startswith("INSERT INTO journal_trade_reviews")) == 2


def test_jrb_every_review_failing_exits_1_keeping_ok_at(monkeypatch, _state):
    prev = _seed_ok(_state, "journal-review-builder")

    def down(*a, **k):
        raise RuntimeError("lane down")

    _fake_llm_lane(monkeypatch, down)
    monkeypatch.setattr(jrb, "_conn", lambda: _jrb_conn(2))
    assert jrb.main([]) == 1
    r = _receipt(_state, "journal-review-builder")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["summary"]["failed"] == 2
    # nothing to review is not a failure
    monkeypatch.setattr(jrb, "_conn", lambda: _jrb_conn(1, reviewed={"S0:paper:2026-10-01"}))
    assert jrb.main([]) == 0


def test_jrb_source_order_dry_run_returns_before_llm_import():
    src = inspect.getsource(jrb.run)
    assert src.index("enforce_readonly(conn)") < src.index("pending_reviews(")
    guard = src.index("if dry_run:\n        # AGENTS")
    assert guard < src.index("return res") < src.index("import llm_lane") < src.index("INSERT INTO")


# ── backfill_subject_identity ───────────────────────────────────────────────


def _bsi_conn(symbols=("AAA",)):
    def responder(sql, params):
        if "information_schema.columns" in sql:
            return {"all": [(c,) for c, _ in bsi.IDENTITY_COLUMNS] + [("symbol",)]}
        if sql.startswith("SELECT DISTINCT symbol"):
            return {"all": [(s,) for s in symbols]}
        if "to_regclass" in sql:
            return {"all": [(None,)]}
        return {"rowcount": 2}

    return FakeConn(responder)


def _bsi_lookup(monkeypatch, fail=False):
    import scripts.lib.cio_subject_guid as csg

    def env(sym):
        if fail:
            return {"identity_lookup_failed": True, "identity_lookup_reason": "unreadable"}
        return {"subject_guid": f"g-{sym}", "issuer_guid": None, "identity_status": "CONFIRMED"}

    monkeypatch.setattr(csg, "lookup_identity_envelope", env)


def test_bsi_dry_run_wins_over_apply(monkeypatch, capsys, _state):
    _bsi_lookup(monkeypatch)
    c = _bsi_conn(("AAA", "BBB"))
    monkeypatch.setattr(bsi, "_db", lambda: c)
    assert bsi.main(["--all", "--apply", "--add-columns", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "apply=False" in out
    s = _dry_line(out)["summary"]
    assert s["resolved"] == 2 * len(bsi.TARGETS) and s["rows_stamped"] == 0
    assert c.readonly is True and c.writes() == [] and c.commits == 0
    c1 = _bsi_conn(("AAA",))
    monkeypatch.setattr(bsi, "_db", lambda: c1)
    assert bsi.main(["--all", "--apply", "--dry-run"]) == 0
    assert _dry_line(capsys.readouterr().out)["summary"]["resolved"] == len(bsi.TARGETS)
    assert not _receipt_file(_state, "identity-sweep-stage0").exists()


def test_bsi_real_run_receipt_has_rows_stamped(monkeypatch, _state):
    _bsi_lookup(monkeypatch)
    c = _bsi_conn(("AAA",))
    monkeypatch.setattr(bsi, "_db", lambda: c)
    assert bsi.main(["--all", "--apply"]) == 0
    r = _receipt(_state, "identity-sweep-stage0")
    assert r["status"] == "ok" and r["ok_at"]
    assert r["summary"]["rows_stamped"] == 2 * len(bsi.TARGETS)
    assert r["summary"]["unresolvable_rows"] == 2 * len(bsi.TARGETS)
    assert c.writes() and c.commits > 0


def test_bsi_registry_unreadable_raises_with_failed_receipt(monkeypatch, _state):
    prev = _seed_ok(_state, "identity-sweep-stage0")
    _bsi_lookup(monkeypatch, fail=True)
    c = _bsi_conn(("AAA",))
    monkeypatch.setattr(bsi, "_db", lambda: c)
    with pytest.raises(RuntimeError):
        bsi.main(["--all", "--apply"])
    r = _receipt(_state, "identity-sweep-stage0")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["exit"] == 1
    assert c.writes() == []
    assert bsi.main(["--all"]) == 1  # the same failure in a dry run: exit 1, no receipt change
    assert _receipt(_state, "identity-sweep-stage0")["status"] == "failed"


def test_bsi_source_order_apply_decided_before_connect():
    src = inspect.getsource(bsi.main)
    assert src.index("apply = bool(args.apply and not args.dry_run)") < src.index("conn = _db()")
    assert src.index("enforce_readonly(conn)") < src.index("backfill(cur")
    assert "args.apply" not in src.split("apply = bool(args.apply and not args.dry_run)", 1)[1]


# ── drain_cio_stance_classification ─────────────────────────────────────────


def _drain_wire(monkeypatch, *, write_fn, match_fn=None, n=2):
    ledger = [{"symbol": f"S{i}", "classification_requested": True, "as_of": "2026-10-10T00:00:00Z"} for i in range(n)]
    c = FakeConn()
    monkeypatch.setattr(drain, "_connect", lambda: c)
    orig = _DRAIN_RUN
    seams = {
        "state_fn": lambda conn, sym: {"active": False, "registry": {"swing"}, "scan": {"symbol": sym}},
        "match_fn": match_fn or (lambda scan: [{"strategy_id": "swing", "confidence": 0.7}]),
        "write_fn": write_fn,
        "rules_fn": lambda sym, apply, proposed=None: {"baseline_action": "HOLD"},
    }
    from datetime import datetime, timezone

    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(drain, "run", lambda **kw: orig(**kw, ledger_rows=ledger, now=now, **seams))
    return c


def test_drain_dry_run_wins_over_apply(monkeypatch, capsys, _state):
    c = _drain_wire(monkeypatch, write_fn=_boom, n=2)
    assert drain.main(["--apply", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[DRY-RUN] pending=2" in out
    s = _dry_line(out)["summary"]
    assert s["would_apply"] == ["S0", "S1"] and s["pending"] == 2
    assert c.readonly is True
    _drain_wire(monkeypatch, write_fn=_boom, n=3)
    drain.main(["--apply", "--dry-run"])
    assert _dry_line(capsys.readouterr().out)["summary"]["pending"] == 3
    assert not _receipt_file(_state, "cio-stance-classification-drain").exists()


def test_drain_real_run_writes_receipt(monkeypatch, _state):
    wrote = []
    _drain_wire(monkeypatch, write_fn=lambda conn, sym, *a: wrote.append(sym), n=2)
    assert drain.main(["--apply"]) == 0
    r = _receipt(_state, "cio-stance-classification-drain")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["applied"] == 2 and wrote == ["S0", "S1"]


def test_drain_every_request_erroring_exits_1_keeping_ok_at(monkeypatch, _state):
    prev = _seed_ok(_state, "cio-stance-classification-drain")

    def no_inputs(scan):
        raise RuntimeError("classifier_inputs_unavailable")

    _drain_wire(monkeypatch, write_fn=_boom, match_fn=no_inputs, n=2)
    assert drain.main(["--apply"]) == 1
    r = _receipt(_state, "cio-stance-classification-drain")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["summary"]["errors"] == 2
    _drain_wire(monkeypatch, write_fn=_boom, n=0)
    assert drain.main(["--apply"]) == 0  # pending=0 is not a failure


def test_drain_source_order_apply_decided_before_run():
    src = inspect.getsource(drain.main)
    assert src.index("apply = bool(args.apply and not args.dry_run)") < src.index("report = run(apply=apply")
    run_src = inspect.getsource(drain.run)
    assert run_src.index("enforce_readonly(conn)") < run_src.index("for req in todo")


# ── cio_draft_plan_hygiene ──────────────────────────────────────────────────


class FakeStore:
    def __init__(self, n=1, fail=False):
        self.fail, self.updated = fail, []
        self._plans = {
            f"p{i}": {
                "plan_id": f"p{i}",
                "status": "draft",
                "situation_type": "S1",
                "revisit_at": "2026-01-01T00:00:00Z",
            }
            for i in range(n)
        }

    def update_plan(self, pid, **kw):
        if self.fail:
            raise OSError("disk full")
        self.updated.append(pid)


def _hyg_store(monkeypatch, store):
    import scripts.lib.cio_plans as plans_mod

    monkeypatch.setattr(plans_mod, "CIOPlanStore", lambda *a, **k: store)


def test_hyg_dry_run_wins_over_apply(monkeypatch, capsys, _state):
    st = FakeStore(2)
    st.update_plan = _boom
    _hyg_store(monkeypatch, st)
    assert hyg.main(["--apply", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would_expire=2 expired=0 apply=False" in out
    assert _dry_line(out)["summary"]["would_expire"] == 2
    _hyg_store(monkeypatch, FakeStore(3))
    assert hyg.main(["--apply", "--dry-run"]) == 0
    assert _dry_line(capsys.readouterr().out)["summary"]["would_expire"] == 3
    assert not _receipt_file(_state, "cio-draft-plan-hygiene").exists()


def test_hyg_real_run_writes_receipt(monkeypatch, _state):
    st = FakeStore(2)
    _hyg_store(monkeypatch, st)
    assert hyg.main(["--apply"]) == 0
    r = _receipt(_state, "cio-draft-plan-hygiene")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"] == {"would_expire": 2, "expired": 2}
    assert st.updated == ["p0", "p1"]


def test_hyg_failure_raises_with_failed_receipt_keeping_ok_at(monkeypatch, _state):
    prev = _seed_ok(_state, "cio-draft-plan-hygiene")
    _hyg_store(monkeypatch, FakeStore(1, fail=True))
    with pytest.raises(OSError):
        hyg.main(["--apply"])
    r = _receipt(_state, "cio-draft-plan-hygiene")
    assert r["status"] == "failed" and r["ok_at"] == prev and r["error"] == "OSError"


def test_hyg_dry_run_refuses_a_store_that_would_rebuild(monkeypatch, tmp_path, capsys, _state):
    """The real CIOPlanStore() writes a projection when none is readable; a dry run must not construct it."""
    monkeypatch.chdir(tmp_path)
    assert hyg.main(["--apply", "--dry-run"]) == 1
    assert "would rebuild" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()
    assert not _receipt_file(_state, "cio-draft-plan-hygiene").exists()


def test_hyg_source_order_apply_decided_before_store():
    src = inspect.getsource(hyg.main)
    assert src.index("apply = bool(args.apply and not args.dry_run)") < src.index("store_preflight(")
    assert src.index("store_preflight(") < src.index("store = CIOPlanStore()")
    tail = src.split("apply = bool(args.apply and not args.dry_run)", 1)[1]
    assert "apply=args.apply" not in tail
