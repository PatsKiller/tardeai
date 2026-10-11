"""Hermetic test bootstrap (AGENTS §24.6): under pytest nothing reaches host state unless a test opts in.

Covers scripts/lib/hermetic_test_guard.py and its wiring in tests/conftest.py:
(a) the M2 test-database bootstrap runs only with M2_TEST_DB=1;
(b) env loaders resolve to an empty fixture, and live host paths refuse loudly, naming the caller;
(c) live-DSN connects raise before libpq.

Every probe path below is refused by the audit hook BEFORE the syscall, so no live file is touched.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import hermetic_test_guard as G  # noqa: E402

RELEASES_PROBE = Path(G.STATE.real_home or Path.home()) / "trade-ai-releases" / "__hermetic_probe__" / "absent.json"
RUNTIME_PROBE = Path(f"/run/user/{os.getuid()}/tradeai/env")


def _refused(fn) -> list[dict]:
    """Run fn, expect HostStateAccessError, and take the record so this test does not fail on it."""
    with pytest.raises(G.HostStateAccessError) as ei:
        fn()
    recs = G.drain()
    assert recs, "refusal was not recorded"
    assert "HERMETIC_TEST_GUARD" in str(ei.value) and "caller" in str(ei.value)
    return recs


def test_guard_is_installed_for_this_session():
    assert G.STATE.installed
    if not G.session_opted_in():
        assert G.STATE.allow is False


# ── (a) M2 bootstrap is opt-in ───────────────────────────────────────────────

def test_m2_bootstrap_is_skipped_without_opt_in():
    if G.m2_opted_in():
        pytest.skip("this session opted in with M2_TEST_DB=1")
    assert os.environ.get("M2_SKIP_DOCKER") == "1"


def test_conftest_gates_m2_bootstrap_on_explicit_opt_in():
    text = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "if _hermetic.m2_opted_in() and os.environ.get(\"M2_SKIP_DOCKER\") != \"1\":" in text
    assert "_ensure_m2_test_db()" in text


# ── (b) loaders resolve to the empty fixture ─────────────────────────────────

def test_env_bootstrap_reads_only_the_empty_fixture():
    if G.session_opted_in():
        pytest.skip("session opted in")
    from scripts.lib import env_bootstrap as EB

    cands = EB._candidates()
    assert cands == [Path(os.environ[G.ENV_FILES_ENV])]
    assert cands[0].read_text() == ""
    meta = EB.load_env(names=("DB_PASSWORD",))
    assert meta["keys_applied"] == 0 and meta["source"] is None
    assert G.drain() == []


def test_env_bootstrap_override_is_inherited_by_a_child_process():
    if G.session_opted_in():
        pytest.skip("session opted in")
    out = subprocess.run(
        [sys.executable, "-c", "from scripts.lib import env_bootstrap as e; print([str(p) for p in e._candidates()])"],
        cwd=str(ROOT), capture_output=True, text=True, check=True, env=dict(os.environ),
    ).stdout
    assert os.environ[G.ENV_FILES_ENV] in out
    assert "tradeai/env" not in out and ".env'" not in out


def test_env_bootstrap_default_order_unchanged_without_override(monkeypatch):
    from scripts.lib import env_bootstrap as EB

    monkeypatch.delenv(G.ENV_FILES_ENV, raising=False)
    names = [p.name for p in EB._candidates()]
    assert names[-2:] == [".env", ".env.pre-sm-migration"] and "env" in names


def test_live_project_root_resolves_to_the_empty_fixture():
    if G.session_opted_in():
        pytest.skip("session opted in")
    from scripts.lib.live_project_root import get_live_project_root

    root = get_live_project_root()
    assert root == Path(os.environ[G.LIVE_ROOT_ENV])
    assert "trade-ai-releases" not in str(root) and list(root.iterdir()) == []


def test_dotenv_loads_nothing_outside_the_temp_dir(tmp_path, monkeypatch):
    import dotenv

    monkeypatch.delenv("HERMETIC_PROBE_NAME", raising=False)
    assert dotenv.load_dotenv(ROOT / ".env") is False
    assert dotenv.dotenv_values(ROOT / ".env") == {}
    assert dotenv.find_dotenv() == ""
    assert G.drain() == []  # short-circuited: the file was never opened
    if getattr(dotenv, "_hermetic_guard", False):  # real python-dotenv installed: temp files still load
        f = tmp_path / ".env"
        f.write_text("HERMETIC_PROBE_NAME=fixture\n")
        assert dotenv.dotenv_values(f) == {"HERMETIC_PROBE_NAME": "fixture"}


# ── (b) host-path tripwire ───────────────────────────────────────────────────

def test_release_tree_open_is_refused_and_names_the_caller():
    recs = _refused(lambda: open(RELEASES_PROBE))
    assert recs[0]["reason"].startswith("live release tree")
    assert "test_hermetic_test_guard_20261011.py" in recs[0]["caller"]


def test_release_tree_listing_and_sqlite_are_refused():
    _refused(lambda: os.listdir(RELEASES_PROBE.parent))
    _refused(lambda: sqlite3.connect(f"file:{RELEASES_PROBE.with_suffix('.sqlite')}?mode=ro", uri=True))


def test_rendered_runtime_env_is_refused():
    recs = _refused(lambda: RUNTIME_PROBE.read_text())
    assert "runtime env" in recs[0]["reason"]


def test_present_dotenv_outside_temp_is_refused_absent_temp_and_template_are_not(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("A=1\n")
    assert (tmp_path / ".env").read_text() == "A=1\n"  # inside the temp dir: allowed
    assert G.classify(tmp_path / "absent" / ".env") is None  # nothing there to reach
    assert G.classify(ROOT / ".env.example") is None
    monkeypatch.setattr(G.STATE, "temp_roots", ())  # now tmp_path stands in for a checkout with a real .env
    recs = _refused(lambda: open(tmp_path / ".env"))
    assert "dotenv" in recs[0]["reason"]
    assert G.drain() == []


def test_state_root_resolves_to_the_empty_fixture():
    if G.session_opted_in():
        pytest.skip("session opted in")
    from scripts.lib.canonical_store_registry import production_state_root

    root = production_state_root()
    assert root == Path(os.environ[G.STATE_ROOT_ENV]) and "trade-ai-releases" not in str(root)


def test_classify_ignores_ordinary_paths():
    assert G.classify(ROOT / "scripts" / "lib" / "env_bootstrap.py") is None
    assert G.classify(3) is None and G.classify(":memory:") is None


@pytest.mark.host_state("guard self-test: proves the marker lifts every layer for one test")
def test_host_state_marker_lifts_the_guard():
    assert G.STATE.allow is True
    assert G.ENV_FILES_ENV not in os.environ and G.LIVE_ROOT_ENV not in os.environ
    assert G.STATE_ROOT_ENV not in os.environ
    assert os.environ["HOME"] == G.STATE.real_home
    if G.STATE.real_xdg_runtime:
        assert os.environ["XDG_RUNTIME_DIR"] == G.STATE.real_xdg_runtime


def test_rendered_secret_resolver_sees_no_render():
    if G.session_opted_in():
        pytest.skip("session opted in")
    from scripts.secrets.resolve_secret import render_env_path

    p = render_env_path()
    assert not p.exists() and G.classify(p) is None


def test_home_is_an_empty_fixture_with_a_git_identity():
    if G.session_opted_in():
        pytest.skip("session opted in")
    home = Path.home()
    assert str(home) != G.STATE.real_home and str(home).startswith(str(G.STATE.fixture_dir))
    assert not (home / "trade-ai-releases").exists()
    out = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True).stdout
    assert out.strip() == "hermetic-test"


def test_marker_scope_ends_with_the_test():
    if not G.session_opted_in():
        assert G.STATE.allow is False
        assert G.ENV_FILES_ENV in os.environ


_INNER = textwrap.dedent(
    """
    import os
    from pathlib import Path
    import pytest

    PROBE = Path(os.environ["TRADEAI_TEST_REAL_HOME"]) / "trade-ai-releases" / "__hermetic_probe__" / "absent.json"

    def test_swallowed():
        try:
            open(PROBE)
        except Exception:
            pass

    @pytest.mark.host_state("inner opt-in")
    def test_opted_in():
        from scripts.lib import hermetic_test_guard as G
        assert G.STATE.allow is True

    def test_clean():
        assert True
    """
)


def _run_inner(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    (tmp_path / "test_inner_probe.py").write_text(body)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env.pop(G.SESSION_OPT_IN_ENV, None)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "tests"), str(ROOT), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "conftest", "--rootdir",
         str(tmp_path), str(tmp_path / "test_inner_probe.py")],
        cwd=str(tmp_path), capture_output=True, text=True, env=env, timeout=300,
    )


def test_a_swallowed_refusal_still_fails_the_test(tmp_path):
    r = _run_inner(tmp_path, _INNER)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "1 failed, 2 passed" in out, out
    assert "HERMETIC_TEST_GUARD" in out and "test_inner_probe.py" in out and "test_swallowed" in out


def test_a_collection_time_access_fails_the_session(tmp_path):
    body = "import os\nfrom pathlib import Path\ntry:\n    open(Path(os.environ['TRADEAI_TEST_REAL_HOME']) / 'trade-ai-releases' / 'x.env')\nexcept OSError:\n    pass\n\ndef test_ok():\n    assert True\n"
    r = _run_inner(tmp_path, body)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "hermetic test guard: collection" in out and "1 passed" in out


# ── (c) live DSN ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "dsn,kwargs,env,refused",
    [
        ("dbname=trade_ai user=trade_ai host=localhost", {}, {}, True),
        ("postgresql://u@127.0.0.1:5432/trade_ai", {}, {}, True),
        (None, {"dbname": "trade_ai", "host": "localhost"}, {}, True),
        (None, {"database": "trade_ai"}, {}, True),
        ("host=localhost", {}, {"PGDATABASE": "trade_ai"}, True),
        ("postgresql://m2:x@127.0.0.1:55432/m2_shadow", {}, {"M2_TEST_DB": "1"}, True),
        ("postgresql://m2:x@127.0.0.1:55432/m2_shadow_test", {}, {}, True),
        ("postgresql://m2:x@127.0.0.1:55432/m2_shadow_test", {}, {"M2_TEST_DB": "1"}, False),
        ("dbname=trade_ai_test host=localhost", {}, {}, False),
        ("dbname=scratch", {}, {G.LIVE_DATABASES_ENV: "scratch"}, True),
    ],
)
def test_refusal_reason(dsn, kwargs, env, refused):
    assert bool(G.refusal_reason(dsn, kwargs, env)) is refused


def test_wrapped_connect_raises_driver_operational_error_before_the_driver():
    import types

    class FakeOperationalError(Exception):
        pass

    calls = []
    mod = types.ModuleType("fakepg")
    mod.connect = lambda *a, **k: calls.append((a, k)) or "conn"
    G._wrap_connect(mod, "connect", FakeOperationalError)
    before = len(G.STATE.db_refusals)
    with pytest.raises(FakeOperationalError, match="HERMETIC_TEST_GUARD"):
        mod.connect("dbname=trade_ai host=localhost")
    assert calls == [] and len(G.STATE.db_refusals) == before + 1
    assert mod.connect(dbname="trade_ai_test") == "conn" and calls


def test_installed_drivers_are_wrapped():
    import importlib.util

    for name in ("psycopg2", "psycopg"):
        if importlib.util.find_spec(name) is None:
            continue
        try:
            mod = __import__(name)
        except ImportError:
            continue
        assert getattr(mod.connect, "_hermetic_guard", False), name
        with pytest.raises(mod.OperationalError, match="HERMETIC_TEST_GUARD"):
            mod.connect("dbname=trade_ai host=127.0.0.1 connect_timeout=1")
