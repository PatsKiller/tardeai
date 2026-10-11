"""Shadow wave 4 (SW4, 2026-10-11): lane scripts copy only named keys from <checkout>/.env, never the whole file.

COVERS = ["scripts/aegis_social_sentiment.py", "scripts/aegis_transcript_discovery.py",
          "scripts/aegis_nightly_ingestion.py", "scripts/hermes_social_sentiment.py",
          "scripts/sync_social_to_intelligence.py", "scripts/backfill_subject_identity.py",
          "scripts/trade_backtest_engine.py", "scripts/feedback_loop_processor.py",
          "scripts/etf_performance_enrich.py"]

AGENTS.md §23.18 (ruling 3): a dispatched R1 lane carries no broker credential. Each of these scripts used to copy
every key of the env file (which also holds ALPACA_* / SCHWAB_* names) into os.environ at import or connect time,
so the lane process held a broker credential whatever the allowlist env_names said. The narrowing keeps the keys the
lane reads (DB_* first, so db_adapter never falls back to env_bootstrap's whole-render load) and drops the rest.

The test runs each script's own loader code against a scratch checkout whose .env carries broker-named keys and
asserts that only allowed names reach os.environ. It also pins the strict argparse that etf_performance_enrich gained
(an unknown flag such as --dryrun used to fall through to the live run). Hermetic: scratch files and a monkeypatched
os.environ only; no DB, no network, no subprocess.
"""

from __future__ import annotations

import os
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from scripts.lib import lane_dispatch as LD  # noqa: E402

ENV_TEXT = "\n".join([
    "# scratch env file",
    "DB_HOST=127.0.0.1",
    "DB_PORT=5432",
    "DB_NAME=trade_ai",
    "DB_USER=trade_ai",
    "DB_PASSWORD=scratch-pw",
    "ALPACA_API_KEY=should-never-load",
    "ALPACA_SECRET_KEY=should-never-load",
    "SCHWAB_APP_KEY=should-never-load",
    "TELEGRAM_BOT_TOKEN=should-never-load",
    "BRAVE_SEARCH_API_KEY=scratch-brave",
    "SEARXNG_URL=http://127.0.0.1:1/search",
    "SOCIAL_FOLD_MAX_AGE_HOURS=24",
]) + "\n"

#: script -> the names its loader may set (DB_* plus what the lane itself reads).
NAMED = {
    "aegis_social_sentiment.py": {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "BRAVE_SEARCH_API_KEY",
                                  "AEGIS_BRAVE_ENABLED", "BRAVE_ROUTER_ENABLED", "SEARCH_ROUTING_ENGINE"},
    "aegis_transcript_discovery.py": {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
                                      "BRAVE_SEARCH_API_KEY", "AEGIS_BRAVE_ENABLED", "BRAVE_ROUTER_ENABLED",
                                      "SEARCH_ROUTING_ENGINE"},
    "aegis_nightly_ingestion.py": {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"},
    "hermes_social_sentiment.py": {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "SEARXNG_URL"},
    "sync_social_to_intelligence.py": {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
                                       "SOCIAL_FOLD_MAX_AGE_HOURS"},
}
DB_ONLY = {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"}


def _scratch_checkout(tmp_path: Path, script: str) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".env").write_text(ENV_TEXT)
    return tmp_path / "scripts" / script


def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith(("DB_", "ALPACA", "SCHWAB", "TELEGRAM", "BRAVE", "SEARXNG", "SOCIAL_FOLD", "AEGIS_",
                         "SEARCH_ROUTING")):
            monkeypatch.delenv(k, raising=False)


def _loader_source(script: str) -> str:
    """The script's own env loader block, verbatim (from the narrowing comment to the end of the loop)."""
    src = (SCRIPTS / script).read_text(encoding="utf-8")
    start = src.index("# Load only the named keys from .env")
    end = src.index("os.environ[k] = v", start) + len("os.environ[k] = v")
    return src[start:end] + "\n"


def _loaded(monkeypatch) -> set[str]:
    return {k for k in os.environ if k.startswith(("DB_", "ALPACA", "SCHWAB", "TELEGRAM", "BRAVE", "SEARXNG",
                                                   "SOCIAL_FOLD"))}


@pytest.mark.parametrize("script", sorted(NAMED))
def test_module_loader_copies_only_its_named_keys(tmp_path, monkeypatch, script):
    _clean_env(monkeypatch)
    path = _scratch_checkout(tmp_path, script)
    ns = {"os": os, "PROJECT_ROOT": path.resolve().parent.parent, "__file__": str(path)}
    exec(compile(_loader_source(script), str(path), "exec"), ns)  # noqa: S102 - the script's own loader text
    loaded = _loaded(monkeypatch)
    assert loaded <= NAMED[script], loaded - NAMED[script]
    assert DB_ONLY <= loaded
    assert os.environ["DB_PASSWORD"] == "scratch-pw"
    assert set(ns["_ENV_NAMES"]) == NAMED[script]
    for name in ns["_ENV_NAMES"]:
        assert not any(f in name for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS), name


def test_backfill_subject_identity_connect_loads_db_keys_only(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    _scratch_checkout(tmp_path, "backfill_subject_identity.py")
    import backfill_subject_identity as bsi

    seen = {}
    monkeypatch.setattr(bsi, "ROOT", tmp_path)
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=lambda **kw: seen.update(kw) or "c"))
    assert bsi._db() == "c"
    assert _loaded(monkeypatch) == DB_ONLY
    assert seen["password"] == "scratch-pw" and seen["dbname"] == "trade_ai"


def _exec_prefix(script: str, marker_end: str, path: Path) -> dict:
    """Run the script's top-of-module text up to (excluding) `marker_end` with __file__ in the scratch checkout."""
    src = (SCRIPTS / script).read_text(encoding="utf-8")
    ns = {"__file__": str(path), "__name__": "sw4_prefix"}
    exec(compile(src[: src.index(marker_end)], str(path), "exec"), ns)  # noqa: S102
    return ns


def test_trade_backtest_engine_module_load_takes_db_keys_only(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    path = _scratch_checkout(tmp_path, "trade_backtest_engine.py")
    _exec_prefix("trade_backtest_engine.py", "import psycopg2", path)
    assert _loaded(monkeypatch) == DB_ONLY


def test_feedback_loop_processor_module_load_takes_db_password_only(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    path = _scratch_checkout(tmp_path, "feedback_loop_processor.py")
    _exec_prefix("feedback_loop_processor.py", 'LANE_ID = "feedback-loop-processor"', path)
    assert _loaded(monkeypatch) == {"DB_PASSWORD"} and os.environ["DB_PASSWORD"] == "scratch-pw"
    assert "load_dotenv(" not in (SCRIPTS / "feedback_loop_processor.py").read_text()


def test_etf_performance_enrich_module_load_takes_db_keys_only(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    path = _scratch_checkout(tmp_path, "etf_performance_enrich.py")
    _exec_prefix("etf_performance_enrich.py", "from db_adapter import _get_conn", path)
    assert _loaded(monkeypatch) == DB_ONLY
    assert "load_dotenv(" not in (SCRIPTS / "etf_performance_enrich.py").read_text()


@pytest.mark.parametrize("argv", [["--dryrun"], ["--dry-run", "--apply"], ["--symbol", "SPY"]])
def test_etf_performance_enrich_unknown_flag_exits_2_not_live(argv, monkeypatch):
    import etf_performance_enrich as epe

    monkeypatch.setattr(epe, "enrich", lambda: pytest.fail("live path reached on a usage error"))
    with pytest.raises(SystemExit) as e:
        epe.main(argv)
    assert e.value.code == 2


def test_no_fixed_script_keeps_a_whole_file_copy():
    whole = re.compile(r"os\.environ\.setdefault\(k\.strip\(\), v\.strip\(\)\)|load_dotenv\(")
    for script in [*NAMED, "trade_backtest_engine.py"]:
        src = (SCRIPTS / script).read_text(encoding="utf-8")
        if script == "trade_backtest_engine.py":
            assert "if k.strip().startswith('DB_'):" in src
            continue
        assert not whole.search(src), script
        assert "if k in _ENV_NAMES and v and k not in os.environ:" in src, script
