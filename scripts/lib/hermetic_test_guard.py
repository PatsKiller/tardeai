"""Hermetic test bootstrap: under pytest nothing reaches host state unless a test opts in (AGENTS §24.6).

Installed by ``tests/conftest.py`` before any test module is imported. Three layers:

1. **Loaders and roots resolve to an empty fixture.** ``env_bootstrap`` reads only ``TRADEAI_ENV_BOOTSTRAP_FILES``
   (an empty file); ``lib.live_project_root`` (and the CURRENT readers that honour it) see ``TRADEAI_LIVE_PROJECT_ROOT``
   / ``TRADE_AI_DEPLOY_CURRENT`` (an empty directory named CURRENT); ``TRADEAI_STATE_ROOT`` is an empty state root;
   ``TRADEAI_DEV_ROOT`` names an absent dev checkout; ``HOME`` is an empty fixture home (git identity only) and
   ``XDG_RUNTIME_DIR`` an empty runtime dir, which is what a CI runner sees. ``dotenv.load_dotenv`` /
   ``dotenv_values`` / ``find_dotenv`` return nothing for any path outside the temp dir. The variables are
   inherited by subprocesses, so a script a test launches resolves the same fixtures. An inherited value that
   names live state is replaced.
2. **Host-path tripwire.** A ``sys.addaudithook`` hook refuses (``HostStateAccessError``, a ``PermissionError``)
   every open / listdir / scandir / sqlite connect / mkdir / remove / rename aimed at ``~/trade-ai-releases/**``,
   ``/run/user/*/tradeai/**`` (``$XDG_RUNTIME_DIR/tradeai``) or a ``.env`` / ``.env.*`` file outside the temp dir,
   and records the caller. A refusal swallowed by a broad ``except`` is still recorded, and conftest turns every
   record into a pytest failure (an ERROR naming the path and the calling frame).
3. **Live DSN refusal.** ``psycopg2.connect`` and ``psycopg.connect`` raise ``LiveDsnRefused`` (a subclass of the
   driver's own ``OperationalError``, so a test that skips on a connect error still skips) before libpq is reached
   when the target database is production (``trade_ai``), the live M2 shadow, a name in
   ``TRADEAI_TEST_LIVE_DATABASES``, or anything on the M2 container port (55432) without ``M2_TEST_DB=1``.

Opt-in: ``@pytest.mark.host_state("reason")`` on a test (layers 1–3 off and the real HOME / XDG_RUNTIME_DIR /
loader variables restored for that test only), or
``TRADEAI_TEST_HOST_STATE=1`` for a whole session the operator runs by hand. The M2 test-database bootstrap in
conftest runs only with ``M2_TEST_DB=1``.

Cause (§20): SHARDS_01_04_HANDOFF "Earlier test setup … was not fully isolated" (2026-10-11): conftest attempted the
M2 maintenance-database setup unless ``M2_SKIP_DOCKER=1``, and installed dotenv/env loaders read host env during
collection; RC7 2026-10-10 (``hdi2test`` rows in five live tables).

Pure stdlib at import. Never reads an env file and never prints a value.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

SESSION_OPT_IN_ENV = "TRADEAI_TEST_HOST_STATE"
M2_OPT_IN_ENV = "M2_TEST_DB"
ENV_FILES_ENV = "TRADEAI_ENV_BOOTSTRAP_FILES"
LIVE_ROOT_ENV = "TRADEAI_LIVE_PROJECT_ROOT"
STATE_ROOT_ENV = "TRADEAI_STATE_ROOT"
REAL_HOME_ENV = "TRADEAI_TEST_REAL_HOME"
DEPLOY_CURRENT_ENV = "TRADE_AI_DEPLOY_CURRENT"
DEV_ROOT_ENV = "TRADEAI_DEV_ROOT"
LIVE_DATABASES_ENV = "TRADEAI_TEST_LIVE_DATABASES"
MARKER = "host_state"

PRODUCTION_DATABASES = frozenset({"trade_ai"})
M2_CONTAINER_PORT = "55432"
_ENV_TEMPLATE_NAMES = frozenset({".env.example", ".env.sample", ".env.template"})
_RUNTIME_ENV_RE = re.compile(r"^/run/user/\d+/tradeai(/|$)")

_AUDIT_EVENTS = {
    "open": (0,),
    "os.listdir": (0,),
    "os.scandir": (0,),
    "os.mkdir": (0,),
    "os.remove": (0,),
    "os.rmdir": (0,),
    "os.rename": (0, 1),
    "os.symlink": (0, 1),
    "os.link": (0, 1),
    "os.truncate": (0,),
    "shutil.copyfile": (0, 1),
    "shutil.rmtree": (0,),
    "sqlite3.connect": (0,),
}


class HostStateAccessError(PermissionError):
    """A test reached a live host path. Recorded even when the caller swallows it."""


class _State:
    installed = False
    allow = False
    violations: list[dict] = []
    db_refusals: list[dict] = []
    fixture_dir: Path | None = None
    releases_root = ""
    runtime_roots: tuple[str, ...] = ()
    temp_roots: tuple[str, ...] = ()
    live_shadow_fn = None
    real_home = ""
    real_xdg_runtime = ""


STATE = _State()


def session_opted_in(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get(SESSION_OPT_IN_ENV, "")).strip() == "1"


def m2_opted_in(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get(M2_OPT_IN_ENV, "")).strip() == "1"


def _norm(p: str) -> str:
    return os.path.normpath(os.path.abspath(p))


def _under(path: str, root: str) -> bool:
    return bool(root) and (path == root or path.startswith(root.rstrip("/") + "/"))


def classify(path) -> str | None:
    """Why ``path`` is live host state, or None. Pure over the installed roots."""
    if isinstance(path, int) or path is None:
        return None
    try:
        raw = os.fsdecode(path)
    except (TypeError, ValueError):
        return None
    if raw.startswith("file:"):  # sqlite URI
        raw = raw[5:].split("?", 1)[0]
    if not raw or raw == ":memory:":
        return None
    p = _norm(raw)
    if _under(p, STATE.releases_root):
        return "live release tree (~/trade-ai-releases)"
    if _RUNTIME_ENV_RE.match(p) or any(_under(p, r) for r in STATE.runtime_roots):
        return "rendered runtime env (/run/user/*/tradeai)"
    name = os.path.basename(p)
    if (name == ".env" or (name.startswith(".env.") and name not in _ENV_TEMPLATE_NAMES)) and not any(
        _under(p, t) for t in STATE.temp_roots
    ):
        # An absent .env (a worktree, CI) holds nothing to reach; refusing it would only fail tests that are
        # already hermetic there. A present one (the main checkout) is refused.
        if os.path.lexists(p):
            return "dotenv file outside the temp dir"
    return None


def _caller() -> str:
    """Innermost frame that is not this module, the stdlib or a site-package. Reads no source (no linecache)."""
    here = os.path.abspath(__file__)
    stdlib = os.path.dirname(os.__file__)
    f = sys._getframe(1)
    while f is not None:
        fn = os.path.abspath(f.f_code.co_filename)
        if not (fn == here or fn.startswith(stdlib) or "site-packages" in fn or f.f_code.co_filename.startswith("<")):
            return f"{fn}:{f.f_lineno} in {f.f_code.co_name}"
        f = f.f_back
    return "<unknown>"


def _audit(event, args):
    idx = _AUDIT_EVENTS.get(event)
    if idx is None or STATE.allow:
        return
    for i in idx:
        if i >= len(args):
            continue
        reason = classify(args[i])
        if reason:
            rec = {"event": event, "path": os.fsdecode(args[i]), "reason": reason, "caller": _caller()}
            STATE.violations.append(rec)
            raise HostStateAccessError(
                f"HERMETIC_TEST_GUARD: {event} {rec['path']!r} refused under pytest ({reason}); "
                f"caller {rec['caller']}. Opt in with @pytest.mark.{MARKER}(reason) (AGENTS §24.6)."
            )


# ── DB ───────────────────────────────────────────────────────────────────────

def live_databases(env=None) -> frozenset[str]:
    env = os.environ if env is None else env
    names = set(PRODUCTION_DATABASES)
    names |= {x.strip() for x in str(env.get(LIVE_DATABASES_ENV, "")).split(",") if x.strip()}
    if STATE.live_shadow_fn is not None:
        try:
            names |= set(STATE.live_shadow_fn())
        except Exception:
            names.add("m2_shadow")
    else:
        names.add("m2_shadow")
    return frozenset(names)


def _parse_conninfo(dsn: str) -> dict:
    s = str(dsn or "").strip()
    if not s:
        return {}
    if "://" in s:
        from urllib.parse import parse_qsl, unquote, urlsplit

        u = urlsplit(s)
        out = {k: v for k, v in parse_qsl(u.query)}
        if u.path.lstrip("/"):
            out["dbname"] = unquote(u.path.lstrip("/"))
        if u.hostname:
            out["host"] = u.hostname
        if u.port:
            out["port"] = str(u.port)
        if u.username:
            out["user"] = unquote(u.username)
        return out
    out = {}
    for m in re.finditer(r"(\w+)\s*=\s*('(?:[^'\\]|\\.)*'|\S+)", s):
        out[m.group(1)] = m.group(2).strip("'")
    return out


def dsn_target(dsn=None, kwargs=None, env=None) -> dict:
    """(dbname, port) a libpq connect would use, following libpq's defaults. Pure over ``env``."""
    env = os.environ if env is None else env
    params = _parse_conninfo(dsn or "")
    for k, v in (kwargs or {}).items():
        if v is None:
            continue
        params["dbname" if k == "database" else k] = str(v)
    user = params.get("user") or env.get("PGUSER") or os.environ.get("USER", "")
    dbname = params.get("dbname") or env.get("PGDATABASE") or user
    port = str(params.get("port") or env.get("PGPORT") or "5432")
    return {"dbname": dbname, "port": port}


def refusal_reason(dsn=None, kwargs=None, env=None) -> str | None:
    env = os.environ if env is None else env
    t = dsn_target(dsn, kwargs, env)
    if t["dbname"] in live_databases(env):
        return f"database {t['dbname']!r} is live"
    if t["port"] == M2_CONTAINER_PORT and not m2_opted_in(env):
        return f"port {M2_CONTAINER_PORT} is the M2 container; set {M2_OPT_IN_ENV}=1 to use its test database"
    return None


def _wrap_connect(module, attr: str, error_base: type) -> None:
    real = getattr(module, attr, None)
    if real is None or getattr(real, "_hermetic_guard", False):
        return
    refused = type("LiveDsnRefused", (error_base,), {"__module__": __name__})

    def connect(*args, **kwargs):
        if not STATE.allow:
            dsn = args[0] if args else kwargs.get("dsn") or kwargs.get("conninfo")
            reason = refusal_reason(dsn, {k: v for k, v in kwargs.items() if k not in ("dsn", "conninfo")})
            if reason:
                rec = {"driver": module.__name__, "reason": reason, "caller": _caller()}
                STATE.db_refusals.append(rec)
                raise refused(
                    f"HERMETIC_TEST_GUARD: {module.__name__}.{attr} refused under pytest ({reason}); "
                    f"caller {rec['caller']}. Use TRADEAI_TEST_ISOLATED_DSN or @pytest.mark.{MARKER} (AGENTS §24.6)."
                )
        return real(*args, **kwargs)

    connect._hermetic_guard = True  # type: ignore[attr-defined]
    connect.__wrapped__ = real  # type: ignore[attr-defined]
    setattr(module, attr, connect)


def install_db_guard() -> list[str]:
    """Wrap the installed Postgres drivers' connect. Returns the drivers wrapped (absent drivers are skipped)."""
    wrapped = []
    try:
        import psycopg2  # noqa: PLC0415

        _wrap_connect(psycopg2, "connect", psycopg2.OperationalError)
        wrapped.append("psycopg2")
    except Exception:
        pass
    try:
        import psycopg  # noqa: PLC0415

        _wrap_connect(psycopg, "connect", psycopg.OperationalError)
        wrapped.append("psycopg")
    except Exception:
        pass
    return wrapped


# ── dotenv ───────────────────────────────────────────────────────────────────

def _temp_path(p) -> bool:
    try:
        n = _norm(os.fsdecode(p))
    except (TypeError, ValueError):
        return False
    return any(_under(n, t) for t in STATE.temp_roots)


def install_dotenv_guard() -> str:
    """Make python-dotenv load nothing from outside the temp dir. Installs a stub when it is not installed."""
    import types

    try:
        import dotenv  # noqa: PLC0415
    except ModuleNotFoundError:
        stub = types.ModuleType("dotenv")
        stub.load_dotenv = lambda *a, **k: False
        stub.find_dotenv = lambda *a, **k: ""
        stub.dotenv_values = lambda *a, **k: {}
        sys.modules["dotenv"] = stub
        return "stub"
    if getattr(dotenv, "_hermetic_guard", False):
        return "already"
    real_load, real_values = dotenv.load_dotenv, dotenv.dotenv_values

    def _allowed(args, kwargs) -> bool:
        if STATE.allow or kwargs.get("stream") is not None:
            return True
        path = args[0] if args else kwargs.get("dotenv_path")
        return bool(path) and _temp_path(path)

    def load_dotenv(*args, **kwargs):
        return real_load(*args, **kwargs) if _allowed(args, kwargs) else False

    def dotenv_values(*args, **kwargs):
        return real_values(*args, **kwargs) if _allowed(args, kwargs) else {}

    real_find = dotenv.find_dotenv

    def find_dotenv(*args, **kwargs):
        return real_find(*args, **kwargs) if STATE.allow else ""

    for mod in (dotenv, sys.modules.get("dotenv.main")):
        if mod is None:
            continue
        mod.load_dotenv, mod.dotenv_values, mod.find_dotenv = load_dotenv, dotenv_values, find_dotenv
    dotenv._hermetic_guard = True
    return "wrapped"


# ── install ──────────────────────────────────────────────────────────────────

def install(*, home: str | None = None) -> dict:
    """Install every layer once per process. Idempotent. Returns what was installed (no values)."""
    if STATE.installed:
        return {"installed": "already"}
    # The real home, remembered across the HOME swap below so a child pytest still guards the real tree.
    home = home or os.environ.get(REAL_HOME_ENV) or os.path.expanduser("~")
    os.environ[REAL_HOME_ENV] = home
    STATE.real_home = home
    STATE.releases_root = _norm(os.path.join(home, "trade-ai-releases"))
    xdg = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    STATE.real_xdg_runtime = xdg
    STATE.runtime_roots = tuple(_norm(os.path.join(x, "tradeai")) for x in (xdg,) if x)
    tmp = {_norm(tempfile.gettempdir()), os.path.realpath(tempfile.gettempdir())}
    STATE.temp_roots = tuple(sorted(tmp))
    STATE.allow = session_opted_in()

    fixture = Path(tempfile.mkdtemp(prefix="tradeai_hermetic_env_"))
    (fixture / "env").write_text("")
    # Named CURRENT so code that derives a release id from the link's resolved name sees what CI sees.
    (fixture / "CURRENT").mkdir()
    (fixture / "state_root").mkdir()
    fake_home = fixture / "home"
    fake_home.mkdir()
    (fake_home / ".gitconfig").write_text(
        "[user]\n\tname = hermetic-test\n\temail = hermetic-test@example.invalid\n[init]\n\tdefaultBranch = main\n"
    )
    STATE.fixture_dir = fixture
    if not STATE.allow:
        # An inherited value that names live state is replaced, never trusted.
        for var, target in ((ENV_FILES_ENV, fixture / "env"), (LIVE_ROOT_ENV, fixture / "CURRENT"),
                            (STATE_ROOT_ENV, fixture / "state_root"), (DEPLOY_CURRENT_ENV, fixture / "CURRENT"),
                            (DEV_ROOT_ENV, fixture / "dev_root_absent")):
            cur = os.environ.get(var, "").strip()
            if not cur or classify(cur) or classify(os.path.join(cur, "x")):
                os.environ[var] = str(target)
        # HOME is the root of most host state (~/trade-ai-releases, ~/.config/systemd, ~/.cursor grants,
        # ~/.pgpass): point it at an empty fixture home, as on a CI runner. Git keeps a fixture identity.
        # Child interpreters keep the real user site-packages (code, not host state): on a host where pytest is a
        # --user install (~/.local), a child `python -m pytest` would otherwise fail to import (train 4, 2026-10-11).
        if not os.environ.get("PYTHONUSERBASE"):
            import site

            os.environ["PYTHONUSERBASE"] = site.getuserbase()
        os.environ["HOME"] = str(fake_home)
        # The rendered secrets live under $XDG_RUNTIME_DIR/tradeai (scripts/secrets/resolve_secret.py and friends).
        if _RUNTIME_ENV_RE.match(_norm(os.path.join(xdg or "/nonexistent", "tradeai"))):
            (fixture / "xdg_runtime").mkdir()
            os.environ["XDG_RUNTIME_DIR"] = str(fixture / "xdg_runtime")
        for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            if os.environ.get(var, "").startswith(home.rstrip("/") + "/"):
                os.environ[var] = str(fake_home / var.lower())
    try:  # the M2 guard's live-shadow names (conftest already imported this spelling)
        from scripts.lib.m2_live_shadow_guard import live_shadow_databases

        STATE.live_shadow_fn = live_shadow_databases
    except Exception:
        STATE.live_shadow_fn = None
    dotenv_mode = install_dotenv_guard()
    drivers = install_db_guard()
    sys.addaudithook(_audit)
    STATE.installed = True
    return {"installed": True, "session_opt_in": STATE.allow, "dotenv": dotenv_mode, "db_drivers": drivers}


def drain() -> list[dict]:
    out = list(STATE.violations)
    STATE.violations.clear()
    return out


def format_violations(recs: list[dict], *, where: str) -> str:
    lines = [f"HERMETIC_TEST_GUARD: {len(recs)} live host-state access(es) during {where} (AGENTS §24.6):"]
    for r in recs[:20]:
        lines.append(f"  {r['event']} {r['path']} — {r['reason']}; caller {r['caller']}")
    if len(recs) > 20:
        lines.append(f"  ... and {len(recs) - 20} more")
    lines.append(f"Fix the test (tmp_path / injected fixture) or opt in with @pytest.mark.{MARKER}(reason).")
    return "\n".join(lines)


class allowed:
    """Context manager: lift the guard (opted-in test). Restores the previous state."""

    def __enter__(self):
        self._prev = STATE.allow
        STATE.allow = True
        return self

    def __exit__(self, *exc):
        STATE.allow = self._prev
        return False
