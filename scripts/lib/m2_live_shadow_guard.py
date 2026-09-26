"""Keep pytest (and any casual re-apply) off the LIVE bitemporal shadow.

WHAT WENT WRONG (found by the M5 audit, 2026-09-23)
----------------------------------------------------
``m2_shadow`` on :55432 stopped being a throwaway benchmark database: the
hourly AEC cycle has written live cognitive memory there since 09-20. But every
schema-apply helper still opted into ``m2.allow_destructive_reset`` for ANY
non-production connection, and the test fixtures defaulted to that database.
So each pytest run executed ``DROP SCHEMA memory_r10_m2 CASCADE`` against live
memory -- the sequence was back at 1 and the only identity was minutes old.

The SQL files' isolated-database allowlist could not help: it was written to
tell production from the shadow, and the shadow IS on it.

WHAT THIS MODULE DOES
---------------------
* Names the live shadow database(s) -- ``M2_LIVE_SHADOW_DATABASES``, default
  the database of the canonical shadow DSN.
* ``destructive_reset_permitted(conn)``: the single client-side decision for
  setting ``m2.allow_destructive_reset``. Never production; never the live
  shadow unless ``TRADEAI_M2_ALLOW_LIVE_SHADOW_RESET=1`` is set AND the process
  is not pytest.
* ``refuse_live_shadow_under_pytest(dsn)``: connect-time barrier -- pytest may
  not open a connection to the live shadow at all.
* ``route_tests_off_live_shadow()``: called from tests/conftest.py before any
  test module is imported; points every M2 / memory-shadow DSN env var at a
  dedicated test database on the same container (``M2_TEST_DATABASE``, default
  ``m2_shadow_test``) and creates it when the container is reachable.

Pure stdlib at import; psycopg2 is imported lazily and only for creation, so
CI (pytest + pyyaml only) imports this module without the driver.
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlsplit, urlunsplit

# Canonical shadow DSNs. The admin DSN is the M2 container's owner; the others
# are the least-privilege roles the SQL files create. Kept here (not in each
# consumer) so the test router and the guards agree on one set of targets.
SHADOW_ADMIN_DSN = "postgresql://m2:m2shadow@127.0.0.1:55432/m2_shadow"
SHADOW_AGENT_DSN = "postgresql://m2_agent:m2agent@127.0.0.1:55432/m2_shadow"
SHADOW_WRITER_DSN = "postgresql://tradeai_memory_shadow_writer:shadowwriter@127.0.0.1:55432/m2_shadow"
SHADOW_READER_DSN = "postgresql://tradeai_memory_shadow_reader:shadowreader@127.0.0.1:55432/m2_shadow"

LIVE_DATABASES_ENV = "M2_LIVE_SHADOW_DATABASES"
LIVE_RESET_ENV = "TRADEAI_M2_ALLOW_LIVE_SHADOW_RESET"
TEST_DATABASE_ENV = "M2_TEST_DATABASE"
DEFAULT_TEST_DATABASE = "m2_shadow_test"

#: env var -> canonical DSN it overrides. Every consumer reads these vars first.
_ROUTED_ENV = {
    "M2_DSN": SHADOW_ADMIN_DSN,
    "TEST_DB_DSN": SHADOW_ADMIN_DSN,
    "M2_AGENT_DSN": SHADOW_AGENT_DSN,
    "MEMORY_SHADOW_DSN": SHADOW_ADMIN_DSN,
    "MEMORY_SHADOW_WRITER_DSN": SHADOW_WRITER_DSN,
    "MEMORY_SHADOW_READER_DSN": SHADOW_READER_DSN,
}


def dsn_database(dsn: str) -> str:
    """Database name from a URI or key=value DSN ('' when absent)."""
    s = str(dsn or "").strip()
    if "://" in s:
        return urlsplit(s).path.lstrip("/").split("?")[0]
    for part in s.split():
        if part.startswith("dbname="):
            return part.split("=", 1)[1].strip("'\"")
    return ""


def with_database(dsn: str, database: str) -> str:
    """Same DSN pointed at another database (URI form only)."""
    u = urlsplit(dsn)
    return urlunsplit((u.scheme, u.netloc, "/" + database, u.query, u.fragment))


def live_shadow_databases() -> set[str]:
    raw = os.environ.get(LIVE_DATABASES_ENV, "")
    names = {x.strip() for x in raw.split(",") if x.strip()}
    return names or {dsn_database(SHADOW_ADMIN_DSN)}


#: Allowed pytest database names: the shared default, or a per-worktree suffix so
#: concurrent acceptance runs in different worktrees never share one database.
#: The SQL files' isolated-database check accepts exactly this pattern too.
TEST_DATABASE_RE = re.compile(r"^m2_shadow_test(?:_[a-z0-9_]{1,40})?$")


def shadow_test_database() -> str:
    name = os.environ.get(TEST_DATABASE_ENV, "").strip() or DEFAULT_TEST_DATABASE
    if not TEST_DATABASE_RE.match(name):
        raise RuntimeError(
            f"M2_TEST_DATABASE_REFUSED: {name!r} is not m2_shadow_test or m2_shadow_test_<suffix>; "
            "tests may never be pointed at another database"
        )
    return name


def under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def _conn_database(conn) -> str:
    try:
        return str((conn.get_dsn_parameters() or {}).get("dbname") or "")
    except Exception:
        return ""


def destructive_reset_permitted(conn, *, is_production: bool) -> bool:
    """May this connection opt into ``m2.allow_destructive_reset``?"""
    if is_production:
        return False
    if _conn_database(conn) in live_shadow_databases():
        return os.environ.get(LIVE_RESET_ENV) == "1" and not under_pytest()
    return True


def refuse_live_shadow_under_pytest(dsn: str) -> str:
    if under_pytest() and dsn_database(dsn) in live_shadow_databases():
        raise RuntimeError(
            f"M2_LIVE_SHADOW_FORBIDDEN_UNDER_PYTEST: {dsn_database(dsn)} holds live cognitive "
            f"memory; tests use {shadow_test_database()} (see tests/conftest.py)"
        )
    return dsn


def route_tests_off_live_shadow() -> dict[str, str]:
    """Point every shadow DSN env var at the test database (explicit values win,
    but are still refused at connect time if they name the live shadow)."""
    db = shadow_test_database()
    routed = {}
    for var, dsn in _ROUTED_ENV.items():
        if not os.environ.get(var, "").strip():
            os.environ[var] = with_database(dsn, db)
        routed[var] = os.environ[var]
    return routed


def set_isolated_agent_password(cur, *, is_production: bool) -> bool:
    """Hand the base SQL the isolated container's throwaway m2_agent password.

    r10_m2_isolated_benchmark.sql no longer carries a credential: it creates
    m2_agent only on an isolated database and only with the password in the
    m2.agent_password GUC. The value is the shadow container's own throwaway,
    taken from SHADOW_AGENT_DSN -- never from the environment, where
    M2_AGENT_DSN holds the PRODUCTION credential. Production is never given one;
    there the role is operator-provisioned (scripts/secrets/ensure_m2_agent_dsn.py).
    Returns True when the GUC was set.
    """
    if is_production:
        return False
    password = urlsplit(SHADOW_AGENT_DSN).password or ""
    if not password:
        return False
    cur.execute("SELECT set_config('m2.agent_password', %s, false)", (password,))
    return True


def ensure_test_database(timeout_s: int = 2) -> bool:
    """CREATE the test database on the shadow container if it is missing.

    Connects to the container's maintenance database, never to the live shadow.
    Returns False (tests then skip) when the driver or the container is absent.
    """
    try:
        import psycopg2  # noqa: PLC0415
        from psycopg2 import sql as _sql  # noqa: PLC0415
    except Exception:
        return False
    db = shadow_test_database()
    if db in live_shadow_databases():
        return False
    try:
        conn = psycopg2.connect(with_database(SHADOW_ADMIN_DSN, "postgres"), connect_timeout=timeout_s)
    except Exception:
        return False
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
            if cur.fetchone() is None:
                cur.execute(_sql.SQL("CREATE DATABASE {}").format(_sql.Identifier(db)))
        return True
    except Exception:
        return False
    finally:
        conn.close()
