#!/usr/bin/env python3
"""A disposable PostgreSQL cluster for operator-control tests. TEST-ONLY.

Why this exists
---------------
``admin_write_guard.admin_write()`` is the single door for every Tier-2/3 operator
write, and step 4 of its chain appends to the append-only ``admin_audit_log`` on
EVERY outcome — including a rejected one. Proving authorization, validation,
conflict and replay behaviour therefore requires a real database that accepts real
writes. The production cluster is not that database: a single rejected probe would
append a production audit row.

So this module stands up a cluster that is unmistakably not production:

  * its own ``initdb`` data directory in a temp path, destroyed afterwards
  * ``listen_addresses = 127.0.0.1`` only, on a dynamically allocated free port
  * a database and role whose names are test-only by construction
  * a randomly generated password that exists only for the life of the process

It uses the host's own ``initdb``/``pg_ctl`` rather than a container image: the
binaries are already present, they match production's major version exactly
(PostgreSQL 17), and no daemon, image pull or shared volume is involved. Nothing
here can outlive the test run.

AUTHORITY: TEST_ONLY. This module never reads production credentials, never
connects to the production cluster, and never writes outside its own temp tree.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

__all__ = [
    "IsolatedPostgres",
    "ClusterIdentity",
    "ProductionIdentityError",
    "assert_not_production",
    "isolated_cluster",
    "pg_bin_dir",
]

#: Names that mean production. A test cluster may never present any of them.
PRODUCTION_DB_NAMES = frozenset({"trade_ai", "tradeai", "postgres", "template1"})
PRODUCTION_USERS = frozenset({"trade_ai", "tradeai", "postgres"})
PRODUCTION_PORT = 5432
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

#: A test database/role must announce itself in its own name.
TEST_DB_PREFIX = "tradeai_test_"
TEST_USER_PREFIX = "tradeai_test_"

#: Production data directories this fixture must never point at.
PRODUCTION_DATA_DIR_MARKERS = ("/var/lib/postgresql", "/var/lib/pgsql")

#: Preferred first — matches the production server's major version.
PREFERRED_PG_MAJORS = ("17", "18", "16", "15")


class ProductionIdentityError(RuntimeError):
    """Raised when a connection target looks like production. Never caught to proceed."""


@dataclass(frozen=True)
class ClusterIdentity:
    """Everything the rail needs to decide 'is this production?'."""

    host: str
    port: int
    dbname: str
    user: str
    data_directory: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "data_directory": self.data_directory,
        }


def assert_not_production(identity: ClusterIdentity) -> dict[str, Any]:
    """The hard rail. Raises before any write if the target resembles production.

    Every check is stated positively so a failure names the exact reason rather
    than a boolean. The rail is deliberately paranoid in both directions: it
    rejects production names AND requires the affirmative test-only markers, so a
    target that is merely unfamiliar is refused rather than assumed safe.
    """
    checks: list[tuple[str, bool, str]] = []

    host = (identity.host or "").strip().lower()
    checks.append(("host_is_loopback", host in LOOPBACK_HOSTS, f"host={identity.host!r} must be loopback"))
    checks.append(
        (
            "port_is_not_production",
            int(identity.port) != PRODUCTION_PORT,
            f"port={identity.port} must not be {PRODUCTION_PORT}",
        )
    )
    checks.append(
        (
            "dbname_is_test_only",
            identity.dbname.startswith(TEST_DB_PREFIX) and identity.dbname not in PRODUCTION_DB_NAMES,
            f"dbname={identity.dbname!r} must start with {TEST_DB_PREFIX!r} and not be a production name",
        )
    )
    checks.append(
        (
            "user_is_test_only",
            identity.user.startswith(TEST_USER_PREFIX) and identity.user not in PRODUCTION_USERS,
            f"user={identity.user!r} must start with {TEST_USER_PREFIX!r} and not be a production user",
        )
    )
    datadir = identity.data_directory
    checks.append(
        (
            "data_directory_is_not_production",
            datadir is None or not any(str(datadir).startswith(m) for m in PRODUCTION_DATA_DIR_MARKERS),
            f"data_directory={datadir!r} must not live under a production PostgreSQL root",
        )
    )

    failed = [(name, why) for name, ok, why in checks if not ok]
    if failed:
        raise ProductionIdentityError(
            "refusing to write: target resembles production — " + "; ".join(f"{n}: {w}" for n, w in failed)
        )
    return {"identity": identity.as_dict(), "checks": {n: ok for n, ok, _ in checks}, "verdict": "ISOLATED"}


def pg_bin_dir() -> Path:
    """Locate initdb/pg_ctl, preferring the production major version."""
    for major in PREFERRED_PG_MAJORS:
        cand = Path(f"/usr/lib/postgresql/{major}/bin")
        if (cand / "initdb").is_file() and (cand / "pg_ctl").is_file():
            return cand
    for name in ("initdb",):
        found = shutil.which(name)
        if found:
            return Path(found).parent
    raise RuntimeError("no PostgreSQL server binaries (initdb/pg_ctl) found on this host")


def _free_port() -> int:
    """Ask the kernel for an unused loopback port and hand it straight to postgres."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    if port == PRODUCTION_PORT:  # pragma: no cover - kernel will not hand this out
        raise RuntimeError("refusing to use the production port")
    return port


@dataclass
class IsolatedPostgres:
    """An ephemeral loopback-only PostgreSQL cluster.

    Use as a context manager. On exit the postmaster is stopped and the entire
    data directory is removed; :attr:`cleanup_proof` records what was destroyed.
    """

    dbname: str = field(default_factory=lambda: f"{TEST_DB_PREFIX}{secrets.token_hex(4)}")
    user: str = field(default_factory=lambda: f"{TEST_USER_PREFIX}{secrets.token_hex(4)}")
    password: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    port: int = field(default_factory=_free_port)
    host: str = "127.0.0.1"

    base_dir: Path | None = None
    data_dir: Path | None = None
    started: bool = False
    cleanup_proof: dict[str, Any] = field(default_factory=dict)

    # ── lifecycle ───────────────────────────────────────────────────────────
    def _run(self, *argv: str, **kw: Any) -> subprocess.CompletedProcess:
        return subprocess.run(argv, capture_output=True, text=True, timeout=180, check=False, **kw)

    def start(self) -> "IsolatedPostgres":
        bindir = pg_bin_dir()
        self.base_dir = Path(tempfile.mkdtemp(prefix="tradeai_testpg_"))
        self.data_dir = self.base_dir / "data"
        pwfile = self.base_dir / "pw"
        pwfile.write_text(self.password)
        pwfile.chmod(0o600)

        init = self._run(
            str(bindir / "initdb"),
            "-D",
            str(self.data_dir),
            "-U",
            self.user,
            "--auth-local=trust",
            "--auth-host=scram-sha-256",
            f"--pwfile={pwfile}",
            "--encoding=UTF8",
            "--no-sync",
        )
        if init.returncode != 0:
            raise RuntimeError(f"initdb failed: {init.stderr[-800:]}")
        pwfile.unlink()

        # Loopback only, dynamic port, and durability off — this cluster is
        # thrown away, so fsync would only cost time.
        (self.data_dir / "postgresql.conf").open("a").write(
            "\n# tradeai isolated test cluster\n"
            "listen_addresses = '127.0.0.1'\n"
            f"port = {self.port}\n"
            f"unix_socket_directories = '{self.base_dir}'\n"
            "fsync = off\n"
            "synchronous_commit = off\n"
            "full_page_writes = off\n"
            "max_connections = 20\n"
        )

        start = self._run(
            str(bindir / "pg_ctl"),
            "-D",
            str(self.data_dir),
            "-l",
            str(self.base_dir / "postmaster.log"),
            "-w",
            "-t",
            "60",
            "start",
        )
        if start.returncode != 0:
            log = self.base_dir / "postmaster.log"
            raise RuntimeError(
                f"pg_ctl start failed: {start.stderr[-400:]}\n{log.read_text()[-800:] if log.is_file() else ''}"
            )
        self.started = True

        deadline = time.time() + 60
        while time.time() < deadline:
            r = self._run(str(bindir / "pg_isready"), "-h", self.host, "-p", str(self.port), "-q")
            if r.returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("isolated cluster never became ready")

        create = self._run(
            str(bindir / "createdb"),
            "-h",
            self.host,
            "-p",
            str(self.port),
            "-U",
            self.user,
            self.dbname,
            env={**os.environ, "PGPASSWORD": self.password},
        )
        if create.returncode != 0:
            raise RuntimeError(f"createdb failed: {create.stderr[-400:]}")
        return self

    def stop(self) -> dict[str, Any]:
        """Stop the postmaster and remove the data directory. Idempotent."""
        proof: dict[str, Any] = {
            "data_directory": str(self.data_dir) if self.data_dir else None,
            "base_directory": str(self.base_dir) if self.base_dir else None,
            "was_started": self.started,
        }
        if self.started and self.data_dir:
            bindir = pg_bin_dir()
            self._run(str(bindir / "pg_ctl"), "-D", str(self.data_dir), "-m", "immediate", "-w", "-t", "30", "stop")
            self.started = False
        if self.base_dir and self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)
        proof["data_directory_removed"] = not (self.data_dir and self.data_dir.exists())
        proof["base_directory_removed"] = not (self.base_dir and self.base_dir.exists())
        proof["port_released"] = not self._port_open()
        self.cleanup_proof = proof
        return proof

    def _port_open(self) -> bool:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(0.5)
            return s.connect_ex((self.host, self.port)) == 0

    # ── identity ────────────────────────────────────────────────────────────
    @property
    def identity(self) -> ClusterIdentity:
        return ClusterIdentity(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            data_directory=str(self.data_dir) if self.data_dir else None,
        )

    def env(self) -> dict[str, str]:
        """The DB_* environment that points db_adapter at THIS cluster.

        db_adapter._load_dotenv_if_needed() returns early when DB_PASSWORD is
        already set, and its .env fallback only fills keys absent from the
        environment — so setting these before import is sufficient to guarantee
        production credentials are never loaded.
        """
        return {
            "DB_HOST": self.host,
            "DB_PORT": str(self.port),
            "DB_NAME": self.dbname,
            "DB_USER": self.user,
            "DB_PASSWORD": self.password,
        }

    def verify_isolated(self) -> dict[str, Any]:
        """Run the rail against this cluster's own reported identity."""
        return assert_not_production(self.identity)

    # ── convenience ─────────────────────────────────────────────────────────
    def psql(self, sql: str) -> subprocess.CompletedProcess:
        bindir = pg_bin_dir()
        return self._run(
            str(bindir / "psql"),
            "-h",
            self.host,
            "-p",
            str(self.port),
            "-U",
            self.user,
            "-d",
            self.dbname,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
            env={**os.environ, "PGPASSWORD": self.password},
        )

    def __enter__(self) -> "IsolatedPostgres":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


@contextlib.contextmanager
def isolated_cluster() -> Iterator[IsolatedPostgres]:
    """Start a verified-isolated cluster; always tear it down."""
    pg = IsolatedPostgres()
    try:
        pg.start()
        pg.verify_isolated()
        yield pg
    finally:
        pg.stop()
