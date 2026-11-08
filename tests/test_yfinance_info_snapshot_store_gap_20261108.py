"""yfinance-info-snapshot: a dry run whose store was never migrated reports the gap and exits 0 (LQ-20261107-1247).

The lane's SHADOW slot runs ``--dry-run``. On this host the store table has never existed
(``to_regclass('public.yfinance_info_snapshot')`` is NULL; ``migrations/2026_10_10_yfinance_info_snapshot.sql``
is in the repo and unapplied), so every slot exited 1 ``unconfigured`` and the n8n executor filed a terminal dead
letter — five of them, the last at 2026-11-08T20:53:47Z. The dry run now follows the house rule already used by
``scripts/etf_analyst_enrich.py`` and ``scripts/classify_instruments.py``: name the required migration, write
nothing, exit 0. The ``--apply`` path is unchanged and still fails closed (exit 1, failed receipt) because the
writer cannot accept a row.

The rest of this file pins the two halves against each other so the gap cannot drift back:
* the dry run reads no universe and calls no provider (the apply path stops at the same check, so a probe would
  advertise a run that cannot store its answer);
* the probe behaviour with the store present is unchanged (at most ``--probe`` symbols).

Hermetic: synthetic ZZ* symbols, a stub DB, a fetch spy. No network, no psycopg2, no production state.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import yfinance_info_snapshot_refresh as yfr  # noqa: E402

NOW = datetime(2026, 11, 8, 14, 40, tzinfo=timezone.utc)
LID = "yfinance-info-snapshot"
MIGRATION = "migrations/2026_10_10_yfinance_info_snapshot.sql"


# ── fakes ────────────────────────────────────────────────────────────────────────────────────────────────────────
class FakeCursor:
    """Answers only the statements the lane issues; records every one so a test can prove what was read."""

    def __init__(self, db):
        self.db, self.description, self._rows, self.rowcount = db, None, [], 0

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.db.statements.append((s, params))
        self.description, self._rows, self.rowcount = None, [], 0
        if "to_regclass" in s:
            if self.db.probe_raises is not None:
                raise self.db.probe_raises
            self._set(["present"], [(self.db.table,)])
        elif s.startswith("SELECT symbol, fetched_at, status") and "FROM yfinance_info_snapshot" in s:
            if not self.db.table:
                raise RuntimeError('relation "yfinance_info_snapshot" does not exist')
            self._set(["symbol", "fetched_at", "status", "quote_type", "payload", "payload_keys", "error"], [])
        elif "FROM operator_starred_symbols" in s:
            self._set(["s", "at", "ref", "label"], [(w, None, None, None) for w in self.db.watch])
        else:
            self._set(["s", "at", "ref", "label"], [])

    def _set(self, cols, rows):
        self.description = [(c,) for c in cols]
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, *, table=True, watch=(), probe_raises=None):
        self.table, self.watch = table, list(watch)
        self.probe_raises = probe_raises
        self.statements, self.readonly, self.commits = [], None, 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _args(**kw):
    base = dict(ok_hours=20.0, negative_hours=168.0, max_symbols=300, sleep=0.25, probe=3)
    base.update(kw)
    return argparse.Namespace(**base)


def _state(tmp_path, held=("ZZA", "ZZB"), prospectus=("ZZP",)):
    st = tmp_path / "state"
    (st / "data/portfolios/state").mkdir(parents=True, exist_ok=True)
    (st / "data/portfolios/state/holdings.json").write_text(json.dumps({"holdings": [
        *[{"symbol": s, "shares": 10, "account": "fixture_brokerage"} for s in held],
        {"symbol": "SPAXX", "shares": 100, "account": "fixture_brokerage", "is_cash": True},
    ]}))
    (st / "data/prospectus").mkdir(parents=True, exist_ok=True)
    (st / "data/prospectus/universe.json").write_text(json.dumps({"items": [{"symbol": s} for s in prospectus]}))
    return st


def _fetch_spy(calls):
    def fetch(sym):
        calls.append(sym)
        return {"status": "ok", "quote_type": "EQUITY", "payload": {"quoteType": "EQUITY", "longName": f"{sym} Corp"}}
    return fetch


def _dry_run_lines(stdout: str) -> list[dict]:
    out = []
    for line in stdout.splitlines():
        if line.startswith("DRY-RUN "):
            out.append(json.loads(line[len("DRY-RUN "):]))
    return out


@pytest.fixture(autouse=True)
def _runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)


def _receipt(tmp_path):
    p = tmp_path / "state/data/runtime" / f"{LID}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


def _run(conn, tmp_path, *, apply, fetch=None, state=None):
    calls = []
    rc = yfr.run(apply=apply, state=state or _state(tmp_path),
                 connect=lambda ro: (setattr(conn, "readonly", ro) or conn),
                 fetch=fetch or _fetch_spy(calls), args=_args(),
                 now_fn=lambda: NOW, sleep_fn=lambda s: None)
    return rc, calls


# ── the gap: dry run reports it, writes nothing, calls no provider ───────────────────────────────────────────────
def test_dry_run_store_absent_exits_0_and_names_the_required_migration(tmp_path, capsys):
    conn = FakeConn(table=False)
    rc, calls = _run(conn, tmp_path, apply=False)
    out, err = capsys.readouterr()
    assert rc == 0
    assert calls == []                       # the provider is never touched
    assert conn.readonly is True             # ... and the session was opened READ ONLY
    assert conn.commits == 0
    assert _receipt(tmp_path) is None        # a dry run writes no receipt
    assert "STORE_ABSENT" in err and MIGRATION in err

    reports = _dry_run_lines(out)
    assert len(reports) == 1
    summary = reports[0]["summary"]
    assert reports[0]["would_write"] == []
    assert summary["store_present"] is False
    assert summary["required_migration"] == MIGRATION
    assert summary["provider_calls"] == 0
    assert MIGRATION in summary["detail"]


def test_dry_run_store_absent_reads_no_universe(tmp_path, capsys):
    """The apply path stops at the table check, so the dry run must not read the universe or the store."""
    conn = FakeConn(table=False, watch=["ZZW"])
    _run(conn, tmp_path, apply=False)
    capsys.readouterr()
    assert len(conn.statements) == 1, [s for s, _ in conn.statements]
    assert "to_regclass" in conn.statements[0][0]


def test_dry_run_store_absent_never_writes_the_output_signal(tmp_path, capsys):
    _run(FakeConn(table=False), tmp_path, apply=False)
    capsys.readouterr()
    signal = tmp_path / "state/data/runtime" / f"{LID}_last.json"
    assert not signal.exists()


# ── the other half: --apply is unchanged and fails closed ────────────────────────────────────────────────────────
def test_apply_store_absent_still_fails_closed_unconfigured(tmp_path, capsys):
    conn = FakeConn(table=False)
    rc, calls = _run(conn, tmp_path, apply=True)
    capsys.readouterr()
    r = _receipt(tmp_path)
    assert rc == 1 and calls == []
    assert r["status"] == "failed" and r["exit"] == 1
    assert r["summary"]["failure_kind"] == "unconfigured"
    assert MIGRATION in r["summary"]["detail"]
    assert r["produced_count"] == 0 and r["attempted_count"] == 0
    assert r["skipped_reasons"] == {"unconfigured": 1}


def test_store_check_error_is_dependency_unavailable_in_both_modes(tmp_path, capsys):
    for apply in (False, True):
        conn = FakeConn(probe_raises=RuntimeError("connection reset"))
        rc, calls = _run(conn, tmp_path, apply=apply)
        capsys.readouterr()
        assert rc == 1 and calls == []
    r = _receipt(tmp_path)
    assert r["status"] == "failed" and r["summary"]["failure_kind"] == "dependency_unavailable"


# ── the store-present path is unchanged ──────────────────────────────────────────────────────────────────────────
def test_dry_run_with_store_present_still_probes_at_most_three(tmp_path, capsys):
    conn = FakeConn(table=True, watch=["ZZW"])
    rc, calls = _run(conn, tmp_path, apply=False)
    out = capsys.readouterr().out
    assert rc == 0 and len(calls) == 3 and conn.readonly is True
    assert _receipt(tmp_path) is None
    report = _dry_run_lines(out)[0]
    assert report["would_write"] == ["table yfinance_info_snapshot", f"data/runtime/{LID}_last.json"]
    assert set(report["summary"]["probe"]) == set(calls)


def test_probe_zero_disables_the_provider_call(tmp_path, capsys):
    calls = []
    rc = yfr.run(apply=False, state=_state(tmp_path), connect=lambda ro: FakeConn(table=True),
                 fetch=_fetch_spy(calls), args=_args(probe=0), now_fn=lambda: NOW, sleep_fn=lambda s: None)
    capsys.readouterr()
    assert rc == 0 and calls == []


# ── the constant names a migration that really exists ────────────────────────────────────────────────────────────
def test_required_migration_constant_names_a_repo_file():
    assert yfr.MIGRATION == MIGRATION
    path = ROOT / MIGRATION
    assert path.is_file(), MIGRATION
    assert "yfinance_info_snapshot" in path.read_text(encoding="utf-8")
