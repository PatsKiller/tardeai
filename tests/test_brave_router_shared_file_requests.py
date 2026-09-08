"""Companion tests for Lane C shared-file requests (out-of-lease Brave callers).

Strict-xfail only where a real direct provider HTTP path still exists outside
Lane C's lease. Callers already routed via brave_search (now governed) or that
only mention Brave in comments/status are classified without xfail.
"""
from __future__ import annotations

import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _has_direct_provider_http(rel: str) -> bool:
    path = ROOT / rel
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"api\.search\.brave\.com", text):
        return False
    # Ignore pure comments / docstrings containing the URL without a request.
    for i, line in enumerate(text.splitlines(), 1):
        if not re.search(r"api\.search\.brave\.com", line):
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        window = "\n".join(text.splitlines()[max(0, i - 8): i + 8])
        if "_get(" in window or "urlopen(" in window or "requests.get(" in window or "Request(" in window:
            return True
    return False


def test_api_v2_uses_router_surface():
    text = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8", errors="replace")
    assert "brave_router" in text


@pytest.mark.xfail(strict=True, reason="SFR-C-003 REJECTED by integration owner: routing a key-liveness probe through a router that is DISABLED BY DEFAULT would report a healthy key as unverified. Lane C's documented fallback taken; defect 11 stays partial here.")
def test_secret_validators_routed():
    assert not _has_direct_provider_http("scripts/secret_validators.py")


@pytest.mark.xfail(strict=True, reason="SFR-C-004 REJECTED by integration owner: same reason as SFR-C-003 — credential_monitor must not report a healthy key as dead when the router flag is off. Fallback taken; defect 11 partial.")
def test_credential_monitor_routed():
    assert not _has_direct_provider_http("scripts/credential_monitor.py")


def test_run_cio_hardening_ci_classified_comment_only():
    assert not _has_direct_provider_http("scripts/run_cio_hardening_ci.py")


def test_alert_dispatcher_classified_budget_status_only():
    # Uses brave_search.get_budget_status, not a search HTTP call.
    assert not _has_direct_provider_http("scripts/alert_dispatcher_unified.py")
    text = (ROOT / "scripts/alert_dispatcher_unified.py").read_text(encoding="utf-8")
    assert "get_budget_status" in text


def test_phase2b_already_via_brave_search():
    # Root fixer embeds budgeted brave_search.search — now governed via router.
    assert not _has_direct_provider_http("phase2b_analyst.py")
    text = (ROOT / "phase2b_analyst.py").read_text(encoding="utf-8")
    assert "brave_search" in text


def test_campaign_closeout_is_scanner_not_caller():
    # Scans for the URL string; does not call the provider.
    assert not _has_direct_provider_http("scripts/lib/campaign_closeout.py")
