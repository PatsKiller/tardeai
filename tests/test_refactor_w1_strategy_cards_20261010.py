"""n8n refactor wave 1 (W2), 2026-10-10 — materialize_watchlist_strategy_cards.py (cron:L217).

``--dry-run`` builds every card on a READ ONLY session and returns before the upsert is reachable: the
upsert moved out of the per-symbol loop into one place after it (same SQL, same params, same single
commit), so the dry run and the real run compute identical cards. A real run writes a LaneRunReceipt@v1;
a crash writes status=failed and re-raises. Offline: a fake connection answers the SELECTs.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
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

import materialize_watchlist_strategy_cards as mat  # noqa: E402

COVERS = ["scripts/materialize_watchlist_strategy_cards.py"]


class _Cur:
    def __init__(self, db):
        self.db, self._rows, self._one = db, [], None

    def execute(self, sql, params=None):
        self.db.sql.append(sql)
        if "INSERT" in sql:
            if self.db.readonly:
                raise RuntimeError("cannot execute INSERT in a read-only transaction")
            self.db.inserts.append(params)
        elif "FROM watchlist_items" in sql:
            self._rows = [{"symbol": s} for s in self.db.symbols]
        elif "FROM ticker_prices" in sql:
            self._rows = [(10.0 + i * 0.1,) for i in range(30)]
        elif "FROM ticker_strategy_classifications" in sql:
            self._one = {"strategy_type": "core_index"}
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one

    def close(self):
        pass


class _Conn:
    def __init__(self, symbols):
        self.symbols, self.sql, self.inserts = symbols, [], []
        self.commits, self.readonly = 0, False

    def set_session(self, readonly=False, **_kw):
        self.readonly = readonly

    def cursor(self, cursor_factory=None):
        return _Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(mat, "STATE_DIR", tmp_path / "portfolio_state")  # absent files -> defaults
    db = {"conn": None, "symbols": ["AAA"]}

    def _get_conn():
        db["conn"] = _Conn(list(db["symbols"]))
        return db["conn"]

    monkeypatch.setattr(mat, "_get_conn", _get_conn)
    return {
        "db": db,
        "receipt": tmp_path / "state/data/runtime/materialize_watchlist_strategy_cards_last.json",
        "root": tmp_path,
    }


def _cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["materialize_watchlist_strategy_cards.py", *argv])
    return mat.cli()


def test_dry_run_reaches_no_insert_no_commit_no_receipt(env, monkeypatch, capsys):
    import lib.lane_last_receipt as llr

    monkeypatch.setattr(llr, "write_lane_receipt", lambda *a, **k: pytest.fail("receipt reached"))
    assert _cli(monkeypatch, "--dry-run") == 0
    conn = env["db"]["conn"]
    assert conn.readonly is True and conn.inserts == [] and conn.commits == 0
    assert not any("INSERT" in s for s in conn.sql)
    assert "DRY RUN: would upsert 1 cards" in capsys.readouterr().out
    assert not env["receipt"].exists()


def test_dry_run_mutation_tested_counts_follow_the_watchlist(env, monkeypatch, capsys):
    _cli(monkeypatch, "--dry-run")
    env["db"]["symbols"] = ["AAA", "BBB", "CCC"]
    _cli(monkeypatch, "--dry-run")
    out = capsys.readouterr().out
    assert "would upsert 1 cards" in out and "would upsert 3 cards" in out


def test_dry_run_and_real_run_compute_identical_cards(env):
    dry = mat.materialize(None, dry_run=True)
    real = mat.materialize(None)
    assert dry == real and len(env["db"]["conn"].inserts) == len(real) == 1
    assert env["db"]["conn"].commits == 1


def test_real_run_upserts_once_per_symbol_and_writes_receipt(env, monkeypatch):
    env["db"]["symbols"] = ["AAA", "BBB"]
    assert _cli(monkeypatch) == 0
    conn = env["db"]["conn"]
    assert [p[0] for p in conn.inserts] == ["AAA", "BBB"] and conn.commits == 1
    assert all(s == mat.UPSERT_SQL for s in conn.sql if "INSERT" in s)
    rc = json.loads(env["receipt"].read_text())
    assert rc["status"] == "ok" and rc["ok_at"] == rc["finished_at"] and rc["summary"]["cards"] == 2


def test_crash_writes_a_failed_receipt_and_reraises(env, monkeypatch):
    assert _cli(monkeypatch) == 0
    ok_at = json.loads(env["receipt"].read_text())["ok_at"]
    monkeypatch.setattr(mat, "load_catalysts", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    with pytest.raises(ValueError):
        _cli(monkeypatch)
    rc = json.loads(env["receipt"].read_text())
    assert rc["status"] == "failed" and rc["ok_at"] == ok_at and rc["summary"]["error"] == "ValueError"


def test_source_order_the_write_is_after_the_dry_run_return():
    src = inspect.getsource(mat.materialize)
    i_ret = src.index("if dry_run:\n        conn.rollback()")
    assert (
        src.index("return results", i_ret) < src.index("cur.execute(UPSERT_SQL, params)") < src.rindex("conn.commit()")
    )
    assert src.count("UPSERT_SQL") == 1 and "INSERT INTO" not in src  # the only write is the one after the loop


def test_state_dir_resolves_on_the_persistent_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    (tmp_path / "data/portfolios/state").mkdir(parents=True)
    assert mat._state_dir() == tmp_path / "data/portfolios/state"


def test_proposed_allowlist_argv_is_dispatcher_eligible():
    from tests.test_agents_policy_4_1_0_amendment import dispatcher_eligible

    entry = {
        "lane_id": "materialize-watchlist-strategy-cards",
        "command": ["$PY", "scripts/materialize_watchlist_strategy_cards.py"],
        "dry_run_arg": ["--dry-run"],
        "live_arg": [],
    }
    assert dispatcher_eligible(entry) == (True, "ok")
