"""LQ-20261107-1512 — the tax-sweep lane produces its own jobs; the 0 at 06:35:09 was dedupe.

Measured read-only on 2026-11-09 against the live DB (release `50d4c6c62`):

``pipeline_runs``::

    overnight_batch_tax  06:35:01.738  success  rows_produced 0   <- cron twin (L345)
    overnight_batch_tax  06:35:09.996  success  rows_produced 0   <- the n8n lane, 9 s later

``watchlist_agent_jobs`` (``submitted_from='tax_sweep'``): 4 rows, all created at 06:35:01.757 —
SRNE, SPCX, XAR (completed) and one CUSIP-shaped symbol (expired).

So the lane was not dead on its first n8n run: it queued 0 because the cron twin had queued the
same ``(symbol, request_type, requested_agent)`` work nine seconds earlier, and
``insert_agent_job_unless_pending`` dedups pending work by design (the key is the work, not the
row id — see scripts/lib/agent_job_queue.py). L345 is now retired (``crontab -l`` reads
``# RETIRED 2026-11-09 n8n-cutover overnight-batch-tax ...``), so the lane runs alone from its
next slot and its own count is the observable one.

This file pins that behaviour at the lane's own boundary with a recording fake connection: it
queues every holding with an unrealized loss worse than -$500 and every SSDI-flagged proposal when
nothing is pending, skips what is already pending, caps the holdings leg at ten, and invents
nothing. No DB, no network, no real holdings — synthetic symbols only; the repository is public.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import overnight_batch as ob  # noqa: E402

PENDING = ("queued", "pending", "processing")


class _State:
    """What the fake DB remembers: recent tax_agent results, SSDI proposals, pending work."""

    def __init__(self, recent=(), proposals=(), pending=()):
        self.recent = list(recent)
        self.proposals = list(proposals)
        self.pending = set(pending)
        self.queued: list[str] = []
        self.committed = False
        self.statements: list[str] = []


class _FakeCursor:
    def __init__(self, state: _State):
        self._state = state
        self._rows: list = []

    def execute(self, sql: str, params=None):
        self._state.statements.append(sql)
        if "FROM watchlist_agent_results" in sql:
            self._rows = [(s,) for s in self._state.recent]
        elif "FROM watchlist_proposals" in sql:
            self._rows = list(self._state.proposals)
        elif sql.startswith("INSERT INTO watchlist_agent_jobs"):
            # The guarded insert binds (id, symbol, requested_agent, request_type, note, status,
            # priority, submitted_from) then the WHERE key. The symbol is the first bound value
            # that names a symbol we know; reading it this way keeps the test independent of the
            # parameter order inside build_guarded_insert.
            symbol = next(p for p in (params or []) if isinstance(p, str) and p in self._symbols())
            if symbol in self._state.pending:
                self._rows = []          # WHERE NOT EXISTS matched: no row returned
            else:
                self._state.queued.append(symbol)
                self._rows = [(f"job-{symbol}",)]
        else:                            # any other statement returns nothing
            self._rows = []

    def _symbols(self) -> set[str]:
        return self._state.symbols

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, state: _State):
        self._state = state

    def cursor(self):
        return _FakeCursor(self._state)

    def commit(self):
        self._state.committed = True

    def close(self):
        pass


def _holdings(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "data" / "portfolios" / "state" / "holdings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"holdings": rows}))
    return p


def _run(monkeypatch, tmp_path, holdings: list[dict], state: _State):
    _holdings(tmp_path, holdings)
    state.symbols = {h["symbol"] for h in holdings if h.get("symbol")}
    state.symbols |= {sym for _, sym in state.proposals}
    monkeypatch.setattr(ob, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ob, "_get_conn", lambda: _FakeConn(state))
    return ob.run_tax_sweep()


class TestTheLaneQueuesItsOwnWork:
    def test_every_loss_past_the_threshold_is_queued(self, monkeypatch, tmp_path):
        state = _State()
        n = _run(monkeypatch, tmp_path, [
            {"symbol": "ZZQA", "gain_loss": -900.0},
            {"symbol": "ZZQB", "gain_loss": -501.0},
            {"symbol": "ZZQC", "gain_loss": -500.0},     # not "worse than" -500
            {"symbol": "ZZQD", "gain_loss": 1200.0},     # a gain is not a harvest
            {"symbol": "ZZQE"},                          # no measurement, no decision
        ], state)
        assert n == 2
        assert sorted(state.queued) == ["ZZQA", "ZZQB"]
        assert state.committed is True

    def test_work_already_pending_is_not_queued_again(self, monkeypatch, tmp_path):
        # The live 06:35:09 case: the same (symbol, request_type, tax_agent) work was already
        # pending from the cron twin nine seconds earlier, so every insert matched NOT EXISTS.
        state = _State(pending=("ZZQA", "ZZQB", "ZZQC"))
        n = _run(monkeypatch, tmp_path, [
            {"symbol": "ZZQA", "gain_loss": -900.0},
            {"symbol": "ZZQB", "gain_loss": -800.0},
            {"symbol": "ZZQC", "gain_loss": -700.0},
        ], state)
        assert n == 0 and state.queued == []
        assert state.committed is True          # a quiet run still closes its transaction

    def test_analysed_in_the_last_24h_is_skipped_before_the_insert(self, monkeypatch, tmp_path):
        state = _State(recent=("ZZQB",))
        n = _run(monkeypatch, tmp_path, [
            {"symbol": "ZZQA", "gain_loss": -900.0},
            {"symbol": "ZZQB", "gain_loss": -800.0},
        ], state)
        assert n == 1 and state.queued == ["ZZQA"]

    def test_the_holdings_leg_is_capped_at_ten(self, monkeypatch, tmp_path):
        rows = [{"symbol": f"ZZQ{i}", "gain_loss": -1000.0 - i} for i in range(14)]
        state = _State()
        n = _run(monkeypatch, tmp_path, rows, state)
        assert n == 10 and len(state.queued) == 10

    def test_ssdi_proposals_add_jobs_on_top_of_the_holdings_cap(self, monkeypatch, tmp_path):
        rows = [{"symbol": f"ZZQ{i}", "gain_loss": -1000.0 - i} for i in range(12)]
        state = _State(proposals=[(101, "ZZSP"), (102, "ZZSQ")])
        n = _run(monkeypatch, tmp_path, rows, state)
        assert n == 12                       # 10 from the holdings leg + 2 proposals
        assert state.queued[-2:] == ["ZZSP", "ZZSQ"]

    def test_no_holdings_file_and_no_proposals_queues_nothing(self, monkeypatch, tmp_path):
        state = _State()
        monkeypatch.setattr(ob, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(ob, "_get_conn", lambda: _FakeConn(state))
        assert ob.run_tax_sweep() == 0
        assert state.queued == []


class TestTheCountIsTheLanesOwnNumber:
    """The lane returns what it queued, so a caller cannot mistake a quiet run for a zero.

    (The caller's reporting is LQ-20261107-1539; this file only pins the lane's side of it.)
    """

    @pytest.mark.parametrize("pending,expected", [
        ((), 4),
        (("ZZQA",), 3),
        (("ZZQA", "ZZQB", "ZZQC", "ZZQD"), 0),
    ])
    def test_return_equals_the_rows_actually_inserted(self, monkeypatch, tmp_path, pending, expected):
        rows = [{"symbol": s, "gain_loss": -900.0} for s in ("ZZQA", "ZZQB", "ZZQC", "ZZQD")]
        state = _State(pending=pending)
        assert _run(monkeypatch, tmp_path, rows, state) == expected
        assert len(state.queued) == expected

    def test_the_return_is_not_a_constant(self, monkeypatch, tmp_path):
        # A hardcoded 0 (the defect behind the false alarm) would make these two answers equal.
        rows = [{"symbol": "ZZQA", "gain_loss": -900.0}]
        assert _run(monkeypatch, tmp_path, rows, _State()) == 1
        assert _run(monkeypatch, tmp_path, rows, _State(pending=("ZZQA",))) == 0
