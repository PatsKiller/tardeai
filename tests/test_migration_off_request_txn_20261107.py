"""MIGRATION_OFF_REQUEST_TXN_20261107 (LQ-20261107-270): migration DDL never rides the request cursor."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import redeploy_schema as rs  # noqa: E402


class Cur:
    def __init__(self, log, fail=False):
        self.log, self.fail = log, fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        if self.fail and "ALTER" in sql:
            raise RuntimeError("canceling statement due to lock timeout")
        self.log.append(sql.strip().split("\n")[0][:60])


class Conn:
    def __init__(self, log, fail=False):
        self.log, self.fail, self.closed = log, fail, False

    def cursor(self):
        return Cur(self.log, self.fail)

    def close(self):
        self.closed = True


def _reset():
    rs._done.clear()
    rs._next_try.clear()


def _file(tmp_path, name="m.sql"):
    p = tmp_path / name
    p.write_text("ALTER TABLE deploy_events ADD COLUMN IF NOT EXISTS x INT;")
    return p


def test_ddl_runs_on_side_connection_not_request_cursor(tmp_path):
    _reset()
    req, side = [], []
    conn = Conn(side)
    rs.run_migrations_once(Cur(req), "k1", (_file(tmp_path),), connect=lambda: conn)
    assert req == []
    assert any("ALTER TABLE" in s for s in side)
    assert any("pg_advisory_lock" in s for s in side) and any("pg_advisory_unlock" in s for s in side)
    assert conn.closed and "k1" in rs._done


def test_memo_skips_second_call(tmp_path):
    _reset()
    calls = []
    f = _file(tmp_path)
    rs.run_migrations_once(None, "k2", (f,), connect=lambda: calls.append(1) or Conn([]))
    rs.run_migrations_once(None, "k2", (f,), connect=lambda: calls.append(1) or Conn([]))
    assert len(calls) == 1


def test_failure_not_memoized_not_raised_and_backs_off(tmp_path):
    _reset()
    side, calls = [], []
    f = _file(tmp_path)
    def mk():
        calls.append(1)
        return Conn(side, fail=True)
    rs.run_migrations_once(None, "k3", (f,), connect=mk)
    assert "k3" not in rs._done
    rs.run_migrations_once(None, "k3", (f,), connect=mk)  # inside backoff
    assert len(calls) == 1
    assert any("pg_advisory_unlock" in s for s in side)


def test_connect_failure_swallowed(tmp_path):
    _reset()
    def boom():
        raise OSError("down")
    rs.run_migrations_once(None, "k4", (_file(tmp_path),), connect=boom)
    assert "k4" not in rs._done


def test_oversight_has_no_request_txn_ddl_fallback():
    src = (Path(__file__).resolve().parent.parent / "scripts/lib/redeploy_oversight.py").read_text()
    body = src.split("def ensure_oversight_schema", 1)[1].split("\ndef ", 1)[0]
    assert "cur.execute" not in body
