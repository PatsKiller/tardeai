#!/usr/bin/env python3
"""Every Finviz caller must go through the global throttle. Pure; no network."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_no_uncovered_finviz_callers():
    """Regression guard for the 2026-06-22 429 storm class."""
    r = subprocess.run([sys.executable,
                        str(ROOT / "scripts" / "audit_finviz_throttle_coverage.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"uncovered Finviz caller(s):\n{r.stdout}"


def test_finviz_get_acquires_before_request(monkeypatch):
    import finviz_http
    order = []

    class Resp:
        status_code = 200
        headers = {}

    monkeypatch.setitem(sys.modules, "finviz_throttle",
                        type("T", (), {"acquire": staticmethod(lambda timeout=300: order.append("acquire")),
                                       "cooldown": staticmethod(lambda s=None: order.append("cooldown"))}))
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: (order.append("request"), Resp())[1])
    finviz_http.finviz_get("https://elite.finviz.com/export?v=152")
    assert order == ["acquire", "request"], f"throttle not acquired first: {order}"


def test_429_publishes_global_cooldown(monkeypatch):
    """A 429 must back off EVERY process, not just this one."""
    import finviz_http
    calls = []

    class Resp:
        status_code = 429
        headers = {"Retry-After": "45"}

    monkeypatch.setitem(sys.modules, "finviz_throttle",
                        type("T", (), {"acquire": staticmethod(lambda timeout=300: None),
                                       "cooldown": staticmethod(lambda s=None: calls.append(s))}))
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())

    try:
        finviz_http.finviz_get("https://elite.finviz.com/export")
        raised = False
    except finviz_http.FinvizRateLimited:
        raised = True
    assert raised, "429 must raise by default"
    assert calls == ["45"], f"Retry-After not published globally: {calls}"


def test_raise_on_429_false_returns_response(monkeypatch):
    """Soft-skip callers still publish the cooldown."""
    import finviz_http
    calls = []

    class Resp:
        status_code = 429
        headers = {}

    monkeypatch.setitem(sys.modules, "finviz_throttle",
                        type("T", (), {"acquire": staticmethod(lambda timeout=300: None),
                                       "cooldown": staticmethod(lambda s=None: calls.append(s))}))
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())
    resp = finviz_http.finviz_get("https://elite.finviz.com/export", raise_on_429=False)
    assert resp.status_code == 429
    assert len(calls) == 1, "cooldown must still be published"


def test_probe_uses_short_throttle_wait(monkeypatch):
    """Health probes must not block a monitoring run for minutes."""
    import finviz_http
    seen = {}

    class Resp:
        status_code = 200
        headers = {}

    monkeypatch.setitem(sys.modules, "finviz_throttle",
                        type("T", (), {"acquire": staticmethod(lambda timeout=300: seen.setdefault("t", timeout)),
                                       "cooldown": staticmethod(lambda s=None: None)}))
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())
    finviz_http.finviz_probe("https://elite.finviz.com/export")
    assert seen["t"] == finviz_http.PROBE_THROTTLE_TIMEOUT
    assert seen["t"] < 300
