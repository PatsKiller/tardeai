#!/usr/bin/env python3
"""401/403 must not consume the transient retry ladder.

Structural pins over hooks/useApi.ts and lib/httpOutcome.ts. The behavioural
assertions live in the node suite (httpOutcome.test.ts, 73 assertions) and in the
browser/state matrix; these guard the WIRING, so the classifier cannot be added
and then quietly bypassed.

No network, no browser, no production path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "apps" / "command-center-v3" / "src"
USE_API = SRC / "hooks" / "useApi.ts"
OUTCOME = SRC / "lib" / "httpOutcome.ts"


@pytest.fixture(scope="module")
def use_api() -> str:
    return USE_API.read_text()


def test_the_classifier_exists_and_is_pure():
    src = OUTCOME.read_text()
    assert "export function classifyStatus" in src
    assert "export function classifyError" in src
    assert "export function parseRetryAfter" in src
    for banned in ("useState", "useEffect", "fetch(", "window."):
        assert banned not in src, f"the classifier must stay pure: found {banned}"


def test_use_api_uses_the_classifier_instead_of_a_bare_throw(use_api):
    """The exact defect: `if (!r.ok) throw` merged 401 with a socket timeout."""
    assert "classifyStatus" in use_api, "useApi must classify a non-ok response"
    assert "if (!r.ok) throw new Error" not in use_api, (
        "a bare throw puts an authorization answer in the transport catch"
    )


def test_terminal_outcomes_stop_the_retry_ladder(use_api):
    assert "terminalRef" in use_api
    body = use_api[use_api.index("if (!r.ok)") :]
    head = body[: body.index("setAuthState('OK')")]
    assert "outcome.terminal" in head
    for cleanup in ("clearTimeout(retryRef.current)", "clearInterval(intervalRef.current)"):
        assert cleanup in head, f"a terminal outcome must {cleanup}"


def test_the_polling_interval_cannot_re_arm_a_terminal_outcome(use_api):
    m = re.search(r"const load = async \(\) => \{(.{0,400})", use_api, re.S)
    assert m, "load() not found"
    assert "if (terminalRef.current) return" in m.group(1), (
        "load() must refuse to re-issue a request that cannot succeed"
    )


def test_only_an_explicit_operator_action_clears_a_terminal_outcome(use_api):
    m = re.search(r"const refetch = useCallback\(\(\) => \{(.{0,300})", use_api, re.S)
    assert m and "terminalRef.current = null" in m.group(1), "refetch() is the explicit re-arm contract"


def test_authorization_failure_never_clears_the_stale_flag(use_api):
    """Nothing got fresher because the server said no."""
    body = use_api[use_api.index("if (!r.ok)") :]
    head = body[: body.index("setAuthState('OK')")]
    assert "setStale(false)" not in head, "a rejected refresh must not present data as fresh"
    assert "setStale(true)" in head, "retained data must stay marked stale"


def test_authorization_failure_does_not_raise_the_reconnect_banner(use_api):
    assert "countsAsConnectionFailure" in use_api, "only connectivity may raise the global failing-feeds banner"


def test_retry_after_is_honoured_for_retryable_outcomes(use_api):
    assert "outcome.retryAfterMs ?? backoffMs(retries)" in use_api, (
        "a server-directed delay must win over the local backoff"
    )


def test_unmount_cancels_every_timer(use_api):
    tail = use_api[use_api.index("return () => {") :]
    for cleanup in (
        "cancelled = true",
        "clearInterval(intervalRef.current)",
        "clearTimeout(retryRef.current)",
        "clearTimeout(slowRetryRef)",
    ):
        assert cleanup in tail, f"unmount must {cleanup}"
    assert "slowRetryRef = undefined" in tail, "the slow-retry handle must be released, not just cleared"


def test_the_auth_state_is_exposed_to_consumers(use_api):
    assert "authState" in use_api
    assert re.search(r"return \{[^}]*authState[^}]*\}", use_api, re.S), (
        "a surface cannot render an authorization state it cannot see"
    )


def test_the_node_suite_runs_in_the_build():
    pkg = (ROOT / "apps" / "command-center-v3" / "package.json").read_text()
    assert "httpOutcome.test.ts" in pkg, "a test that CI never runs is not a test"
