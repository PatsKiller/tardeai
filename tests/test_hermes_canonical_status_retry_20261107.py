"""LQ-20261107-207: the canonical-status probe tolerates a slow first call after a server restart."""
import io
import json
import socket
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_hermes_canonical_status as m  # noqa: E402

CFG = {"first_call_timeout_s": 60.0, "timeout_s": 20.0, "retries": 2, "backoff_s": [3.0, 8.0]}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(script, seen):
    it = iter(script)

    def op(url, timeout):
        seen.append(timeout)
        x = next(it)
        if isinstance(x, Exception):
            raise x
        return _Resp(json.dumps({"data": x}).encode())
    return op


def setup_function(_):
    m._first_call_done = False


def test_first_call_gets_long_timeout_then_normal():
    seen = []
    op = _opener([{"a": 1}, {"b": 2}], seen)
    assert m.api("health", cfg=CFG, opener=op, sleep=lambda s: None) == {"a": 1}
    assert m.api("health", cfg=CFG, opener=op, sleep=lambda s: None) == {"b": 2}
    assert seen == [60.0, 20.0]


def test_timeout_is_retried_with_backoff_and_succeeds():
    seen, slept = [], []
    op = _opener([socket.timeout("timed out"), socket.timeout("timed out"), {"ok": True}], seen)
    assert m.api("health", cfg=CFG, opener=op, sleep=slept.append) == {"ok": True}
    assert slept == [3.0, 8.0]
    assert seen == [60.0, 60.0, 60.0]


def test_connection_refused_urlerror_retried():
    seen = []
    err = urllib.error.URLError(ConnectionRefusedError("refused"))
    op = _opener([err, {"ok": 1}], seen)
    assert m.api("health", cfg=CFG, opener=op, sleep=lambda s: None) == {"ok": 1}


def test_http_error_not_retried():
    seen = []
    err = urllib.error.HTTPError("u", 500, "boom", {}, None)
    op = _opener([err, {"never": 1}], seen)
    out = m.api("health", cfg=CFG, opener=op, sleep=lambda s: None)
    assert "_error" in out and len(seen) == 1


def test_gives_up_after_retries_and_reports_error():
    seen = []
    op = _opener([socket.timeout("t")] * 3, seen)
    out = m.api("health", cfg=CFG, opener=op, sleep=lambda s: None)
    assert "_error" in out and len(seen) == 3


def test_config_file_is_read_and_broken_file_falls_back(tmp_path):
    good = tmp_path / "c.json"
    good.write_text(json.dumps({"first_call_timeout_s": 90, "retries": 1}))
    c = m.probe_config(good)
    assert c["first_call_timeout_s"] == 90.0 and c["retries"] == 1 and c["timeout_s"] == 20.0
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    assert m.probe_config(bad) == m._PROBE_DEFAULTS
    assert m.probe_config(tmp_path / "missing.json") == m._PROBE_DEFAULTS


def test_repo_config_exceeds_observed_23_5s_first_call():
    c = m.probe_config()
    assert c["first_call_timeout_s"] > 23.5
