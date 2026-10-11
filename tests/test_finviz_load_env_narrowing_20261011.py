"""finviz_enrichment._load_env copies only the FINVIZ_* names it needs into os.environ (W4 canary blocker, 2026-10-11).

COVERS = ["scripts/finviz_enrichment.py"]

Before this change `_load_env` (called from `_fetch_view`, the live fetch path of the `finviz-enrichment` lane, cron
L142) copied EVERY name in the tmpfs secret render and the disk .env into os.environ. The render carries broker
credentials (ALPACA_*, SCHWAB_*: config/secret_registry.yaml), so the live ingest process held them, which AGENTS
§23.18 forbids for a provider owner and which blocked the lane's canary (allowlist env_report_reason).

Pinned here:
* with a fake render and a fake .env (tmp_path, fake values) holding ALPACA_*, SCHWAB_*, SNAPTRADE_*, TELEGRAM_* and
  DB_PASSWORD next to the FINVIZ_* keys, only the FINVIZ_* keys reach os.environ, on both the resolve_secret path and
  the plain-.env fallback path;
* setdefault semantics are kept (an exported value wins; the render wins over .env);
* `_ENV_KEYS` is exactly the FINVIZ_* names of the lane's allowlist env_names, and every FINVIZ_* name the live path
  reads (finviz_throttle tunables + the _env auth trio) is in it;
* `_load_env` is the module's only os.environ writer;
* social_ingest.py and sec_data_ingest.py (the other two W4 owners) never write os.environ at all, so they cannot
  copy the render either.

Hermetic: tmp_path files with fake values, monkeypatched env; no network, no DB, no real secret file read.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_enrichment as FE  # noqa: E402

BROKER_AND_OTHER = (
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_IRA_API_KEY", "ALPACA_TAXABLE_SECRET_KEY",
    "SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "SNAPTRADE_USER_SECRET", "TELEGRAM_BOT_TOKEN", "DB_PASSWORD",
    "OPENAI_API_KEY",
)
FINVIZ_RENDER = ("FINVIZ_API_TOKEN", "FINVIZ_COOKIE")
FINVIZ_DOTENV = ("FINVIZ_USER_AGENT", "FINVIZ_MIN_INTERVAL", "FINVIZ_COOLDOWN_DEFAULT", "FINVIZ_MAX_COOLDOWN_S")


def _write(path: Path, names, tag: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{n}=fake-{tag}-{n.lower()}\n" for n in names), encoding="utf-8")


@pytest.fixture()
def fake_secrets(tmp_path, monkeypatch):
    """A fake render at $XDG_RUNTIME_DIR/tradeai/env and a fake <root>/.env; every involved name unset."""
    xdg = tmp_path / "xdg"
    root = tmp_path / "checkout"
    _write(xdg / "tradeai" / "env", BROKER_AND_OTHER + FINVIZ_RENDER + ("FINVIZ_USER_AGENT",), "render")
    _write(root / ".env", BROKER_AND_OTHER + FINVIZ_RENDER + FINVIZ_DOTENV, "dotenv")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg))
    for n in set(BROKER_AND_OTHER + FINVIZ_RENDER + FINVIZ_DOTENV):
        monkeypatch.delenv(n, raising=False)
    for n in [k for k in os.environ if k.startswith(("ALPACA_", "SCHWAB_"))]:  # set by other tests' collection
        monkeypatch.delenv(n, raising=False)
    return root


def _assert_no_foreign_names() -> None:
    leaked = sorted(n for n in BROKER_AND_OTHER if n in os.environ)
    assert leaked == [], f"_load_env copied non-FINVIZ names into os.environ: {leaked}"
    assert not any(k.startswith(("ALPACA_", "SCHWAB_")) for k in os.environ)


def test_render_path_copies_only_finviz_keys(fake_secrets):
    FE._load_env(fake_secrets)
    _assert_no_foreign_names()
    # render first, then .env (setdefault: first wins)
    assert os.environ["FINVIZ_COOKIE"] == "fake-render-finviz_cookie"
    assert os.environ["FINVIZ_API_TOKEN"] == "fake-render-finviz_api_token"
    assert os.environ["FINVIZ_USER_AGENT"] == "fake-render-finviz_user_agent"
    assert os.environ["FINVIZ_MIN_INTERVAL"] == "fake-dotenv-finviz_min_interval"


def test_exported_value_wins(fake_secrets, monkeypatch):
    monkeypatch.setenv("FINVIZ_COOKIE", "exported")
    FE._load_env(fake_secrets)
    assert os.environ["FINVIZ_COOKIE"] == "exported"
    _assert_no_foreign_names()


def test_fallback_path_copies_only_finviz_keys(fake_secrets, monkeypatch):
    # resolve_secret unimportable -> the plain .env fallback branch
    monkeypatch.setitem(sys.modules, "resolve_secret", None)
    FE._load_env(fake_secrets)
    _assert_no_foreign_names()
    assert os.environ["FINVIZ_COOKIE"] == "fake-dotenv-finviz_cookie"
    assert os.environ["FINVIZ_MAX_COOLDOWN_S"] == "fake-dotenv-finviz_max_cooldown_s"


def test_no_files_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "none"))
    before = dict(os.environ)
    FE._load_env(tmp_path / "no-checkout")
    assert dict(os.environ) == before


def test_env_keys_equal_the_allowlist_finviz_names():
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    entries = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("lane_id") == "finviz-enrichment" and "env_names" in o:
                entries.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(allow)
    assert len(entries) == 1
    allow_finviz = {n for n in entries[0]["env_names"] if n.startswith("FINVIZ_")}
    assert set(FE._ENV_KEYS) == allow_finviz
    assert not any(n.startswith(("ALPACA_", "SCHWAB_")) for n in FE._ENV_KEYS)


def test_every_finviz_name_the_live_path_reads_is_loaded():
    throttle = (ROOT / "scripts" / "finviz_throttle.py").read_text(encoding="utf-8")
    for n in ("FINVIZ_MIN_INTERVAL", "FINVIZ_COOLDOWN_DEFAULT", "FINVIZ_MAX_COOLDOWN_S"):
        assert f'os.getenv("{n}"' in throttle
        assert n in FE._ENV_KEYS
    src = (ROOT / "scripts" / "finviz_enrichment.py").read_text(encoding="utf-8")
    for n in ("FINVIZ_API_TOKEN", "FINVIZ_COOKIE", "FINVIZ_USER_AGENT"):
        assert f'_env("{n}"' in src
        assert n in FE._ENV_KEYS


def _environ_writers(path: Path) -> list[str]:
    """Functions (or <module>) holding an os.environ write: item assignment, setdefault/update/pop, putenv."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []

    def is_environ(node) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "environ"
                and isinstance(node.value, ast.Name) and node.value.id in ("os", "_os"))

    def visit(node, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner
            if isinstance(child, (ast.Assign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                if any(isinstance(t, ast.Subscript) and is_environ(t.value) for t in targets):
                    out.append(name)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                f = child.func
                if (is_environ(f.value) and f.attr in ("setdefault", "update", "pop", "clear")) or f.attr == "putenv":
                    out.append(name)
            visit(child, name)

    visit(tree, "<module>")
    return out


def test_load_env_is_the_only_environ_writer_in_finviz_enrichment():
    assert set(_environ_writers(ROOT / "scripts" / "finviz_enrichment.py")) == {"_load_env"}


@pytest.mark.parametrize("script", ["social_ingest.py", "sec_data_ingest.py"])
def test_other_w4_owners_never_write_os_environ(script):
    assert _environ_writers(ROOT / "scripts" / script) == []
