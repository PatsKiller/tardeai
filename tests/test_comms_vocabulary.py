#!/usr/bin/env python3
"""Unit tests for the canonical message-class vocabulary (Wave A F3)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.vocabulary import (  # noqa: E402
    CANONICAL_MESSAGE_CLASSES,
    MESSAGE_CLASS_ALIASES,
    is_canonical,
    normalize_message_class,
)


def test_operational_synonyms_collapse_to_ops():
    for alias in ("operator_alert", "ops_alert", "alert", "health", "health_digest", "health_debug"):
        assert normalize_message_class(alias) == "ops", alias


def test_canonical_classes_pass_through_unchanged():
    for cls in ("ops", "report", "proposal", "research", "digest", "operator_command"):
        assert normalize_message_class(cls) == cls


def test_protected_fact_classes_are_never_aliased_away():
    # Collapsing approval/protection_incident into ops would drop the
    # fail-closed protected-facts gate in required_missing.
    for cls in ("approval", "protection_incident", "broker_fact", "order_state", "risk_limit", "account_fact"):
        assert normalize_message_class(cls) == cls
        assert cls in CANONICAL_MESSAGE_CLASSES


def test_blank_is_not_coerced_to_a_valid_class():
    # A missing class must stay missing so required_missing rejects it.
    assert normalize_message_class("") == ""
    assert normalize_message_class(None) == ""


def test_unknown_class_passes_through_not_coerced():
    # Validate against a known set, never normalize input to make it valid.
    assert normalize_message_class("something_new") == "something_new"
    assert not is_canonical("something_new")


def test_case_and_separator_normalization_only_for_aliases():
    assert normalize_message_class(" OPERATOR_ALERT ") == "ops"
    assert normalize_message_class("health-digest") == "ops"
    assert is_canonical("approval")
    assert is_canonical("ops")
    assert not is_canonical("operator_alert")
