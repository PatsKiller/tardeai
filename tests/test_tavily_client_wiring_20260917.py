"""Tavily slot wiring — the declared-but-unwired backup slot (row 03).

Before 2026-09-17 `providers.tavily` was declared in the registry with an
operator approval and a 20/day budget, sat in `domains.web_search.backup`, and
had no client anywhere in the tree. Every Brave denial reached slot 2 and
recorded NO_ADAPTER.

These tests pin the two properties that make the slot safe to leave wired on a
host that has no key: it never raises out of the client, and it never spends.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.brave_router import SPILL_ADAPTERS  # noqa: E402
from scripts.lib.data_source_authority import resolve_backup  # noqa: E402
from scripts.lib.tavily_client import (  # noqa: E402
    NOT_CONFIGURED,
    api_key,
    configured,
    tavily_search,
)


# ── the gap this closes ────────────────────────────────────────────────────


def test_every_declared_backup_slot_has_an_adapter():
    """The regression that started this: a declared slot with no transport."""
    for provider in resolve_backup("web_search"):
        assert provider in SPILL_ADAPTERS, (
            f"{provider!r} is in domains.web_search.backup but has no SPILL_ADAPTERS "
            "entry — spill will record NO_ADAPTER for it"
        )


def test_tavily_is_registered():
    assert "tavily" in SPILL_ADAPTERS
    assert callable(SPILL_ADAPTERS["tavily"])


# ── unconfigured host: fail soft, spend nothing ────────────────────────────


def test_api_key_absent_is_empty_not_error():
    assert api_key({}) == ""
    assert configured({}) is False


def test_api_key_accepts_either_env_spelling():
    assert api_key({"TAVILY_API_KEY": "k1"}) == "k1"
    assert api_key({"TAVILY_API": "k2"}) == "k2"
    # conventional spelling wins when both are set
    assert api_key({"TAVILY_API_KEY": "k1", "TAVILY_API": "k2"}) == "k1"


def test_blank_key_is_treated_as_absent():
    assert api_key({"TAVILY_API_KEY": "   "}) == ""


def test_search_without_key_returns_error_row_and_makes_no_call(monkeypatch):
    """No key must not become a network call, and must not raise."""
    def _explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("urlopen called despite no API key configured")

    monkeypatch.setattr("urllib.request.urlopen", _explode)
    hits = tavily_search("AVAV earnings", env={})
    assert len(hits) == 1
    assert NOT_CONFIGURED in hits[0]["error"]
    assert hits[0]["engine"] == "tavily"
    assert "url" not in hits[0]


def test_transport_raises_on_all_error_response_so_chain_refunds(monkeypatch):
    """The router contract: a dead slot raises so its budget unit is refunded."""
    monkeypatch.setenv("BRAVE_ROUTER_LIVE", "1")
    transport = SPILL_ADAPTERS["tavily"]
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API", raising=False)
    with pytest.raises(RuntimeError, match="tavily"):
        transport("AVAV earnings", "general", 3)


def test_transport_refuses_network_when_not_armed(monkeypatch):
    monkeypatch.delenv("BRAVE_ROUTER_LIVE", raising=False)
    with pytest.raises(RuntimeError, match="BRAVE_ROUTER_LIVE"):
        SPILL_ADAPTERS["tavily"]("AVAV earnings", "general", 3)


# ── configured host: normalized to the shared hit shape ────────────────────


def test_results_normalized_to_shared_shape(monkeypatch):
    import io
    import json as _json

    body = _json.dumps({"results": [
        {"title": "Acme beats", "url": "https://www.example.com/a",
         "content": "revenue up", "published_date": "2026-09-16"},
    ]}).encode()

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp(body))
    hits = tavily_search("acme", env={"TAVILY_API_KEY": "k"}, limit=5)
    assert len(hits) == 1
    h = hits[0]
    # same keys the searxng slot produces, so _normalize_spill_results is happy
    for key in ("title", "snippet", "url", "domain", "query", "engine"):
        assert key in h
    assert h["domain"] == "example.com"
    assert h["engine"] == "tavily"
