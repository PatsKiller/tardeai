"""Refactor wave 2 (cron -> n8n, 2026-10-10), bucket V4: catalyst lanes.

- scripts/catalyst_momentum_engine.py (cron L381, band overnight): --dry-run wins over --apply and
  --generate-proposals; it never connects to Postgres, stages nothing, spawns no auto_proposal_generator and
  writes no marker or receipt. Real runs leave a per-band receipt; a run whose every catalyst search errored
  exits 1; a search error entry is no longer counted (or staged) as a catalyst source.
- scripts/news_to_catalyst.py (cron L406): --dry-run is a READ ONLY session with deterministic
  classification only (allow_llm=False) and no INSERT; real runs leave a receipt.
Hermetic: fake connections and modules, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the real
# driver is absent, so the dry-run safety tests still run in CI instead of being skipped by importorskip.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    import types as _types

    _pg = _types.ModuleType("psycopg2")
    _pg_extras = _types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import catalyst_momentum_engine as cme  # noqa: E402
import news_to_catalyst as ntc  # noqa: E402
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


# ── catalyst_momentum_engine ─────────────────────────────────────────────────────────────────────────
def _engine_env(monkeypatch, search):
    cands = [{"symbol": "AAA", "rvol": 9.0, "gap_pct": 4}, {"symbol": "BBB", "rvol": 6.0, "gap_pct": 2}]
    monkeypatch.setitem(
        sys.modules,
        "hermes_momentum_candidate_reader",
        types.SimpleNamespace(get_momentum_candidates=lambda **k: cands),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_momentum_catalyst_researcher",
        types.SimpleNamespace(search_catalyst=search, classify_catalyst=lambda t: "earnings"),
    )
    monkeypatch.setattr(cme, "kill_active", lambda: False)
    monkeypatch.setenv("ALPACA_MODE", "paper")


def _three_sources(sym, q):
    return [{"title": f"{sym} beats", "content": "earnings", "url": f"https://x/{sym}/{i}"} for i in range(3)]


def test_engine_dry_run_reaches_no_db_writer_subprocess_marker_or_receipt(monkeypatch, capsys):
    _engine_env(monkeypatch, _three_sources)
    import subprocess

    import psycopg2

    import lib.writers.hermes_research_writer as hrw

    monkeypatch.setattr(psycopg2, "connect", _boom)
    monkeypatch.setattr(hrw, "write_research_rows", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(cme.subprocess, "run", _boom)
    monkeypatch.setattr(cme, "_write_last_run", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    monkeypatch.setattr(sys, "argv", ["x", "--band", "overnight", "--apply", "--generate-proposals", "--dry-run"])
    assert cme.main() == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["lane_id"] == "catalyst-momentum-engine-overnight"
    assert [w["symbol"] for w in rep["summary"]["would_stage"]] == ["AAA", "BBB"]
    assert rep["summary"]["would_attempt_proposals"] == ["AAA"]  # overnight prop_cap = 1
    assert any("auto_proposal_generator" in w for w in rep["would_write"])


def test_engine_dry_branch_comes_first_in_source():
    src = inspect.getsource(cme.main)
    assert src.index("if args.dry_run") < src.index("_run(args")
    dry = inspect.getsource(cme._dry_run)
    for forbidden in ("psycopg2", "write_research_rows", "subprocess.run", "_write_last_run(", "write_lane_receipt"):
        assert forbidden not in dry, forbidden


def test_usable_sources_drops_search_error_entries():
    assert cme._usable_sources([{"error": "timed out"}]) == ([], True)
    ok = [{"title": "t", "url": "u"}]
    assert cme._usable_sources(ok) == (ok, False)
    assert cme._usable_sources([]) == ([], False)


class _RC:
    def __init__(self, n):
        self.rows_written = n


def _engine_live(monkeypatch, search):
    _engine_env(monkeypatch, search)
    import psycopg2

    import lib.writers.hermes_research_writer as hrw

    staged = []
    monkeypatch.setattr(psycopg2, "connect", lambda **k: FakeConn())
    monkeypatch.setattr(hrw, "write_research_rows", lambda cur, rows, producer: staged.extend(rows) or _RC(len(rows)))
    marker = {}
    monkeypatch.setattr(cme, "_write_last_run", lambda payload: marker.update(payload) or None)
    monkeypatch.setattr(sys, "argv", ["x", "--band", "overnight", "--apply"])
    return staged, marker


def test_engine_real_run_writes_per_band_receipt(monkeypatch, _state):
    staged, marker = _engine_live(monkeypatch, _three_sources)
    assert cme.main() == 0
    assert [r["symbol"] for r in staged] == ["AAA", "BBB"] and marker["staged"] == 2
    rec = _receipt(_state, "catalyst-momentum-engine-overnight")
    assert rec["status"] == "ok" and rec["summary"]["staged"] == 2 and rec["summary"]["search_errors"] == 0


def test_engine_all_searches_errored_exits_1_and_stages_nothing(monkeypatch, _state):
    staged, _ = _engine_live(monkeypatch, lambda sym, q: [{"error": "HTTP Error 502"}])
    assert cme.main() == 1
    assert staged == []  # the error entry is not a source (it used to pass the accuracy gate)
    rec = _receipt(_state, "catalyst-momentum-engine-overnight")
    assert rec["status"] == "failed" and rec["summary"]["search_errors"] == 2 and rec["ok_at"] is None


def test_engine_no_catalyst_found_is_a_finding_not_a_failure(monkeypatch, _state):
    staged, _ = _engine_live(monkeypatch, lambda sym, q: [])
    assert cme.main() == 0 and staged == []
    assert _receipt(_state, "catalyst-momentum-engine-overnight")["status"] == "ok"


# ── news_to_catalyst ─────────────────────────────────────────────────────────────────────────────────
def _news_env(monkeypatch, rows, fail_on=None):
    def responder(sql, params):
        if sql.startswith("SELECT catalyst_type, base_weight"):
            return {"all": [("earnings_beat", 0.8)]}
        if sql.startswith("SELECT n.id"):
            return {"all": rows}
        if sql.startswith("INSERT INTO catalyst_events"):
            return {"one": (101,)}
        return None

    conn = FakeConn(responder, fail_on=fail_on)
    monkeypatch.setattr(ntc, "_get_conn", lambda: conn)
    seen = []

    def classify(title, summary, symbol, source=None, allow_llm=True):
        seen.append(allow_llm)
        return {
            "catalyst_type": "earnings_beat",
            "severity": "medium",
            "confidence": 0.7,
            "impact_score": 7.0,
            "method": "regex",
            "direction": "up",
        }

    monkeypatch.setitem(sys.modules, "catalyst_classifier", types.SimpleNamespace(classify=classify))
    monkeypatch.setitem(
        sys.modules,
        "lib.hermes_discovery.symbol_validation",
        types.SimpleNamespace(
            gate_catalyst_symbol=lambda s: (s != "JUNK", "x"), is_research_directive_slug=lambda s: False
        ),
    )
    return conn, seen


_ROWS = [
    (1, "AAA", "s", "AAA beats estimates", "", "rss", "u1", None),
    (2, "JUNK", "s", "junk", "", "rss", "u2", None),
    (3, "BBB", "s", "BBB raises guidance", "", "rss", "u3", None),
]


def test_news_dry_run_is_read_only_and_never_uses_the_llm(monkeypatch, capsys):
    conn, seen = _news_env(monkeypatch, _ROWS)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    monkeypatch.setenv("CATALYST_LLM_BUDGET", "25")
    assert ntc.main(["--dry-run", "--json"]) == 0
    assert conn.readonly is True and conn.commits == 0 and conn.writes() == []
    assert seen and not any(seen)
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert out["dry_run"] is True and out["would_create"] == 2 and out["created"] == 0
    assert out["skipped"]["not_in_ticker_universe"] == 1
    assert _dry_line(cap.err)["summary"]["would_create"] == 2


def test_news_dry_run_count_follows_the_data(monkeypatch, capsys):
    _news_env(monkeypatch, _ROWS[:1])
    assert ntc.main(["--dry-run"]) == 0
    assert _dry_line(capsys.readouterr().out)["summary"]["would_create"] == 1


def test_news_real_run_inserts_and_writes_receipt(monkeypatch, _state):
    conn, seen = _news_env(monkeypatch, _ROWS)
    assert ntc.main([]) == 0
    assert len([s for s in conn.writes() if s.startswith("INSERT INTO catalyst_events")]) == 2
    assert conn.commits >= 2 and all(seen)
    rec = _receipt(_state, "news-to-catalyst")
    assert rec["status"] == "ok" and rec["summary"]["created"] == 2


def test_news_crash_leaves_failed_receipt(monkeypatch, _state):
    _news_env(monkeypatch, _ROWS, fail_on="INSERT INTO catalyst_events")
    with pytest.raises(RuntimeError):
        ntc.main([])
    rec = _receipt(_state, "news-to-catalyst")
    assert rec["status"] == "failed" and rec["exit"] == 1 and rec["ok_at"] is None
