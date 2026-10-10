"""Refactor wave 2 (cron -> n8n, 2026-10-10): LLM, ingest and alert lanes.

- holdings_llm_refresh.py (cron:L383 --run --limit 50): --dry-run on a READ ONLY session never reaches
  a fetch, the governed cloud (paid) call, the UPDATE or the DecisionPayload emit; a real run writes
  holdings_llm_refresh_last.json and exits 1 when it had candidates and refreshed none.
- hermes_directive_discovery.py (cron:L448 --apply): --dry-run wins over --apply, READ ONLY session,
  no INSERT/commit; a real --apply writes hermes_directive_discovery_last.json.
- earnings_enrich.py (cron:L551): no per-run ALTER TABLE (migration + read-only column check, exit 2);
  --dry/--dry-run never reaches write_earnings/commit; exit 1 when every fetch raised; receipt.
- ipo_lockup_alert.py (cron:L488, a SENDER): --dry-run never reaches save_alert_event, the fired-set
  write or the yfinance lookup; a tranche is remembered only when its alert row was written; exit 1 and a
  failed receipt when a due alert could not be written.
Hermetic: fake connections / modules, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import earnings_enrich as ee  # noqa: E402
import hermes_directive_discovery as hdd  # noqa: E402
import holdings_llm_refresh as hlr  # noqa: E402
import ipo_lockup_alert as ila  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


class FakeConn:
    """Answers statements by substring (first match wins); records everything."""

    def __init__(self, answers):
        self.answers = answers
        self.log: list = []
        self.closed = 0

    def cursor(self, *a, **k):
        conn = self

        class C:
            rowcount = 1

            def execute(self, sql, params=None):
                flat = " ".join(sql.split())
                conn.log.append(("execute", flat))
                self._rows = next((rows for sub, rows in conn.answers if sub in flat), [])

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

    def mutations(self):
        bad = ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")
        return [s for s in self.sqls() if s.lstrip().upper().startswith(bad)]


def _forbid(monkeypatch, obj, name):
    def boom(*a, **k):
        raise AssertionError(f"dry run reached {name}")

    monkeypatch.setattr(obj, name, boom)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


def _readonly(conn):
    return ("set_session", {"readonly": True}) in conn.log


def _receipt(name):
    return json.loads(llr.receipt_path(name).read_text())


# ── holdings_llm_refresh ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def hlr_env(monkeypatch, state, tmp_path):
    hold = tmp_path / "served" / "holdings.json"
    hold.parent.mkdir(parents=True)
    hold.write_text(json.dumps({"positions": [{"symbol": "LMT", "shares": 3}, {"symbol": "NOC", "shares": 1}]}))
    monkeypatch.setattr(hlr, "_holdings_path", lambda: hold)
    conn = FakeConn([("FROM watchlist_items", [])])
    monkeypatch.setattr(hlr, "get_db", lambda: conn)
    calls = []

    def gen(prompt, **kw):
        calls.append(kw)
        return '{"health": "STABLE"}', "grok"

    monkeypatch.setitem(sys.modules, "lib.governed_cloud_generation", types.SimpleNamespace(generate_cloud=gen))
    monkeypatch.setitem(
        sys.modules, "lib.agent_decision_payload", types.SimpleNamespace(emit_holdings_health_payload=lambda out: None)
    )
    monkeypatch.setattr(
        hlr,
        "parse_holdings_health_result",
        lambda raw: {"health": "STABLE", "action": "HOLD", "confidence": 60} if raw else None,
    )
    return conn, calls, hold


def test_hlr_dry_run_reaches_no_fetch_call_or_write(hlr_env, monkeypatch, capsys, state):
    conn, calls, _ = hlr_env
    for name in ("fetch_news", "fetch_social", "fetch_agent_views", "fetch_technical", "build_holdings_prompt"):
        _forbid(monkeypatch, hlr, name)
    _forbid(monkeypatch, llr, "write_receipt")
    assert hlr.main(["--dry-run", "--limit", "50"]) == 0
    out = capsys.readouterr().out
    assert "LMT: dry_run" in out and "NOC: dry_run" in out and "nothing written" in out
    assert calls == [] and conn.mutations() == [] and ("commit",) not in conn.log and _readonly(conn)
    assert not state.exists()


def test_hlr_dry_run_report_tracks_state(hlr_env, capsys):
    _, _, hold = hlr_env
    hlr.main(["--dry-run"])
    before = capsys.readouterr().out
    hold.write_text(json.dumps({"positions": [{"symbol": "LMT", "shares": 3}]}))
    hlr.main(["--dry-run"])
    after = capsys.readouterr().out
    assert "NOC: dry_run" in before and "NOC: dry_run" not in after


def test_hlr_refresh_one_returns_before_any_fetch_on_dry_run():
    src = inspect.getsource(hlr.refresh_one)
    assert (
        src.index("if dry_run:")
        < src.index("fetch_news(")
        < src.index("generate_cloud(")
        < src.index("UPDATE watchlist_items")
    )


def test_hlr_real_run_updates_and_receipts(hlr_env, monkeypatch):
    conn, calls, _ = hlr_env
    for name in ("fetch_news", "fetch_social", "fetch_agent_views"):
        monkeypatch.setattr(hlr, name, lambda c, s, **k: [])
    monkeypatch.setattr(hlr, "fetch_technical", lambda c, s: {})
    assert hlr.main(["--run", "--limit", "50"]) == 0
    assert len(calls) == 2 and len(conn.mutations()) == 2 and not _readonly(conn)
    rc = _receipt("holdings_llm_refresh")
    assert rc["status"] == "ok" and rc["summary"]["refreshed"] == 2


def test_hlr_real_run_that_refreshes_nothing_exits_1(hlr_env, monkeypatch):
    for name in ("fetch_news", "fetch_social", "fetch_agent_views"):
        monkeypatch.setattr(hlr, name, lambda c, s, **k: [])
    monkeypatch.setattr(hlr, "fetch_technical", lambda c, s: {})
    monkeypatch.setitem(
        sys.modules, "lib.governed_cloud_generation", types.SimpleNamespace(generate_cloud=lambda p, **k: ("", None))
    )
    assert hlr.main(["--run"]) == 1
    rc = _receipt("holdings_llm_refresh")
    assert rc["status"] == "failed" and rc["ok_at"] is None and rc["summary"]["statuses"] == {"empty": 2}


def test_hlr_reads_the_served_holdings_path():
    src = inspect.getsource(hlr._holdings_path)
    assert "portfolio_state_write_targets(PROJECT_ROOT)[0]" in src


# ── hermes_directive_discovery ──────────────────────────────────────────────────────────────────
@pytest.fixture
def hdd_conn(monkeypatch, state):
    conn = FakeConn(
        [
            (
                "FROM watch_directives WHERE status",
                [(1, "AI DC", {"keywords": ["datacenter"], "seed_symbols": ["NVDA"]}, True)],
            ),
            ("FROM hermes_research_intelligence", [("AMD", "AI datacenter", "t", 0.7, None)]),
            ("FROM intelligence_entities", []),
            ("SELECT 1 FROM hermes_directive_hits_staging", []),
            ("FROM watch_directive_hits", []),
        ]
    )
    monkeypatch.setattr(hdd, "_conn", lambda: conn)
    monkeypatch.setitem(
        sys.modules,
        "research_critique_pipeline",
        types.SimpleNamespace(is_removal_flagged=lambda spec: False, load_critique_snapshot=lambda: {}),
    )
    return conn


@pytest.mark.parametrize("argv", [[], ["--dry-run"], ["--dry-run", "--apply"]])
def test_hdd_dry_run_reaches_no_write(hdd_conn, monkeypatch, capsys, state, argv):
    _forbid(monkeypatch, llr, "write_receipt")
    assert hdd.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["would_write"] == {"table": "hermes_directive_hits_staging", "rows": 2}
    assert hdd_conn.mutations() == [] and ("commit",) not in hdd_conn.log and _readonly(hdd_conn)
    assert not state.exists()


def test_hdd_dry_run_report_tracks_state(hdd_conn, capsys):
    hdd.main(["--dry-run"])
    before = json.loads(capsys.readouterr().out)["staged"]
    hdd_conn.answers.insert(0, ("SELECT 1 FROM hermes_directive_hits_staging", [(1,)]))  # all already pending
    hdd.main(["--dry-run"])
    after = json.loads(capsys.readouterr().out)["staged"]
    assert (before, after) == (2, 0)


def test_hdd_insert_only_under_apply():
    src = inspect.getsource(hdd.run)
    assert src.index('if apply:\n                cur.execute("""INSERT') > src.index("enforce_readonly(conn)")


def test_hdd_apply_stages_and_receipts(hdd_conn):
    assert hdd.main(["--apply"]) == 0
    assert len(hdd_conn.mutations()) == 2 and ("commit",) in hdd_conn.log and not _readonly(hdd_conn)
    rc = _receipt("hermes_directive_discovery")
    assert rc["status"] == "ok" and rc["summary"]["staged"] == 2


# ── earnings_enrich ─────────────────────────────────────────────────────────────────────────────
class _ED:
    def __len__(self):
        return 1


@pytest.fixture
def ee_env(monkeypatch, state):
    conn = FakeConn([("information_schema.columns", [(c,) for c in ee.REQUIRED_COLUMNS])])
    monkeypatch.setattr(ee, "_conn", lambda: conn)
    fetched = []

    class T:
        def __init__(self, s):
            self.s = s

        def get_earnings_dates(self, limit=12):
            fetched.append(self.s)
            return _ED()

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    nd = date.today() + timedelta(days=20)
    monkeypatch.setattr(ee, "_extract", lambda ed: (nd, date.today() - timedelta(days=70), 1.0, 1.1, 10.0))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    return conn, fetched


def test_ee_dry_run_reaches_no_write_and_no_ddl(ee_env, monkeypatch, capsys, state):
    conn, fetched = ee_env
    _forbid(monkeypatch, ee, "write_earnings")
    _forbid(monkeypatch, llr, "write_receipt")
    assert ee.main(["--symbols", "NOC,LMT", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["would_write"] == {"table": "symbol_profiles", "rows": 2}
    assert fetched == ["NOC", "LMT"]
    assert conn.mutations() == [] and ("commit",) not in conn.log and _readonly(conn) and not state.exists()


def test_ee_old_dry_flag_is_the_same_dry_run(ee_env, monkeypatch, capsys):
    conn, _ = ee_env
    _forbid(monkeypatch, ee, "write_earnings")
    assert ee.main(["--symbols", "NOC", "--dry"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry_run" and conn.mutations() == []


def test_ee_no_per_run_alter_and_migration_declares_the_columns():
    src = (ROOT / "scripts" / "earnings_enrich.py").read_text()
    assert "ALTER TABLE" not in src.split('"""', 2)[2]  # outside the module docstring
    assert "def ensure_columns" not in src
    mig = (ROOT / ee.MIGRATION).read_text()
    for col in ee.REQUIRED_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {col} " in mig


def test_ee_missing_column_exits_2_naming_the_migration(ee_env, capsys):
    conn, _ = ee_env
    conn.answers[0] = ("information_schema.columns", [("next_earnings_date",)])
    assert ee.main(["--symbols", "NOC", "--dry-run"]) == 2
    assert ee.MIGRATION in capsys.readouterr().out
    assert ee.main(["--symbols", "NOC"]) == 2
    assert _receipt("earnings_enrich")["status"] == "failed"


def test_ee_real_run_writes_and_receipts(ee_env, monkeypatch):
    conn, _ = ee_env
    written = []
    monkeypatch.setattr(
        ee,
        "write_earnings",
        lambda cur, s, **kw: written.append(s) or types.SimpleNamespace(rows_written=1, rejected=[]),
    )
    assert ee.main(["--symbols", "NOC,LMT"]) == 0
    assert written == ["NOC", "LMT"] and ("commit",) in conn.log and not _readonly(conn)
    rc = _receipt("earnings_enrich")
    assert rc["status"] == "ok" and rc["summary"] == {"symbols": 2, "updated": 2, "fetch_errors": 0}


def test_ee_every_fetch_raising_exits_1(ee_env, monkeypatch):
    class Dead:
        def __init__(self, s):
            pass

        def get_earnings_dates(self, limit=12):
            raise RuntimeError("429")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Dead))
    assert ee.main(["--symbols", "NOC,LMT"]) == 1
    rc = _receipt("earnings_enrich")
    assert rc["status"] == "failed" and rc["ok_at"] is None


# ── ipo_lockup_alert ────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def ila_env(monkeypatch, state, tmp_path):
    soon = (date.today() + timedelta(days=5)).isoformat()
    far = (date.today() + timedelta(days=60)).isoformat()
    info = {
        "company": "SpaceX",
        "tranches": [
            {"date": soon, "days_until": 5, "pct_unlocked": 10, "desc": "bonus if ≥$175.50"},
            {"date": far, "days_until": 60, "pct_unlocked": 50, "desc": "main"},
        ],
    }
    monkeypatch.setitem(
        sys.modules, "ipo_lockups", types.SimpleNamespace(all_symbols=lambda: ["SPCX"], lockup_info=lambda s: info)
    )
    fired = tmp_path / "runtime" / "lockup_alerts_fired.json"
    monkeypatch.setattr(ila, "FIRED", fired)
    saved = []
    monkeypatch.setitem(
        sys.modules,
        "alert_event_writer",
        types.SimpleNamespace(save_alert_event=lambda **kw: saved.append(kw) or 42),
    )
    monkeypatch.setattr(ila, "_live_price", lambda s: 180.0)
    return fired, saved, soon


def test_ila_dry_run_reaches_no_send_no_write_no_fetch(ila_env, monkeypatch, capsys, state):
    fired, saved, soon = ila_env
    _forbid(monkeypatch, ila, "_save_fired")
    _forbid(monkeypatch, ila, "_live_price")
    _forbid(monkeypatch, llr, "write_receipt")
    assert ila.main(["--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and len(out["would_fire"]) == 1 and soon in out["would_fire"][0]
    assert saved == [] and not fired.exists() and not state.exists()


def test_ila_dry_run_report_tracks_state(ila_env, capsys):
    fired, _, soon = ila_env
    ila.main(["--dry-run"])
    before = len(json.loads(capsys.readouterr().out)["would_fire"])
    fired.parent.mkdir(parents=True)
    fired.write_text(json.dumps([f"SPCX:{soon}"]))
    ila.main(["--dry-run"])
    after = len(json.loads(capsys.readouterr().out)["would_fire"])
    assert (before, after) == (1, 0)


def test_ila_dry_run_returns_before_the_sender():
    src = inspect.getsource(ila.check)
    assert src.index("if dry_run:") < src.index("from alert_event_writer import save_alert_event")
    assert src.index("if dry_run:") < src.index("_live_price(sym)") < src.index("_save_fired(fired)")


def test_ila_real_run_fires_remembers_and_receipts(ila_env, capsys):
    fired, saved, soon = ila_env
    assert ila.main([]) == 0
    assert len(saved) == 1 and "live SPCX $180.00" in saved[0]["raw_text"]
    assert json.loads(fired.read_text()) == [f"SPCX:{soon}"]
    rc = _receipt("ipo_lockup_alert")
    assert rc["status"] == "ok" and rc["summary"] == {"fired": 1, "failed": 0}
    assert ila.main([]) == 0 and len(saved) == 1  # not repeated


def test_ila_unwritten_alert_is_not_remembered_and_exits_1(ila_env, monkeypatch):
    fired, _, _ = ila_env
    monkeypatch.setitem(sys.modules, "alert_event_writer", types.SimpleNamespace(save_alert_event=lambda **kw: None))
    assert ila.main([]) == 1
    assert not fired.exists()  # the next run retries the tranche
    rc = _receipt("ipo_lockup_alert")
    assert rc["status"] == "failed" and rc["ok_at"] is None and rc["summary"]["failed"] == 1


def test_ila_fired_set_resolves_through_the_resolution_layer():
    assert 'resolve_durable_dir("data/runtime", ROOT)' in inspect.getsource(ila._runtime_dir)
