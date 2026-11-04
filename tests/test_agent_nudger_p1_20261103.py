"""Nudger P1: the repo-owned copy decides exactly like the live script (2026-11-03)."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_nudger as N  # noqa: E402

BUSY = "· Working (3s · esc to interrupt)\n> "
IDLE = "❯ \n  ? for shortcuts"
STALL = "API Error: 529 Overloaded\n❯ "
UNSENT = "❯ please finish the task\n  ? for shortcuts"


def seen(screen, changed_at, nudged_at=None):
    """A state record whose screen hash matches, so decide() does not treat it as first-seen."""
    rec = {"hash": hashlib.sha256(N.tail_of(screen).encode()).hexdigest(), "changed_at": changed_at}
    if nudged_at is not None:
        rec["nudged_at"] = nudged_at
    return rec


def cfg(**kw):
    c = dict(N.DEFAULTS)
    c.update(kw)
    return c


def test_busy_screen_is_busy():
    assert N.decide(BUSY, {}, 1000.0, cfg())["action"] == "busy"


def test_idle_screen_waits_then_nudges_then_cools_down():
    c = cfg()
    assert N.decide(IDLE, {}, 1000.0, c)["action"] == "wait"          # first seen: idle clock starts now
    assert N.decide(IDLE, seen(IDLE, 1000.0 - 300), 1000.0, c)["action"] == "NUDGE"
    assert N.decide(IDLE, seen(IDLE, 1000.0 - 300, 1000.0 - 60), 1000.0, c)["action"] == "cooldown"


def test_a_vendor_stall_resumes_immediately_but_rate_limited():
    c = cfg()
    assert N.decide(STALL, seen(STALL, 1000.0 - 10), 1000.0, c)["action"] == "RESUME"
    assert N.decide(STALL, seen(STALL, 1000.0 - 10, 1000.0 - 30), 1000.0, c)["action"] == "wait"


def test_unsent_text_gets_enter_after_two_minutes():
    c = cfg()
    assert N.decide(UNSENT, seen(UNSENT, 1000.0 - 300), 1000.0, c)["action"] == "ENTER"


def test_the_built_in_refusal_survives_an_empty_config_list():
    for name in ("cc-deepseek-broker", "cc-order-entry", "cx-execution", "cu-mbi"):
        assert N.refused_session(name, cfg(refused_regex="")) is True, name
        assert N.refused_session(name, cfg(refused_regex="nothing-here")) is True, name
    assert N.refused_session("cc-deepseek-6", cfg(refused_regex="")) is False


def test_refused_sessions_are_never_listed_or_captured():
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return type("R", (), {"stdout": "cc-deepseek-broker\ncc-deepseek-6\ncodex\n", "returncode": 0})()
    assert N.list_sessions(cfg(), run=run) == (["cc-deepseek-6"], True)
    assert calls and calls[0][:3] == ["tmux", "ls", "-F"]


def test_dry_run_writes_nothing_and_types_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(N, "list_sessions", lambda c, run=None: (["cc-deepseek-6"], True))
    monkeypatch.setattr(N, "capture", lambda s, run=None: (IDLE, True))
    typed = []
    monkeypatch.setattr(N, "send", lambda s, t, run=None, sleep=None: typed.append((s, t)))
    state = tmp_path / "state.json"
    rec = seen(IDLE, 1000.0 - 300)
    state.write_text(json.dumps({"cc-deepseek-6": rec}))
    rc = N.main(["--state", str(state), "--ledger", str(tmp_path / "ledger.jsonl"), "--coord-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and typed == [] and "DRY RUN" in out and "would: " in out
    assert not (tmp_path / "ledger.jsonl").exists()
    assert json.loads(state.read_text())["cc-deepseek-6"] == rec


def test_apply_types_the_fixed_prompt_and_writes_one_ledger_line(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "list_sessions", lambda c, run=None: (["cc-deepseek-6"], True))
    monkeypatch.setattr(N, "capture", lambda s, run=None: (IDLE, True))
    typed = []

    def send_ok(s, t, run=None, sleep=None):
        # P2 (2026-11-04): send() now reports whether tmux confirmed the keystroke, and a nudge is counted only when
        # it did. The stub returns True because this test is about the typing path, not about a failed send.
        typed.append((s, t))
        return True

    monkeypatch.setattr(N, "send", send_ok)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"cc-deepseek-6": seen(IDLE, 1000.0 - 300)}))
    rc = N.main(["--apply", "--state", str(state), "--ledger", str(tmp_path / "ledger.jsonl"),
                 "--coord-dir", str(tmp_path)])
    assert rc == 0 and typed and typed[0][0] == "cc-deepseek-6"
    assert "WORKERS.md" in typed[0][1] and str(tmp_path) in typed[0][1]
    lines = (tmp_path / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["by"] == "agent-nudger"
    assert json.loads(state.read_text())["cc-deepseek-6"]["nudged_at"] > 0
