"""ANCHOR: AGENT_OUTCOME_SCORER_CONN_NO_SECRET_LQ917_20261108 — LQ-20261107-917.

The outcome scorer opens its session from the environment, not a credential file.

``agent_outcome_scorer._get_conn`` read ``PROJECT_ROOT/.env`` by hand for ``DB_PASSWORD`` and passed
a hardcoded host/port/db/user to ``psycopg2.connect``. Three consequences, all live on 2026-11-07:

* a worktree has no ``.env`` (``new-worktree.sh`` never links one), so the scorer could not open a
  session there at all — ``FileNotFoundError`` before the first query;
* where the password is withheld (the emulation harness, a bounded n8n child) the lane was recorded
  ``CANNOT_EMULATE needs_credential``;
* the hardcoded ``host='127.0.0.1'`` made peer auth over the local socket impossible, and it ignored
  ``DB_HOST``/``PGHOST`` entirely.

The fix: the sanctioned ``env_bootstrap.load_env`` supplies ``DB_*`` (honouring the tmpfs render, the
hermetic ``TRADEAI_ENV_BOOTSTRAP_FILES`` override and the executor's per-lane bound), each ``PG*``
name is a fallback after its ``DB_*`` twin, the host defaults to the local socket, and the password
is passed only when one is configured — so peer auth / ``.pgpass`` can serve.

The connection is stubbed throughout: no DB, no network, no credential read.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import agent_outcome_scorer as aos  # noqa: E402

_DB_NAMES = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
             "PGHOST", "PGPORT", "PGDATABASE", "PGUSER")


class _Conn:
    def close(self) -> None:  # the scorer's callers close the session
        pass


def _isolate(monkeypatch, tmp_path) -> Path:
    """No DB_*/PG* name inherited, and an EMPTY env file so the loader copies nothing."""
    for name in _DB_NAMES:
        monkeypatch.delenv(name, raising=False)
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_ENV_BOOTSTRAP_FILES", str(empty))
    return empty


def _capture(monkeypatch) -> dict:
    seen: dict = {}

    def fake_connect(**kwargs):
        seen.update(kwargs)
        return _Conn()

    monkeypatch.setattr(aos.psycopg2, "connect", fake_connect)
    return seen


# ── the environment is the only source ────────────────────────────────────────────────────────────
def test_the_session_is_built_from_the_database_environment(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("DB_HOST", "db.example.invalid")
    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_NAME", "scratch")
    monkeypatch.setenv("DB_USER", "worker")
    monkeypatch.setenv("DB_PASSWORD", "fixture-not-a-secret")  # gitleaks:allow -- synthetic fixture, no credential
    seen = _capture(monkeypatch)

    aos._get_conn()

    assert seen["host"] == "db.example.invalid"
    assert seen["port"] == "6543"
    assert seen["dbname"] == "scratch"
    assert seen["user"] == "worker"
    assert seen["password"] == os.environ["DB_PASSWORD"]


def test_with_nothing_configured_the_host_is_the_peer_socket_and_no_password_is_passed(monkeypatch, tmp_path):
    """Peer auth: a socket path, the OS user, and no password kwarg value. The old code required a
    ``.env`` and would have raised here; it also fixed host to 127.0.0.1."""
    _isolate(monkeypatch, tmp_path)
    seen = _capture(monkeypatch)

    aos._get_conn()

    assert seen["host"] == "/var/run/postgresql"
    assert seen["password"] is None
    assert seen["user"] is None          # libpq uses the OS user, which is what peer auth matches
    assert seen["dbname"] == "trade_ai"


def test_a_pghost_socket_is_honoured_when_db_host_is_unset(monkeypatch, tmp_path):
    """The libpq names are read after their DB_* twin — a host that sets only PGHOST gets the socket."""
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("PGHOST", "/run/postgresql")
    monkeypatch.setenv("PGUSER", "peer_user")
    monkeypatch.setenv("PGPORT", "6432")
    seen = _capture(monkeypatch)

    aos._get_conn()

    assert seen["host"] == "/run/postgresql"
    assert seen["user"] == "peer_user"
    assert seen["port"] == "6432"


def test_db_names_win_over_the_libpq_fallback(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("DB_HOST", "from-db-host.example")
    monkeypatch.setenv("PGHOST", "/run/postgresql")
    seen = _capture(monkeypatch)

    aos._get_conn()

    assert seen["host"] == "from-db-host.example"


def test_the_connection_is_attributed_to_the_lane(monkeypatch, tmp_path):
    """pg_stat_activity / idle-txn triage must be able to name this process."""
    _isolate(monkeypatch, tmp_path)
    seen = _capture(monkeypatch)

    aos._get_conn()

    assert seen["application_name"] == aos.LANE_ID == "agent-outcome-scorer"


# ── no credential file is parsed, and the file load is name-bound ────────────────────────────────
def test_the_connection_parses_no_credential_file(monkeypatch, tmp_path):
    """The old code called ``(PROJECT_ROOT / '.env').read_text()`` on every connect. Nothing named
    ``.env`` may be opened now — the values come from the process environment."""
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("DB_HOST", "db.example.invalid")
    opened: list[Path] = []
    real_read_text = Path.read_text

    def spy(self, *args, **kwargs):
        opened.append(Path(self))
        if Path(self).name in (".env", ".env.pre-sm-migration"):
            return ""          # the old code would take pw='' from this
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)
    seen = _capture(monkeypatch)

    aos._get_conn()

    assert [p for p in opened if p.name in (".env", ".env.pre-sm-migration")] == []
    assert seen["host"] == "db.example.invalid"


def test_the_env_file_load_is_bound_to_the_database_names(monkeypatch, tmp_path):
    """Values do load from the sanctioned file, but only the names this connection reads — an
    unrelated switch in the same file is not copied into the process."""
    _isolate(monkeypatch, tmp_path)
    render = tmp_path / "render.env"
    render.write_text("DB_HOST=from-the-render.example\nDB_PORT=7000\nUNRELATED_SWITCH=1\n",
                      encoding="utf-8")
    monkeypatch.setenv("TRADEAI_ENV_BOOTSTRAP_FILES", str(render))
    seen = _capture(monkeypatch)

    aos._get_conn()

    assert seen["host"] == "from-the-render.example"
    assert seen["port"] == "7000"
    assert "UNRELATED_SWITCH" not in os.environ


def test_the_module_no_longer_opens_the_checkout_env_by_hand():
    """A source pin: the hand-rolled parse and the hardcoded TCP host are gone."""
    src = Path(aos.__file__).read_text(encoding="utf-8")
    assert "PROJECT_ROOT / '.env'" not in src
    assert "env_bootstrap" in src
    assert 'host=\'127.0.0.1\'' not in src
