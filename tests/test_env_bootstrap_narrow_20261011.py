"""Env-file loaders never put a broker name into a bounded process (canary blocker, 2026-10-11).

``scripts/lib/env_bootstrap.load_env`` (the loader ``db_adapter`` falls back to when DB_PASSWORD is unset) re-read the
WHOLE rendered secret file into ``os.environ``. That file carries ALPACA_* / SCHWAB_* (config/secret_registry.yaml),
so every DB-using lane was credential-exposed (AGENTS §23.18) and an enforced executor child was silently re-expanded
past its allowlist. Pins:

- ``load_env(names=...)`` copies only those names; bound mode (the executor's ``TRADEAI_ENV_BOUND_NAMES``) copies only
  the bound names and never a broker name; ``db_adapter`` in a bound process copies DB_* only, and its connection
  parameters still resolve.
- The unbound default is the legacy whole-file copy, unchanged (cron relies on it; narrowing it is an operator call).
- The four per-script checkout ``.env`` loops of the newly enforced lanes copy only ``_ENV_KEYS``, and ``_ENV_KEYS``
  covers every env name their process reads, so behaviour is identical for every name the caller uses.

Hermetic: fake render/.env files under tmp_path with synthetic values; never reads the live render, a real .env or
the live ledger, and no DB connection is opened (psycopg2 is stubbed in the subprocesses).
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

import env_bootstrap as EB  # noqa: E402

from scripts import n8n_run_executor as X  # noqa: E402

FAKE = "fixture-value-"
DB = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_CONN_TRACE"]
BROKER = ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_TAXABLE_API_KEY", "SCHWAB_APP_KEY", "SCHWAB_APP_SECRET",
          "SNAPTRADE_USER_SECRET", "MOOMOO_TRADE_PWD", "IBKR_ACCOUNT", "TRADING_MODE", "PAPER_BROKER_TOKEN"]
OTHER = ["TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY", "FINVIZ_COOKIE"]
ALL = DB + BROKER + OTHER


def _render(path: Path, names=ALL) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# fake render (synthetic values)", "BWS_ACCESS_TOKEN='" + FAKE + "bws'"]
    lines += [f"{n}='{FAKE}{n}'" for n in names]
    lines[lines.index(f"DB_PORT='{FAKE}DB_PORT'")] = "DB_PORT='5433'"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def fake_env(monkeypatch, tmp_path):
    """A process env with none of the fixture names, and env_bootstrap pointed at one fake render only. load_env
    writes os.environ directly, so the whole env (and the module's _LOADED flag) is restored afterwards: no fixture
    value may leak into a later test (telegram_alert.ensure_loaded, the DB barrier in conftest)."""
    saved = dict(os.environ)
    monkeypatch.setattr(EB, "_LOADED", EB._LOADED)
    for name in ALL + ["BWS_ACCESS_TOKEN", EB.ENV_BOUND_NAMES_ENV]:
        os.environ.pop(name, None)
    render = _render(tmp_path / "xdg" / "tradeai" / "env")
    monkeypatch.setattr(EB, "_candidates", lambda: [render])
    yield monkeypatch
    monkeypatch.undo()
    os.environ.clear()
    os.environ.update(saved)


def _present() -> set:
    return {n for n in ALL + ["BWS_ACCESS_TOKEN"] if n in os.environ}


# ── broker names ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", BROKER + ["alpaca_api_key", "X_BROKER", "BROKER_URL"])
def test_broker_names_are_recognised(name):
    assert EB.is_broker_name(name)


@pytest.mark.parametrize("name", DB + OTHER + ["TRADEAI_STATE_ROOT", "PAPERBROKER"])
def test_non_broker_names_are_not(name):
    assert not EB.is_broker_name(name)


def test_every_broker_vendor_name_in_the_secret_registry_is_denied():
    reg = yaml.safe_load((ROOT / "config" / "secret_registry.yaml").read_text(encoding="utf-8"))["secrets"]
    vendors = ("alpaca", "schwab", "snaptrade", "moomoo", "ibkr")
    broker = {n for n, v in reg.items()
              if any(x in (n + " " + json.dumps(v)).lower() for x in vendors) and not n.startswith("DB_")}
    assert {"ALPACA_API_KEY", "SCHWAB_APP_KEY", "SNAPTRADE_CONSUMER_KEY"} <= broker
    assert all(EB.is_broker_name(n) for n in broker), sorted(n for n in broker if not EB.is_broker_name(n))
    assert not EB.is_broker_name("DB_PASSWORD")


# ── load_env ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_names_copies_only_the_named_keys(fake_env):
    meta = EB.load_env(names=("DB_HOST", "DB_PASSWORD"))
    assert _present() == {"DB_HOST", "DB_PASSWORD"}
    assert os.environ["DB_PASSWORD"] == FAKE + "DB_PASSWORD"
    assert meta["scope"] == "names" and meta["keys_applied"] == 2 and meta["ok"]
    assert FAKE not in json.dumps(meta)  # metadata never carries a value


def test_a_single_string_is_one_name_not_its_characters(fake_env):
    EB.load_env(names="DB_USER")
    assert _present() == {"DB_USER"}


def test_names_never_overrides_an_exported_value(fake_env):
    fake_env.setenv("DB_HOST", "exported")
    EB.load_env(names=DB)
    assert os.environ["DB_HOST"] == "exported"


def test_bound_process_copies_only_bound_names_and_never_a_broker_name(fake_env):
    fake_env.setenv(EB.ENV_BOUND_NAMES_ENV, ",".join(DB + ["ALPACA_API_KEY", "TELEGRAM_BOT_TOKEN"]))
    meta = EB.load_env()  # the legacy call shape: bound mode still applies
    assert _present() == set(DB) | {"TELEGRAM_BOT_TOKEN"}
    assert "ALPACA_API_KEY" not in os.environ  # listed in the bound, still refused
    assert meta["scope"] == "bound"


def test_bound_intersects_explicit_names_and_refuses_an_explicit_broker_name(fake_env):
    fake_env.setenv(EB.ENV_BOUND_NAMES_ENV, "DB_HOST,DB_USER,SCHWAB_APP_KEY")
    EB.load_env(names=("DB_HOST", "DB_PASSWORD", "SCHWAB_APP_KEY"))
    assert _present() == {"DB_HOST"}


def test_empty_bound_copies_nothing(fake_env):
    fake_env.setenv(EB.ENV_BOUND_NAMES_ENV, "")
    EB.load_env()
    assert _present() == set()
    assert EB.bound_names({EB.ENV_BOUND_NAMES_ENV: ""}) == frozenset()
    assert EB.bound_names({}) is None


def test_ensure_loaded_is_bounded_too(fake_env):
    fake_env.setenv(EB.ENV_BOUND_NAMES_ENV, "DB_NAME")
    fake_env.setattr(EB, "_LOADED", False)
    EB.ensure_loaded()
    assert _present() == {"DB_NAME"}


def test_unbound_default_is_the_legacy_whole_file_copy_unchanged(fake_env):
    """Cron lines that source no env file rely on this (env_bootstrap docstring). Narrowing it — including dropping
    broker names from it — is an operator decision; this pins that the PR did not change it silently."""
    meta = EB.load_env()
    assert _present() == set(ALL)  # BWS_* still never
    assert meta["scope"] == "all"


def test_required_still_fails_loud_without_values(fake_env):
    with pytest.raises(RuntimeError) as exc:
        EB.load_env(names=("DB_HOST",), required=["DB_HOST", "NOT_IN_FILE"])
    assert "NOT_IN_FILE" in str(exc.value) and FAKE not in str(exc.value)


# ── db_adapter + the executor, in real child processes ────────────────────────────────────────────────────────

_PROBE = r"""
import json, os, sys, types
captured = {}
stub = types.ModuleType("psycopg2")


def _connect(**kw):
    captured.update(kw)
    raise RuntimeError("stub: no connection is ever opened")


stub.connect = _connect
stub.extras = types.ModuleType("psycopg2.extras")
stub.extensions = types.ModuleType("psycopg2.extensions")
sys.modules.update({"psycopg2": stub, "psycopg2.extras": stub.extras, "psycopg2.extensions": stub.extensions})
sys.path.insert(0, os.path.join(os.environ["PROJ_UNDER_TEST"], "scripts"))
import db_adapter
try:
    db_adapter._get_conn()
except Exception:
    pass
names = json.loads(os.environ["PROBE_NAMES"])
print(json.dumps({"present": sorted(n for n in names if n in os.environ), "use_db": db_adapter.USE_DB,
                  "conn": {k: captured.get(k) for k in ("host", "port", "dbname", "user", "password")}}))
"""


def _probe(env: dict) -> dict:
    env = dict(env, PROJ_UNDER_TEST=str(ROOT), PROBE_NAMES=json.dumps(ALL + ["BWS_ACCESS_TOKEN"]))
    out = subprocess.run([sys.executable, "-c", _PROBE], env=env, cwd=str(ROOT), capture_output=True, text=True,
                         timeout=60, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _base_env(tmp_path: Path) -> dict:
    _render(tmp_path / "tradeai" / "env")
    return {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "XDG_RUNTIME_DIR": str(tmp_path)}


def test_db_adapter_in_a_bound_process_loads_db_names_only_and_still_connects(tmp_path):
    env = _base_env(tmp_path)
    env[EB.ENV_BOUND_NAMES_ENV] = ",".join(DB + ["TELEGRAM_BOT_TOKEN", "ALPACA_API_KEY"])
    got = _probe(env)
    assert got["present"] == sorted(DB)  # not even the bound TELEGRAM name: the DB path asks for DB_* only
    assert got["use_db"] is True
    assert got["conn"] == {"host": FAKE + "DB_HOST", "port": 5433, "dbname": FAKE + "DB_NAME",
                           "user": FAKE + "DB_USER", "password": FAKE + "DB_PASSWORD"}


def test_db_adapter_unbound_keeps_the_legacy_load_for_cron(tmp_path):
    got = _probe(_base_env(tmp_path))
    assert got["present"] == sorted(ALL) and got["use_db"] is True
    assert got["conn"]["password"] == FAKE + "DB_PASSWORD"


def test_enforced_executor_child_never_re_expands_through_any_loader(tmp_path):
    """The real P7 builder + a real child: the executor env holds broker names (EnvironmentFile=render), the lane
    lists DB names only; neither the inherited env nor a db_adapter / env_bootstrap load gives the child more."""
    parent = dict(_base_env(tmp_path), **{n: FAKE + n for n in BROKER + OTHER})
    parent[X.ENV_ALLOWLIST_MODE_ENV] = "enforce"
    entry = {"lane_id": "fixture-lane", "env_names": ["DB_HOST", "DB_NAME", "DB_PASSWORD", "DB_PORT", "DB_USER"],
             "env_allowlist_mode": "enforce"}
    child, block = X.build_child_env(parent, "fixture-lane", entry)
    assert block["effective_mode"] == "enforce"
    assert child[X.ENV_BOUND_NAMES_ENV] == "DB_HOST,DB_NAME,DB_PASSWORD,DB_PORT,DB_USER"
    assert not any(EB.is_broker_name(k) for k in child)
    got = _probe(child)
    assert not any(EB.is_broker_name(n) for n in got["present"])
    assert set(got["present"]) <= set(entry["env_names"]) and got["use_db"] is True


def test_report_and_off_children_carry_no_bound_marker():
    env = {"PATH": "/bin", "DB_PASSWORD": FAKE}
    for mode in ("report", "off"):
        child, _ = X.build_child_env(dict(env, **{X.ENV_ALLOWLIST_MODE_ENV: mode}), "x",
                                     {"lane_id": "x", "env_names": ["DB_PASSWORD"]})
        assert X.ENV_BOUND_NAMES_ENV not in child


def test_executor_and_loader_share_the_marker_name():
    assert X.ENV_BOUND_NAMES_ENV == EB.ENV_BOUND_NAMES_ENV
    assert X.ENV_BOUND_NAMES_ENV in X.CHILD_ENV_BASE_NAMES


# ── the per-script loaders of the lanes enforced in this PR ───────────────────────────────────────────────────

NARROWED = {
    "backtest-history-snapshot": "scripts/backtest_history_snapshot.py",
    "catalyst-calibration": "scripts/catalyst_calibration.py",
    "classifier-health-check": "scripts/monitoring/classifier_health_check.py",
    "setup-quality-prior": "scripts/setup_quality_prior.py",
    # already enforced (P7) but their whole-.env loop re-read the file: found by the strengthened P7 closure guard
    "source-attribution-monitor": "scripts/source_attribution_monitor.py",
    "watch-directives-monitor": "scripts/watch_directives_monitor.py",
}


def _loader_statements(src: str) -> list[ast.stmt]:
    """The module-level _ENV_KEYS assignment and the .env loop(s) that write os.environ — the code under test."""
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_ENV_KEYS" for t in n.targets))
            or (isinstance(n, ast.For) and "os.environ" in ast.unparse(n))]
    assert len(keep) == 2, [ast.unparse(n)[:60] for n in keep]
    return keep


@pytest.mark.parametrize("lane", sorted(NARROWED))
def test_narrowed_script_loader_copies_only_env_keys(lane, tmp_path):
    src = (ROOT / NARROWED[lane]).read_text(encoding="utf-8")
    _render(tmp_path / ".env", ALL + ["TRADEAI_PERSISTENT_STATE_ROOT"])
    fake_environ: dict = {}
    ns = {"os": SimpleNamespace(environ=fake_environ), "ROOT": tmp_path, "PROJECT_ROOT": tmp_path,
          "_ENV": tmp_path / ".env", "_ENV_FILE": tmp_path / ".env", "Path": Path}
    exec(compile(ast.Module(body=_loader_statements(src), type_ignores=[]), NARROWED[lane], "exec"), ns)  # noqa: S102
    keys = ns["_ENV_KEYS"]
    assert set(fake_environ) == keys & (set(ALL) | {"TRADEAI_PERSISTENT_STATE_ROOT"})
    assert not any(EB.is_broker_name(k) for k in fake_environ)
    assert "TELEGRAM_BOT_TOKEN" not in fake_environ and "BWS_ACCESS_TOKEN" not in fake_environ


@pytest.mark.parametrize("lane", sorted(NARROWED))
def test_env_keys_cover_every_name_the_process_reads(lane):
    """Identical behaviour per caller: every env name read anywhere in the lane's local import closure (the P7
    static guard) is still copied from the .env, so the narrowing changes nothing the process uses."""
    import test_n8n_executor_env_allowlist_20261009 as P7
    path = ROOT / NARROWED[lane]
    keys = P7._module_env_keys(ast.parse(path.read_text(encoding="utf-8")))
    reads_besides_loader: set = set()
    visited: set = set()
    reads = P7._env_reads(path, visited)
    for mod in visited:
        tree = ast.parse(mod.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func) in {"os.getenv", "os.environ.get"} \
                    and node.args and isinstance(node.args[0], ast.Constant):
                reads_besides_loader.add(node.args[0].value)
    assert reads_besides_loader <= keys, sorted(reads_besides_loader - keys)
    assert keys <= reads | {"TRADEAI_STATE_ROOT"}
    assert not any(EB.is_broker_name(k) for k in keys)


@pytest.mark.parametrize("script", ["scripts/materialize_watchlist_strategy_cards.py",
                                    "scripts/research_insight_extractor.py"])
@pytest.mark.parametrize("exported", [True, False])
def test_env_first_db_password_with_the_cron_dotenv_fallback(script, exported, tmp_path, monkeypatch):
    """The executor passes DB_PASSWORD through the allowlist; cron (no env) still reads the .env DB_PASSWORD line.
    Either way nothing is copied into the process env."""
    tree = ast.parse((ROOT / script).read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_get_conn")
    _render(tmp_path / ".env")
    captured: dict = {}
    stub = SimpleNamespace(connect=lambda **kw: captured.update(kw) or "conn")
    monkeypatch.setitem(sys.modules, "psycopg2", stub)
    fake_environ = {"DB_PASSWORD": "from-the-env"} if exported else {}
    ns = {"os": SimpleNamespace(environ=fake_environ), "PROJECT_ROOT": tmp_path, "sys": sys}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), script, "exec"), ns)  # noqa: S102
    assert ns["_get_conn"]() == "conn"
    assert captured["password"] == ("from-the-env" if exported else "'" + FAKE + "DB_PASSWORD'")
    assert fake_environ == ({"DB_PASSWORD": "from-the-env"} if exported else {})


def test_db_adapter_db_names_are_exactly_what_it_reads():
    import re
    src = (ROOT / "scripts" / "db_adapter.py").read_text(encoding="utf-8")
    reads = set(re.findall(r'(?:getenv|environ\.get)\(\s*"(DB_[A-Z_]+)"', src))
    tree = ast.parse(src)
    names = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "DB_ENV_NAMES" for t in n.targets))
    assert set(names) == reads == set(DB)
