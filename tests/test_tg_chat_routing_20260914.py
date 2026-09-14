"""Generic alerts go to the operator's direct chats, not the Proposal Decisions group.

2026-09-14 Telegram export audit: holdings, stop and health messages appeared in the proposal group
because tg_chat_ids.chat_ids() merged both chat sets and generic broadcasters used it. Operator
approved the routing map. Offline: env only, fake ids.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import tg_chat_ids as t  # noqa: E402

COVERS = ["scripts/tg_chat_ids.py"]


def _env(monkeypatch, dm="111,222", group="-999"):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", dm)
    monkeypatch.setenv("TRADEAI_PROPOSAL_ALERT_CHAT_ID", group)


def test_generic_broadcast_goes_to_direct_chats_only(monkeypatch):
    _env(monkeypatch)
    assert t.chat_ids() == ["111", "222"]
    assert "-999" not in t.chat_ids()


def test_proposal_group_is_its_own_list(monkeypatch):
    _env(monkeypatch)
    assert t.proposal_chat_ids() == ["-999"]


def test_inbound_allowlist_keeps_every_operator_chat(monkeypatch):
    _env(monkeypatch, dm="111, 222,111")
    assert t.allowed_chat_ids() == ["-999", "111", "222"]


def test_generic_broadcasters_do_not_ask_for_the_proposal_group():
    for rel in ("scripts/alert_dispatcher_unified.py", "scripts/hermes_score_alerts.py",
                "scripts/telegram_command_handler.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "proposal_chat_ids" not in src and "allowed_chat_ids" not in src, rel
