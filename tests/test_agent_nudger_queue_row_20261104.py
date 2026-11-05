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


# ── the MAIN caller dispatches the row prompt (CX2, codex-cloud 2026-11-05) ─────────────────────────────────────
#
# The tests above exercise selection and formatting directly. None drove `main()` with a queue fixture, and the other
# caller tests (P1/P2) never passed a matching row, so reverting the send site to the generic heartbeat would have left
# every one of them green. These drive the caller itself (AGENTS.md §8A: "Test the caller, not only the helper").

IDLE_SCREEN = "❯ \n  ? for shortcuts"


def seed_idle_state(tmp_path: Path, session: str, screen: str = IDLE_SCREEN) -> Path:
    """A state record whose hash matches the screen, so decide() votes NUDGE instead of 'first seen'."""
    import hashlib
    import time

    now = time.time()
    rec = {"hash": hashlib.sha256(N.tail_of(screen).encode()).hexdigest(),
           "changed_at": now - 30 * 60,   # idle 30 min: past the 4-minute idle_minutes
           "nudged_at": now - 60 * 60}    # last nudge 60 min ago: past the 10-minute min_gap
    path = tmp_path / "state.json"
    path.write_text(json.dumps({session: rec}), encoding="utf-8")
    return path


def run_main(monkeypatch, tmp_path: Path, queue_path: Path, *, apply: bool, session="cc-deepseek-8"):
    """Invoke the real main() with a working, captured transport; returns (rc, [(session, text), ...])."""
    calls = []

    def fake_send(session_name, text, **_kwargs):
        calls.append((session_name, text))
        return True

    monkeypatch.setattr(N, "list_sessions", lambda cfg: ([session], True))
    monkeypatch.setattr(N, "capture", lambda name: (IDLE_SCREEN, True))
    monkeypatch.setattr(N, "send", fake_send)
    # A live main() writes a LaneRunReceipt; point it at the test's own tree so this caller test writes nothing durable.
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rc = N.main(["--apply" if apply else "--dry-run",
                 "--state", str(tmp_path / "state.json"),
                 "--ledger", str(tmp_path / "ledger.jsonl"),
                 "--coord-dir", COORD,
                 "--queue", str(queue_path)])
    return rc, calls


def test_main_sends_the_queue_row_prompt_to_an_idle_session(tmp_path, monkeypatch):
    """CX2: the caller must dispatch the row prompt. Reverting the send site to `PROMPT.format(...)` turns this red."""
    path = write_queue(tmp_path, [row("FQ-042", "cc-deepseek-8", "queued")])
    seed_idle_state(tmp_path, "cc-deepseek-8")
    rc, calls = run_main(monkeypatch, tmp_path, path, apply=True)
    assert rc == 0
    assert len(calls) == 1, calls
    session_name, text = calls[0]
    assert session_name == "cc-deepseek-8"
    assert "Your next queue row is FQ-042" in text, text
    assert "no sideways scroll at 390" in text, "the row's ACCEPTANCE must reach the caller's send()"
    assert "re-read /coord/WORKERS.md" not in text, "a queue row must replace the generic heartbeat, not join it"


def test_main_falls_back_to_the_generic_heartbeat_when_no_row_matches(tmp_path, monkeypatch):
    """The floor: no queued row for the session means the old heartbeat, exactly, and it still types."""
    path = write_queue(tmp_path, [row("FQ-001", "someone-else", "queued"),
                                  row("FQ-002", "cc-deepseek-8", "done")])
    seed_idle_state(tmp_path, "cc-deepseek-8")
    rc, calls = run_main(monkeypatch, tmp_path, path, apply=True)
    assert rc == 0
    assert len(calls) == 1, calls
    assert calls[0][1] == N.PROMPT.format(coord=COORD), "no matching row must fall back to the generic prompt"


def test_dry_run_prints_the_constructed_queue_prompt(tmp_path, monkeypatch, capsys):
    """CX1: the acceptance lives only in the message; a dry-run preview that omits it cannot be reviewed."""
    path = write_queue(tmp_path, [row("FQ-043", "cc-deepseek-8", "queued",
                                      acceptance={"what": "wording that only the message carries"})])
    seed_idle_state(tmp_path, "cc-deepseek-8")
    rc, calls = run_main(monkeypatch, tmp_path, path, apply=False)
    out = capsys.readouterr().out
    assert rc == 0 and calls == [], "a dry run must type nothing"
    assert "FQ-043" in out
    assert "wording that only the message carries" in out, (
        "the dry-run plan must print the constructed prompt (AGENTS.md §6), not only the row id and page")
