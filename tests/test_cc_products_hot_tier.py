"""hot_tier against an in-process fake RESP server (LQ-20261107-2595). Never touches the real Valkey on :6379."""

from __future__ import annotations

import socket
import socketserver
import threading
import time
from datetime import datetime, timezone

import pytest

from scripts.lib.cc_products.hot_tier import HotTier, HotTierDown, pack, product_key, unpack


class _Handler(socketserver.BaseRequestHandler):
    def _read_command(self, f):
        line = f.readline()
        if not line:
            return None
        assert line.startswith(b"*"), line
        n = int(line[1:].strip())
        parts = []
        for _ in range(n):
            hdr = f.readline()
            assert hdr.startswith(b"$"), hdr
            ln = int(hdr[1:].strip())
            data = f.read(ln + 2)
            parts.append(data[:-2])
        return parts

    def handle(self):
        srv = self.server
        if srv.mode == "silent":
            srv.release.wait(5)
            return
        f = self.request.makefile("rb")
        while True:
            try:
                cmd = self._read_command(f)
            except (OSError, AssertionError, ValueError):
                return
            if cmd is None:
                return
            srv.commands.append(cmd)
            if srv.mode == "garbage":
                self.request.sendall(b"?what is this\r\n")
                continue
            name = cmd[0].upper()
            if name == b"PING":
                self.request.sendall(b"+PONG\r\n")
            elif name == b"GET":
                v = srv.store.get(cmd[1])
                if v is None:
                    self.request.sendall(b"$-1\r\n")
                else:
                    self.request.sendall(b"$%d\r\n" % len(v) + v + b"\r\n")
            elif name == b"SET":
                srv.store[cmd[1]] = cmd[2]
                self.request.sendall(b"+OK\r\n")
            else:
                self.request.sendall(b"-ERR unknown command\r\n")


class FakeResp(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, mode="normal"):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mode = mode
        self.store: dict[bytes, bytes] = {}
        self.commands: list[list[bytes]] = []
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def close(self):
        self.release.set()
        self.shutdown()
        self.server_close()


@pytest.fixture
def fake():
    srv = FakeResp()
    yield srv
    srv.close()


def closed_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_product_key_shape():
    assert product_key("cio.pages") == "cc:product:cio.pages:global"
    assert product_key("x", "acct:1") == "cc:product:x:acct:1"


def test_get_hit(fake):
    fake.store[b"k1"] = b"hello"
    assert HotTier(port=fake.port, timeout_s=1).get("k1") == b"hello"


def test_get_miss_is_none(fake):
    assert HotTier(port=fake.port, timeout_s=1).get("absent") is None
    assert fake.commands[-1] == [b"GET", b"absent"]


def test_set_sends_ex(fake):
    HotTier(port=fake.port, timeout_s=1).set("k2", b"v", 37)
    assert fake.commands[-1] == [b"SET", b"k2", b"v", b"EX", b"37"]
    assert fake.store[b"k2"] == b"v"


def test_set_with_ex_below_one_writes_nothing(fake):
    HotTier(port=fake.port, timeout_s=1).set("k3", b"v", 0)
    HotTier(port=fake.port, timeout_s=1).set("k3", b"v", -5)
    assert fake.commands == []


def test_binary_body_with_crlf_round_trips(fake):
    body = b"\r\n$-1\r\n*3\r\n" + bytes(range(256)) + b"\r\n"
    hot = HotTier(port=fake.port, timeout_s=1)
    hot.set("bin", body, 60)
    assert hot.get("bin") == body


def test_large_body_round_trips(fake):
    body = (b"x\r\n" * 400_000)[:1_100_000]
    hot = HotTier(port=fake.port, timeout_s=2)
    hot.set("big", body, 60)
    assert hot.get("big") == body


def test_ping_true(fake):
    assert HotTier(port=fake.port, timeout_s=1).ping() is True


def _assert_down_fast(fn, timeout_s):
    t0 = time.monotonic()
    with pytest.raises(HotTierDown):
        fn()
    elapsed = time.monotonic() - t0
    assert elapsed < timeout_s + 0.5, elapsed


def test_connection_refused_raises_down():
    hot = HotTier(port=closed_port(), timeout_s=0.2)
    _assert_down_fast(lambda: hot.get("k"), 0.2)
    _assert_down_fast(lambda: hot.set("k", b"v", 10), 0.2)
    assert hot.ping() is False


def test_silent_server_raises_down_within_timeout():
    srv = FakeResp(mode="silent")
    try:
        hot = HotTier(port=srv.port, timeout_s=0.2)
        t0 = time.monotonic()
        with pytest.raises(HotTierDown):
            hot.get("k")
        elapsed = time.monotonic() - t0
        assert 0.15 <= elapsed < 0.7, elapsed
        t0 = time.monotonic()
        assert hot.ping() is False
        assert time.monotonic() - t0 < 0.7
    finally:
        srv.close()


def test_garbage_reply_raises_down():
    srv = FakeResp(mode="garbage")
    try:
        hot = HotTier(port=srv.port, timeout_s=0.5)
        _assert_down_fast(lambda: hot.get("k"), 0.5)
        _assert_down_fast(lambda: hot.set("k", b"v", 10), 0.5)
        assert hot.ping() is False
    finally:
        srv.close()


def test_error_reply_raises_down(fake):
    hot = HotTier(port=fake.port, timeout_s=1)
    with pytest.raises(HotTierDown):
        hot._call(b"NOSUCH")


def test_pack_unpack_round_trip():
    row = {
        "product_id": "cio.pages",
        "scope_key": "global",
        "body": b'{"a":1}\r\n\x00\xff',
        "etag": "sha256:abc",
        "seq": 7,
        "as_of": datetime(2026, 11, 12, 14, 30, 5, 123456, tzinfo=timezone.utc),
        "built_at": datetime(2026, 11, 12, 14, 31, tzinfo=timezone.utc),
        "next_refresh_at": None,
        "stale_after_s": 360,
        "hard_expiry_s": 1800,
        "purge_after_s": 604800,
        "status": "OK",
        "source_watermarks": {"a": "2026-11-12T14:30:05+00:00", "n": [1, 2]},
        "builder_sha": "deadbeef",
        "bytes": 11,
        "build_ms": 42,
    }
    back = unpack(pack(row))
    assert back == row
    assert back["as_of"].utcoffset().total_seconds() == 0
    assert isinstance(back["body"], bytes)


def test_unpack_rejects_truncated():
    with pytest.raises(ValueError):
        unpack(b"\x00\x00")
    with pytest.raises(ValueError):
        unpack(b"\x00\x00\x00\xff{}")
