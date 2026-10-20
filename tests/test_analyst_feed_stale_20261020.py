"""Analyst feed stale 87 days (2026-10-20): pro_analyst_fetch spends its --max cap on what is due.

Reproduction: the fetch universe was ~2,340 symbols (2,299 directive-watch rows) against `--max 250`,
built as an unordered `SELECT DISTINCT` with held positions appended LAST, then cut with `syms[:mx]`.
The same ~250 symbols were refetched daily; held NVDA/PFLT/SPCX were last fetched 2026-07-25, so the
Communications drawer's "Analysts" fact showed 87-day-old Street targets.

Pins: held first, then actionable, then the directive backlog oldest-fetch-first, never-covered symbols
in a per-day rotation after covered ones, recently fetched symbols last; a held symbol beyond position
`--max` of the SQL universe is fetched; --dry-run stays read-only with no yfinance call.
Hermetic: fake DB connection and modules, tmp ROOT, no network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    sys.modules.setdefault("psycopg2", _pg)

NOW = datetime(2026, 10, 20, 10, 10, tzinfo=timezone.utc)
WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "ALTER", "DROP")


def _load():
    orig = Path.read_text

    def read_text(self, *a, **k):
        return "" if self.name == ".env" else orig(self, *a, **k)

    with mock.patch.object(Path, "read_text", read_text):
        spec = importlib.util.spec_from_file_location("paf_20261020", SCRIPTS / "pro_analyst_fetch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def paf():
    return _load()


def test_prioritize_order(paf):
    tiers = {
        "DIRNEW": paf.TIER_DIRECTIVE,  # directive, never covered
        "DIROLD": paf.TIER_DIRECTIVE,  # directive, fetched 90 days ago
        "DIRMID": paf.TIER_DIRECTIVE,  # directive, fetched 10 days ago
        "DIRFRESH": paf.TIER_DIRECTIVE,  # fetched 2 hours ago: not due
        "ACT": paf.TIER_ACTIONABLE,
        "NVDA": paf.TIER_HELD,  # held, 87 days stale
        "HELDFRESH": paf.TIER_HELD,  # held, fetched 2 hours ago: not due
    }
    last = {
        "DIROLD": NOW - timedelta(days=90),
        "DIRMID": NOW - timedelta(days=10),
        "DIRFRESH": NOW - timedelta(hours=2),
        "ACT": NOW - timedelta(days=3),
        "NVDA": NOW - timedelta(days=87),
        "HELDFRESH": NOW - timedelta(hours=2),
    }
    order = paf.prioritize(tiers, last, now=NOW, today="2026-10-20")
    assert order == ["NVDA", "ACT", "DIROLD", "DIRMID", "DIRNEW", "HELDFRESH", "DIRFRESH"]


def test_naive_timestamps_are_treated_as_utc(paf):
    naive = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    assert not paf.is_due(naive, NOW)
    assert paf.is_due(None, NOW)
    assert paf.is_due(NOW - timedelta(hours=paf.DUE_AFTER_HOURS + 1), NOW)


def test_never_covered_rotation_is_daily_and_deterministic(paf):
    tiers = {f"N{i:03d}": paf.TIER_DIRECTIVE for i in range(200)}
    a1 = paf.prioritize(tiers, {}, now=NOW, today="2026-10-20")
    a2 = paf.prioritize(tiers, {}, now=NOW, today="2026-10-20")
    b = paf.prioritize(tiers, {}, now=NOW, today="2026-10-21")
    assert a1 == a2 and a1 != b and sorted(a1) == sorted(b)
    # the first 25 slots are not the same set every day (no permanent starvation)
    assert set(a1[:25]) != set(b[:25])


class _Conn:
    """Fake connection: the universe query returns 300 directive symbols that are 1 day stale."""

    def __init__(self, universe, last):
        self.universe, self.last, self.sql, self.calls = universe, last, [], []

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                flat = " ".join(str(sql).split())
                conn.sql.append(flat)
                if "FROM yahoo_analyst_targets_history" in flat:
                    self._rows = [(s, ts) for s, ts in conn.last.items() if s in params[0]]
                elif "SELECT DISTINCT symbol" in flat:
                    self._rows = list(conn.universe)
                else:
                    self._rows = []

            def fetchall(self):
                return self._rows

        return C()

    def set_session(self, **kw):
        self.calls.append(("set_session", kw))

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        pass


class _YF:
    def __init__(self):
        self.symbols = []

    def Ticker(self, sym):  # noqa: N802 -- yfinance API name
        self.symbols.append(sym)
        return types.SimpleNamespace(info={"targetMeanPrice": 10.0, "numberOfAnalystOpinions": 3})


@pytest.fixture
def world(paf, monkeypatch, tmp_path):
    universe = [(f"D{i:03d}", 2) for i in range(300)] + [("ACT", 1)]
    last = {s: datetime.now(timezone.utc) - timedelta(days=1) for s, _ in universe}
    last["NVDA"] = datetime.now(timezone.utc) - timedelta(days=87)
    last["D299"] = datetime.now(timezone.utc) - timedelta(days=60)
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "holdings.json").write_text(json.dumps({"holdings": [{"symbol": "NVDA"}, {"symbol": "CASH", "is_cash": True}]}))
    paf.ROOT = tmp_path
    conn = _Conn(universe, last)
    monkeypatch.setattr(paf.psycopg2, "connect", lambda **kw: conn)
    save, report = mock.Mock(), mock.Mock()
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(save_yahoo_analyst_targets_history=save))
    monkeypatch.setitem(sys.modules, "lib.data_source_report", types.SimpleNamespace(report_source=report))
    monkeypatch.setattr("time.sleep", lambda s: None)
    yf = _YF()
    monkeypatch.setitem(sys.modules, "yfinance", yf)
    return paf, conn, save, yf


def test_held_symbol_past_the_cap_is_fetched(world):
    paf, conn, save, yf = world
    assert paf.main(["--max", "3"]) == 0
    # held first, then actionable, then the stalest directive symbol -- not the first 3 of the SQL result
    assert yf.symbols == ["NVDA", "ACT", "D299"]
    saved = [r["symbol"] for r in save.call_args.args[1]]
    assert saved == ["NVDA", "ACT", "D299"]
    assert not [s for s in conn.sql if s.upper().startswith(WRITE_PREFIXES)]


def test_dry_run_is_read_only_and_reports_the_batch(world, capsys):
    paf, conn, save, yf = world
    assert paf.main(["--max", "3", "--dry-run"]) == 0
    assert yf.symbols == [] and not save.called
    assert ("set_session", {"readonly": True}) in conn.calls
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["would_fetch_sample"] == ["NVDA", "ACT", "D299"]
    assert payload["held_in_batch"] == 1 and payload["actionable_in_batch"] == 1
    assert payload["directive_in_batch"] == 1
