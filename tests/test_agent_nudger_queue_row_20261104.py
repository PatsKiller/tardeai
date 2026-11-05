"""FQ-093 (lead dispatch 2026-11-04): an idle session is nudged with its NEXT queue row, not "go read the board".

The lead's words: "the nudger sends an idle session its NEXT queue row instead of a generic heartbeat ... eleven
sessions dispatched twice this hour by hand because every session does one turn and stops".

Runs in CI:  pytest -q tests/test_agent_nudger_queue_row_20261104.py
"""
# ANCHOR: AGENT_NUDGER_QUEUE_ROW_20261104 — gate record: config/ci_gates/AGENT_NUDGER_QUEUE_ROW_20261104.json
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_nudger as N  # noqa: E402

COORD = "/coord"


def write_queue(tmp_path: Path, items) -> Path:
    path = tmp_path / "AUDIT_FIX_QUEUE.json"
    path.write_text(json.dumps({"schema": "AuditFixQueue@v1", "items": items}), encoding="utf-8")
    return path


def row(rid, owner, status, page="/health", check="D", severity="P2", acceptance=None):
    return {
        "id": rid, "owner": owner, "status": status, "page": page, "check": check, "severity": severity,
        "acceptance": acceptance if acceptance is not None else {
            "what": "the page overflows the phone width",
            "expected": "no sideways scroll at 390",
            "actual": "621 px wide",
            "evidence": "health/phone390.png",
        },
    }


# ── selection ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_picks_the_first_queued_row_owned_by_the_session(tmp_path):
    path = write_queue(tmp_path, [
        row("FQ-001", "someone-else", "queued"),
        row("FQ-002", "cc-deepseek-8", "in_progress"),
        row("FQ-003", "cc-deepseek-8", "queued"),
        row("FQ-004", "cc-deepseek-8", "queued"),
    ])
    picked = N.queue_row_for_session("cc-deepseek-8", str(path))
    assert picked is not None and picked["id"] == "FQ-003", "first queued row in file order, not any queued row"


def test_a_session_with_no_queued_row_gets_none(tmp_path):
    path = write_queue(tmp_path, [row("FQ-001", "other", "queued"), row("FQ-002", "cc-deepseek-8", "done")])
    assert N.queue_row_for_session("cc-deepseek-8", str(path)) is None


def test_owner_match_is_exact_not_a_prefix(tmp_path):
    path = write_queue(tmp_path, [row("FQ-001", "cc-deepseek-80", "queued")])
    assert N.queue_row_for_session("cc-deepseek-8", str(path)) is None, "cc-deepseek-80 is a different session"


# ── never crashes the nudge lane ────────────────────────────────────────────────────────────────────────────────
def test_missing_queue_falls_back_without_raising(tmp_path):
    assert N.queue_row_for_session("cc-deepseek-8", str(tmp_path / "absent.json")) is None


def test_half_written_queue_falls_back_without_raising(tmp_path):
    path = tmp_path / "AUDIT_FIX_QUEUE.json"
    path.write_text('{"items": [{"id": "FQ-0', encoding="utf-8")  # torn write, as a concurrent writer leaves it
    assert N.queue_row_for_session("cc-deepseek-8", str(path)) is None


def test_unexpected_shapes_fall_back_without_raising(tmp_path):
    for blob in ('[]', '{"items": 5}', '{"items": [null, "x"]}', '"nope"'):
        path = tmp_path / "q.json"
        path.write_text(blob, encoding="utf-8")
        assert N.queue_row_for_session("cc-deepseek-8", str(path)) is None, blob


def test_bare_list_is_accepted(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps([row("FQ-009", "cc-deepseek-8", "queued")]), encoding="utf-8")
    assert N.queue_row_for_session("cc-deepseek-8", str(path))["id"] == "FQ-009"


# ── the prompt names the work ────────────────────────────────────────────────────────────────────────────────────
def test_prompt_names_id_page_check_and_acceptance(tmp_path):
    path = write_queue(tmp_path, [row("FQ-037", "cc-deepseek-8", "queued")])
    text = N.row_prompt(N.queue_row_for_session("cc-deepseek-8", str(path)), COORD)
    for needle in ("FQ-037", "/health", "check D", "the page overflows the phone width",
                   "no sideways scroll at 390", "621 px wide", "health/phone390.png"):
        assert needle in text, f"missing {needle!r} in: {text}"
    assert "read the PRIORITY QUEUE" not in text, "the generic board-reading instruction must be replaced, not joined"


def test_prompt_keeps_the_close_and_take_next_instructions():
    text = N.row_prompt(row("FQ-037", "cc-deepseek-8", "queued"), COORD)
    assert "red-then-green evidence" in text
    assert "no_longer_reproduces" in text, "a row already fixed must be closable without a second dispatch"
    assert f"{COORD}/inbox/<lead>/" in text
    assert "take your next row" in text


def test_string_acceptance_is_rendered_verbatim():
    text = N.row_prompt(row("FQ-099", "x", "queued", acceptance="one line of acceptance"), COORD)
    assert "one line of acceptance" in text


def test_acceptance_dict_with_partial_fields_does_not_print_none(tmp_path):
    text = N.row_prompt(row("FQ-098", "x", "queued", acceptance={"what": "w only"}), COORD)
    assert "w only" in text and "None" not in text


def test_prompt_contains_no_newline_so_send_keys_submits_it():
    text = N.row_prompt(row("FQ-037", "cc-deepseek-8", "queued"), COORD)
    assert "\n" not in text and "\r" not in text, "send-keys -l types a newline as a separate line event"


def test_interpolated_values_cannot_reintroduce_a_newline():
    """F3 (cc-deepseek-5): page/check/acceptance values are data and may carry a line break; the prompt must not."""
    r = row("FQ-050", "cc-deepseek-8", "queued", page="/health\noverflow", check="D\nE",
            acceptance={"what": "two lines\nin one value", "expected": "one\nline"})
    text = N.row_prompt(r, COORD)
    assert "\n" not in text and "\r" not in text, "a value's line break must be collapsed, not templated away"


def test_send_types_a_single_line_into_tmux():
    """F2 (cc-deepseek-6/cc-deepseek-9): what reaches `send-keys -l` must carry no newline, even from a row prompt."""
    calls = []

    class _Proc:
        returncode = 0
        stdout = ""

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return _Proc()

    # Drive the guard with text that is ALREADY multi-line: `send()` must flatten it before `send-keys -l`, whatever
    # the caller hands it (the F2 defect was the send path, not only the row template). Nothing else collapses it.
    assert N.send("some-session", "line one\nline two\rline three", run=fake_run, sleep=lambda _s: None) is True
    assert calls[0][:4] == ["tmux", "send-keys", "-t", "some-session"], calls[0]
    typed = calls[0][-1]
    assert "\n" not in typed and "\r" not in typed, "the argv handed to send-keys -l must be one line"


def test_a_row_without_a_check_or_severity_still_renders():
    text = N.row_prompt(row("FQ-097", "x", "queued", check="", severity=""), COORD)
    assert "FQ-097" in text and "check" not in text.split("Acceptance:")[0].replace("/health", "")
