"""ANCHOR: LOCAL_LLM_HEALTH_GATE_20261107 — the blocklist itself must satisfy check 5.

Companion to ``tests/test_check_local_llm_health_gate_20261107.py`` (which pins the ancestor-chain
exclusion and the retired-sentinel routing acceptance). This file pins the one case that file does
not: a policy that disables **every** model (``local_llm.DISABLED_MODELS == {"*"}``).

Context (2026-11-07, QUALITY ROUND 2 item 1): ``trade-close-llm-analyzer-source`` refused to run
``--apply`` on every weekly slot because the preflight's ``disabled_model_routing`` check compared
the resolution of ``qwen3:14b`` against ``LOCAL_LLM_SAFE_MODEL``. After the local-generative
retirement, ``_resolve_model`` answers the sentinel ``LOCAL_GENERATIVE_RETIRED``, so the comparison
could never hold again. The retired sentinel is now accepted; this file covers the stronger form of
the same property — the shipped blocklist blocks everything, so no request can route to a local
generative model at all — and keeps the one outcome that must never pass: a request that reports
"blocked" while resolving to the very model it asked for.

Hermetic: no Ollama, no network, no subprocess. Only the real facade's constants are read.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_local_llm_health as H  # noqa: E402

SAFE = "gemma3:4b"
RETIRED = "LOCAL_GENERATIVE_RETIRED"
EVERYTHING = {"*"}


def _ok(resolved, blocked, *, disabled=EVERYTHING, safe=SAFE, retired=RETIRED):
    return H._routing_blocked(resolved, blocked, safe_model=safe, retired=retired,
                              disabled=disabled)


# ── the blocklist alone proves the property ─────────────────────────────────


def test_a_total_blocklist_passes_even_with_an_unrecognised_resolution():
    """``{"*"}`` blocks every model; the sentinel string is then immaterial."""
    assert _ok("deepseek-flash", True) is True


def test_the_total_blocklist_passes_the_live_shipped_resolution():
    local_llm = pytest.importorskip("local_llm")
    resolved, blocked = local_llm._resolve_model("qwen3:14b")
    assert H._routing_blocked(resolved, blocked, safe_model=H.SAFE_MODEL,
                              retired=local_llm.OLLAMA_MODEL,
                              disabled=local_llm.DISABLED_MODELS) is True


# ── what must still fail ────────────────────────────────────────────────────


def test_a_partial_blocklist_does_not_excuse_an_unknown_resolution():
    assert _ok("deepseek-flash", True, disabled={"qwen3:14b"}) is False


def test_an_unblocked_request_fails_even_under_a_total_blocklist():
    assert _ok(RETIRED, False) is False


def test_a_request_that_resolves_to_itself_fails_even_under_a_total_blocklist():
    """'blocked' plus the blocked model back is not a block."""
    assert _ok("qwen3:14b", True) is False


def test_an_empty_resolution_fails_even_under_a_total_blocklist():
    assert _ok("", True) is False
    assert _ok(None, True) is False


# ── the call site actually passes the policy ────────────────────────────────


def test_main_passes_the_blocklist_into_the_route_check(monkeypatch):
    """Guards the wiring: a helper that accepts the policy is useless if main() never hands it over."""
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"models": []}'

    def fake_routing(resolved, was_blocked, **kwargs):
        seen.update(kwargs)
        return True

    import local_llm
    monkeypatch.setattr(H.urllib.request, "urlopen", lambda *a, **k: _Resp())   # check 1: no network
    monkeypatch.setattr(H, "_get_loaded_models", lambda: [])
    monkeypatch.setattr(H, "_call_ollama", lambda *a, **k: '{"answer": 4, "status": "ok"}')
    monkeypatch.setattr(H, "_check_no_unsafe_jobs", lambda: (True, "no unsafe jobs"))
    monkeypatch.setattr(H, "_routing_blocked", fake_routing)
    monkeypatch.setattr(local_llm, "_resolve_model", lambda m: (RETIRED, True))
    monkeypatch.setattr(H, "SAFE_MODEL", SAFE)

    with pytest.raises(SystemExit) as exit_info:
        H.main()
    assert exit_info.value.code == 0, "the gate itself must pass"
    assert seen.get("disabled") == EVERYTHING
    assert seen.get("retired") == local_llm.OLLAMA_MODEL
