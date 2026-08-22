"""Friday oversight: auto = ChatGPT OAuth; paid requires --apply-paid."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import defense_weekly_paid_review as weekly


class _FakeConn:
    def __init__(self):
        self.committed = False
        self.closed = False

    def cursor(self):
        return object()

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_parse_args_default_is_not_paid():
    args = weekly.parse_args([])
    assert args.apply_paid is False
    assert args.seat == "paid"
    assert args.dry_run is False


def test_intended_mode_paid_only_with_flag():
    cfg = {
        "oversight_paid": {"weekly_paid_review": True},
        "oversight_free": {"weekly_auto_review": True, "weekly_auto_seat": "chatgpt"},
    }
    auto = weekly.parse_args([])
    paid = weekly.parse_args(["--apply-paid"])
    assert weekly.intended_mode(auto, cfg) == "auto_chatgpt"
    assert weekly.intended_mode(paid, cfg) == "paid"


def test_config_true_cannot_auto_spend_paid():
    """Old Friday cron spent Claude because weekly_paid_review=true with no flag."""
    cfg = {
        "oversight_paid": {"weekly_paid_review": True},
        "oversight_free": {"weekly_auto_review": True, "weekly_auto_seat": "chatgpt"},
    }
    assert weekly.intended_mode(weekly.parse_args([]), cfg) != "paid"


def test_weekly_auto_review_off_skips():
    cfg = {"oversight_free": {"weekly_auto_review": False}}
    assert weekly.intended_mode(weekly.parse_args([]), cfg) == "skip"


def test_auto_seat_defaults_chatgpt():
    assert weekly.auto_seat({"oversight_free": {}}) == "chatgpt"
    assert weekly.auto_seat({"oversight_free": {"weekly_auto_seat": "CHATGPT"}}) == "chatgpt"


def test_dry_run_auto_does_not_call_llm():
    do = MagicMock()
    conn = _FakeConn()
    rc = weekly.main(["--dry-run"], do=do, get_conn=lambda: conn, send_telegram=lambda *a, **k: None)
    assert rc == 0
    do.run_paid_review.assert_not_called()
    do.run_free_critiques.assert_not_called()


def test_dry_run_apply_paid_still_does_not_call_llm():
    do = MagicMock()
    conn = _FakeConn()
    rc = weekly.main(
        ["--dry-run", "--apply-paid"],
        do=do, get_conn=lambda: conn, send_telegram=lambda *a, **k: None)
    assert rc == 0
    do.run_paid_review.assert_not_called()
    do.run_free_critiques.assert_not_called()


def test_default_main_calls_chatgpt_oauth_not_paid():
    do = MagicMock()
    do.run_free_critiques.return_value = {
        "build_hash": "abc", "seats": {"chatgpt": "ok"}, "token_estimate": 1}
    conn = _FakeConn()
    notes = []
    rc = weekly.main([], do=do, get_conn=lambda: conn, send_telegram=lambda m, **k: notes.append(m))
    assert rc == 0
    do.run_paid_review.assert_not_called()
    do.run_free_critiques.assert_called_once()
    kwargs = do.run_free_critiques.call_args
    assert kwargs.kwargs.get("seats") == ["chatgpt"]
    assert kwargs.kwargs.get("force") is True
    assert "chatgpt oauth" in notes[0]
    assert "$0" in notes[0]
    assert "paid" not in notes[0].lower() or "oauth" in notes[0]
    assert conn.committed is True


def test_apply_paid_calls_run_paid_review():
    do = MagicMock()
    do.run_paid_review.return_value = {
        "ok": True, "spent_usd": 0.4,
        "results": {"paid": {"model": "claude-opus-4-8", "status": "ok"}},
    }
    conn = _FakeConn()
    notes = []
    rc = weekly.main(
        ["--apply-paid"], do=do, get_conn=lambda: conn,
        send_telegram=lambda m, **k: notes.append(m))
    assert rc == 0
    do.run_free_critiques.assert_not_called()
    do.run_paid_review.assert_called_once()
    assert do.run_paid_review.call_args.kwargs.get("seats") == ["paid"] or (
        len(do.run_paid_review.call_args.args) >= 2
        and do.run_paid_review.call_args.args[1] == ["paid"])
    assert "manual --apply-paid" in notes[0]
    assert "claude-opus-4-8" in notes[0]


def test_apply_paid_custom_seat():
    do = MagicMock()
    do.run_paid_review.return_value = {
        "ok": True, "spent_usd": 0.1,
        "results": {"paid_gpt": {"model": "gpt-5.4", "status": "ok"}},
    }
    conn = _FakeConn()
    rc = weekly.main(
        ["--apply-paid", "--seat", "paid_gpt"],
        do=do, get_conn=lambda: conn, send_telegram=lambda *a, **k: None)
    assert rc == 0
    assert do.run_paid_review.call_args.kwargs.get("seats") == ["paid_gpt"]


def test_config_on_disk_paid_defaults_off_auto_chatgpt():
    cfg = json.loads((weekly.ROOT / "config" / "defense_recommendations.json").read_text())
    assert cfg["oversight_paid"]["weekly_paid_review"] is False
    assert cfg["oversight_free"]["weekly_auto_review"] is True
    assert cfg["oversight_free"]["weekly_auto_seat"] == "chatgpt"


def test_free_critiques_signature_accepts_seats():
    import inspect
    import defense_oversight as do
    sig = inspect.signature(do.run_free_critiques)
    assert "seats" in sig.parameters
    assert "chatgpt" in dict(do.FREE_SEATS)


def test_cron_source_never_calls_paid_without_flag():
    src = (weekly.ROOT / "scripts" / "defense_weekly_paid_review.py").read_text()
    assert "run_paid_review" in src
    assert "--apply-paid" in src
    # Default argv path is auto_chatgpt; paid is behind intended_mode == paid
    assert 'if mode == "paid"' in src
    assert "seats=[seat_auto]" in src
