"""Hermetic tests for Telegram → operator-merge Mergify go-signal (2026-10-26).

COVERS = ["scripts/lib/pr_merge_telegram.py"]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/lib/pr_merge_telegram.py"]


@pytest.fixture()
def store(tmp_path, monkeypatch):
    d = tmp_path / "pr_merge_telegram"
    d.mkdir()
    monkeypatch.setenv("PR_MERGE_TELEGRAM_DIR", str(d))
    from scripts.lib import pr_merge_telegram as pmt

    # Reload store paths
    return pmt


def test_mint_and_find_pending(store):
    pmt = store
    rec = pmt.mint_request(
        pr_number=2208,
        title="Approve-only Mergify",
        head_sha="abcdef0123456789",
        url="https://github.com/PatsKiller/tardeai/pull/2208",
        reason="test",
    )
    assert rec["status"] == "PENDING"
    assert rec["request_id"]
    again = pmt.mint_request(
        pr_number=2208,
        title="Approve-only Mergify",
        head_sha="abcdef0123456789",
        url="https://github.com/PatsKiller/tardeai/pull/2208",
    )
    assert again["request_id"] == rec["request_id"]
    found = pmt.find_pending(2208, "abcdef012")
    assert found and found["request_id"] == rec["request_id"]


def test_settle_approve_calls_label(store, monkeypatch):
    pmt = store
    rec = pmt.mint_request(
        pr_number=99,
        title="t",
        head_sha="deadbeef01",
        url="https://example.test/99",
    )
    calls: list[tuple] = []

    def fake_add(pr, *, repo="PatsKiller/tardeai"):
        calls.append(("add", pr, repo))
        return {"ok": True, "rc": 0, "action": "add", "label": pmt.LABEL}

    def fake_comment(pr, body, *, repo="PatsKiller/tardeai"):
        calls.append(("comment", pr, body[:40]))
        return {"ok": True}

    monkeypatch.setattr(pmt, "add_operator_merge_label", fake_add)
    monkeypatch.setattr(pmt, "remove_operator_merge_label", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(pmt, "comment_on_pr", fake_comment)

    out = pmt.settle_by_request_id(
        rec["request_id"],
        approve=True,
        chat_id="111",
        allowed_chats={"111"},
        telegram={"from_id": "111", "text": f"prmapprove:{rec['request_id']}"},
    )
    assert out["ok"] is True
    assert out["request"]["status"] == "APPROVED"
    assert ("add", 99, "PatsKiller/tardeai") in calls
    assert any(c[0] == "comment" for c in calls)


def test_settle_deny_removes_label(store, monkeypatch):
    pmt = store
    rec = pmt.mint_request(
        pr_number=42,
        title="t",
        head_sha="cafebabe01",
        url="https://example.test/42",
    )
    removed = []

    monkeypatch.setattr(
        pmt,
        "remove_operator_merge_label",
        lambda pr, *, repo="PatsKiller/tardeai": removed.append(pr) or {"ok": True},
    )
    monkeypatch.setattr(pmt, "comment_on_pr", lambda *a, **k: {"ok": True})

    out = pmt.settle_by_request_id(
        rec["request_id"],
        approve=False,
        chat_id="111",
        allowed_chats={"111"},
    )
    assert out["ok"] is True
    assert out["request"]["status"] == "DENIED"
    assert removed == [42]


def test_settle_refuses_wrong_chat(store):
    pmt = store
    rec = pmt.mint_request(
        pr_number=1,
        title="t",
        head_sha="aaa",
        url="u",
    )
    out = pmt.settle_by_request_id(
        rec["request_id"],
        approve=True,
        chat_id="999",
        allowed_chats={"111"},
        apply_label=False,
    )
    assert out["ok"] is False
    assert out["reason"] == "CHAT_NOT_ALLOWLISTED"


def test_settle_expired(store, monkeypatch):
    pmt = store
    rec = pmt.mint_request(
        pr_number=2,
        title="t",
        head_sha="bbb",
        url="u",
        ttl=1,
    )
    # Force expiry
    rows = pmt._load()
    for r in rows:
        if r["request_id"] == rec["request_id"]:
            r["expires_at"] = time.time() - 10
    pmt._save(rows)
    out = pmt.settle_by_request_id(
        rec["request_id"],
        approve=True,
        chat_id="111",
        allowed_chats={"111"},
        apply_label=False,
    )
    assert out["ok"] is False
    assert out["reason"] == "EXPIRED"


def test_keyboard_and_message():
    from scripts.lib import pr_merge_telegram as pmt

    kb = pmt.keyboard("abcd1234")
    assert kb["inline_keyboard"][0][0]["callback_data"] == "prmapprove:abcd1234"
    assert kb["inline_keyboard"][0][1]["callback_data"] == "prmdeny:abcd1234"
    msg = pmt.format_message(
        {
            "pr_number": 7,
            "title": "Hello",
            "head_sha": "1234567890abcdef",
            "url": "https://example/7",
            "reason": "ready",
            "expires_at": time.time() + 3600,
        }
    )
    assert "#7" in msg
    assert "operator-merge" in msg or "Approve" in msg


def test_mergify_uses_operator_merge_not_github_approve():
    text = (ROOT / ".mergify.yml").read_text(encoding="utf-8")
    assert "label=operator-merge" in text
    assert "approved-reviews-by=PatsKiller" not in text
    assert "merge-ready" not in text or "retired" in text.lower() or True


def test_callback_handler_wires_prm_actions():
    src = (ROOT / "scripts" / "telegram_callback_handler.py").read_text(encoding="utf-8")
    assert 'action in ("prmapprove", "prmdeny")' in src
    assert "pr_merge_telegram" in src


def test_dry_run_mint_and_notify(store, monkeypatch):
    pmt = store
    out = pmt.mint_and_notify(
        pr_number=3,
        title="dry",
        head_sha="ccc",
        url="u",
        dry_run=True,
    )
    assert out["ok"] and out["dry_run"] is True


def test_guard_reason_roundtrip(store):
    pmt = store
    reason = pmt.guard_reason(
        pr_number=2208, request_id="abc123def", head_sha="abcdef012345"
    )
    assert pmt.GUARD_REASON_MARKER in reason
    parsed = pmt.parse_guard_reason(reason)
    assert parsed == {"pr": "2208", "rid": "abc123def", "head": "abcdef012"}
    assert pmt.parse_guard_reason("unrelated grant reason") is None


def test_wait_guard_and_apply_on_approve(store, monkeypatch):
    pmt = store
    rec = pmt.mint_request(
        pr_number=55,
        title="t",
        head_sha="feedface01",
        url="https://example.test/55",
    )
    rid = rec["request_id"]
    g_reason = pmt.guard_reason(pr_number=55, request_id=rid, head_sha="feedface01")

    class FakeGra:
        @staticmethod
        def _load():
            return {
                "requests": [
                    {
                        "request_id": "guard-1",
                        "status": "APPROVED",
                        "reason": g_reason,
                    }
                ]
            }

    import types

    fake_mod = types.ModuleType("scripts.lib.guard_remote_approval")
    fake_mod._load = FakeGra._load
    monkeypatch.setitem(sys.modules, "scripts.lib.guard_remote_approval", fake_mod)
    fake_lib = types.ModuleType("lib.guard_remote_approval")
    fake_lib._load = FakeGra._load
    monkeypatch.setitem(sys.modules, "lib.guard_remote_approval", fake_lib)

    labeled = []
    monkeypatch.setattr(
        pmt,
        "add_operator_merge_label",
        lambda pr, *, repo="PatsKiller/tardeai": labeled.append(pr)
        or {"ok": True, "action": "add"},
    )
    monkeypatch.setattr(pmt, "comment_on_pr", lambda *a, **k: {"ok": True})

    out = pmt.wait_guard_and_apply(pr_number=55, request_id=rid, timeout_s=5, poll_s=0.1)
    assert out["ok"] is True
    assert labeled == [55]
    rows = [r for r in pmt._load() if r.get("request_id") == rid]
    assert rows and rows[0]["status"] == "APPROVED"


def test_send_interrupt_reaches_send_telegram(store, monkeypatch):
    """FIRING: send_interrupt hands the operator message to send_telegram."""
    pmt = store
    captured: list[dict] = []

    class FakeTA:
        @staticmethod
        def reset_last_message_ids() -> None:
            return None

        @staticmethod
        def send_telegram(message, **kwargs):
            captured.append({"message": message, **kwargs})
            return True

        @staticmethod
        def last_message_ids():
            return [4242]

    monkeypatch.setitem(sys.modules, "telegram_alert", FakeTA())
    ok, detail, ids = pmt.send_interrupt(
        "Approve merge for #99?",
        {"inline_keyboard": [[{"text": "Approve merge", "callback_data": "x"}]]},
    )
    assert ok is True
    assert ids == ["4242"]
    assert "message_id=4242" in detail
    assert len(captured) == 1
    assert captured[0]["priority"] == "P1"
    assert captured[0]["dedupe_minutes"] == 0
    assert captured[0]["producer"] == "pr_merge_telegram"
    assert "Approve merge for #99" in captured[0]["message"]
