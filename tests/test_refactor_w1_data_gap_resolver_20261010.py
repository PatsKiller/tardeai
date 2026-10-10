"""n8n refactor wave 1 — data_gap_resolver.py (cron:L137 / L147 / L161).

Pins, without a database:
1. ``--dry-run`` cannot reach a mutation: the session is opened READ ONLY before any query, no
   writer transition / resolver action / chain resolve / abandon_stale is called, no INSERT or
   UPDATE is issued, nothing is committed, and no receipt is written.
2. A real run writes ``<state_root>/data/runtime/<lane_id>_last.json`` per cadence, with ok_at
   only on success; a failed run keeps the previous ok_at.
3. Exit codes: per-gap FAIL (the resolver could not help) is a finding (exit 0); an escaped
   exception, a crashed chain step, or every attempted gap raising is a failed run (exit 1).
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


def _load():
    import importlib.util

    key = "_tested_refactor_w1_data_gap_resolver"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ROOT / "scripts" / "data_gap_resolver.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load()


class ReadOnlyViolation(AssertionError):
    pass


class FakeCursor:
    """Records SQL; refuses writes once the owning connection is read-only (like Postgres)."""

    def __init__(self, conn, fetchone=None, fetchall=None):
        self.conn = conn
        self.calls: list[tuple[str, list | None]] = []
        self._one = list(fetchone or [])
        self._all = list(fetchall or [])
        self.rowcount = 1

    def execute(self, sql, params=None):
        flat = " ".join(str(sql).split())
        if self.conn.readonly and flat.split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE"):
            raise ReadOnlyViolation(flat)
        self.calls.append((flat, None if params is None else list(params)))

    def fetchone(self):
        return self._one.pop(0) if self._one else None

    def fetchall(self):
        return self._all.pop(0) if self._all else []


class FakeConn:
    def __init__(self, fetchone=None, fetchall=None):
        self.readonly = False
        self.set_session_before_cursor = None
        self.cur = None
        self._fetchone, self._fetchall = fetchone, fetchall
        self.commits = 0
        self.closed = False

    def set_session(self, readonly=False, **_kw):
        self.set_session_before_cursor = self.cur is None
        self.readonly = bool(readonly)

    def cursor(self):
        if self.cur is None:
            self.cur = FakeCursor(self, self._fetchone, self._fetchall)
        return self.cur

    def commit(self):
        if self.readonly:
            raise ReadOnlyViolation("commit on a dry run")
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def _boom(*_a, **_k):
    raise AssertionError("a dry run reached a mutation")


@pytest.fixture
def state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return tmp_path


def _arm_mutation_traps(monkeypatch):
    for name in (
        "mark_enriching",
        "mark_dispatched",
        "mark_resolved",
        "reopen",
        "abandon",
        "abandon_stale",
        "_requeue_source_job",
    ):
        monkeypatch.setattr(R, name, _boom)
    monkeypatch.setattr(R, "GAP_RESOLVERS", {k: _boom for k in R.GAP_RESOLVERS})
    monkeypatch.setattr(R, "_resolve_missing_catalyst", _boom)
    import scripts.lib.gap_resolver as G

    monkeypatch.setattr(G, "resolve", _boom)


def test_dry_run_opens_read_only_session_and_reaches_no_mutation(monkeypatch, state_root, capsys):
    _arm_mutation_traps(monkeypatch)
    conn = FakeConn(
        fetchone=[(4,)],  # would-abandon count
        fetchall=[
            [(9, "SCHG", "stale_news", "gap_1", "completed", "res-1", 0, False)],  # verify_dispatched
            [(1, "AAPL", "missing_sector", "d", None), (2, "NOC", "explicit", "d", 7)],  # open gaps
            [("NOC", "explicit", "2026-08-01")],  # persistent >7d
            [(2, "NOC", "explicit", "d")],  # chain catalyst-shaped opens
        ],
    )
    monkeypatch.setattr(R, "get_db_connection", lambda: conn)
    code = R.main(["--dry-run", "--weekly-audit"])
    assert code == 0
    assert conn.readonly is True and conn.set_session_before_cursor is True
    assert conn.commits == 0
    assert not [s for s, _ in conn.cur.calls if s.split(" ", 1)[0] in ("INSERT", "UPDATE", "DELETE")]
    out = capsys.readouterr().out
    assert "[DRY] AAPL: missing_sector -> would resolve" in out
    assert "would abandon 4 gaps older than 30 days" in out
    assert "[DRY chain] NOC" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("DRY-RUN "))
    report = json.loads(line[len("DRY-RUN ") :])
    assert report["lane_id"] == "data-gap-resolver-weekly"
    assert report["summary"]["would_abandon_30d"] == 4 and report["summary"]["resolved"] == 2
    assert not (state_root / "data").exists(), "a dry run wrote a receipt"


def test_dry_run_report_varies_with_state(monkeypatch, state_root, capsys):
    """Mutation test (§6): change the underlying rows, the report changes with them."""
    _arm_mutation_traps(monkeypatch)
    for gaps, expect in (([], 0), ([(1, "AAPL", "missing_sector", "d", None)] * 3, 3)):
        conn = FakeConn(fetchall=[[], gaps])
        monkeypatch.setattr(R, "get_db_connection", lambda c=conn: c)
        assert R.main(["--dry-run"]) == 0
        line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("DRY-RUN "))
        assert json.loads(line[8:])["summary"]["open_gaps"] == expect


def test_dry_run_gate_precedes_every_writer_in_source():
    """The ordering IS the bug class (§6, PR #1143): read-only session before the first query."""
    src = inspect.getsource(R.resolve_gaps)
    assert src.index("conn.set_session(readonly=True)") < src.index("verify_dispatched(")
    loop = src[src.index("for gap_id, symbol, gap_type, detail, source_job_id in gaps") :]
    assert loop.index("if dry_run:") < loop.index("mark_enriching(")
    weekly = src[src.index("if weekly_audit:") :]
    assert weekly.index("if dry_run:") < weekly.index("abandon_stale(")


@pytest.mark.parametrize(
    "argv,lane",
    [
        ([], "data-gap-resolver-at-0-10-16"),
        (["--pre-overnight"], "data-gap-resolver-pre"),
        (["--weekly-audit"], "data-gap-resolver-weekly"),
    ],
)
def test_real_run_writes_lane_receipt_with_ok_at(monkeypatch, state_root, argv, lane):
    conn = FakeConn(fetchall=[[], [(1, "AAPL", "missing_sector", "d", None)], [], [], []])
    monkeypatch.setattr(R, "get_db_connection", lambda: conn)
    monkeypatch.setattr(R, "GAP_RESOLVERS", {"missing_sector": lambda s, c: False})  # FAIL = finding
    monkeypatch.setattr(R, "abandon_stale", lambda cur, older_than_days: 0)
    assert R.main(argv) == 0
    doc = json.loads((state_root / "data" / "runtime" / f"{lane}_last.json").read_text())
    assert doc["schema"] == "LaneRunReceipt@v1" and doc["lane_id"] == lane
    assert doc["status"] == "ok" and doc["ok_at"] == doc["finished_at"]
    assert doc["summary"]["failed"] == 1 and doc["summary"]["errors"] == 0


def test_every_attempted_gap_raising_is_a_failed_run_and_keeps_previous_ok_at(monkeypatch, state_root):
    path = state_root / "data" / "runtime" / "data-gap-resolver-at-0-10-16_last.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok_at": "2026-10-09T15:00:00+00:00"}))

    def raises(_s, _c):
        raise RuntimeError("provider down")

    conn = FakeConn(fetchall=[[], [(1, "AAPL", "missing_sector", "d", None)], [], []])
    monkeypatch.setattr(R, "get_db_connection", lambda: conn)
    monkeypatch.setattr(R, "GAP_RESOLVERS", {"missing_sector": raises})
    assert R.main([]) == 1
    doc = json.loads(path.read_text())
    assert doc["status"] == "failed" and doc["exit"] == 1
    assert doc["ok_at"] == "2026-10-09T15:00:00+00:00"


def test_escaped_exception_exits_nonzero_with_failed_receipt(monkeypatch, state_root):
    def no_db():
        raise ConnectionError("db down")

    monkeypatch.setattr(R, "get_db_connection", no_db)
    assert R.main(["--pre-overnight"]) == 1
    doc = json.loads((state_root / "data/runtime/data-gap-resolver-pre_last.json").read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None and "ConnectionError" in doc["summary"]["error"]


def test_run_failed_semantics():
    assert R.run_failed({"attempted": 3, "errors": 0, "failed": 3}) is False  # findings only
    assert R.run_failed({"attempted": 0, "errors": 0}) is False
    assert R.run_failed({"attempted": 2, "errors": 2}) is True
    assert R.run_failed({"attempted": 2, "errors": 1}) is False
    assert R.run_failed({"chain_error": "ImportError: x"}) is True
