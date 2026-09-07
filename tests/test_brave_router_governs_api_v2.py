"""SFR-C-001 companion: api_v2 must route through brave_router.

SFR-C-001 was APPLIED on 2026-09-07: api_v2 now reports governed router health
instead of a hardcoded "402 - needs $5 credit" status. The xfail marker is gone.
"""
from __future__ import annotations

from pathlib import Path
import re
import pytest

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "scripts" / "api_v2.py"


# SFR-C-001 APPLIED by the integration owner at INTEGRATION_ORDER.md step 10.
# xfail marker removed per this module's own instruction ("when the change lands
# it must XPASS -> remove the xfail marker").
def test_no_direct_brave_call():
    text = API.read_text(encoding="utf-8", errors="replace")
    has_direct = bool(re.search(r"api\.search\.brave\.com", text)) and (
        "urlopen(" in text or "requests.get(" in text or "brave_search" in text
    )
    # Desired end state: no direct provider HTTP; imports brave_router instead.
    assert "brave_router" in text
    assert not has_direct
