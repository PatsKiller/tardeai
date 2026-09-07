"""SFR-C-001 companion: api_v2 must route through brave_router.

Until the integration owner applies the shared-file request, this test is an
expected failure (strict xfail). When the change lands it must XPASS → remove
the xfail marker.
"""
from __future__ import annotations

from pathlib import Path
import re
import pytest

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "scripts" / "api_v2.py"


@pytest.mark.xfail(
    strict=True,
    reason="SFR-C-001 pending: api_v2 still direct-calls Brave; integration-owned",
)
def test_no_direct_brave_call():
    text = API.read_text(encoding="utf-8", errors="replace")
    has_direct = bool(re.search(r"api\.search\.brave\.com", text)) and (
        "urlopen(" in text or "requests.get(" in text or "brave_search" in text
    )
    # Desired end state: no direct provider HTTP; imports brave_router instead.
    assert "brave_router" in text
    assert not has_direct
