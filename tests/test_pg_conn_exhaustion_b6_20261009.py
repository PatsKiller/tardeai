"""n8nmat/b6 (2026-10-09) — Postgres connection-slot hygiene.

* lib/pg_attribution sets PGAPPNAME once per process so raw psycopg2.connect callers are
  attributable (the 2026-10-05 top holder was application_name '' with 19 of 73 slots).
* reconcile_protection_advisory_outcomes survives an APPLIED audit row without broker_order_*
  blocks and names its connection.
* run_protection_pipeline.sh logs the real exit status and resolves its tree from its own path.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import pg_attribution as PA  # noqa: E402


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("PGAPPNAME", raising=False)
    monkeypatch.delenv("TRADEAI_PGAPPNAME_PID", raising=False)
    return monkeypatch


def test_script_basename_is_the_name():
    assert PA.process_app_name(["/x/scripts/screener_pm.py", "--apply"]) == "screener_pm.py"


def test_dash_m_run_uses_the_module_name(monkeypatch):
    fake = types.ModuleType("__main__")
    fake.__spec__ = types.SimpleNamespace(name="active_trader.motion_runtime")
    monkeypatch.setitem(sys.modules, "__main__", fake)
    assert PA.process_app_name(["/v/lib/python3.13/site-packages/x/__main__.py"]) == "active_trader.motion_runtime"


def test_name_is_capped_at_namedatalen():
    assert len(PA.process_app_name(["/" + "a" * 200 + ".py"])) == 63


def test_sets_pgappname_and_owner_pid(clean_env):
    assert PA.ensure_pgappname("job_x.py") == "job_x.py"
    assert os.environ["PGAPPNAME"] == "job_x.py"
    assert os.environ["TRADEAI_PGAPPNAME_PID"] == str(os.getpid())
    # idempotent for the owning process
    assert PA.ensure_pgappname("other.py") == "job_x.py"


def test_explicit_operator_value_is_never_overwritten(clean_env):
    clean_env.setenv("PGAPPNAME", "set_by_unit_file")
    assert PA.ensure_pgappname("job_x.py") == "set_by_unit_file"
    assert "TRADEAI_PGAPPNAME_PID" not in os.environ


def test_child_inheriting_a_parents_value_rederives_its_own(clean_env):
    clean_env.setenv("PGAPPNAME", "portfolio_server.py")
    clean_env.setenv("TRADEAI_PGAPPNAME_PID", "1")  # a different (parent) pid
    assert PA.ensure_pgappname("child_job.py") == "child_job.py"


def test_db_adapter_and_env_bootstrap_wire_the_attribution():
    da = (ROOT / "scripts" / "db_adapter.py").read_text(encoding="utf-8")
    assert "from pg_attribution import ensure_pgappname" in da
    assert "\n_ensure_pgappname()\n" in da
    eb = (ROOT / "scripts" / "lib" / "env_bootstrap.py").read_text(encoding="utf-8")
    assert "ensure_pgappname()" in eb


def test_env_bootstrap_load_env_sets_pgappname(clean_env, tmp_path):
    import env_bootstrap as EB
    clean_env.setattr(EB, "_candidates", lambda: [])
    EB.load_env()
    assert os.environ.get("PGAPPNAME")


# ── reconcile_protection_advisory_outcomes ─────────────────────────────────────────────
def _load_reconcile():
    spec = importlib.util.spec_from_file_location(
        "rpao_b6", ROOT / "scripts" / "reconcile_protection_advisory_outcomes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_audit_row_without_broker_order_blocks_is_not_a_crash():
    m = _load_reconcile()
    assert m._audit_stop({"status": "APPLIED", "action": "MOVE_STOP"}, "before") is None
    assert m._audit_stop({"broker_order_before": None}, "before") is None
    assert m._audit_stop({"broker_order_after": {"stop_price": "12.5"}}, "after") == 12.5
    assert m._audit_stop(None, "after") is None


def test_reconcile_names_its_connection_and_closes_on_error(monkeypatch):
    m = _load_reconcile()
    src = (ROOT / "scripts" / "reconcile_protection_advisory_outcomes.py").read_text(encoding="utf-8")
    assert 'application_name="reconcile_protection_advisory_outcomes"' in src
    closed = []

    class Conn:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "db", lambda: Conn())

    def boom(conn, persist=True):
        raise KeyError("broker_order_before")
    monkeypatch.setattr(m, "_reconcile", boom)
    with pytest.raises(KeyError):
        m.run(persist=False)
    assert closed == [True]


# ── run_protection_pipeline.sh ─────────────────────────────────────────────────────────
def _pipeline_tree(tmp_path: Path, failing: str) -> Path:
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    (tree / "logs").mkdir()
    sh = (ROOT / "scripts" / "run_protection_pipeline.sh").read_bytes()
    (tree / "scripts" / "run_protection_pipeline.sh").write_bytes(sh)
    for line in sh.decode().splitlines():
        if line.startswith("run "):
            name = line.split()[1]
            body = "import sys; sys.exit(3)\n" if name == failing else "print('ok')\n"
            (tree / "scripts" / name).write_text(body)
    return tree


def test_pipeline_logs_the_real_exit_status_and_runs_from_its_own_tree(tmp_path):
    tree = _pipeline_tree(tmp_path, "reconcile_protection_advisory_outcomes.py")
    env = {k: v for k, v in os.environ.items() if k != "PY"}
    env["PY"] = sys.executable
    r = subprocess.run(["bash", str(tree / "scripts" / "run_protection_pipeline.sh")],
                       cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    log = (tree / "logs" / "protection_pipeline.log").read_text()
    assert "WARN reconcile_protection_advisory_outcomes.py rc=3" in log
    assert log.count("WARN") == 1
    assert "failed_steps=1" in log


def test_pipeline_has_no_hardcoded_home_path():
    src = (ROOT / "scripts" / "run_protection_pipeline.sh").read_text(encoding="utf-8")
    assert "/home/johnclaw" not in src
    assert 'BASH_SOURCE[0]' in src


# ── per-call / per-symbol connection churn reached from api_v2 request threads ─────────
def test_price_counts_use_one_connection_for_many_symbols(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import price_db_sync as PDS

    opened, closed, queries = [], [], []

    class Cur:
        def execute(self, sql, params):
            queries.append((sql, params))

        def fetchall(self):
            return [("AAPL", 70), ("MSFT", 12)]

        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(PDS, "_get_conn", lambda: opened.append(True) or Conn())
    got = PDS.count_price_rows_many(["aapl", "MSFT", "nvda", "AAPL"])
    assert got == {"AAPL": 70, "MSFT": 12, "NVDA": 0}
    assert len(opened) == 1 and len(closed) == 1 and len(queries) == 1
    assert "ANY(%s)" in queries[0][0]
    assert PDS.count_price_rows("msft") == 12
    assert PDS.count_price_rows_many([]) == {}


def test_raw_connects_reached_from_request_threads_are_named_and_closed():
    src = {n: (ROOT / "scripts" / n).read_text(encoding="utf-8") for n in (
        "price_db_sync.py", "process_watchlist_agent_jobs.py", "hybrid_rag_context_adapter.py", "api_v2.py")}
    assert 'application_name="price_db_sync"' in src["price_db_sync.py"]
    assert "count_price_rows(s) < min_rows]" not in src["price_db_sync.py"].replace(
        "The callers filtered `[s for s in syms if count_price_rows(s) < min_rows]`", "")
    assert 'application_name="process_watchlist_agent_jobs"' in src["process_watchlist_agent_jobs.py"]
    assert 'application_name="hybrid_rag_context_adapter"' in src["hybrid_rag_context_adapter.py"]
    i = src["api_v2.py"].index('application_name="api_v2:hermes_maturity"')
    block = src["api_v2.py"][i:i + 400]
    assert "finally:" in block and "conn.close()" in block


def test_tests_never_fall_back_to_the_operators_pgpass():
    """conftest points libpq at a non-existent PGPASSFILE: a worktree (no .env) used to send
    password="" and libpq read the stale ~/.pgpass -> FATAL at the live server per connect."""
    pgpass = os.environ.get("PGPASSFILE", "")
    assert pgpass, "conftest must set PGPASSFILE"
    assert not os.path.exists(pgpass)
    assert Path(pgpass).resolve() != (Path.home() / ".pgpass").resolve()
