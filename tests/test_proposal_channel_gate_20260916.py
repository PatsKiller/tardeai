"""D2 (2026-09-16): Proposal Decisions group is proposals-only — routing gate.

The proposal group (TRADEAI_PROPOSAL_ALERT_CHAT_ID) must carry proposals and
approvals only. This pins the routing invariants:

1. classify_alert_channel routes ONLY PROPOSAL_ALERT_TYPES to "proposal".
2. telegram_destination_for_alert returns the proposal chat only for proposal types.
3. Generic broadcasters never ask for proposal_chat_ids (extended from
   test_tg_chat_routing_20260914).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from telegram_alert_routing_policy import (  # noqa: E402
    PROPOSAL_ALERT_TYPES,
    classify_alert_channel,
    telegram_destination_for_alert,
)


def test_only_proposal_types_route_to_proposal_channel():
    for t in PROPOSAL_ALERT_TYPES:
        assert classify_alert_channel({"alert_type": t}) == "proposal"
    for t in ("orphaned_stop", "material_change", "cio_entry_state", "health",
              "go_scalp", "scanner_candidate"):
        assert classify_alert_channel({"alert_type": t}) == "general", t


def test_non_proposal_alert_never_targets_the_proposal_group(monkeypatch):
    monkeypatch.setenv("TRADEAI_PROPOSAL_ALERT_CHAT_ID", "-100_proposal")
    monkeypatch.setenv("TRADEAI_GENERAL_ALERT_CHAT_ID", "111_general")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    dest = telegram_destination_for_alert({"alert_type": "orphaned_stop"})
    assert dest["channel_type"] == "general"
    assert dest["chat_id"] == "111_general"
    assert dest["chat_id"] != "-100_proposal"


def test_proposal_alert_targets_the_proposal_group(monkeypatch):
    monkeypatch.setenv("TRADEAI_PROPOSAL_ALERT_CHAT_ID", "-100_proposal")
    monkeypatch.setenv("TRADEAI_GENERAL_ALERT_CHAT_ID", "111_general")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    dest = telegram_destination_for_alert({"alert_type": "ACTIONABLE_READY"})
    assert dest["channel_type"] == "proposal"
    assert dest["chat_id"] == "-100_proposal"


def test_generic_broadcasters_never_ask_for_the_proposal_group():
    import tg_chat_ids  # noqa: E402
    forbidden = {"proposal_chat_ids", "allowed_chat_ids"}
    for rel in ("scripts/alert_dispatcher_unified.py",
                "scripts/hermes_score_alerts.py",
                "scripts/telegram_command_handler.py",
                "scripts/system_health_alerts.py",
                "scripts/stop_health_check.py",
                "scripts/screener_go_alerts.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in src, f"{rel} asks for {name}"

    # The only caller of proposal_chat_ids outside the definition is the tg_chat_ids module itself.
    import re
    callers = []
    for py in (ROOT / "scripts").rglob("*.py"):
        src = py.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(?<!def )\bproposal_chat_ids\s*\(", src):
            callers.append(py.relative_to(ROOT).as_posix())
    assert callers == ["scripts/tg_chat_ids.py"], callers
