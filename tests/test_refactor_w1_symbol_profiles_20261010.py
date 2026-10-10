"""Refactor wave 1 (cron -> n8n, 2026-10-10): the symbol-profile group.

- build_symbol_profiles.py (cron L508): --dry-run computes the stale universe on a READ ONLY session and
  returns before yfinance/Finviz are imported and before upsert/commit; a real run writes
  build_symbol_profiles[_watchlist]_last.json (ok_at only on success).
- refresh_symbol_cards.py (cron L502): --dry-run fetches + validates and never starts the profile
  subprocess (it writes symbol_profiles) or touches the cards file; --skip-profiles drops the embedded
  profile step; the no-flag cron form still runs both; a real run writes refresh_symbol_cards_last.json.
- fund_technicals_enrich.py (cron L552): the per-run ALTER TABLE is gone (migration file instead, a
  read-only column check in the script); --dry/--dry-run never reaches upsert/commit; a real run writes
  fund_technicals_enrich_last.json and exits 1 when every symbol failed.
Hermetic: fake DB modules via sys.modules, fake yfinance, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_symbol_profiles as bsp  # noqa: E402
import fund_technicals_enrich as fte  # noqa: E402
import refresh_symbol_cards as rsc  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


def _forbid(monkeypatch, obj, name):
    def boom(*a, **k):
        raise AssertionError(f"dry run reached {name}")

    monkeypatch.setattr(obj, name, boom)


class FakeConn:
    """Answers SELECTs by substring; records everything."""

    def __init__(self, answers):
        self.answers = answers  # list of (substring, rows)
        self.log: list = []

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                conn.log.append(("execute", " ".join(sql.split())))
                self._rows = next((rows for sub, rows in conn.answers if sub in sql), [])

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0] if self._rows else None

            @property
            def connection(self):
                return conn

        return C()

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def set_session(self, **kw):
        self.log.append(("set_session", kw))

    def close(self):
        self.log.append(("close",))

    def sqls(self):
        return [e[1] for e in self.log if e[0] == "execute"]


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


# ── build_symbol_profiles ───────────────────────────────────────────────────────────────────────
@pytest.fixture
def bsp_env(monkeypatch, state):
    conn = FakeConn(
        [
            ("FROM watchlist_items", [("CCC",)]),
            ("updated_at > now() - interval '30 days'", [("AAA",)]),
            ("COALESCE(source, '') = 'finviz'", []),
        ]
    )
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    monkeypatch.setitem(sys.modules, "watch_universe", types.SimpleNamespace(symbols=lambda cur: {"AAA", "BBB"}))
    monkeypatch.setitem(
        sys.modules, "holding_proxies", types.SimpleNamespace(HOLDING_PROXY_MAP={"401K-FUND": ("SPY", "Broad Equity")})
    )
    monkeypatch.setattr(bsp, "_profile_lane", lambda: {})
    monkeypatch.setattr(bsp, "_cio_ranked", lambda n: [])
    return conn


def test_bsp_dry_run_reaches_no_fetch_and_no_write(bsp_env, monkeypatch, capsys, state):
    monkeypatch.setitem(sys.modules, "yfinance", None)  # an import would raise ImportError
    _forbid(monkeypatch, bsp, "upsert_profile")
    _forbid(monkeypatch, bsp, "_finviz_map")
    _forbid(monkeypatch, llr, "write_receipt")
    assert bsp.main(["--watchlist-top", "300", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    # AAA is fresh; BBB + CCC (watchlist top) need fetching; the proxy code gets a label row.
    assert out["mode"] == "dry_run" and out["checked"] == 3
    assert out["would_fetch"] == 2 and out["would_upsert_proxy_labels"] == 1
    assert ("commit",) not in bsp_env.log
    assert ("set_session", {"readonly": True}) in bsp_env.log
    assert not state.exists()


def test_bsp_dry_run_report_tracks_state(bsp_env, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "yfinance", None)
    bsp.main(["--dry-run"])
    before = json.loads(capsys.readouterr().out)["checked"]
    bsp_env.answers[1] = ("updated_at > now() - interval '30 days'", [])  # nothing fresh any more
    bsp.main(["--dry-run"])
    after = json.loads(capsys.readouterr().out)["checked"]
    assert (before, after) == (2, 3)


def test_bsp_source_order_dry_run_returns_before_fetch_and_upsert():
    src = inspect.getsource(bsp.run)
    cut = src.index("conn.rollback()  # end the read transaction")
    assert cut < src.index("import yfinance as yf") < src.index("upsert_profile(cur, sym")


def _fake_yf(monkeypatch):
    class T:
        def __init__(self, s):
            self.info = {"longBusinessSummary": f"{s} makes things. It sells them.", "sector": "Tech"}

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))


def test_bsp_real_run_writes_lane_receipt(bsp_env, monkeypatch, state):
    _fake_yf(monkeypatch)
    monkeypatch.setattr(bsp, "_finviz_map", lambda uni: {})
    written = []
    monkeypatch.setattr(
        bsp,
        "upsert_profile",
        lambda cur, sym, f, source: written.append(sym) or types.SimpleNamespace(rows_written=1, rows_rejected=0),
    )
    assert bsp.main(["--watchlist-top", "300"]) == 0
    assert sorted(written) == ["401K-FUND", "BBB", "CCC"] and ("commit",) in bsp_env.log
    doc = json.loads((state / "data/runtime/build_symbol_profiles_watchlist_last.json").read_text())
    assert doc["status"] == "ok" and doc["ok_at"] and doc["summary"]["updated"] == 3


def test_bsp_failure_leaves_failed_receipt(bsp_env, monkeypatch, state):
    _fake_yf(monkeypatch)
    monkeypatch.setattr(bsp, "_finviz_map", lambda uni: {})

    def locked(*a, **k):
        raise RuntimeError("LockNotAvailable")

    monkeypatch.setattr(bsp, "upsert_profile", locked)
    with pytest.raises(RuntimeError):
        bsp.main(["--watchlist-top", "300"])
    doc = json.loads((state / "data/runtime/build_symbol_profiles_watchlist_last.json").read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None


def test_bsp_adhoc_symbols_run_writes_no_lane_receipt(bsp_env, monkeypatch, state):
    _fake_yf(monkeypatch)
    monkeypatch.setattr(bsp, "_finviz_map", lambda uni: {})
    monkeypatch.setattr(bsp, "upsert_profile", lambda *a, **k: types.SimpleNamespace(rows_written=1, rows_rejected=0))
    assert bsp.main(["--symbols", "ZZZ", "--force"]) == 0
    assert not (state / "data/runtime").exists()


# ── refresh_symbol_cards ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def rsc_env(monkeypatch, tmp_path, state):
    calls = []
    monkeypatch.setattr(rsc, "CARDS_FILE", tmp_path / "symbol_cards_latest.json")
    monkeypatch.setattr(rsc.time, "sleep", lambda s: calls.append(("sleep", s)))
    monkeypatch.setattr(
        rsc,
        "load_policy",
        lambda: {"materialize_timeout_s": 180.0, "materialize_retries": 1, "retry_backoff_s": 30.0, "min_cards": 30},
    )
    monkeypatch.setattr(
        rsc.subprocess,
        "run",
        lambda cmd, **k: calls.append(("subprocess", cmd)) or types.SimpleNamespace(stdout='{"updated": 0}', stderr=""),
    )
    outcomes = []

    def fetch(timeout_s, min_cards):
        calls.append(("fetch", timeout_s))
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    monkeypatch.setattr(rsc, "_fetch_cards", fetch)
    return {"calls": calls, "outcomes": outcomes, "cards": tmp_path / "symbol_cards_latest.json"}


def test_rsc_dry_run_fetches_and_validates_but_writes_nothing(rsc_env, monkeypatch, capsys, state):
    _forbid(monkeypatch, rsc.subprocess, "run")
    _forbid(monkeypatch, rsc.os, "replace")
    _forbid(monkeypatch, llr, "write_receipt")
    rsc_env["outcomes"].append((b'{"data":{"cards":{}}}', 3329))
    assert rsc.main(["--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["valid"] and out["cards"] == 3329
    assert not rsc_env["cards"].exists() and not state.exists()


def test_rsc_dry_run_reports_an_invalid_endpoint_and_exits_nonzero(rsc_env, monkeypatch, capsys):
    _forbid(monkeypatch, rsc.subprocess, "run")
    rsc_env["outcomes"].extend([ValueError("only 3 cards"), TimeoutError("timed out")])
    assert rsc.main(["--dry-run"]) == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["valid"] is False and "timed out" in out["error"]
    assert not rsc_env["cards"].exists()


def test_rsc_cron_form_still_runs_profiles_then_materializes_with_receipt(rsc_env, state):
    rsc_env["outcomes"].append((b"{}", 40))
    assert rsc.main([]) == 0
    kinds = [c[0] for c in rsc_env["calls"]]
    assert kinds == ["subprocess", "fetch"], "no-flag cron behaviour must be unchanged"
    assert rsc_env["calls"][0][1][1].endswith("scripts/build_symbol_profiles.py")
    doc = json.loads((state / "data/runtime/refresh_symbol_cards_last.json").read_text())
    assert doc["status"] == "ok" and doc["summary"]["cards"] == 40


def test_rsc_skip_profiles_drops_the_embedded_profile_step(rsc_env, state):
    rsc_env["outcomes"].append((b"{}", 40))
    assert rsc.main(["--skip-profiles"]) == 0
    assert [c[0] for c in rsc_env["calls"]] == ["fetch"]


def test_rsc_failed_materialize_exits_1_with_failed_receipt(rsc_env, state):
    rsc_env["cards"].write_text("old")
    rsc_env["outcomes"].extend([TimeoutError("t1"), TimeoutError("t2")])
    assert rsc.main(["--skip-profiles"]) == 1
    assert rsc_env["cards"].read_text() == "old"
    doc = json.loads((state / "data/runtime/refresh_symbol_cards_last.json").read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None


def test_rsc_profile_step_uses_the_release_safe_interpreter():
    assert "venv_python(ROOT)" in inspect.getsource(rsc._python)
    assert "sys.executable" not in inspect.getsource(rsc.build_profiles)


# ── fund_technicals_enrich ──────────────────────────────────────────────────────────────────────
class _Hist:
    def __init__(self, n=60):
        import datetime as dt

        self._closes = [10.0 + i * 0.1 for i in range(n)]
        self.index = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(n)]

    def __len__(self):
        return len(self._closes)

    def __getitem__(self, k):
        return types.SimpleNamespace(tolist=lambda: list(self._closes))


@pytest.fixture
def fte_env(monkeypatch, state):
    cols = [(c,) for c in fte.REQUIRED_COLUMNS]
    conn = FakeConn([("information_schema.columns", cols), ("instrument_type IN", [("FCNTX",), ("AMANX",)])])
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    monkeypatch.setattr(fte, "_holdings_path", lambda: Path("/nonexistent/holdings.json"))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    hist = {"FCNTX": _Hist(), "AMANX": _Hist(70)}

    class T:
        def __init__(self, s):
            self.s = s

        def history(self, **k):
            h = hist.get(self.s)
            if isinstance(h, Exception):
                raise h
            return h

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    return {"conn": conn, "hist": hist}


@pytest.mark.parametrize("flag", ["--dry", "--dry-run"])
def test_fte_dry_run_reaches_no_write(fte_env, monkeypatch, capsys, state, flag):
    _forbid(monkeypatch, fte, "upsert_profile")
    _forbid(monkeypatch, llr, "write_receipt")
    assert fte.main([flag]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["computed"] == 2
    assert out["would_write"] == {"table": "symbol_profiles", "rows": 2}
    log = fte_env["conn"].log
    assert ("commit",) not in log and ("set_session", {"readonly": True}) in log
    assert not any("ALTER" in s.upper() for s in fte_env["conn"].sqls())
    assert not state.exists()


def test_fte_no_per_run_ddl_left_in_the_script():
    src = (ROOT / "scripts" / "fund_technicals_enrich.py").read_text()
    code = src.split('"""', 2)[2]  # skip the module docstring that explains the removal
    assert "ADD COLUMN" not in code and "ensure_columns" not in code
    mig = ROOT / fte.MIGRATION
    assert mig.is_file() and all(c in mig.read_text() for c in fte.REQUIRED_COLUMNS)
    assert "ADD COLUMN IF NOT EXISTS" in mig.read_text()


def test_fte_missing_columns_exit_2_naming_the_migration(fte_env, capsys, state):
    fte_env["conn"].answers[0] = ("information_schema.columns", [("rsi14",)])
    assert fte.main([]) == 2
    assert fte.MIGRATION in capsys.readouterr().out
    doc = json.loads((state / "data/runtime/fund_technicals_enrich_last.json").read_text())
    assert doc["status"] == "failed"


def test_fte_real_run_upserts_commits_and_writes_ok_receipt(fte_env, monkeypatch, state):
    written = []
    monkeypatch.setattr(
        fte,
        "upsert_profile",
        lambda cur, s, f, **k: written.append(s) or types.SimpleNamespace(rows_written=1, rejected=[]),
    )
    assert fte.main([]) == 0
    assert written == ["AMANX", "FCNTX"] and ("commit",) in fte_env["conn"].log
    doc = json.loads((state / "data/runtime/fund_technicals_enrich_last.json").read_text())
    assert doc["status"] == "ok" and doc["summary"] == {"symbols": 2, "updated": 2, "computed": 2}


def test_fte_every_symbol_failing_is_exit_1(fte_env, monkeypatch, state):
    fte_env["hist"].update({"FCNTX": RuntimeError("rate limited"), "AMANX": RuntimeError("rate limited")})
    monkeypatch.setattr(fte, "upsert_profile", lambda *a, **k: types.SimpleNamespace(rows_written=1, rejected=[]))
    assert fte.main([]) == 1
    doc = json.loads((state / "data/runtime/fund_technicals_enrich_last.json").read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None
