"""Hermes external lane breaker trips on 'unavailable' too (2026-09-27 due diligence).

3,021 of 3,374 ChatGPT rows in a week were CODEX_HEADLESS_UNAVAILABLE retries; the
breaker only counted HTTP 401/403 errors. Hermetic: pure function, no DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import hermes_external_researcher as her  # noqa: E402

UNAV = ("unavailable", "[UNAVAILABLE] CODEX_HEADLESS_UNAVAILABLE: openai-codex is authed but did not finalize")


def test_six_unavailable_rows_open_the_breaker():
    assert her.breaker_trips([UNAV] * 6, n=6)


def test_auth_errors_still_open_it_and_mixed_failures_count():
    assert her.breaker_trips([("error", "[ERROR HTTP 403] forbidden")] * 3 + [UNAV] * 3, n=6)
    assert her.breaker_trips([("auth_pending", "[AUTH_PENDING]")] * 6, n=6)


def test_one_success_or_a_non_lane_error_keeps_it_closed():
    assert not her.breaker_trips([UNAV] * 5 + [("sent", "ok")], n=6)
    assert not her.breaker_trips([("error", "[ERROR HTTP 500] upstream")] * 6, n=6)
    assert not her.breaker_trips([("skipped", "[SKIPPED_BUDGET]")] * 6, n=6)


def test_too_few_rows_never_trip():
    assert not her.breaker_trips([UNAV] * 5, n=6)
