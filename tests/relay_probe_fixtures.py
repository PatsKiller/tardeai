"""Owned loopback descriptors for relay probes; production servers/guards stay unchanged.

The same stdlib validation is used by the optional pre-import safety harness.
Only sockets allocated by this fixture are transferable, and every child keeps
the kernel descriptor for each permitted peer rather than trusting a port list.
"""

from __future__ import annotations

import fcntl
import json
import os
import runpy
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

CAP_ENV = "TRADEAI_FIXTURE_SOCKET_MANIFEST_FD"
BASE_ENV = "TRADEAI_FIXTURE_SOCKET_SCOPE_BASE"
SCHEMA = "FixtureSocketTransfer@v1"
OWNED = {}


class FixtureCapabilityRefused(ValueError):
    pass


def scope_root(path):
    root = Path(path).resolve()
    allowed = Path(os.environ.get("REASSESS_SCRATCH") or os.environ.get(BASE_ENV) or tempfile.gettempdir()).resolve()
    if not root.is_relative_to(allowed) or root == allowed:
        raise FixtureCapabilityRefused("socket scope is outside a specific scratch fixture")
    return root


def socket_record(fd):
    if type(fd) is not int or fd <= 2:
        raise FixtureCapabilityRefused("socket descriptor must be an explicit non-stdio FD")
    st = os.fstat(fd)
    if not stat.S_ISSOCK(st.st_mode):
        raise FixtureCapabilityRefused("descriptor is not a socket")
    with socket.socket(fileno=os.dup(fd)) as sock:
        address = sock.getsockname()
        if (
            sock.family != socket.AF_INET
            or sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
            or not isinstance(address, tuple)
            or address[0] != "127.0.0.1"
            or address[1] < 1024
        ):
            raise FixtureCapabilityRefused("descriptor is not an assigned unprivileged IPv4 loopback endpoint")
        try:
            sock.getpeername()
        except OSError:
            pass
        else:
            raise FixtureCapabilityRefused("a connected socket is not a fixture listener/peer endpoint")
        listening = bool(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN))
    return {
        "fd": fd,
        "device": st.st_dev,
        "inode": st.st_ino,
        "host": address[0],
        "port": address[1],
        "listening": listening,
    }


def identity(record):
    return record["device"], record["inode"]


def validate_manifest(fd, *, allowed_scope, expected_parent, passed_fds, owned=None):
    """Pure refusal before adoption/connect; inspect only explicitly supplied FDs."""
    if type(fd) is not int or fd <= 2 or fd not in passed_fds:
        raise FixtureCapabilityRefused("manifest descriptor was not explicitly passed")
    st = os.fstat(fd)
    path = Path(os.readlink(f"/proc/self/fd/{fd}"))
    if (
        not stat.S_ISREG(st.st_mode)
        or st.st_uid != os.getuid()
        or stat.S_IMODE(st.st_mode) != 0o600
        or not path.resolve().is_relative_to(Path(allowed_scope).resolve())
        or not path.name.startswith(".fixture-socket-")
        or path.suffix != ".json"
        or fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
    ):
        raise FixtureCapabilityRefused("manifest FD is not a private readonly scratch fixture")
    raw = os.pread(fd, 65537, 0)
    if len(raw) > 65536:
        raise FixtureCapabilityRefused("oversized capability manifest")
    try:
        doc = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureCapabilityRefused("malformed capability manifest") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("scope"), str) or not doc["scope"]:
        raise FixtureCapabilityRefused("manifest requires an object with an explicit scratch scope")
    scope = Path(doc["scope"]).resolve()
    if (
        doc.get("schema") != SCHEMA
        or type(doc.get("owner_pid")) is not int
        or doc["owner_pid"] != expected_parent
        or not scope.is_relative_to(Path(allowed_scope).resolve())
        or not path.resolve().is_relative_to(scope)
    ):
        raise FixtureCapabilityRefused("manifest provenance is outside the owning fixture/process")
    records = doc.get("endpoints")
    if not isinstance(records, list) or not records or len(records) > 8:
        raise FixtureCapabilityRefused("bounded explicit endpoint descriptors required")
    seen, validated = set(), []
    for row in records:
        if not isinstance(row, dict) or type(row.get("fd")) is not int or row["fd"] not in passed_fds:
            raise FixtureCapabilityRefused("endpoint descriptor was not explicitly passed")
        if (
            any(type(row.get(k)) is not int for k in ("device", "inode", "port"))
            or type(row.get("listening")) is not bool
        ):
            raise FixtureCapabilityRefused("endpoint descriptor metadata has an invalid type")
        actual = socket_record(row["fd"])
        sid = identity(actual)
        if sid in seen or any(row.get(k) != v for k, v in actual.items()):
            raise FixtureCapabilityRefused("descriptor identity/endpoint differs from the manifest")
        seen.add(sid)
        role = row.get("role")
        if role not in {"listener", "peer", "refusal_peer"} or actual["listening"] != (role != "refusal_peer"):
            raise FixtureCapabilityRefused("descriptor role/listen state does not match")
        if row.get("scope") != str(scope):
            raise FixtureCapabilityRefused("descriptor belongs to a different fixture scope")
        if owned is not None and (sid not in owned or owned[sid].get("scope") != str(scope)):
            raise FixtureCapabilityRefused("descriptor was not allocated by the owning fixture")
        validated.append(dict(row))
    if sum(row["role"] == "listener" for row in validated) != 1:
        raise FixtureCapabilityRefused("exactly one owned listener must be adopted")
    return {"scope": str(scope), "endpoints": validated}


class Endpoint:
    def __init__(self, scope, *, listening=True):
        self.scope = scope_root(scope)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.bind(("127.0.0.1", 0))
            if listening:
                self.socket.listen(64)
            self.record = dict(socket_record(self.socket.fileno()), scope=str(self.scope))
            OWNED[identity(self.record)] = self.record
            claim = getattr(sys, "_reassess_fixture_socket_claim", None)
            if claim:
                claim(self.record)
        except BaseException:
            self.socket.close()
            raise

    @property
    def port(self):
        return self.record["port"]

    def close(self):
        OWNED.pop(identity(self.record), None)
        self.socket.close()


def write_manifest(scope, listener, peers=()):
    scope = scope_root(scope)
    records = [dict(listener.record, role="listener")]
    records += [dict(peer.record, role="peer" if peer.record["listening"] else "refusal_peer") for peer in peers]
    path = scope / (".fixture-socket-" + uuid.uuid4().hex + ".json")
    data = json.dumps({"schema": SCHEMA, "scope": str(scope), "owner_pid": os.getpid(), "endpoints": records}).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    fd = os.open(path, os.O_RDONLY)
    passed = tuple([fd] + [r["fd"] for r in records])
    try:
        validate_manifest(fd, allowed_scope=scope, expected_parent=os.getpid(), passed_fds=passed, owned=OWNED)
    except BaseException:
        os.close(fd)
        raise
    return fd, passed


def bootstrap(script, args):
    """Keep CLI, production bind floors, server subclasses and handlers; adopt the parent's socket."""
    import http.server

    fd = int(os.environ[CAP_ENV])
    approved = getattr(sys, "_reassess_fixture_socket_manifest", None)
    if approved is None:
        # Inspect the private FD before reading its document. The launcher's
        # namespace and actual inherited descriptors supply the admission scope.
        passed = {int(name) for name in os.listdir("/proc/self/fd") if name.isdigit() and int(name) > 2}
        approved = validate_manifest(
            fd,
            allowed_scope=Path(os.environ[BASE_ENV]).resolve(),
            expected_parent=os.getppid(),
            passed_fds=passed,
        )
    listener = next(r for r in approved["endpoints"] if r["role"] == "listener")
    os.environ.pop(CAP_ENV, None)
    os.environ.pop(BASE_ENV, None)
    os.close(fd)
    base = http.server.ThreadingHTTPServer

    class AdoptedServer(base):
        def __init__(self, address, handler, *pos, **kw):
            if address != (listener["host"], listener["port"]):
                raise FixtureCapabilityRefused("server requested a different endpoint")
            actual = socket_record(listener["fd"])
            if any(actual[k] != listener[k] for k in actual):
                raise FixtureCapabilityRefused("listener changed before adoption")
            super().__init__(address, handler, *pos, bind_and_activate=False, **kw)
            self.socket.close()
            self.socket = socket.socket(fileno=os.dup(listener["fd"]))
            self.server_address = self.socket.getsockname()
            self.server_name, self.server_port = "localhost", self.server_address[1]

    http.server.ThreadingHTTPServer = AdoptedServer
    sys.path.insert(0, str(script.parent))
    sys.path.insert(0, str(script.parent.parent))
    sys.argv = [str(script), *args]
    runpy.run_path(str(script), run_name="__main__")


class ProbeSession:
    def __init__(self, contract, scope):
        self.contract, self.scope = contract, scope_root(scope)
        self.endpoints, self.owners = {}, []

    def endpoint(self, *, listening=True):
        ep = Endpoint(self.scope, listening=listening)
        self.endpoints[ep.port] = ep
        return ep

    def start(self, owner, script, args, env, peers, log_name):
        owner._fixture_listener = self.endpoint()
        owner.port = owner._fixture_listener.port
        args = [str(owner.port) if arg == "FIXTURE_ASSIGNED_PORT" else arg for arg in args]
        fd, passed = write_manifest(self.scope, owner._fixture_listener, peers)
        env[CAP_ENV] = str(fd)
        env[BASE_ENV] = os.environ.get("REASSESS_SCRATCH") or tempfile.gettempdir()
        log_path = owner.scratch / log_name
        try:
            with log_path.open("w") as log:
                owner.proc = subprocess.Popen(
                    [owner.python, str(Path(__file__).resolve()), "--bootstrap", str(script), *args],
                    cwd=str(owner.scratch),
                    env=env,
                    pass_fds=passed,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
        finally:
            os.close(fd)
        self.owners.append(owner)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if owner.proc.poll() is not None:
                raise RuntimeError(f"fixture {log_name} exited {owner.proc.returncode}: {log_path.read_text()[:300]}")
            # A parent listener is already bound: wait for the child readiness message, not a misleading TCP handshake.
            text = log_path.read_text()
            if '"bound"' in text or '"authority"' in text or "FIXTURE_STUB_READY" in text:
                return owner
            time.sleep(0.05)
        raise RuntimeError("fixture server did not become ready")

    def factories(self):
        session, C = self, self.contract
        from tests.pipeline_runner_fixtures import runner_env

        class FixtureRelay(C.ScratchRelay):
            def __enter__(self):
                self.scratch.mkdir(parents=True, exist_ok=True)
                if self.copy_ledger:
                    C._copy_ledger(self.ledger_source, self.ledger)
                if self.gateway_url:
                    from urllib.parse import urlparse

                    url = urlparse(self.gateway_url)
                    if url.hostname != "127.0.0.1" or url.port not in session.endpoints:
                        raise FixtureCapabilityRefused("relay peer is not an owned fixture descriptor")
                    peer = session.endpoints[url.port]
                else:
                    peer = session.endpoint(listening=False)
                    self.gateway_url = f"http://127.0.0.1:{peer.port}"
                env = runner_env(self.scratch)
                env.update(
                    TRADEAI_N8N_RELAY_BEARER=self.bearer,
                    TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N=self.n8n_key,
                    TRADEAI_STATE_ROOT=str(self.scratch / "state"),
                    TRADEAI_N8N_COORDINATION_LEDGER=str(self.ledger),
                    TRADEAI_N8N_GATEWAY_URL=self.gateway_url,
                    TRADEAI_N8N_RELAY_LIVE_LANES="",
                )
                return session.start(
                    self,
                    self.relay_root / "scripts/n8n_run_relay.py",
                    ["--host", "127.0.0.1", "--port", "FIXTURE_ASSIGNED_PORT"],
                    env,
                    [peer],
                    "relay.stdout",
                )

        class FixtureGateway(C.ScratchGateway):
            def __enter__(self):
                self.scratch.mkdir(parents=True, exist_ok=True)
                env = runner_env(self.scratch)
                env.update(
                    TRADEAI_N8N_GATEWAY_HMAC_KEY=self.key,
                    TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N=self.n8n_key,
                    TRADEAI_STATE_ROOT=str(self.scratch / "state"),
                    TRADEAI_N8N_COORDINATION_LEDGER=str(self.ledger),
                )
                cfg = self.relay_root / "config"
                return session.start(
                    self,
                    self.relay_root / "scripts/n8n_coordination_gateway.py",
                    [
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "FIXTURE_ASSIGNED_PORT",
                        "--expected-sha",
                        "0" * 40,
                        "--ledger",
                        str(self.ledger),
                        "--registry",
                        str(self.registry),
                        "--run-allowlist",
                        str(cfg / "n8n_run_allowlist.json"),
                        "--retry-policies",
                        str(cfg / "n8n_retry_policies.json"),
                    ],
                    env,
                    [],
                    "gateway.stdout",
                )

        return FixtureRelay, FixtureGateway

    def close(self):
        for owner in reversed(self.owners):
            owner.__exit__(None, None, None)
        for endpoint in self.endpoints.values():
            endpoint.close()


def install_probe_fixtures(monkeypatch, contract, scope):
    session = ProbeSession(contract, scope)
    relay, gateway = session.factories()
    monkeypatch.setattr(contract, "ScratchRelay", relay)
    monkeypatch.setattr(contract, "ScratchGateway", gateway)
    return session


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "--bootstrap":
        raise SystemExit("fixture bootstrap requires an explicit source script")
    bootstrap(Path(sys.argv[2]).resolve(), sys.argv[3:])
