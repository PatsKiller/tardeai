"""The Communications ledger must not report a delivery that did not happen.

Measured 2026-09-05, two adjacent rows in `communication_deliveries`, both
LEGACY_DELIVERED, both with provider_message_id NULL:

    21:35:36  approval request   — arrived in Telegram
    21:39:43  Health Inspector   — router suppressed it; never arrived

The Communications page showed the operator a delivered alert they never
received. `_best_effort_comms_publish` hardcoded status="LEGACY_DELIVERED" on
the strength of a docstring claim that "the legacy path delivers this class",
and `send_telegram` read `result["delivered"]` on the very next line without
passing it.

A status asserted identically for a delivered and an undelivered message carries
no information, and is worse than no status because the surface renders it as
fact.

No database is touched here: the comms client and settle path are stubbed, which
also keeps this suite off the live Postgres that tests/conftest.py warns about.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import telegram_alert  # noqa: E402


@pytest.fixture
def settled(monkeypatch):
    """Capture what status the ledger would be told, without a DB."""
    calls: list[dict] = []

    class _Pub:
        delivery_ids = ["d-1"]

    import scripts.lib.comms.adapters as adapters
    import scripts.lib.comms.client as client
    import scripts.lib.comms.delivery as delivery

    monkeypatch.setattr(adapters, "from_plain_message",
                        lambda **kw: {"stub": True}, raising=False)
    monkeypatch.setattr(client, "publish_communication",
                        lambda *a, **k: _Pub(), raising=False)
    monkeypatch.setattr(
        delivery, "settle_delivery",
        lambda did, *, status, provider_coordinates=None, **k:
            calls.append({"id": did, "status": status,
                          "coords": provider_coordinates or {}}),
        raising=False)
    return calls


# ── the three outcomes are three different words ────────────────────────────

def test_a_delivered_message_settles_legacy_delivered(settled):
    telegram_alert._best_effort_comms_publish("m", message_class="ops", delivered=True)
    assert settled[0]["status"] == "LEGACY_DELIVERED"


def test_a_suppressed_message_settles_suppressed_not_delivered(settled):
    """The 21:39 Health Inspector case."""
    telegram_alert._best_effort_comms_publish("m", message_class="ops", delivered=False)
    assert settled[0]["status"] == "SUPPRESSED"
    assert settled[0]["status"] != "LEGACY_DELIVERED"


def test_an_unknown_outcome_settles_unknown_not_the_flattering_value(settled):
    """None means nobody observed it. Borrowing LEGACY_DELIVERED there is how
    the lie got in originally."""
    telegram_alert._best_effort_comms_publish("m", message_class="ops")
    assert settled[0]["status"] == "UNKNOWN"


def test_the_observation_is_recorded_beside_the_status(settled):
    """So a later reader can tell an observed delivery from an assumed one."""
    telegram_alert._best_effort_comms_publish("m", message_class="ops", delivered=False)
    assert settled[0]["coords"].get("observed_delivered") is False


def test_the_two_adjacent_rows_no_longer_look_identical(settled):
    """The exact incident: one arrived, one did not, both said the same thing."""
    telegram_alert._best_effort_comms_publish("approval", message_class="ops",
                                              delivered=True)
    telegram_alert._best_effort_comms_publish("health inspector", message_class="ops",
                                              delivered=False)
    assert settled[0]["status"] != settled[1]["status"]


# ── the caller must actually pass what it knows ─────────────────────────────

def test_every_publish_call_in_the_module_passes_the_observed_outcome():
    """Scoped to the MODULE, not to one function.

    The first version of this read only `send_telegram`'s source and passed
    while `send_telegram_document` — a sibling with `ok` right there in scope —
    published without it, settling every document row LEGACY_DELIVERED
    including failed sends. A guard that inspects one caller cannot see the
    caller next to it.
    """
    import re

    src = (ROOT / "scripts" / "telegram_alert.py").read_text(encoding="utf-8")
    # Invocations only — the def line carries `message: str` and is excluded.
    invocations = [c for c in re.findall(r"_best_effort_comms_publish\((.*?)\)", src, re.S)
                   if "message_class" in c and "message: str" not in c]
    assert len(invocations) >= 4, f"expected every call site, found {len(invocations)}"
    for call in invocations:
        assert "delivered=" in call, (
            f"a publish call omits the observed outcome: {' '.join(call.split())[:90]}")


def test_the_helper_still_refuses_to_default_to_delivered():
    """A future caller that forgets must land on UNKNOWN, never on delivered."""
    import inspect

    sig = inspect.signature(telegram_alert._best_effort_comms_publish)
    assert sig.parameters["delivered"].default is None
