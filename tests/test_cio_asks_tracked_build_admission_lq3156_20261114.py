"""LQ-20261114-3156 — the tracked-asks SWR build is judged by the REQUESTER, not by the build thread.

Live defect this pins (2026-11-14 05:45Z, served 7b0cc18d0): ``GET /api/v2/cio/asks/tracked`` answered 200
``tracked: null`` forever with ``last_build_error: "RuntimeError: build returned HTTP 403"`` — 371 failed builds,
640 UNKNOWN reads. ``_asks_tracked_cached`` handed ``cio_ask_api.handle`` to the serve-last-good SWR cache with no
identity; ``handle`` builds its Ctx from ``cc_auth``'s THREAD-locals inside the build, and the SWR runs the build on a
background thread where the request identity is empty → ``_operator()`` refuses → 403 → a failed build. Two effects:
the panel never loads, and the route's intended 403-for-non-operator was swallowed into a 200 UNKNOWN.

The contract pinned here:
1. ``cio_ask_api.snapshot_ctx()`` reads the identity ONCE and keeps answering it from any thread.
2. An operator request builds (and the build still succeeds after the request thread's identity is gone — the
   regression test; the OLD no-ctx build refuses on that thread, which is the discriminant).
3. A non-operator (anonymous, service token, non-serve_proxy listener, unallowlisted tailnet login) is answered by
   the handler's real 403 and starts NO build — no compute, no SWR lease.

Hermetic: no DB, no Valkey, no network, no server. ``cio_ask_core._deps(None)`` returns None under pytest, so the
tracked read is an honest empty list, never a production store read.
"""
from __future__ import annotations

import types

import pytest

import scripts.api_v2 as api
import scripts.lib.cio_ask_api as caa

# ``_default_ctx`` imports ``cc_auth`` the way the SERVER does: first ``lib``, falling back to ``scripts.lib``.
# Under pytest ``scripts/`` is on sys.path (conftest), so both names exist as DISTINCT module objects and the
# thread-local identity lives in ``lib.cc_auth``. Patch the one the code under test actually reads.
try:  # pragma: no cover - the branch taken depends on sys.path, not on behaviour
    from lib import cc_auth
except ImportError:  # pragma: no cover
    import scripts.lib.cc_auth as cc_auth

LOGIN = "john@example.com"
OPERATOR = "tailnet:" + LOGIN


@pytest.fixture(autouse=True)
def _reset_identity():
    yield
    cc_auth.set_request_principal(None)
    cc_auth.set_request_context(None, None)


def _identity(monkeypatch, principal: str, listener: str | None) -> None:
    """Stand in for portfolio_server's gate: the per-request identity on THIS thread."""
    monkeypatch.setattr(cc_auth, "load_config",
                        lambda path=None: types.SimpleNamespace(allowed_logins=frozenset({LOGIN})))
    cc_auth.set_request_principal(principal)
    cc_auth.set_request_context(listener, {})


def test_snapshot_ctx_freezes_the_values_read_on_the_request_thread(monkeypatch):
    _identity(monkeypatch, OPERATOR, caa.SERVE_PROXY)
    snap = caa.snapshot_ctx()
    # Another thread (the SWR build) has no request identity; the snapshot must not follow it.
    cc_auth.set_request_principal("service-token")
    cc_auth.set_request_context("service", {})
    assert snap.principal() == OPERATOR
    assert snap.listener() == caa.SERVE_PROXY


def test_operator_accepts_the_snapshot_after_the_request_thread_is_gone(monkeypatch):
    _identity(monkeypatch, OPERATOR, caa.SERVE_PROXY)
    snap = caa.snapshot_ctx()
    cc_auth.set_request_principal(None)
    cc_auth.set_request_context(None, None)
    assert caa._operator(snap) == OPERATOR


@pytest.mark.parametrize("principal,listener", [
    ("", None),                                   # anonymous
    ("service-token", "service"),                 # an agent / the service token
    ("tailnet:" + LOGIN, "web"),                  # tailnet, but not on the serve proxy
    ("tailnet:someone-else@example.com", caa.SERVE_PROXY),  # not in allowed_logins
])
def test_a_non_operator_gets_the_real_403_and_starts_no_build(monkeypatch, principal, listener):
    _identity(monkeypatch, principal, listener)

    def tripwire(*a, **k):  # noqa: ANN002, ANN003 -- any call is the failure; a build must never start here
        raise AssertionError("a background build was started for a non-operator")

    monkeypatch.setattr(api, "_shared_get_cached", tripwire)
    status, body = api._asks_tracked_cached("/api/v2/cio/asks/tracked", "GET", None, None)
    assert status == 403
    assert body["error"] == "AGENT_CALLER_REFUSED"


def test_the_build_is_judged_by_the_requester_not_by_the_build_thread(monkeypatch):
    """The regression: the SWR runs the build later, on another thread. The identity captured at request time is what
    `handle` must see. Without ``ctx=...`` the same build gets 403 on that thread (asserted last, as the discriminant)."""
    _identity(monkeypatch, OPERATOR, caa.SERVE_PROXY)
    seen: dict = {}

    def fake_cached(key, ttl, build, **kw):  # noqa: ANN001, ANN003 -- mirrors _shared_get_cached's positional contract
        seen["key"], seen["build"] = key, build
        return {"cached": True}

    monkeypatch.setattr(api, "_shared_get_cached", fake_cached)
    assert api._asks_tracked_cached("/api/v2/cio/asks/tracked", "GET", None, None) == {"cached": True}
    assert seen["key"] == "cio_asks_tracked"

    # The SWR background thread: no request identity at all.
    cc_auth.set_request_principal(None)
    cc_auth.set_request_context(None, None)
    status, body = seen["build"]()
    assert status == 200 and body["ok"] is True
    assert body["data"]["tracked"] == []  # pytest: _deps(None) is None, so an honest empty list, never a store read

    # Discriminant: the pre-3156 build (no ctx) refuses on this thread — the failure the receipt recorded.
    status_old, body_old = caa.handle("/api/v2/cio/asks/tracked", "GET")
    assert status_old == 403 and body_old["error"] == "AGENT_CALLER_REFUSED"


def test_a_config_failure_stays_an_honest_503_and_starts_no_build(monkeypatch):
    """The snapshot is the handler's own config read, taken on the request thread. If it fails, the handler answers
    503 AUTH_CONFIG_UNAVAILABLE on THIS thread: a config fault must not become an unhandled 500, and it must not be
    deferred to a background build that would fail anonymously (the defect this file pins)."""
    def boom(path=None):
        raise RuntimeError("config unreadable")

    monkeypatch.setattr(cc_auth, "load_config", boom)  # the ONE read both the snapshot and the handler make

    def tripwire(*a, **k):  # noqa: ANN002, ANN003 -- any call is the failure: no build may start
        raise AssertionError("a build was started while the config was unreadable")

    monkeypatch.setattr(api, "_shared_get_cached", tripwire)
    status, body = api._asks_tracked_cached("/api/v2/cio/asks/tracked", "GET", None, None)
    assert status == 503
    assert body["error"] == "AUTH_CONFIG_UNAVAILABLE"
