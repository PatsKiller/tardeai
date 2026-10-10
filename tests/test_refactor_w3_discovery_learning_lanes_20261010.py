"""Refactor wave 3 (cron -> n8n, 2026-10-10), bucket X3: discovery + learning lanes.

Nine cron rows, one script each:
- research_watchlist_discovery.py (L858), sync_social_to_intelligence.py (L859), hermes_social_sentiment.py (L860),
  candidate_discovery_orchestrator.py (L861), drain_discovery_backlog.py (L862), build_lesson_candidates.py (L876),
  agent_outcome_scorer.py (L275): ``--dry-run`` wins over ``--apply``.
- desk_suggestions_digest.py (L863): ``--dry-run`` never reaches either receipt; a real run keeps the
  ScheduledJobReceipt@v1 contract file AND writes a LaneRunReceipt@v1.
- record_decision_outcome.py (L218): new ``--dry-run``; unknown args are now a usage error.

Per script: the dry run reaches no write (writers patched to raise, fake cursor records no INSERT/UPDATE/commit),
prints a DRY-RUN report, writes no receipt, and its DB session is READ ONLY; a real run writes a receipt with
ok_at; a failure exits non-zero and keeps the previous ok_at; source-ordering asserts where the guard order is
the bug class. Hermetic: fake connections and modules, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
import sys
import types
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Put THIS checkout first even if an earlier-collected module (e.g. health_agent) prepended another tree's
# scripts/ dir, and drop any copy of the modules under test that was imported from elsewhere.
_UNDER_TEST = (
    "agent_outcome_scorer",
    "candidate_discovery_orchestrator",
    "desk_suggestions_digest",
    "drain_discovery_backlog",
    "hermes_social_sentiment",
    "record_decision_outcome",
    "research_watchlist_discovery",
    "sync_social_to_intelligence",
    "scripts.build_lesson_candidates",
)
for _p in (str(ROOT), str(ROOT / "scripts")):
    while _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)
for _m in _UNDER_TEST:
    _f = getattr(sys.modules.get(_m), "__file__", None)
    if _f and not Path(_f).resolve().is_relative_to(ROOT):
        del sys.modules[_m]

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the real
# driver is absent, so the dry-run safety tests still run in CI instead of being skipped by importorskip.
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

import agent_outcome_scorer as aos  # noqa: E402
import candidate_discovery_orchestrator as cdo  # noqa: E402
import desk_suggestions_digest as dsd  # noqa: E402
import drain_discovery_backlog as ddb  # noqa: E402
import hermes_social_sentiment as hss  # noqa: E402
import record_decision_outcome as rdo  # noqa: E402
import research_watchlist_discovery as rwd  # noqa: E402
import sync_social_to_intelligence as sst  # noqa: E402

import scripts.build_lesson_candidates as blc  # noqa: E402

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

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, responder=None, fail_on=None):
        self.responder, self.fail_on = responder, fail_on
        self.sql, self.commits, self.readonly, self.closed, self.autocommit = [], 0, None, False, False

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
    raise AssertionError("dry run reached a write / fetch / telemetry path")


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


@pytest.fixture
def sources(monkeypatch):
    """Record report_source calls (data_source_health) instead of opening a DB connection."""
    calls = []
    fake = types.SimpleNamespace(report_source=lambda *a, **k: calls.append((a, k)))
    monkeypatch.setitem(sys.modules, "lib.data_source_report", fake)
    return calls


def _rpath(state, lane):
    return state / "data" / "runtime" / f"{lane}_last.json"


def _receipt(state, lane):
    return json.loads(_rpath(state, lane).read_text())


def _seed_ok(state, lane, ok_at="2026-10-01T00:00:00+00:00"):
    p = _rpath(state, lane)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": "LaneRunReceipt@v1", "lane_id": lane, "ok_at": ok_at}))
    return ok_at


def _dry_line(text):
    line = next(ln for ln in text.splitlines() if ln.startswith("DRY-RUN "))
    return json.loads(line[len("DRY-RUN ") :])


def _no_runtime_files(state):
    d = state / "data" / "runtime"
    return not d.exists() or not any(d.iterdir())


def _src(fn):
    """The function's code without its docstring (docstrings name the writers they promise not to reach)."""
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(getattr(node.body[0], "value", None), ast.Constant)
    ):
        node.body = node.body[1:]
    return ast.unparse(node)


# ── research_watchlist_discovery (L858) ──────────────────────────────────────────────────────────────
def _rwd_responder(n_research=3, listed=("AAA",)):
    def r(sql, params):
        if "FROM hermes_research_intelligence" in sql:
            return {"all": [(f"R{i}" if i else "AAA", "topic", "s", 0.9, "staged") for i in range(n_research)]}
        if "FROM social_sentiment_history" in sql:
            return {"all": [("SOC", 12, 0.7, True)]}
        if sql.startswith("SELECT symbol FROM watchlist_items"):
            return {"all": [(s,) for s in listed]}
        if sql.startswith("INSERT INTO watchlist_items"):
            return {"one": (True,)}
        return {}

    return r


def test_rwd_dry_run_wins_over_apply_and_writes_nothing(monkeypatch, capsys, _state, sources):
    conn = FakeConn(_rwd_responder())
    monkeypatch.setattr(rwd, "_get_conn", lambda: conn)
    monkeypatch.setattr(rwd, "_upsert", _boom)
    assert rwd.main(["--apply", "--dry-run"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["candidates"] == 4
    assert rep["summary"]["would_insert"] == 3 and rep["summary"]["would_refresh"] == 1
    assert conn.writes() == [] and conn.commits == 0 and conn.readonly is True
    assert sources == [] and _no_runtime_files(_state)


def test_rwd_dry_run_report_varies_with_state(monkeypatch, capsys):
    monkeypatch.setattr(rwd, "_get_conn", lambda: FakeConn(_rwd_responder(n_research=1, listed=())))
    assert rwd.main([]) == 0  # no --apply is still a dry run
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["candidates"] == 2 and rep["summary"]["would_insert"] == 2


def test_rwd_real_run_writes_receipt(monkeypatch, _state, sources):
    conn = FakeConn(_rwd_responder())
    monkeypatch.setattr(rwd, "_get_conn", lambda: conn)
    assert rwd.main(["--apply"]) == 0
    rec = _receipt(_state, "research-watchlist-discovery")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["written"] == 4
    assert any(s.startswith("INSERT INTO watchlist_items") for s in conn.sql)
    assert sources and sources[0][0][0] == "research_discovery"


def test_rwd_every_upsert_failed_exits_1_and_keeps_ok_at(monkeypatch, _state, sources):
    prev = _seed_ok(_state, "research-watchlist-discovery")
    monkeypatch.setattr(rwd, "_get_conn", lambda: FakeConn(_rwd_responder(), fail_on="INSERT INTO watchlist_items"))
    assert rwd.main(["--apply"]) == 1
    rec = _receipt(_state, "research-watchlist-discovery")
    assert rec["status"] == "failed" and rec["ok_at"] == prev and rec["summary"]["failed"] == 4


def test_rwd_db_unavailable_raises_with_failed_receipt(monkeypatch, _state):
    prev = _seed_ok(_state, "research-watchlist-discovery")

    def down():
        raise ConnectionError("db down")

    monkeypatch.setattr(rwd, "_get_conn", down)
    with pytest.raises(ConnectionError):
        rwd.main(["--apply"])
    rec = _receipt(_state, "research-watchlist-discovery")
    assert rec["status"] == "failed" and rec["ok_at"] == prev and rec["error"] == "ConnectionError"
    assert rwd.main(["--dry-run"]) == 1  # a dry run with no DB is a failed run too, and still no receipt write
    assert _receipt(_state, "research-watchlist-discovery")["ok_at"] == prev


def test_rwd_source_ordering():
    main = _src(rwd.main)
    assert main.index("return _dry_run(args)") < main.index("_upsert(")
    dry = _src(rwd._dry_run)
    for forbidden in ("_upsert(", ".commit(", "report_source", "write_lane_receipt"):
        assert forbidden not in dry


# ── sync_social_to_intelligence (L859) ───────────────────────────────────────────────────────────────
def _sst_env(monkeypatch, conn, universe=("AAA", "BBB"), upsert=None, universe_raises=False):
    def ru():
        if universe_raises:
            raise ImportError("no aegis")
        return [{"symbol": s} for s in universe]

    monkeypatch.setitem(sys.modules, "aegis_nightly_ingestion", types.SimpleNamespace(resolve_universe=ru))
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    calls = []

    def default_upsert(c, sym, kind, fields, source=None):
        calls.append(sym)
        return True

    monkeypatch.setitem(
        sys.modules, "intelligence_entity_manager", types.SimpleNamespace(upsert_entity=upsert or default_upsert)
    )
    return calls


def _sst_responder(rows=(("AAA", 0.5, 7), ("BBB", -0.4, 3))):
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)

    def r(sql, params):
        if "FROM social_sentiment_history" in sql:
            return {
                "description": [("symbol",), ("sentiment_score",), ("mention_count",), ("observed_at",)],
                "all": [(s, sc, m, now) for s, sc, m in rows],
            }
        return {}

    return r


def test_sst_dry_run_wins_and_never_reaches_upsert(monkeypatch, capsys, _state, sources):
    conn = FakeConn(_sst_responder())
    _sst_env(monkeypatch, conn, upsert=_boom)
    assert sst.main(["--apply", "--dry-run"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["would_fold"] == 2 and rep["summary"]["labels"] == {"bullish": 1, "bearish": 1}
    assert conn.readonly is True and conn.writes() == [] and sources == [] and _no_runtime_files(_state)


def test_sst_real_run_writes_receipt(monkeypatch, _state, sources):
    calls = _sst_env(monkeypatch, FakeConn(_sst_responder()))
    assert sst.main(["--apply"]) == 0
    assert calls == ["AAA", "BBB"]
    rec = _receipt(_state, "sync-social-to-intelligence")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["folded"] == 2
    assert sources[0][0][:2] == ("social", True)


def test_sst_every_fold_failed_exits_1(monkeypatch, _state, sources):
    prev = _seed_ok(_state, "sync-social-to-intelligence")
    _sst_env(monkeypatch, FakeConn(_sst_responder()), upsert=lambda *a, **k: False)
    assert sst.main(["--apply"]) == 1
    rec = _receipt(_state, "sync-social-to-intelligence")
    assert rec["status"] == "failed" and rec["ok_at"] == prev


def test_sst_no_fresh_sentiment_is_a_finding_not_a_failure(monkeypatch, _state, sources):
    _sst_env(monkeypatch, FakeConn(_sst_responder(rows=())))
    assert sst.main(["--apply"]) == 0
    assert _receipt(_state, "sync-social-to-intelligence")["summary"]["rows"] == 0


def test_sst_universe_failure_raises_with_failed_receipt(monkeypatch, _state, sources):
    prev = _seed_ok(_state, "sync-social-to-intelligence")
    _sst_env(monkeypatch, FakeConn(_sst_responder()), universe_raises=True)
    with pytest.raises(RuntimeError):
        sst.main(["--apply"])
    rec = _receipt(_state, "sync-social-to-intelligence")
    assert rec["status"] == "failed" and rec["ok_at"] == prev
    assert sst.main(["--dry-run"]) == 1


def test_sst_source_ordering():
    main = _src(sst.main)
    assert main.index("return _dry_run()") < main.index("upsert_entity")
    dry = _src(sst._dry_run)
    assert dry.index("enforce_readonly") < dry.index("resolve_universe()")
    for forbidden in ("upsert_entity(", "report_source", "write_lane_receipt"):
        assert forbidden not in dry


# ── hermes_social_sentiment (L860) ───────────────────────────────────────────────────────────────────
def _hss_env(monkeypatch, conn, universe=("AAA", "BBB", "CCC")):
    monkeypatch.setitem(
        sys.modules,
        "aegis_nightly_ingestion",
        types.SimpleNamespace(resolve_universe=lambda: [{"symbol": s} for s in universe]),
    )
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    monkeypatch.setattr(hss.time, "sleep", lambda *_: None)


def test_hss_dry_run_sends_no_searxng_and_persists_nothing(monkeypatch, capsys, _state, sources):
    conn = FakeConn()
    _hss_env(monkeypatch, conn)
    monkeypatch.setattr(hss, "_searxng", _boom)
    monkeypatch.setattr(hss, "search_forum", _boom)
    monkeypatch.setattr(hss, "persist", _boom)
    monkeypatch.setattr(hss.urllib.request, "urlopen", _boom)
    assert hss.main(["--apply", "--dry-run", "--max-symbols", "2"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["universe"] == 2 and rep["summary"]["would_fetch_searxng_queries"] == 6
    assert conn.readonly is True and sources == [] and _no_runtime_files(_state)


def test_hss_dry_run_varies_with_cap(monkeypatch, capsys):
    _hss_env(monkeypatch, FakeConn())
    monkeypatch.setattr(hss, "_searxng", _boom)
    assert hss.main(["--max-symbols", "3"]) == 0  # no --apply is still a dry run
    assert _dry_line(capsys.readouterr().out)["summary"]["would_fetch_searxng_queries"] == 9


def test_hss_real_run_writes_receipt(monkeypatch, _state, sources):
    _hss_env(monkeypatch, FakeConn())
    monkeypatch.setattr(
        hss,
        "_searxng",
        lambda q, categories="general": (
            hss._FETCH_STATS.__setitem__("ok", hss._FETCH_STATS["ok"] + 1),
            [{"url": f"https://reddit.com/{q}", "title": "bullish calls"}],
        )[1],
    )
    persisted = []
    monkeypatch.setattr(hss, "persist", lambda sym, s: persisted.append(sym) or True)
    assert hss.main(["--apply"]) == 0
    assert persisted == ["AAA", "BBB", "CCC"]
    rec = _receipt(_state, "hermes-social-sentiment")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["written"] == 3


def test_hss_every_searxng_request_failed_exits_1(monkeypatch, _state, sources):
    prev = _seed_ok(_state, "hermes-social-sentiment")
    _hss_env(monkeypatch, FakeConn())

    def down(*a, **k):
        raise OSError("searxng down")

    monkeypatch.setattr(hss.urllib.request, "urlopen", down)
    monkeypatch.setattr(hss, "persist", _boom)
    assert hss.main(["--apply"]) == 1
    rec = _receipt(_state, "hermes-social-sentiment")
    assert rec["status"] == "failed" and rec["ok_at"] == prev and rec["summary"]["searxng_errors"] == 9


def test_hss_source_ordering():
    main = _src(hss.main)
    assert main.index("return _dry_run(args)") < main.index("search_forum(")
    dry = _src(hss._dry_run)
    for forbidden in ("search_forum(", "_searxng(", "persist(", "report_source", "write_lane_receipt"):
        assert forbidden not in dry


# ── candidate_discovery_orchestrator (L861) ──────────────────────────────────────────────────────────
class _Src:
    def __init__(self, key, syms=(), boom=False):
        self.source_key, self.syms, self.boom, self.calls = key, syms, boom, 0

    def discover(self, conn, limit=50):
        self.calls += 1
        if self.boom:
            raise RuntimeError(f"{self.source_key} broke")
        return [{"symbol": s, "source_key": self.source_key, "reason": "r"} for s in self.syms]


def test_cdo_dry_run_skips_finviz_and_records_nothing(monkeypatch, capsys, _state, sources):
    conn = FakeConn()
    finviz = _Src("finviz")
    finviz.discover = _boom
    srcs = [finviz, _Src("incubator", ("AAA", "BBB")), _Src("news_catalyst", ("AAA",))]
    monkeypatch.setattr(cdo, "_get_conn", lambda: conn)
    monkeypatch.setattr(cdo, "_all_sources", lambda: srcs)
    monkeypatch.setattr(cdo, "_record_events", _boom)
    assert cdo.main(["--apply", "--dry-run"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["would_record"] == 3 and rep["summary"]["skipped_sources"] == ["finviz"]
    assert conn.readonly is True and conn.writes() == [] and sources == [] and _no_runtime_files(_state)


def test_cdo_real_run_records_and_writes_receipt(monkeypatch, _state, sources):
    conn = FakeConn()
    monkeypatch.setattr(cdo, "_get_conn", lambda: conn)
    monkeypatch.setattr(cdo, "_all_sources", lambda: [_Src("incubator", ("AAA",)), _Src("social_scalp", ())])
    assert cdo.main(["--apply"]) == 0
    assert sum(s.startswith("INSERT INTO candidate_discovery_events") for s in conn.sql) == 1
    rec = _receipt(_state, "candidate-discovery-orchestrator")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["recorded"] == 1


def test_cdo_every_source_raised_exits_1(monkeypatch, _state, sources):
    prev = _seed_ok(_state, "candidate-discovery-orchestrator")
    monkeypatch.setattr(cdo, "_get_conn", lambda: FakeConn())
    monkeypatch.setattr(cdo, "_all_sources", lambda: [_Src("incubator", boom=True), _Src("news_catalyst", boom=True)])
    assert cdo.main(["--apply"]) == 1
    rec = _receipt(_state, "candidate-discovery-orchestrator")
    assert rec["status"] == "failed" and rec["ok_at"] == prev


def test_cdo_record_failure_raises_with_failed_receipt(monkeypatch, _state, sources):
    prev = _seed_ok(_state, "candidate-discovery-orchestrator")
    monkeypatch.setattr(cdo, "_get_conn", lambda: FakeConn(fail_on="INSERT INTO candidate_discovery_events"))
    monkeypatch.setattr(cdo, "_all_sources", lambda: [_Src("incubator", ("AAA",))])
    with pytest.raises(RuntimeError):
        cdo.main(["--apply"])
    assert _receipt(_state, "candidate-discovery-orchestrator")["ok_at"] == prev


def test_cdo_source_ordering():
    main = _src(cdo.main)
    assert main.index("return _dry_run(args)") < main.index("_record_events(")
    dry = _src(cdo._dry_run)
    assert "skip=DRY_RUN_SKIP_SOURCES" in dry and "finviz" in cdo.DRY_RUN_SKIP_SOURCES
    for forbidden in ("_record_events(", "report_source", "write_lane_receipt"):
        assert forbidden not in dry


# ── drain_discovery_backlog (L862) ───────────────────────────────────────────────────────────────────
def _ddb_responder(n_promote=2, n_archive=3):
    def r(sql, params):
        if "status = 'CLUSTERED'" in sql:
            return {"all": [(i, f"p{i}", None) for i in range(n_promote)]}
        if "status IN ('DISCOVERED', 'CLUSTERED')" in sql:
            return {"all": [(100 + i, f"a{i}", "DISCOVERED") for i in range(n_archive)]}
        return {}

    return r


def test_ddb_dry_run_wins_over_apply(monkeypatch, capsys, _state):
    conn = FakeConn(_ddb_responder())
    monkeypatch.setattr(ddb, "_get_conn", lambda: conn)
    monkeypatch.setattr(ddb, "_transition", _boom)
    assert ddb.main(["--apply", "--dry-run"]) == 0  # before wave 3 this combination APPLIED
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["would_promote"] == 2 and rep["summary"]["would_archive"] == 3
    assert conn.writes() == [] and conn.commits == 0 and conn.readonly is True and _no_runtime_files(_state)


def test_ddb_dry_run_varies_with_promote_max(monkeypatch, capsys):
    seen = {}

    def r(sql, params):
        if "status = 'CLUSTERED'" in sql:
            seen["limit"] = params[0]
            return {"all": [(i, "p", None) for i in range(params[0])]}
        return {"all": []}

    monkeypatch.setattr(ddb, "_get_conn", lambda: FakeConn(r))
    assert ddb.main(["--promote-max", "4"]) == 0
    assert _dry_line(capsys.readouterr().out)["summary"]["would_promote"] == 4 and seen["limit"] == 4


def test_ddb_real_run_writes_receipt(monkeypatch, _state):
    conn = FakeConn(_ddb_responder())
    monkeypatch.setattr(ddb, "_get_conn", lambda: conn)
    assert ddb.main(["--apply"]) == 0
    assert sum(s.startswith("UPDATE hermes_discovery_candidates") for s in conn.sql) == 5
    assert sum(s.startswith("INSERT INTO hermes_discovery_audit") for s in conn.sql) == 5
    rec = _receipt(_state, "drain-discovery-backlog")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"] == {"promoted": 2, "archived": 3}


def test_ddb_failure_raises_with_failed_receipt(monkeypatch, _state):
    prev = _seed_ok(_state, "drain-discovery-backlog")
    conn = FakeConn(_ddb_responder(), fail_on="INSERT INTO hermes_discovery_audit")
    monkeypatch.setattr(ddb, "_get_conn", lambda: conn)
    with pytest.raises(RuntimeError):
        ddb.main(["--apply"])
    rec = _receipt(_state, "drain-discovery-backlog")
    assert rec["status"] == "failed" and rec["ok_at"] == prev and conn.commits == 0


def test_ddb_source_ordering():
    main = _src(ddb.main)
    assert main.index("return _dry_run(args)") < main.index("UPDATE hermes_discovery_candidates")
    dry = _src(ddb._dry_run)
    for forbidden in ("UPDATE hermes", "INSERT INTO", "_transition(", ".commit(", "write_lane_receipt"):
        assert forbidden not in dry


# ── desk_suggestions_digest (L863) ───────────────────────────────────────────────────────────────────
def _dsd_responder(pending=5):
    def r(sql, params):
        if "GROUP BY src" in sql:
            return {"all": [("desk", pending, datetime(2026, 10, 1, tzinfo=timezone.utc))]}
        if "ORDER BY surfaced_at DESC" in sql:
            return {"all": [("AAA", "desk", "reason", None)]}
        return {}

    return r


def test_dsd_dry_run_writes_neither_receipt(monkeypatch, capsys, _state):
    conn = FakeConn(_dsd_responder())
    monkeypatch.setattr(dsd, "_get_conn", lambda: conn)
    assert dsd.cli(["--dry-run", "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert "pending STAGED_FOR_REVIEW suggestions: 5" in out
    assert _dry_line(out)["summary"]["pending"] == 5
    assert conn.readonly is True and conn.writes() == [] and _no_runtime_files(_state)


def test_dsd_real_run_keeps_legacy_contract_and_adds_lane_receipt(monkeypatch, _state):
    monkeypatch.setattr(dsd, "_get_conn", lambda: FakeConn(_dsd_responder(pending=7)))
    assert dsd.cli([]) == 0
    legacy = json.loads((_state / "data" / "runtime" / "desk_suggestions_digest_last.json").read_text())
    assert legacy["schema"] == "ScheduledJobReceipt@v1" and legacy["exit"] == 0 and legacy["ok_at"]
    assert legacy["summary"]["pending"] == 7
    rec = _receipt(_state, "desk-suggestions-digest")
    assert rec["schema"] == "LaneRunReceipt@v1" and rec["status"] == "ok" and rec["summary"]["pending"] == 7


def test_dsd_receipt_override_still_works(monkeypatch, tmp_path, _state):
    monkeypatch.setattr(dsd, "_get_conn", lambda: FakeConn(_dsd_responder()))
    dest = tmp_path / "custom.json"
    assert dsd.cli(["--receipt", str(dest)]) == 0
    assert json.loads(dest.read_text())["exit"] == 0


def test_dsd_failure_exits_nonzero_with_failed_receipts(monkeypatch, _state):
    prev = _seed_ok(_state, "desk-suggestions-digest")

    def down():
        raise ConnectionError("db down")

    monkeypatch.setattr(dsd, "_get_conn", down)
    with pytest.raises(ConnectionError):
        dsd.cli([])
    rec = _receipt(_state, "desk-suggestions-digest")
    assert rec["status"] == "failed" and rec["ok_at"] == prev
    legacy = json.loads((_state / "data" / "runtime" / "desk_suggestions_digest_last.json").read_text())
    assert legacy["exit"] == 1 and legacy["ok_at"] is None


def test_dsd_usage_error_exits_2_before_any_receipt(monkeypatch, _state):
    monkeypatch.setattr(dsd, "_get_conn", _boom)
    with pytest.raises(SystemExit) as ei:
        dsd.cli(["--bogus"])
    assert ei.value.code == 2 and _no_runtime_files(_state)


def test_dsd_source_ordering():
    cli = _src(dsd.cli)
    assert cli.index("if args.dry_run:") < cli.index("run_with_receipt(")
    assert cli.index("return 0") < cli.index("run_with_receipt(")


# ── build_lesson_candidates (L876) ───────────────────────────────────────────────────────────────────
def _blc_root(tmp_path, monkeypatch, n=30, store=True):
    root = tmp_path / "prod"
    cio = root / "data" / "cio"
    cio.mkdir(parents=True)
    if store:
        (cio / "outcome_observations.jsonl").write_text(json.dumps({"observation_id": "o1"}) + "\n")
    (cio / "lesson_candidates.jsonl").write_text(json.dumps({"lesson_id": "L0", "scope": "OLD"}) + "\n")
    monkeypatch.setattr(blc, "_state_root", lambda: root)
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(cio))
    cands = [
        {"lesson_id": f"L{i}", "scope": f"S{i}", "task_class": "TRIM", "status": "PROVISIONAL", "statement": "x"}
        for i in range(n)
    ]
    monkeypatch.setattr(blc, "build_candidates", lambda obs, searched_counterexamples=True: [dict(c) for c in cands])
    monkeypatch.setattr(blc, "needs_outcome_provenance_amendment", lambda prev, cand: False)
    return root


def test_blc_dry_run_wins_over_apply(monkeypatch, tmp_path, capsys, _state):
    root = _blc_root(tmp_path, monkeypatch)
    before = (root / blc.LESSON_CANDIDATE_PATH).read_bytes()
    monkeypatch.setattr(blc, "_append", _boom)
    assert blc.main(["--apply", "--dry-run"]) == 0
    out = capsys.readouterr().out
    rep = _dry_line(out)
    assert rep["summary"]["candidates"] == 30 and rep["summary"]["would_append_new"] == 29
    assert "(+5 more candidates not listed" in out  # detail capped at 25
    assert (root / blc.LESSON_CANDIDATE_PATH).read_bytes() == before and _no_runtime_files(_state)


def test_blc_real_run_writes_receipt(monkeypatch, tmp_path, _state):
    root = _blc_root(tmp_path, monkeypatch, n=3)
    assert blc.main(["--apply"]) == 0
    assert len((root / blc.LESSON_CANDIDATE_PATH).read_text().splitlines()) == 3  # L0 kept + L1, L2 appended
    rec = _receipt(_state, "build-lesson-candidates")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["written"] == 2


def test_blc_missing_observation_store_exits_1(monkeypatch, tmp_path, _state):
    prev = _seed_ok(_state, "build-lesson-candidates")
    _blc_root(tmp_path, monkeypatch, store=False)
    assert blc.main(["--apply"]) == 1
    rec = _receipt(_state, "build-lesson-candidates")
    assert rec["status"] == "failed" and rec["ok_at"] == prev


def test_blc_append_failure_raises_with_failed_receipt(monkeypatch, tmp_path, _state):
    prev = _seed_ok(_state, "build-lesson-candidates")
    _blc_root(tmp_path, monkeypatch, n=3)

    def full(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(blc, "_append", full)
    with pytest.raises(OSError):
        blc.main(["--apply"])
    rec = _receipt(_state, "build-lesson-candidates")
    assert rec["status"] == "failed" and rec["ok_at"] == prev and rec["error"] == "OSError"


def test_blc_source_ordering():
    main = _src(blc.main)
    dry = main[main.index("if args.dry_run or not args.apply:") : main.index("lr = _receipt_lib()")]
    assert "run(apply=False)" in dry and "write_lane_receipt" not in dry and "apply=True" not in dry


# ── record_decision_outcome (L218) ───────────────────────────────────────────────────────────────────
def _rdo_responder(n_dec=2, n_uneval=3):
    def r(sql, params):
        if "FROM watchlist_final_synthesis" in sql:
            return {
                "all": [
                    {
                        "symbol": f"S{i}",
                        "recommendation": "BUY",
                        "confidence": 0.7,
                        "updated_at": date(2026, 10, 1),
                        "strategy_type": "x",
                        "latest_price": 10.0 if i else None,
                    }
                    for i in range(n_dec)
                ]
            }
        if "FROM decision_outcomes dout WHERE dout.evaluated_at IS NULL" in sql:
            return {
                "all": [
                    {"id": i, "symbol": "S", "created_at": date(2026, 9, 1), "price_at_decision": 10.0}
                    for i in range(n_uneval)
                ]
            }
        if "FROM ticker_prices" in sql:
            return {"one": {"close_price": 11.0}}
        return {}

    return r


def test_rdo_dry_run_reads_only(monkeypatch, capsys, _state):
    conn = FakeConn(_rdo_responder())
    monkeypatch.setattr(rdo, "_get_conn", lambda: conn)
    monkeypatch.setattr(rdo, "record_current_decisions", _boom)
    monkeypatch.setattr(rdo, "backfill_prices", _boom)
    assert rdo.main(["--dry-run", "--backfill"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"] == {"would_record": 2, "would_record_no_price": 1, "unevaluated": 3, "would_backfill": 3}
    assert conn.readonly is True and conn.writes() == [] and conn.commits == 0 and _no_runtime_files(_state)


def test_rdo_dry_run_varies_with_state(monkeypatch, capsys):
    monkeypatch.setattr(rdo, "_get_conn", lambda: FakeConn(_rdo_responder(n_dec=5)))
    assert rdo.main(["--dry-run"]) == 0
    assert _dry_line(capsys.readouterr().out)["summary"]["would_record"] == 5


def test_rdo_real_run_cron_form_writes_receipt(monkeypatch, _state):
    conn = FakeConn(_rdo_responder())
    monkeypatch.setattr(rdo, "_get_conn", lambda: conn)
    assert rdo.main([]) == 0
    assert sum(s.startswith("INSERT INTO decision_outcomes") for s in conn.sql) == 2 and conn.commits == 1
    rec = _receipt(_state, "record-decision-outcome")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"] == {"recorded": 2}


def test_rdo_failure_raises_with_failed_receipt(monkeypatch, _state):
    prev = _seed_ok(_state, "record-decision-outcome")
    monkeypatch.setattr(rdo, "_get_conn", lambda: FakeConn(_rdo_responder(), fail_on="INSERT INTO decision_outcomes"))
    with pytest.raises(RuntimeError):
        rdo.main([])
    rec = _receipt(_state, "record-decision-outcome")
    assert rec["status"] == "failed" and rec["ok_at"] == prev


def test_rdo_unknown_argument_is_usage_error(monkeypatch, _state):
    monkeypatch.setattr(rdo, "_get_conn", _boom)
    with pytest.raises(SystemExit) as ei:
        rdo.main(["--bogus"])
    assert ei.value.code == 2 and _no_runtime_files(_state)


def test_rdo_source_ordering():
    main = _src(rdo.main)
    assert main.index("if args.dry_run:") < main.index("record_current_decisions()")
    dry = _src(rdo.dry_run)
    assert dry.index("enforce_readonly") < dry.index("_select_decisions")
    for forbidden in (
        "INSERT INTO",
        "UPDATE decision_outcomes",
        "record_current_decisions(",
        "backfill_prices(",
        ".commit(",
        "write_lane_receipt",
    ):
        assert forbidden not in dry


# ── agent_outcome_scorer (L275) ──────────────────────────────────────────────────────────────────────
def _aos_responder(n_pairs=2, labels=2):
    def r(sql, params):
        if "FROM watchlist_agent_results war" in sql:
            return {
                "all": [
                    {
                        "war_id": i,
                        "agent_name": "maria",
                        "symbol": f"S{i}",
                        "recommendation": "BUY",
                        "confidence": 0.7,
                        "recommendation_date": date(2026, 9, 1),
                        "trade_id": i,
                        "entry_date": date(2026, 9, 2),
                        "exit_date": date(2026, 9, 20),
                        "entry_price": 10,
                        "exit_price": 12,
                        "realized_pnl": 2,
                        "pnl_pct": 20.0 if i else -12.0,
                    }
                    for i in range(n_pairs)
                ]
            }
        if "FROM stopped_out_watch" in sql:
            return {"all": []}
        if sql.startswith("SELECT COUNT(DISTINCT agent_name)"):
            return {"one": (1,)}
        if sql.startswith("SELECT COUNT(*) FROM agent_calibration"):
            return {"one": (1,)}
        if "FROM trade_ai_scans t" in sql:
            return {"all": [(f"lab{i}", 5, 2, 1, 1, 3.0) for i in range(labels)]}
        if sql.startswith("SELECT COUNT(*) FROM agent_recommendation_outcomes"):
            return {"one": (2,)}
        return {"all": [], "one": None}

    return r


class _Telemetry:
    entered = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        _Telemetry.entered.append(1)
        return self

    def __exit__(self, *a):
        return False

    def rows(self, n):
        pass


def test_aos_dry_run_wins_and_reaches_no_write_or_telemetry(monkeypatch, capsys, _state):
    conn = FakeConn(_aos_responder())
    monkeypatch.setattr(aos, "_get_conn", lambda: conn)
    monkeypatch.setattr(aos, "PipelineRun", _boom)
    for fn in ("save_outcomes", "rebuild_calibration", "write_calibration_to_rules", "update_source_performance"):
        monkeypatch.setattr(aos, fn, _boom)
    assert aos.main(["--apply", "--dry-run"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["unscored_pairs"] == 2 and rep["summary"]["verdicts"] == {"WRONG": 1, "CORRECT": 1}
    assert rep["summary"]["source_labels"] == 2
    assert conn.readonly is True and conn.writes() == [] and conn.commits == 0 and _no_runtime_files(_state)


def test_aos_apply_and_bare_are_live_and_write_receipt(monkeypatch, _state):
    _Telemetry.entered = []
    monkeypatch.setattr(aos, "PipelineRun", _Telemetry)
    for argv in (["--apply"], []):
        conn = FakeConn(_aos_responder())
        monkeypatch.setattr(aos, "_get_conn", lambda: conn)
        assert aos.main(argv) == 0
        assert sum(s.startswith("INSERT INTO agent_recommendation_outcomes") for s in conn.sql) == 2
    assert len(_Telemetry.entered) == 2
    rec = _receipt(_state, "agent-outcome-scorer")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["saved"] == 2


def test_aos_source_performance_failure_exits_1_and_keeps_ok_at(monkeypatch, _state):
    prev = _seed_ok(_state, "agent-outcome-scorer")
    monkeypatch.setattr(aos, "PipelineRun", _Telemetry)
    monkeypatch.setattr(aos, "_get_conn", lambda: FakeConn(_aos_responder(), fail_on="FROM trade_ai_scans t"))
    with pytest.raises(SystemExit) as ei:
        aos.main(["--apply"])
    assert ei.value.code == 1
    rec = _receipt(_state, "agent-outcome-scorer")
    assert rec["status"] == "failed" and rec["ok_at"] == prev and rec["summary"]["source_performance_ok"] is False


def test_aos_every_save_failed_exits_1(monkeypatch, _state):
    monkeypatch.setattr(aos, "PipelineRun", _Telemetry)
    monkeypatch.setattr(
        aos, "_get_conn", lambda: FakeConn(_aos_responder(), fail_on="INSERT INTO agent_recommendation_outcomes")
    )
    with pytest.raises(SystemExit) as ei:
        aos.main(["--apply"])
    assert ei.value.code == 1
    assert _receipt(_state, "agent-outcome-scorer")["summary"]["save_failed"] == 2


def test_aos_crash_raises_with_failed_receipt(monkeypatch, _state):
    prev = _seed_ok(_state, "agent-outcome-scorer")
    monkeypatch.setattr(aos, "PipelineRun", _Telemetry)

    def down():
        raise ConnectionError("db down")

    monkeypatch.setattr(aos, "_get_conn", down)
    with pytest.raises(ConnectionError):
        aos.main(["--apply"])
    rec = _receipt(_state, "agent-outcome-scorer")
    assert rec["status"] == "failed" and rec["ok_at"] == prev and rec["error"] == "ConnectionError"


def test_aos_source_ordering():
    main = _src(aos.main)
    assert main.index("if args.dry_run:") < main.index("PipelineRun(")
    dry = _src(aos.dry_run)
    assert dry.index("enforce_readonly") < dry.index("match_and_score")
    for forbidden in (
        "save_outcomes",
        "rebuild_calibration(",
        "write_calibration_to_rules(",
        "update_source_performance(",
        "PipelineRun(",
        ".commit(",
        "write_lane_receipt",
        "INSERT INTO",
    ):
        assert forbidden not in dry


def test_modules_under_test_come_from_this_checkout():
    for mod in (aos, cdo, dsd, ddb, hss, rdo, rwd, sst, blc):
        assert Path(mod.__file__).resolve().is_relative_to(ROOT), mod.__file__
