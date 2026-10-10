"""Refactor wave 2 (cron -> n8n, 2026-10-10), bucket V3 -- research lanes.

- research_insight_extractor.py (cron:L418): --dry-run classifies on a READ ONLY session and returns
  before the INSERT; per-item failures are counted (were `except: pass`); every extraction failing is
  exit 1; real run writes research-insight-extractor_last.json.
- pro_analyst_fetch.py / build_pro_analyst_read_model.py / pro_analyst_monitor.py + the new
  run_pro_analyst_chain.py (cron:L437): each step's --dry-run reaches no yfinance call, no DB/file write,
  no SIEM row, no Telegram; the fetch exits 1 when every symbol errored; the chain stops at the first
  failing step (&& semantics), never adds --send on its own, and writes the lane receipt
  pro-analyst-fetch_last.json.
- hermes_discovery_ingestors.py (cron:L682): --scheduled --dry-run reaches no inbox write and no
  Telegram; every enabled ingestor failing is exit 1 (was 0); real run writes a receipt.
Hermetic: fake DB connections / modules, TRADEAI_STATE_ROOT = tmp, no network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

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

WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "ALTER", "DROP")


def _load(name: str):
    """Import scripts/<name>.py privately; serve an empty .env (a checkout has none) for that read."""
    orig = Path.read_text

    def read_text(self, *a, **k):
        if self.name == ".env":
            return ""
        return orig(self, *a, **k)

    with mock.patch.object(Path, "read_text", read_text):
        spec = importlib.util.spec_from_file_location(f"w2v3_{name}", SCRIPTS / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class FakeConn:
    def __init__(self, responder=None, dict_rows=True):
        self.responder = responder or (lambda sql, params: [])
        self.dict_rows = dict_rows
        self.sql: list[str] = []
        self.calls: list = []

    def cursor(self, *a, **k):
        conn = self

        class C:
            def execute(self, sql, params=None):
                flat = " ".join(str(sql).split())
                conn.sql.append(flat)
                self._rows = list(conn.responder(flat, params) or [])

            def _c(self, r):
                return r if conn.dict_rows else tuple(r.values())

            def fetchall(self):
                return [self._c(r) for r in self._rows]

            def fetchone(self):
                return self._c(self._rows[0]) if self._rows else None

        return C()

    def writes(self):
        return [s for s in self.sql if s.upper().startswith(WRITE_PREFIXES)]

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def set_session(self, **kw):
        self.calls.append(("set_session", kw))

    def close(self):
        self.calls.append("close")


def _receipt(state, name):
    p = state / "data" / "runtime" / f"{name}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


# ── research_insight_extractor (cron:L418) ────────────────────────────────────


def _rie_rows(sql, params):
    if "FROM news_articles" in sql:
        return [
            {
                "id": 1,
                "symbol": "AAA",
                "title": "AAA upgrade, strong growth outlook",
                "summary": "beat expectations and guidance raise",
                "source": "x",
                "strategy_type": None,
            }
        ]
    if sql.startswith("INSERT INTO research_insights"):
        return [{"id": 99}]
    return []


@pytest.fixture
def rie(monkeypatch):
    mod = _load("research_insight_extractor")
    conns: list = []

    def get_conn(dry_run=False):
        c = FakeConn(_rie_rows)
        c.dry_run = dry_run
        conns.append(c)
        return c

    monkeypatch.setattr(mod, "_get_conn", get_conn)
    return mod, conns


def test_extractor_dry_run_inserts_nothing(rie, state):
    mod, conns = rie
    assert mod.run_default(dry_run=True) == 0
    assert conns and all(c.dry_run for c in conns)
    assert [w for c in conns for w in c.writes()] == []
    assert _receipt(state, "research-insight-extractor") is None


def test_extractor_real_run_inserts_and_writes_receipt(rie, state):
    mod, conns = rie
    assert mod.run_default() == 0
    assert any(w.startswith("INSERT INTO research_insights") for c in conns for w in c.writes())
    rec = _receipt(state, "research-insight-extractor")
    assert rec["status"] == "ok" and rec["summary"] == {"news": 1, "catalysts": 0, "failed": 0}


def test_extractor_every_item_failing_is_exit_1(rie, state, monkeypatch):
    mod, _ = rie
    monkeypatch.setattr(mod, "extract_insight", mock.Mock(side_effect=RuntimeError("boom")))
    assert mod.run_default() == 1
    rec = _receipt(state, "research-insight-extractor")
    assert rec["status"] == "failed" and rec["summary"]["failed"] == 1


def test_extractor_dry_connection_is_read_only(monkeypatch):
    mod = _load("research_insight_extractor")
    conn = FakeConn()
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: "DB_PASSWORD=x\n")
    import psycopg2

    monkeypatch.setattr(psycopg2, "connect", lambda **kw: conn)
    mod._get_conn(dry_run=True)
    assert conn.calls == ["rollback", ("set_session", {"readonly": True})]


# ── pro_analyst chain (cron:L437) ─────────────────────────────────────────────


class _YF:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def Ticker(self, sym):  # noqa: N802 -- yfinance API name
        self.calls += 1
        if self.fail:
            raise RuntimeError("429")
        return types.SimpleNamespace(info={"targetMeanPrice": 10.0, "numberOfAnalystOpinions": 3})


@pytest.fixture
def paf(monkeypatch, tmp_path):
    mod = _load("pro_analyst_fetch")
    mod.ROOT = tmp_path  # no holdings.json under tmp: the held-symbol union is skipped
    conn = FakeConn(lambda sql, params: [{"symbol": "AAA"}] if "SELECT DISTINCT symbol" in sql else [], dict_rows=False)
    monkeypatch.setattr(mod.psycopg2, "connect", lambda **kw: conn)
    save = mock.Mock()
    report = mock.Mock()
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(save_yahoo_analyst_targets_history=save))
    monkeypatch.setitem(sys.modules, "lib.data_source_report", types.SimpleNamespace(report_source=report))
    monkeypatch.setattr("time.sleep", lambda s: None)
    return mod, conn, save, report


def test_fetch_dry_run_reaches_no_yfinance_save_or_health_report(paf, state, monkeypatch):
    mod, conn, save, report = paf
    yf = _YF()
    monkeypatch.setitem(sys.modules, "yfinance", yf)
    assert mod.main(["--max", "5", "--dry-run"]) == 0
    assert yf.calls == 0 and not save.called and not report.called
    assert ("set_session", {"readonly": True}) in conn.calls


def test_fetch_real_run_saves_and_reports_health(paf, state, monkeypatch):
    mod, _, save, report = paf
    monkeypatch.setitem(sys.modules, "yfinance", _YF())
    assert mod.main(["--max", "5"]) == 0
    assert save.called and report.call_args.args[:2] == ("yahoo_finance", True)


def test_fetch_every_symbol_erroring_is_exit_1(paf, state, monkeypatch):
    mod, _, save, _ = paf
    monkeypatch.setitem(sys.modules, "yfinance", _YF(fail=True))
    assert mod.main(["--max", "5"]) == 1
    assert not save.called


def test_read_model_dry_run_writes_no_file(monkeypatch, tmp_path):
    mod = _load("build_pro_analyst_read_model")
    conn = FakeConn()
    monkeypatch.setattr(mod, "_db", lambda: conn)
    mod.OUT = tmp_path / "pills.json"
    assert mod.main(["--dry-run"]) == 0
    assert not mod.OUT.exists() and ("set_session", {"readonly": True}) in conn.calls
    assert mod.main([]) == 0 and mod.OUT.exists()


def test_monitor_dry_run_writes_nothing_and_missing_read_model_is_exit_1(monkeypatch, tmp_path):
    mod = _load("pro_analyst_monitor")
    mod.SRC, mod.HIST = tmp_path / "missing.json", tmp_path / "hist.json"
    monkeypatch.setattr(sys, "argv", ["pro_analyst_monitor.py", "--dry-run"])
    assert mod.main() == 1
    mod.SRC.write_text(
        json.dumps(
            {
                "pills": [
                    {
                        "symbol": "AAA",
                        "has_professional_coverage": True,
                        "divergence": "divergent",
                        "internal_direction": "bullish",
                        "street_direction": "bearish",
                    }
                ]
            }
        )
    )
    siem, tg = mock.Mock(), mock.Mock()
    monkeypatch.setattr(mod, "_siem_alert", siem)
    monkeypatch.setattr(mod, "_telegram", tg)
    assert mod.main() == 0
    assert not mod.HIST.exists() and not siem.called and not tg.called


def test_chain_dry_run_passes_dry_run_everywhere_and_never_send(monkeypatch):
    mod = _load("run_pro_analyst_chain")
    runner = mock.Mock(return_value=types.SimpleNamespace(returncode=0))
    out = mod.run_chain(250, send=False, dry_run=True, runner=runner)
    argvs = [c.args[0] for c in runner.call_args_list]
    assert [Path(a[1]).name for a in argvs] == [
        "pro_analyst_fetch.py",
        "build_pro_analyst_read_model.py",
        "pro_analyst_monitor.py",
    ]
    assert all(a[-1] == "--dry-run" for a in argvs) and not any("--send" in a for a in argvs)
    assert out["ok"] is True


def test_chain_stops_at_first_failure_and_receipts_it(monkeypatch, state):
    mod = _load("run_pro_analyst_chain")
    runner = mock.Mock(return_value=types.SimpleNamespace(returncode=1))
    monkeypatch.setattr(mod.subprocess, "run", runner)
    assert mod.main(["--max", "250"]) == 1
    assert runner.call_count == 1  # && semantics: the read model and monitor did not run
    rec = _receipt(state, "pro-analyst-fetch")
    assert rec["status"] == "failed" and rec["summary"]["steps"][0]["step"] == "pro_analyst_fetch"


def test_chain_dry_run_main_writes_no_receipt(monkeypatch, state):
    mod = _load("run_pro_analyst_chain")
    monkeypatch.setattr(mod.subprocess, "run", mock.Mock(return_value=types.SimpleNamespace(returncode=0)))
    assert mod.main(["--dry-run"]) == 0
    assert _receipt(state, "pro-analyst-fetch") is None


def test_chain_send_only_when_asked():
    mod = _load("run_pro_analyst_chain")
    steps = dict(mod.build_steps(250, send=True, dry_run=False))
    assert steps["pro_analyst_monitor"] == ["pro_analyst_monitor.py", "--send"]
    assert steps["pro_analyst_fetch"] == ["pro_analyst_fetch.py", "--max", "250"]


# ── hermes_discovery_ingestors (cron:L682) ────────────────────────────────────


@pytest.fixture
def hdi(monkeypatch, tmp_path):
    mod = _load("hermes_discovery_ingestors")
    cfg = tmp_path / "sched.json"
    cfg.write_text(json.dumps({"enabled": True, "max_candidates_per_run": 5}))
    monkeypatch.setattr(mod, "SCHEDULE_CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "SCORECARD_PATH", tmp_path / "no_scorecard.json")
    monkeypatch.setattr(mod, "ALERT_THROTTLE_PATH", tmp_path / "throttle.json")
    monkeypatch.setattr(mod, "_domain_counts_today", lambda: {"by_domain": {}, "ticker": 0, "legal_tax": 0})
    send = mock.Mock(return_value=True)
    monkeypatch.setitem(sys.modules, "telegram_alert", types.SimpleNamespace(send_telegram=send))
    upsert = mock.Mock(side_effect=AssertionError("inbox write"))
    monkeypatch.setattr(mod.inbox, "upsert_candidate", upsert)
    return mod, send, upsert, tmp_path


def _ingestors(mod, fn):
    return {name: fn for name in mod.INGESTORS}


def test_hermes_dry_run_all_failed_is_exit_1_without_send_or_receipt(hdi, state, monkeypatch):
    mod, send, upsert, tmp_path = hdi
    monkeypatch.setattr(mod, "INGESTORS", _ingestors(mod, mock.Mock(side_effect=RuntimeError("db"))))
    monkeypatch.setattr(sys, "argv", ["x", "--scheduled", "--dry-run", "--json"])
    assert mod.main() == 1
    assert not send.called and not upsert.called and not (tmp_path / "throttle.json").exists()
    assert _receipt(state, "hermes-discovery-ingestors") is None


def test_hermes_dry_run_passes_dry_run_to_ingestors(hdi, state, monkeypatch):
    mod, send, upsert, _ = hdi
    seen = []

    def fake(limit, dry_run, gate=None, **kw):
        seen.append(dry_run)
        return {"scanned": 1, "upserted": 0, "skipped": 0}

    monkeypatch.setattr(mod, "INGESTORS", _ingestors(mod, fake))
    monkeypatch.setattr(sys, "argv", ["x", "--scheduled", "--dry-run"])
    assert mod.main() == 0
    assert seen and all(seen) and not send.called


def test_hermes_real_run_receipt_ok_and_one_failure_is_a_finding(hdi, state, monkeypatch):
    mod, _, _, _ = hdi
    calls = {"n": 0}

    def fake(limit, dry_run, gate=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("one producer down")
        return {"scanned": 2, "upserted": 1, "skipped": 0}

    monkeypatch.setattr(mod, "INGESTORS", _ingestors(mod, fake))
    monkeypatch.setattr(sys, "argv", ["x", "--scheduled"])
    assert mod.main() == 0
    rec = _receipt(state, "hermes-discovery-ingestors")
    assert rec["status"] == "ok" and rec["ok_at"]


def test_hermes_real_run_all_failed_is_failed_receipt(hdi, state, monkeypatch):
    mod, send, _, _ = hdi
    monkeypatch.setattr(mod, "INGESTORS", _ingestors(mod, mock.Mock(side_effect=RuntimeError("db"))))
    monkeypatch.setattr(sys, "argv", ["x", "--scheduled"])
    assert mod.main() == 1
    assert send.called  # existing behaviour: one throttled CRITICAL send on a real run (unchanged)
    assert _receipt(state, "hermes-discovery-ingestors")["status"] == "failed"
