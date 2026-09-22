"""A delivered message must not throw away its provider id.

MEASURED 2026-09-22, communication_deliveries over 24h:
    SUPPRESSED 5,072 | LEGACY_DELIVERED 121 | SENT 17 | RESERVED 4
Of the 138 messages actually DELIVERED, only 17 carried a provider id -- 12.3%.
All 121 id-less deliveries came from ONE producer: telegram_alert.send_telegram.

#1179 wired attach_telegram_message_id into 7 call sites, but on the legacy path
last_message_id() correctly returned None every time, so attach honestly
no-opped. The wiring was never the defect: _legacy_send called
_raw_send_telegram (the bool wrapper) instead of _raw_send_telegram_result,
and only the RESULT variant populates _LAST_MESSAGE_IDS.

This also corrects the Phase 2 gate itself: ">=95% of alerts carry a
telegram_message_id" is unreachable when 97.3% are deliberately suppressed by
the router and never sent. The honest denominator is DELIVERED messages.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "scripts" / "telegram_alert.py"


@pytest.fixture
def src() -> str:
    if not TARGET.is_file():
        pytest.skip("telegram_alert not present")
    return TARGET.read_text(encoding="utf-8")


def _body(src: str, name: str) -> str:
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(src, n) or ""
    raise AssertionError(f"{name} not found")


def test_legacy_send_uses_the_result_variant(src: str) -> None:
    """The whole defect in one assertion."""
    body = _body(src, "_legacy_send")
    assert "_raw_send_telegram_result(" in body, (
        "_legacy_send must call the RESULT variant -- it is the only function "
        "that populates _LAST_MESSAGE_IDS"
    )


def test_legacy_send_no_longer_calls_the_bool_wrapper(src: str) -> None:
    """REGRESSION GUARD: reverting to _raw_send_telegram loses the id again."""
    body = _body(src, "_legacy_send")
    calls = [n for n in ast.walk(ast.parse(body))
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_raw_send_telegram"]
    assert not calls, "_legacy_send is back on the bool wrapper; the provider id is discarded"


def test_the_bool_contract_is_unchanged(src: str) -> None:
    """>=36 verified boolean callers depend on this returning a plain bool."""
    body = _body(src, "_legacy_send")
    assert "-> bool:" in body
    assert "return bool(" in body, "the bool contract was widened; callers would break"


def test_only_the_result_variant_records_the_id(src: str) -> None:
    """Pin WHY this matters, so the two functions cannot be swapped back."""
    res = _body(src, "_raw_send_telegram_result")
    assert "_LAST_MESSAGE_IDS.extend(" in res
    wrapper = _body(src, "_raw_send_telegram")
    assert "_LAST_MESSAGE_IDS" not in wrapper, (
        "the bool wrapper now records ids too -- update this test's premise"
    )


def test_a_suppressed_send_still_reports_no_id(src: str) -> None:
    """Empty is the HONEST answer when nothing reached the transport.

    97.3% of sends are router-suppressed. Those must keep returning None rather
    than inheriting the previous message's id.
    """
    assert "reset_last_message_ids()" in src
    res = _body(src, "_raw_send_telegram_result")
    assert "reset_last_message_ids()" in res, "the id is not cleared at the start of a send"


def test_the_detector_can_fail(src: str) -> None:
    """POSITIVE CONTROL: the old shape must fail the assertion above."""
    old = (
        "def _legacy_send(message, bypass_router) -> bool:\n"
        "    return _raw_send_telegram(message)\n"
    )
    calls = [n for n in ast.walk(ast.parse(old))
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_raw_send_telegram"]
    assert calls, "the control does not reproduce the old shape"
