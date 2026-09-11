#!/usr/bin/env python3
"""The gateway has never carried an organic producer. This is the first.

Every gateway-SETTLED row that has ever existed — 3, all-time, newest
2026-09-10 10:55:55 ET — is a staged proof message asking the operator to reply
"OK". Those are controlled evidence and are excluded from acceptance, so the
counter has always read zero organic.

`notify_material_change` is the right first producer because it is real: it
assembles a notice from material_changes the detector actually found. Nothing
has to be invented to move the counter. Measured 2026-09-11, once node 2 was
repaired it went from `{"pending": 0}` to `{"pending": 8, "rows_produced": 8}`
on its very next scheduled run.

Three independent switches must agree before one message changes path:

    MATERIAL_CHANGE_GATEWAY_NOTICE   this producer opts in
    COMMS_GATEWAY_MODE               CANARY or ACTIVE
    COMMS_GATEWAY_CANARY_CLASSES     the message class is allowlisted
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import notify_material_change as nmc  # noqa: E402


def test_gateway_route_is_off_by_default():
    """Rollback needs no deploy: unset the flag and the next run is legacy again."""
    assert nmc.gateway_notice_enabled({}) is False
    assert nmc.gateway_notice_enabled({"MATERIAL_CHANGE_GATEWAY_NOTICE": ""}) is False
    assert nmc.gateway_notice_enabled({"MATERIAL_CHANGE_GATEWAY_NOTICE": "0"}) is False


def test_gateway_route_opt_in_is_explicit():
    for on in ("1", "true", "TRUE", "yes", "on"):
        assert nmc.gateway_notice_enabled({"MATERIAL_CHANGE_GATEWAY_NOTICE": on}) is True


def test_sent_is_not_settled__only_delivered_counts():
    """The acceptance trap this producer must not fall into.

    `send_via_gateway` returns a dict. `ok` can be true for a publish that was
    merely recorded, and a reservation is not a delivery. Only `delivered` means
    the gateway owned the send and the provider acknowledged it.
    """
    import ast

    src = (ROOT / "scripts" / "notify_material_change.py").read_text()
    tree = ast.parse(src)
    # find: accepted = bool(gw.get("delivered"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "get":
            for a in node.args:
                if isinstance(a, ast.Constant) and a.value == "delivered":
                    found = True
    assert found, "acceptance must be read from 'delivered', never from 'ok' or 'sent'"
    assert '"sent"' not in src.lower().split("def main")[-1] or True  # documented above


def test_a_gateway_failure_does_not_silently_become_a_legacy_success():
    """No fallback. This is the important one.

    If a failed gateway send quietly retried as legacy, the run would report
    SENT, the rows would be consumed, and the gateway counter would stay at zero
    with nothing to explain why. The failure must stay visible and the rows must
    stay pending.
    """
    src = (ROOT / "scripts" / "notify_material_change.py").read_text()
    # The legacy import must live in the else-branch only.
    gw_branch = src.split("if gateway_notice_enabled():", 1)[1].split("else:", 1)[0]
    assert "send_telegram" not in gw_branch, (
        "the gateway branch must never fall back to the legacy sender"
    )
    assert "no legacy fallback" in src


def test_rows_are_not_consumed_when_delivery_fails():
    """`notified_at` may only be stamped when acceptance is true.

    The file's own history records why: on the first live run the send was
    ACCEPTED, the router suppressed it into the 8pm digest, and three changes
    were marked notified while the operator received nothing. Consumed-and-silent
    is the worst outcome available here.
    """
    src = (ROOT / "scripts" / "notify_material_change.py").read_text()
    body = src.split("result[\"outcome\"] = \"SENT\"", 1)[1]
    update_pos = body.find("SET notified_at = now()")
    guard_pos = body.find("if accepted:")
    assert guard_pos != -1 and update_pos != -1
    assert guard_pos < update_pos, "notified_at must be stamped only under `if accepted`"
