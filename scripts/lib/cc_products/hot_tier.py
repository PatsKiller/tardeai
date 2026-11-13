"""Optional hot tier in front of the product store: a stdlib RESP2 client for loopback Valkey (LQ-20261107-2595).

Valkey here is a pure cache (256 MB, allkeys-lru, no persistence), so a miss is normal and an outage is survivable:
every failure surfaces as ``HotTierDown`` and the read path falls back to Postgres. Each call opens one short
connection, and every socket operation runs against a single per-call deadline of ``timeout_s``.
"""

from __future__ import annotations

import json
import socket
import struct
import time
from datetime import datetime


class HotTierDown(Exception):
    """The hot tier could not answer: connect, I/O, timeout or protocol error."""


def product_key(product_id: str, scope_key: str = "global") -> str:
    return f"cc:product:{product_id}:{scope_key}"


def _encode_command(*parts: bytes) -> bytes:
    out = [b"*%d\r\n" % len(parts)]
    for p in parts:
        out.append(b"$%d\r\n" % len(p))
        out.append(p)
        out.append(b"\r\n")
    return b"".join(out)


class _Conn:
    def __init__(self, host: str, port: int, timeout_s: float):
        self.deadline = time.monotonic() + timeout_s
        self.buf = b""
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout_s)
        except OSError as exc:
            raise HotTierDown(f"connect {host}:{port}: {exc}") from exc

    def _remaining(self) -> float:
        rem = self.deadline - time.monotonic()
        if rem <= 0:
            raise HotTierDown("timeout")
        return rem

    def send(self, data: bytes) -> None:
        try:
            self.sock.settimeout(self._remaining())
            self.sock.sendall(data)
        except HotTierDown:
            raise
        except OSError as exc:
            raise HotTierDown(f"send: {exc}") from exc

    def _fill(self) -> None:
        try:
            self.sock.settimeout(self._remaining())
            chunk = self.sock.recv(65536)
        except HotTierDown:
            raise
        except OSError as exc:  # socket.timeout is an OSError
            raise HotTierDown(f"recv: {exc}") from exc
        if not chunk:
            raise HotTierDown("connection closed by server")
        self.buf += chunk

    def read_line(self) -> bytes:
        while True:
            i = self.buf.find(b"\r\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 2 :]
                return line
            if len(self.buf) > 1024:
                raise HotTierDown("protocol: reply line too long")
            self._fill()

    def read_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            self._fill()
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def read_reply(self):
        """One RESP2 reply. Simple string → str, bulk → bytes|None, integer → int. Errors raise HotTierDown."""
        line = self.read_line()
        if not line:
            raise HotTierDown("protocol: empty reply line")
        kind, rest = line[:1], line[1:]
        if kind == b"+":
            return rest.decode("utf-8", "replace")
        if kind == b"-":
            raise HotTierDown(f"server error: {rest.decode('utf-8', 'replace')}")
        if kind == b":":
            try:
                return int(rest)
            except ValueError as exc:
                raise HotTierDown(f"protocol: bad integer {rest!r}") from exc
        if kind == b"$":
            try:
                n = int(rest)
            except ValueError as exc:
                raise HotTierDown(f"protocol: bad bulk length {rest!r}") from exc
            if n == -1:
                return None
            if n < 0:
                raise HotTierDown(f"protocol: bad bulk length {n}")
            data = self.read_exact(n + 2)
            if data[-2:] != b"\r\n":
                raise HotTierDown("protocol: bulk not terminated by CRLF")
            return data[:-2]
        raise HotTierDown(f"protocol: unexpected reply type {kind!r}")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class HotTier:
    def __init__(self, host="127.0.0.1", port=6379, timeout_s=0.05):
        self.host = host
        self.port = int(port)
        self.timeout_s = float(timeout_s)

    def _call(self, *parts: bytes):
        conn = _Conn(self.host, self.port, self.timeout_s)
        try:
            conn.send(_encode_command(*parts))
            return conn.read_reply()
        finally:
            conn.close()

    def get(self, key: str) -> bytes | None:
        reply = self._call(b"GET", key.encode("utf-8"))
        if reply is not None and not isinstance(reply, bytes):
            raise HotTierDown(f"protocol: GET returned {type(reply).__name__}")
        return reply

    def set(self, key: str, value: bytes, ex_s: int) -> None:
        ex_s = int(ex_s)
        if ex_s < 1:
            return
        reply = self._call(b"SET", key.encode("utf-8"), bytes(value), b"EX", str(ex_s).encode("ascii"))
        if reply != "OK":
            raise HotTierDown(f"protocol: SET returned {reply!r}")

    def ping(self) -> bool:
        try:
            return self._call(b"PING") == "PONG"
        except Exception:  # noqa: BLE001 - ping never raises, by contract
            return False


# ── row packing: 4-byte big-endian header length, JSON header, raw body ──────────────────────────────────────────

_HEADER_LEN = struct.Struct(">I")


def pack(row: dict) -> bytes:
    fields: dict = {}
    dt_fields: list[str] = []
    body = row.get("body")
    for k, v in row.items():
        if k == "body":
            continue
        if isinstance(v, datetime):
            fields[k] = v.isoformat()
            dt_fields.append(k)
        else:
            fields[k] = v
    header = json.dumps(
        {"v": 1, "fields": fields, "dt": dt_fields, "has_body": "body" in row, "body_none": body is None},
        separators=(",", ":"),
    ).encode("utf-8")
    return _HEADER_LEN.pack(len(header)) + header + (bytes(body) if body is not None else b"")


def unpack(b: bytes) -> dict:
    b = bytes(b)
    if len(b) < _HEADER_LEN.size:
        raise ValueError("packed product too short")
    (hlen,) = _HEADER_LEN.unpack_from(b, 0)
    start = _HEADER_LEN.size
    if start + hlen > len(b):
        raise ValueError("packed product header overruns the buffer")
    header = json.loads(b[start : start + hlen].decode("utf-8"))
    if header.get("v") != 1:
        raise ValueError(f"unknown packed product version {header.get('v')!r}")
    row = dict(header["fields"])
    for k in header.get("dt", []):
        if row.get(k) is not None:
            row[k] = datetime.fromisoformat(row[k])
    if header.get("has_body", True):
        row["body"] = None if header.get("body_none") else b[start + hlen :]
    return row
