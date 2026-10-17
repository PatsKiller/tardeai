#!/usr/bin/env python3
"""Allowlisted egress for the sandboxed self-heal fix agent (stdlib only; also runs standalone inside the sandbox).

Architect review 2026-10-16 (finding 2): the headless Claude Code process must run inside an enforced boundary whose
network reaches only what the CLI needs. The agent sandbox (bwrap ``--unshare-net``) has NO route out except this:

    sandbox: claude --HTTPS_PROXY=http://127.0.0.1:<port>--> bridge (in the sandbox, TCP 127.0.0.1:<port>)
             --unix socket (bind-mounted read-only)--> host: EgressProxy (CONNECT only, host:port allowlist) --> API

* ``EgressProxy`` (host side, a thread of the fixer): accepts only ``CONNECT host:port`` for an allowlisted
  ``host:port``; anything else (plain HTTP, other hosts, other ports, IP literals not listed) gets 403 and is logged.
  TLS is end-to-end between the CLI and the API; the proxy never sees plaintext and never injects credentials.
* ``bridge`` (sandbox side): ``python -I self_heal_egress.py bridge --unix S --port P -- <argv>`` listens on the
  sandbox's own loopback, forwards each connection to the unix socket, runs ``<argv>`` and exits with its code.

Inside the sandbox, localhost is the sandbox's own loopback: the host's Postgres, n8n, the command-center API and
every other host port are unreachable.
"""
from __future__ import annotations

import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
from typing import Iterable, Optional

_MAX_HEAD = 8192


def _splice(a: socket.socket, b: socket.socket) -> None:
    def pump(src: socket.socket, dst: socket.socket) -> None:
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s, how in ((dst, socket.SHUT_WR), (src, socket.SHUT_RD)):
                try:
                    s.shutdown(how)
                except OSError:
                    pass

    t = threading.Thread(target=pump, args=(b, a), daemon=True)
    t.start()
    pump(a, b)
    t.join(timeout=600)


def parse_connect(head: bytes) -> Optional[tuple[str, int]]:
    """(host, port) of a ``CONNECT host:port HTTP/1.x`` request line, else None."""
    try:
        line = head.split(b"\r\n", 1)[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    bits = line.split()
    if len(bits) != 3 or bits[0] != "CONNECT" or not bits[2].startswith("HTTP/1."):
        return None
    host, sep, port = bits[1].rpartition(":")
    if not sep or not port.isdigit() or not host:
        return None
    return host.strip("[]").lower(), int(port)


class EgressProxy:
    """CONNECT-only allowlist proxy on a unix socket (host side)."""

    def __init__(self, sock_path: str, allow: Iterable[str], *, connect_timeout: float = 15.0):
        self.sock_path = str(sock_path)
        self.allow = {str(a).lower() for a in allow}
        self.timeout = connect_timeout
        self.log: list[dict] = []
        self._lock = threading.Lock()
        proxy = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                proxy._handle(self.request)

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        self._srv = Server(self.sock_path, Handler)
        os.chmod(self.sock_path, 0o600)
        self._t = threading.Thread(target=self._srv.serve_forever, name="shf-egress", daemon=True)

    def _note(self, **row) -> None:
        with self._lock:
            self.log.append({"at": time.time(), **row})

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(30)
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < _MAX_HEAD:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
        except OSError:
            return
        target = parse_connect(head)
        if target is None or f"{target[0]}:{target[1]}" not in self.allow:
            self._note(decision="deny", target=f"{target[0]}:{target[1]}" if target else head[:80].decode(
                "latin-1", "replace").split("\r\n", 1)[0])
            try:
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            return
        try:
            up = socket.create_connection(target, timeout=self.timeout)
        except OSError as exc:
            self._note(decision="upstream_error", target=f"{target[0]}:{target[1]}", error=type(exc).__name__)
            try:
                conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            return
        self._note(decision="allow", target=f"{target[0]}:{target[1]}")
        conn.settimeout(None)
        up.settimeout(None)
        try:
            conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            rest = head.split(b"\r\n\r\n", 1)[1]
            if rest:
                up.sendall(rest)
            _splice(conn, up)
        finally:
            up.close()

    def summary(self) -> dict:
        with self._lock:
            rows = list(self.log)
        out: dict = {"allowed": {}, "denied": {}}
        for r in rows:
            key = "allowed" if r["decision"] == "allow" else "denied"
            out[key][r.get("target")] = out[key].get(r.get("target"), 0) + 1
        return out

    def __enter__(self) -> "EgressProxy":
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._srv.shutdown()
        self._srv.server_close()
        try:
            os.unlink(self.sock_path)
        except OSError:
            pass


def bridge(unix_path: str, port: int, argv: list[str]) -> int:
    """Sandbox side: TCP 127.0.0.1:port -> unix socket, then run argv and return its exit code."""

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                up.connect(unix_path)
            except OSError:
                return
            try:
                _splice(self.request, up)
            finally:
                up.close()

    class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    srv = Server(("127.0.0.1", int(port)), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        return subprocess.call(argv)
    finally:
        srv.shutdown()


def main(argv: Optional[list[str]] = None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) >= 6 and a[0] == "bridge" and a[1] == "--unix" and a[3] == "--port" and a[5] == "--":
        return bridge(a[2], int(a[4]), a[6:])
    print("usage: self_heal_egress.py bridge --unix PATH --port N -- CMD...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
