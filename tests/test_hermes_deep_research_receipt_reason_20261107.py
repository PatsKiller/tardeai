"""A failed deep-research run must say WHY, not only that it failed.

2026-11-07: ``hermes-deep-research-local`` had failed 13 runs in a row. The receipt carried

    {"completed": false, "counts": {"failed": 3}, "apply": true, "status": "RUN_FAILED"}

and nothing else, so the Quality tab could say only "(its receipt says status failed)". The cause was
external and specific — the local ChatGPT OAuth proxy answered 429 for 28 hours — and a quota exhaustion,
an auth prompt and a dead proxy need three different operator actions. They must not collapse into the
word "failed".

Everything here is synthetic: the messages are constructed, no provider is called and no DB is touched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "deep_research_receipt_reason", ROOT / "scripts" / "hermes_deep_research_local.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _module()


def test_a_rate_limited_quota_is_not_an_auth_failure():
    """The exact message hermes_external_researcher raises when the ChatGPT session is out of quota."""
    exc = RuntimeError(
        "CODEX_UNAVAILABLE_RATE_LIMITED: upstream ChatGPT OAuth quota/rate limit — not an auth failure "
        "(re-login will not help); the CLI fallback shares the same session, so it was not attempted: HTTP 429")
    assert MOD.classify_failure(exc) == "provider_rate_limited"


def test_an_unlogged_in_session_asks_for_a_login():
    assert MOD.classify_failure(RuntimeError("AUTH_PENDING: openai-codex not logged in.")) == "provider_auth_pending"


def test_a_dead_proxy_is_its_own_reason():
    exc = RuntimeError("CODEX_HEADLESS_UNAVAILABLE: openai-codex is authed but did not finalize a response")
    assert MOD.classify_failure(exc) == "provider_headless_unavailable"


def test_an_unrecognised_error_keeps_its_type():
    assert MOD.classify_failure(ValueError("boom")) == "error_ValueError"


def test_a_failed_target_records_its_reason_under_its_symbol():
    MOD._FAILURE_REASONS.clear()
    assert MOD._failed("SPRC", "provider_empty_response", "chatgpt oauth returned no content") == "failed"
    assert MOD._FAILURE_REASONS == {"SPRC": "provider_empty_response"}
    MOD._FAILURE_REASONS.clear()


def test_the_receipt_error_names_every_reason_most_frequent_first():
    counts = {"failed": 3}
    reasons = {"SPRC": "provider_rate_limited", "IVF": "provider_rate_limited", "AXTI": "provider_empty_response"}
    line = MOD.failure_summary(counts, reasons)
    assert line == "3 of 3 targets failed: provider_rate_limited x2, provider_empty_response x1"


def test_a_successful_run_has_no_failure_summary():
    assert MOD.failure_summary({"applied": 3}, {}) == ""


def test_run_one_records_the_reason_when_the_provider_is_rate_limited(monkeypatch):
    """End to end through run_one with a stubbed context and a stubbed provider — no DB, no network."""
    import hermes_external_researcher

    def rate_limited(model, prompt):
        raise RuntimeError("CODEX_UNAVAILABLE_RATE_LIMITED: upstream ChatGPT OAuth quota/rate limit; HTTP 429")

    monkeypatch.setattr(MOD, "gather_context", lambda conn, sym: {"recent_trades": [], "prior_research": []})
    monkeypatch.setattr(hermes_external_researcher, "call_codex_cli", rate_limited)
    MOD._FAILURE_REASONS.clear()
    try:
        assert MOD.run_one(object(), "SPRC", "chatgpt", apply=False) == "failed"
        assert MOD._FAILURE_REASONS == {"SPRC": "provider_rate_limited"}
    finally:
        MOD._FAILURE_REASONS.clear()


def test_the_receipt_carries_the_failure_summary_as_its_error():
    """The Quality tab reads receipt.error; the summary alone never reaches that line."""
    text = (ROOT / "scripts" / "hermes_deep_research_local.py").read_text(encoding="utf-8")
    assert 'error=None if ok else (summary.get("failure_summary") or None)' in text, (
        "a failed run must put its reason on the receipt's error field")
    assert '_LAST_RUN["failure_summary"] = failure_summary(counts, _FAILURE_REASONS)' in text, (
        "the failure summary is not recorded on the run summary")
