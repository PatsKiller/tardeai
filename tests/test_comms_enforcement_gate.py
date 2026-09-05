#!/usr/bin/env python3
"""Runtime require_event_id gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.comms.enforcement import (  # noqa: E402
    MissingCommunicationEventId,
    assert_delivery_not_owned_in_off_or_shadow,
    require_event_id,
)


def test_require_event_id_accepts_value():
    assert require_event_id("evt_123", adapter="telegram") == "evt_123"


def test_require_event_id_rejects_empty():
    with pytest.raises(MissingCommunicationEventId):
        require_event_id(None, adapter="telegram")
    with pytest.raises(MissingCommunicationEventId):
        require_event_id("  ", adapter="smtp")


def test_delivery_owned_illegal_in_off_shadow():
    assert_delivery_not_owned_in_off_or_shadow("OFF", delivery_owned=False)
    with pytest.raises(RuntimeError):
        assert_delivery_not_owned_in_off_or_shadow("SHADOW", delivery_owned=True)
