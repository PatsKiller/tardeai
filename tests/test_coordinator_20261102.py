"""Co-coordinators by territory (operator 2026-11-02, PLAN_CO_COORDINATORS_20261102).

Proves scripts/coordinator.py and scripts/lib/coordination_view.py:
  * the registry (CoordinatorRegistry@v1): appointment records the operator's verbatim quote, exactly one lead,
    heartbeat freshness, territories and assignments; a stood-down coordinator cannot heartbeat;
  * the shared notebook: append-only ledger, BOARD.md regenerated, inbox send/read (moved, never deleted), handoff
    (snapshot + territory and lead transfer), whoami;
  * the check rule: a check_request needs a DIFFERENT ACTIVE coordinator's ok/block; a same-coordinator or stale
    answer is refused; a resolved check leaves the pending list;
  * durability: every write is locked and atomic (no temp files left), concurrent appends all land as valid JSONL,
    and the read-only view never creates the store.

Hermetic: a tmp state root; no network, DB or credential. AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load(name: str, rel: str):
    """Load a producer by FILE PATH, registering spec.name in sys.modules BEFORE exec_module (AGENTS §7)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader, rel
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


C = _load("coordinator", "scripts/coordinator.py")
V = _load("coordination_view", "scripts/lib/coordination_view.py")


def run(root: Path, *args: str) -> int:
    return C.main(["--state-root", str(root), *args])


def refused(root: Path, *args: str) -> int:
    """A missing required flag is argparse's refusal (SystemExit 2), not a command status."""
    try:
        return run(root, *args)
    except SystemExit as exc:
        return int(exc.code or 0)


def appoint(root: Path, cid: str = "claude-lead", role: str = "lead", terr: str = "release",
            session: str | None = None, vendor: str = "claude", quote: str = "appoint this one") -> int:
    return run(root, "appoint", "--id", cid, "--vendor", vendor, "--session", session or f"s-{cid}",
               "--territories", terr, "--role", role, "--quote", quote)


def registry(root: Path) -> dict:
    return json.loads((root / "data" / "coordination" / "coordinator" / "coordinators.json").read_text())


def ledger(root: Path) -> list[dict]:
    p = root / "data" / "coordination" / "coordinator" / "ledger.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


# ── registry ──────────────────────────────────────────────────────────────────────────────────────────


def test_appoint_requires_the_operator_quote(tmp_path):
    assert run(tmp_path, "appoint", "--id", "x", "--vendor", "codex", "--territories", "agents",
               "--role", "member", "--quote", "   ") == 2
    assert not (tmp_path / "data" / "coordination" / "coordinator" / "coordinators.json").exists()


def test_appoint_writes_the_registry_and_records_the_quote(tmp_path):
    assert appoint(tmp_path, quote="codex is the coordinator for agents") == 0
    reg = registry(tmp_path)
    assert reg["schema"] == C.SCHEMA_REGISTRY and reg["coordinators"][0]["id"] == "claude-lead"
    assert reg["coordinators"][0]["appointed_quote"] == "codex is the coordinator for agents"
    assert reg["coordinators"][0]["role"] == "lead" and reg["coordinators"][0]["territories"] == ["release"]
    events = ledger(tmp_path)
    assert events[0]["kind"] == "appoint" and events[0]["operator_quote"] == "codex is the coordinator for agents"
    assert (tmp_path / "data" / "coordination" / "coordinator" / "BOARD.md").exists()


def test_exactly_one_lead(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "lead", "agents") == 2
    assert [c["id"] for c in registry(tmp_path)["coordinators"]] == ["claude-lead"]


def test_heartbeat_and_stand_down(tmp_path):
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    assert run(tmp_path, "heartbeat", "--id", "codex-a") == 0
    # a stand-down is an operator act: no words, no change (the parser requires --quote)
    assert refused(tmp_path, "stand-down", "--id", "codex-a") == 2
    assert registry(tmp_path)["coordinators"][0]["status"] != "stood_down"
    plan = run(tmp_path, "stand-down", "--id", "codex-a", "--quote", "stop the agents lane", "--dry-run")
    assert plan == 0 and registry(tmp_path)["coordinators"][0]["status"] != "stood_down"
    assert run(tmp_path, "stand-down", "--id", "codex-a", "--quote", "stop the agents lane") == 0
    assert registry(tmp_path)["coordinators"][0]["status"] == "stood_down"
    assert run(tmp_path, "heartbeat", "--id", "codex-a") == 2  # the operator alone re-appoints


def test_assign_known_territory_only(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert run(tmp_path, "assign", "pr:2485", "nope") == 2
    assert run(tmp_path, "assign", "pr:2485", "release") == 0
    assert registry(tmp_path)["assignments"] == {"pr:2485": "release"}


def test_whoami_matches_the_session(tmp_path):
    assert appoint(tmp_path, "codex-a", "member", "agents", session="sock-9") == 0
    assert run(tmp_path, "whoami", "--session", "sock-9") == 0
    assert run(tmp_path, "whoami", "--session", "nobody") == 1


# ── checks ────────────────────────────────────────────────────────────────────────────────────────────


def test_a_check_needs_a_different_active_coordinator(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    assert run(tmp_path, "check", "request", "pr:2485", "--sha", "abc123", "--by", "claude-lead") == 0
    assert run(tmp_path, "check", "ok", "pr:2485", "--sha", "abc123", "--by", "claude-lead") == 2
    assert run(tmp_path, "check", "ok", "pr:2485", "--sha", "abc123", "--by", "codex-a") == 0
    kinds = [e["kind"] for e in ledger(tmp_path)]
    assert kinds.count("check_request") == 1 and kinds.count("check_ok") == 1


def test_a_stale_coordinator_cannot_answer_a_check(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    reg = registry(tmp_path)
    reg["coordinators"][1]["last_heartbeat"] = "2026-01-01T00:00:00Z"
    (tmp_path / "data" / "coordination" / "coordinator" / "coordinators.json").write_text(json.dumps(reg))
    assert run(tmp_path, "check", "request", "pr:1", "--sha", "s", "--by", "claude-lead") == 0
    assert run(tmp_path, "check", "ok", "pr:1", "--sha", "s", "--by", "codex-a") == 2


def test_pending_checks_clear_on_ok(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    assert run(tmp_path, "check", "request", "pr:9", "--sha", "d", "--by", "claude-lead") == 0
    assert len(C.pending_checks(C.read_events(tmp_path))) == 1
    assert run(tmp_path, "check", "block", "pr:9", "--sha", "d", "--by", "codex-a", "--reason", "no") == 0
    assert C.pending_checks(C.read_events(tmp_path)) == []


# ── notebook ─────────────────────────────────────────────────────────────────────────────────────────


def test_inbox_send_and_read_moves_never_deletes(tmp_path, capsys):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert run(tmp_path, "inbox", "send", "--to", "claude-lead", "--from", "codex-a", "--text", "one voice: hold") == 0
    capsys.readouterr()
    assert run(tmp_path, "inbox", "read", "--id", "claude-lead") == 0
    out = capsys.readouterr().out
    assert "one voice: hold" in out and "moved to" in out
    moved = list((tmp_path / "data" / "coordination" / "coordinator" / "inbox" / "claude-lead" / "read").iterdir())
    assert len(moved) == 1


def test_handoff_moves_territories_and_lead(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    # a lead handoff is an operator act: no words, no change
    assert refused(tmp_path, "handoff", "--from", "claude-lead", "--to", "codex-a") == 2
    assert registry(tmp_path)["lead"] == "claude-lead"
    assert run(tmp_path, "handoff", "--from", "claude-lead", "--to", "codex-a",
               "--quote", "let codex lead now", "--dry-run") == 0
    assert registry(tmp_path)["lead"] == "claude-lead"
    assert run(tmp_path, "handoff", "--from", "claude-lead", "--to", "codex-a",
               "--quote", "let codex lead now") == 0
    reg = registry(tmp_path)
    by = {c["id"]: c for c in reg["coordinators"]}
    # the top-level lead follows the role, or every later mutation is refused as divergent
    assert reg["lead"] == "codex-a"
    assert run(tmp_path, "assign", "pr:2492", "release") == 0
    assert by["codex-a"]["role"] == "lead" and by["claude-lead"]["role"] == "member"
    assert set(by["codex-a"]["territories"]) == {"agents", "release"} and by["claude-lead"]["territories"] == []
    snaps = list((tmp_path / "data" / "coordination" / "coordinator" / "handoffs").iterdir())
    assert len(snaps) == 1 and "Handoff claude-lead -> codex-a" in snaps[0].read_text()


def test_a_failed_handoff_append_leaves_ownership_unchanged(tmp_path, monkeypatch, capsys):
    """cx-openai D52 triage at b10809549 (#2492): the validated handoff event is appended BEFORE the ownership
    change. The previous order wrote (and fsynced) the new registry first, so an append failure left the territories
    and the lead already moved with no handoff record -- the lock serialises writers but supplies no rollback."""
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    reg_path = tmp_path / "data" / "coordination" / "coordinator" / "coordinators.json"
    before = reg_path.read_bytes()

    def unwritable(root, event):
        raise OSError("ledger unwritable")

    monkeypatch.setattr(C, "append_event", unwritable)
    assert run(tmp_path, "handoff", "--from", "claude-lead", "--to", "codex-a",
               "--quote", "let codex lead now") == 2
    assert reg_path.read_bytes() == before  # not one byte: ownership did not move without its event
    reg = registry(tmp_path)
    assert reg["lead"] == "claude-lead"
    by = {c["id"]: c for c in reg["coordinators"]}
    assert by["claude-lead"]["role"] == "lead" and set(by["codex-a"]["territories"]) == {"agents"}
    assert "ownership is unchanged" in capsys.readouterr().err


def test_a_failed_assignment_append_leaves_the_assignment_unchanged(tmp_path, monkeypatch, capsys):
    """cx-openai D52 KEEP_BLOCK at d0f84722c (#2492): the assignment event is appended BEFORE the reassignment.
    cmd_assign wrote the registry first, so a failed append left pr:1 moved with zero ledger events naming it."""
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert run(tmp_path, "assign", "pr:1", "release") == 0
    events = len(ledger(tmp_path))
    reg_path = tmp_path / "data" / "coordination" / "coordinator" / "coordinators.json"
    before = reg_path.read_bytes()

    def unwritable(root, event):
        raise OSError("ledger unwritable")

    monkeypatch.setattr(C, "append_event", unwritable)
    assert run(tmp_path, "assign", "pr:1", "ui") == 2
    assert reg_path.read_bytes() == before  # the reassignment did not move without its event
    assert registry(tmp_path)["assignments"]["pr:1"] == "release"
    assert len(ledger(tmp_path)) == events  # and no event was written either
    assert "the assignment is unchanged" in capsys.readouterr().err


def test_an_assignment_is_recorded_in_the_ledger_and_the_board(tmp_path):
    """The success control: the event exists, the registry holds the assignment, the board names it."""
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert run(tmp_path, "assign", "pr:7", "release") == 0
    assert [e for e in ledger(tmp_path) if e["kind"] == "assign" and e["subject"] == "pr:7"]
    assert registry(tmp_path)["assignments"]["pr:7"] == "release"
    assert "pr:7" in (tmp_path / "data" / "coordination" / "coordinator" / "BOARD.md").read_text()


def test_board_regenerates(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert run(tmp_path, "assign", "pr:2485", "release") == 0
    assert run(tmp_path, "board") == 0
    md = (tmp_path / "data" / "coordination" / "coordinator" / "BOARD.md").read_text()
    assert "Coordination board" in md and "claude-lead" in md and "pr:2485" in md


# ── durability ───────────────────────────────────────────────────────────────────────────────────────


def test_no_temp_files_are_left_behind(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    d = tmp_path / "data" / "coordination"
    leftovers = [p.name for p in d.rglob(".*") if p.is_file() and p.name != ".lock"]
    assert leftovers == []


def test_concurrent_appends_are_valid_jsonl(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda i: run(tmp_path, "event", "note", "--subject", f"n{i}", "--detail", "x"), range(20)))
    events = ledger(tmp_path)
    assert len(events) == 22  # appoint + initial heartbeat + 20 notes
    assert {e["subject"] for e in events if e["kind"] == "note"} == {f"n{i}" for i in range(20)}


# ── read-only view ───────────────────────────────────────────────────────────────────────────────────


def test_view_reads_without_creating_the_store(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    data = V.coordinators_view(tmp_path)
    assert data["schema"] == V.SCHEMA_VIEW and data["registry_present"] is False
    assert data["coordinators"] == [] and data["lead"] is None
    assert not (tmp_path / "data").exists()  # a GET never creates anything


def test_view_reports_freshness_and_the_board(tmp_path, monkeypatch):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    reg = registry(tmp_path)
    reg["coordinators"][1]["last_heartbeat"] = "2026-01-01T00:00:00Z"
    (tmp_path / "data" / "coordination" / "coordinator" / "coordinators.json").write_text(json.dumps(reg))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    view = V.coordinators_view(tmp_path)
    states = {c["id"]: c["state"] for c in view["coordinators"]}
    assert states["claude-lead"] == "active" and states["codex-a"] == "stale"
    assert view["lead"] == "claude-lead"
    board = V.board_view(tmp_path, limit=5)
    assert board["board_present"] is True and "Coordination board" in board["board_md"]
    assert len(board["events"]) <= 5


def test_view_ignores_a_foreign_path(tmp_path):
    assert V.handle("/api/v2/coordination/claims", {}, None) is None


# ── join command (one server-side template) ──────────────────────────────────────────────────────────


def _write_template(root: Path, text: str) -> Path:
    d = root / "data" / "coordination" / "coordinator"
    d.mkdir(parents=True, exist_ok=True)
    p = d / V.JOIN_TEMPLATE
    p.write_text(text, encoding="utf-8")
    return p


def _join(query: dict) -> dict:
    return V.handle("/api/v2/coordination/join-command", query, None)


def test_join_command_renders_the_template_and_follows_edits(tmp_path, monkeypatch):
    _write_template(tmp_path, "Your coordinator id is {id}. Read and follow /x/ONBOARDING.md\n")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    out = _join({"id": ["codex-a"], "vendor": ["codex"]})
    assert out["schema"] == V.SCHEMA_JOIN and out["valid"] is True and out["template_present"] is True
    assert out["line"] == "Your coordinator id is codex-a. Read and follow /x/ONBOARDING.md"
    assert out["template_modified_at"]
    # Editing the template is the only change: the page follows it with no deploy.
    _write_template(tmp_path, "Join as {id} ({vendor})")
    assert _join({"id": ["codex-a"], "vendor": ["codex"]})["line"] == "Join as codex-a (codex)"


def test_join_command_defaults_the_id_from_the_vendor(tmp_path, monkeypatch):
    _write_template(tmp_path, "id={id} vendor={vendor}")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert _join({"vendor": ["codex"]})["line"] == "id=codex vendor=codex"
    assert _join({"vendor": ["claude"]})["line"] == "id=claude vendor=claude"


def test_join_command_validates_the_id_and_vendor(tmp_path, monkeypatch):
    _write_template(tmp_path, "id {id}")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    bad = _join({"id": ["Bad ID"], "vendor": ["codex"]})
    assert bad["valid"] is False and "a-z0-9-" in bad["error"] and bad["line"] is None
    assert _join({"id": ["ok-1"], "vendor": ["not-a-vendor"]})["valid"] is False


def test_join_command_reports_a_missing_template_without_creating_it(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    out = _join({"id": ["a"], "vendor": ["claude"]})
    assert out["template_present"] is False and out["line"] is None
    assert not (tmp_path / "data").exists()


# ── agent screens (snapshot) ─────────────────────────────────────────────────────────────────────────


def _fake_tmux(tmp_path: Path) -> Path:
    p = tmp_path / "fake-tmux"
    p.write_text('''#!/usr/bin/env python3
import sys, time
a = sys.argv[1:]
now = int(time.time())
if a and a[0] == "list-sessions":
    print(f"cc-deepseek-1\\t{now - 5}")
    print(f"codex\\t{now - 500}")
    print(f"other\\t{now - 5}")
elif a and a[0] == "capture-pane":
    print("hello from the pane")
    print("second line")
sys.exit(0)
''', encoding="utf-8")
    p.chmod(0o755)
    return p


def test_snapshot_writes_one_file_per_matching_session(tmp_path, capsys):
    tmux = _fake_tmux(tmp_path)
    assert run(tmp_path, "snapshot", "--tmux-bin", str(tmux), "--lines", "10") == 0
    capsys.readouterr()
    d = tmp_path / "data" / "coordination" / "coordinator" / "agents"
    assert sorted(f.name for f in d.iterdir()) == ["cc-deepseek-1.txt", "codex.txt"]  # 'other' is not a default
    busy = (d / "cc-deepseek-1.txt").read_text()
    assert busy.startswith("captured_at: ") and "session: cc-deepseek-1" in busy
    assert "state: busy" in busy and "hello from the pane" in busy
    assert "state: idle" in (d / "codex.txt").read_text()  # 500 s of silence


def test_snapshot_patterns_are_configurable(tmp_path):
    tmux = _fake_tmux(tmp_path)
    assert run(tmp_path, "snapshot", "--tmux-bin", str(tmux), "--sessions", "other") == 0
    d = tmp_path / "data" / "coordination" / "coordinator" / "agents"
    assert sorted(f.stem for f in d.iterdir()) == ["other"]


def test_snapshot_without_tmux_is_a_no_op(tmp_path):
    assert run(tmp_path, "snapshot", "--tmux-bin", str(tmp_path / "no-such-tmux")) == 0
    d = tmp_path / "data" / "coordination" / "coordinator" / "agents"
    assert not d.exists() or list(d.iterdir()) == []


def test_view_lists_agent_snapshots(tmp_path, monkeypatch):
    tmux = _fake_tmux(tmp_path)
    assert run(tmp_path, "snapshot", "--tmux-bin", str(tmux)) == 0
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    agents = {a["session"]: a for a in V.coordinators_view(tmp_path)["agents"]}
    assert agents["cc-deepseek-1"]["state"] == "busy" and agents["codex"]["state"] == "idle"
    assert agents["cc-deepseek-1"]["captured_at"]


# ── partner docs rendered as-is ──────────────────────────────────────────────────────────────────────


def test_docs_render_as_written(tmp_path, monkeypatch):
    d = tmp_path / "data" / "coordination" / "coordinator"
    d.mkdir(parents=True)
    text = "# Partner onboarding\n\nas-is **text** with `code`\n"
    (d / "ONBOARDING.md").write_text(text, encoding="utf-8")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    out = V.handle("/api/v2/coordination/docs", {"name": ["ONBOARDING.md"]}, None)
    assert out["present"] is True and out["text"] == text and out["modified_at"]
    assert V.handle("/api/v2/coordination/docs", {"name": ["../AGENTS.md"]}, None)["present"] is False
    assert V.handle("/api/v2/coordination/docs", {"name": ["RULES_INTERIM.md"]}, None)["present"] is False


# ── operator transfers: give / lead / take-back / add / ack ──────────────────────────────────────────


def _tmux_that_logs(tmp_path: Path):
    """A fake tmux whose send-keys calls are appended to a file (the notice assertion)."""
    log = tmp_path / "tmux-sends.log"
    p = tmp_path / "fake-tmux-sends"
    p.write_text('''#!/usr/bin/env python3
import sys, time
a = sys.argv[1:]
if a and a[0] == "list-sessions":
    now = int(time.time())
    print("s-claude\\t" + str(now - 5))
    print("s-codex\\t" + str(now - 5))
elif a and a[0] == "capture-pane":
    print("pane")
elif a and a[0] == "send-keys":
    with open(%r, "a", encoding="utf-8") as f:
        f.write(" ".join(a[1:]) + "\\n")
sys.exit(0)
''' % str(log), encoding="utf-8")
    p.chmod(0o755)
    return p, log


def _seed_lead_and_codex(root: Path, tmux: Path) -> None:
    assert run(root, "appoint", "--id", "claude-lead", "--vendor", "claude", "--session", "s-claude",
               "--territories", "release,agents,ui,ops", "--role", "lead", "--quote", "lead") == 0
    assert run(root, "add", "codex", "--vendor", "codex", "--session", "s-codex", "--quote", "add codex") == 0


def test_give_all_round_trip_notifies_and_acks(tmp_path):
    tmux, log = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "codex", "all", "--quote", "codex handles everything",
               "--tmux-bin", str(tmux)) == 0
    by = {c["id"]: c for c in registry(tmp_path)["coordinators"]}
    assert set(by["codex"]["territories"]) == {"agents", "ops", "release", "ui"}
    assert by["claude-lead"]["territories"] == []
    assert by["codex"]["role"] == "member" and by["claude-lead"]["role"] == "lead"  # give moves territory, not lead
    sends = log.read_text().splitlines()
    assert len(sends) == 2 and any("s-claude" in s for s in sends) and any("s-codex" in s for s in sends)
    assert all("coord ack codex" in s for s in sends)
    assert run(tmp_path, "ack", "codex") == 0
    assert [p for p in registry(tmp_path)["pending_acks"].values() if not p["acknowledged"]] == []
    assert run(tmp_path, "take-back", "codex", "--quote", "take it back", "--tmux-bin", str(tmux)) == 0
    by = {c["id"]: c for c in registry(tmp_path)["coordinators"]}
    assert set(by["claude-lead"]["territories"]) == {"agents", "ops", "release", "ui"}
    assert by["codex"]["territories"] == []


def test_lead_swaps_the_role_and_keeps_territories(tmp_path):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "lead", "codex", "--quote", "codex is the lead now", "--tmux-bin", str(tmux)) == 0
    by = {c["id"]: c for c in registry(tmp_path)["coordinators"]}
    assert by["codex"]["role"] == "lead" and by["claude-lead"]["role"] == "member"
    assert set(by["claude-lead"]["territories"]) == {"agents", "ops", "release", "ui"}  # territories untouched


def test_a_transfer_without_the_operator_words_is_refused(tmp_path):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    before = ledger(tmp_path)
    assert run(tmp_path, "give", "codex", "agents", "--quote", "   ", "--tmux-bin", str(tmux)) == 2
    assert ledger(tmp_path) == before  # nothing written, not even the write-ahead event
    assert run(tmp_path, "take-back", "codex", "--quote", "", "--tmux-bin", str(tmux)) == 2
    assert run(tmp_path, "lead", "codex", "--quote", "", "--tmux-bin", str(tmux)) == 2


def test_give_refuses_an_unknown_coordinator_or_territory(tmp_path):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "nobody", "agents", "--quote", "q", "--tmux-bin", str(tmux)) == 2
    assert run(tmp_path, "give", "codex", "nope", "--quote", "q", "--tmux-bin", str(tmux)) == 2


def test_a_transfer_to_a_stood_down_destination_is_refused_before_any_write(tmp_path, capsys):
    """D52 triage @046e73199: existence is not eligibility. A working lead transferred to a stood-down
    destination was demoted and a stood_down replacement persisted, which `heartbeat` then refuses."""
    tmux, log = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "stand-down", "--id", "codex", "--quote", "codex is done") == 0
    reg_path = tmp_path / "data" / "coordination" / "coordinator" / "coordinators.json"
    before_reg, before_led = reg_path.read_bytes(), ledger(tmp_path)
    capsys.readouterr()
    assert run(tmp_path, "lead", "codex", "--quote", "make codex the lead", "--tmux-bin", str(tmux)) == 2
    err = capsys.readouterr().err
    assert "codex" in err and "stood_down" in err  # the refusal names the destination and its state
    assert reg_path.read_bytes() == before_reg  # not one byte: no ledger event, no handoff, no board
    assert ledger(tmp_path) == before_led
    assert not log.exists()  # no session was told anything
    by = {c["id"]: c for c in registry(tmp_path)["coordinators"]}
    assert by["claude-lead"]["role"] == "lead"  # the working lead is not demoted
    assert set(by["claude-lead"]["territories"]) == {"agents", "ops", "release", "ui"}
    assert by["codex"]["status"] == "stood_down" and by["codex"]["role"] == "member"
    # every transfer verb shares the same plan validation
    assert run(tmp_path, "give", "codex", "agents", "--quote", "q", "--tmux-bin", str(tmux)) == 2
    assert reg_path.read_bytes() == before_reg


def test_ack_by_the_wrong_coordinator_is_refused(tmp_path):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "codex", "agents", "--quote", "q", "--tmux-bin", str(tmux)) == 0
    assert run(tmp_path, "ack", "claude-lead") == 2
    assert run(tmp_path, "ack", "codex") == 0


def test_transfer_writes_the_ledger_first_and_a_handoff(tmp_path):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "codex", "all", "--quote", "codex handles everything",
               "--tmux-bin", str(tmux)) == 0
    kinds = [e["kind"] for e in ledger(tmp_path)]
    assert kinds.index("transfer_give") < kinds.index("transfer_notified")
    tr = [e for e in ledger(tmp_path) if e["kind"] == "transfer_give"][0]
    assert tr["operator_quote"] == "codex handles everything"
    assert tr["detail"] == "coord give codex all --quote codex handles everything --tmux-bin " + str(tmux)
    snaps = list((tmp_path / "data" / "coordination" / "coordinator" / "handoffs").iterdir())
    assert [p.name for p in snaps] == [f"{tr['transfer_id']}-operator-to-codex.md"]


def test_ack_timeout_alerts_once_through_the_chokepoint(tmp_path, monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(C, "_operator_alert", lambda subject, summary: calls.append((subject, summary)) or True)
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "codex", "agents", "--quote", "q", "--tmux-bin", str(tmux),
               "--now", "2026-11-02T15:00:00Z") == 0
    assert run(tmp_path, "timeouts", "--apply", "--now", "2026-11-02T15:05:00Z") == 0  # inside the window
    assert calls == []
    assert run(tmp_path, "timeouts", "--apply", "--now", "2026-11-02T15:16:00Z") == 0
    assert len(calls) == 1 and calls[0][0] == "codex"
    assert run(tmp_path, "timeouts", "--apply", "--now", "2026-11-02T16:30:00Z") == 0
    assert len(calls) == 1  # alerted once, never repeated
    assert [e for e in ledger(tmp_path) if e["kind"] == "ack_timeout"]


def test_add_prints_the_join_line_from_the_template(tmp_path):
    d = tmp_path / "data" / "coordination" / "coordinator"
    d.mkdir(parents=True)
    (d / "join_command.template").write_text("Your coordinator id is {id} ({vendor}).\n", encoding="utf-8")
    assert run(tmp_path, "appoint", "--id", "claude-lead", "--vendor", "claude", "--role", "lead",
               "--territories", "release", "--quote", "lead") == 0
    assert run(tmp_path, "add", "codex", "--vendor", "codex", "--quote", "add codex") == 0
    assert registry(tmp_path)["coordinators"][-1]["id"] == "codex"


# ── repairs: read-only status, dry runs, ledger-first add, notification sides, take-back ─────────────


def test_status_is_strictly_read_only_on_an_absent_store(tmp_path):
    assert run(tmp_path, "status") == 0
    assert not (tmp_path / "data").exists()  # no lock, no directories, no board


def test_give_dry_run_writes_notifies_and_alerts_nothing(tmp_path, capsys):
    tmux, log = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    before_reg, before_led = registry(tmp_path), ledger(tmp_path)
    capsys.readouterr()
    assert run(tmp_path, "give", "codex", "all", "--quote", "q", "--tmux-bin", str(tmux), "--dry-run") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["transfer_id"] and out["handoff_path"]
    assert out["ledger_event"]["kind"] == "transfer_give" and out["notices"]
    assert registry(tmp_path) == before_reg and ledger(tmp_path) == before_led and not log.exists()


def test_timeouts_dry_run_is_the_default_and_writes_nothing(tmp_path, monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr(C, "_operator_alert", lambda s, m: calls.append((s, m)) or True)
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "codex", "agents", "--quote", "q", "--tmux-bin", str(tmux),
               "--now", "2026-11-02T15:00:00Z") == 0
    before = ledger(tmp_path)
    capsys.readouterr()
    assert run(tmp_path, "timeouts", "--now", "2026-11-02T15:16:00Z") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["expired"][0]["action"] == "would_alert"
    assert calls == [] and ledger(tmp_path) == before
    assert run(tmp_path, "timeouts", "--apply", "--dry-run") == 2  # mutually exclusive


def test_a_refused_alert_is_visible_and_retried_after_the_backoff(tmp_path, monkeypatch):
    outcomes = iter([False, True])
    monkeypatch.setattr(C, "_operator_alert", lambda s, m: next(outcomes))
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "codex", "agents", "--quote", "q", "--tmux-bin", str(tmux),
               "--now", "2026-11-02T15:00:00Z") == 0
    assert run(tmp_path, "timeouts", "--apply", "--now", "2026-11-02T15:16:00Z") == 0  # delivery refused
    failed = [e for e in ledger(tmp_path) if e["kind"] == "ack_alert_failed"]
    assert failed and failed[0]["alert_queued"] is False
    pending = list(registry(tmp_path)["pending_acks"].values())[0]
    assert pending["alerted"] is False and pending["alert_attempts"] == 1
    assert run(tmp_path, "timeouts", "--apply", "--now", "2026-11-02T15:20:00Z") == 0  # still cooling
    assert list(registry(tmp_path)["pending_acks"].values())[0]["alert_attempts"] == 1
    assert run(tmp_path, "timeouts", "--apply", "--now", "2026-11-02T15:40:00Z") == 0  # retry succeeds
    pending = list(registry(tmp_path)["pending_acks"].values())[0]
    assert pending["alerted"] is True and pending["alert_attempts"] == 2


def test_operator_alert_uses_the_comms_intent_chokepoint_contract(monkeypatch):
    seen: dict = {}

    def fake_queue_intent(**kw):
        seen.update(kw)
        return {"request_id": "x"}

    fake = types.SimpleNamespace(queue_intent=fake_queue_intent)
    monkeypatch.setitem(sys.modules, "lib.host_comms_intents", fake)
    assert C._operator_alert("codex", "no ack") is True
    assert seen["producer"] == "coordinator" and seen["domain"] == "coordination"
    assert seen["kind"] == "coordinator_ack_timeout" and seen["subject"] == "codex"

    def refuse(**kw):
        raise RuntimeError("intent_unrouted")

    monkeypatch.setitem(sys.modules, "lib.host_comms_intents", types.SimpleNamespace(queue_intent=refuse))
    assert C._operator_alert("codex", "no ack") is False  # refused is False, never a direct send


def test_add_writes_the_ledger_before_the_registry(tmp_path, monkeypatch):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    real = C._atomic_write

    def boom(path, text):
        if path.name == "coordinators.json":
            raise OSError("disk full")
        return real(path, text)

    monkeypatch.setattr(C, "_atomic_write", boom)
    with pytest.raises(OSError):
        run(tmp_path, "add", "grok", "--vendor", "grok", "--quote", "add grok")
    assert any(e["kind"] == "appoint" and e["subject"] == "grok" for e in ledger(tmp_path))


def test_add_refuses_a_territory_already_held(tmp_path):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "add", "grok", "--vendor", "grok", "--territories", "agents",
               "--quote", "add grok") == 2
    assert not any(c["id"] == "grok" for c in registry(tmp_path)["coordinators"])


def test_a_lead_transfer_notifies_the_former_lead_and_the_new_lead(tmp_path):
    tmux, log = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "lead", "codex", "--quote", "codex leads", "--tmux-bin", str(tmux)) == 0
    sends = log.read_text().splitlines()
    assert len(sends) == 2 and any("s-claude" in s for s in sends) and any("s-codex" in s for s in sends)


def test_take_back_refuses_nothing_to_take_and_a_lead_holder(tmp_path):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    # codex holds nothing
    assert run(tmp_path, "take-back", "codex", "--quote", "q", "--tmux-bin", str(tmux)) == 2
    # codex holds all AND is lead: take-back refuses and says to move the lead first
    assert run(tmp_path, "give", "codex", "all", "--quote", "q", "--tmux-bin", str(tmux)) == 0
    assert run(tmp_path, "lead", "codex", "--quote", "q", "--tmux-bin", str(tmux)) == 0
    assert run(tmp_path, "take-back", "codex", "--quote", "q", "--tmux-bin", str(tmux)) == 2
    # move the lead back, then take-back returns every territory
    assert run(tmp_path, "lead", "claude-lead", "--quote", "q", "--tmux-bin", str(tmux)) == 0
    assert run(tmp_path, "take-back", "codex", "--quote", "q", "--tmux-bin", str(tmux)) == 0
    by = {c["id"]: c for c in registry(tmp_path)["coordinators"]}
    assert set(by["claude-lead"]["territories"]) == {"agents", "ops", "release", "ui"}
    assert by["codex"]["territories"] == []


# ── final acceptance: same-second transfers, lock-free dry runs, write-ahead timeout alerts ─────────────


def _fixture_dir(root: Path) -> Path:
    return root / "data" / "coordination" / "coordinator"


HAND_WRITTEN_SEED = {
    "schema": "CoordinatorRegistry@v1",
    "lead": "codex",
    "coordinators": [
        {"id": "codex", "vendor": "codex", "where": "tmux cx-openai (start: cxo)", "role": "lead",
         "territories": ["release", "agents", "ui", "ops"]},
        {"id": "claude-lead", "vendor": "claude", "where": "Remote Control session", "role": "observer",
         "territories": []},
    ],
    "updated_at": "2026-11-02T15:59:25Z",
    "updated_by": "codex",
    "operator_quote": "Then give Codex everything. You will just be watching when I ask.",
    "note": "Interim hand-written registry.",
}


def _seed_hand_written(root: Path) -> Path:
    """The synthetic fixture that mirrors the hand-written seed (no live registry is read or written)."""
    d = _fixture_dir(root)
    d.mkdir(parents=True)
    (d / "coordinators.json").write_text(json.dumps(HAND_WRITTEN_SEED, indent=1), encoding="utf-8")
    return d


def test_two_same_second_transfers_keep_both_events_handoffs_and_pending_acks(tmp_path):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    frozen = "2026-11-02T15:00:00Z"  # both calls land in the same second
    assert run(tmp_path, "give", "codex", "agents", "--quote", "q1", "--tmux-bin", str(tmux),
               "--now", frozen) == 0
    assert run(tmp_path, "give", "codex", "ops", "--quote", "q2", "--tmux-bin", str(tmux),
               "--now", frozen) == 0
    reg = registry(tmp_path)
    pending = [p for p in reg["pending_acks"].values() if not p["acknowledged"]]
    assert sorted(p["kind"] for p in pending) == ["give", "give"]
    assert sorted(p["territories"][0] for p in pending) == ["agents", "ops"]
    assert len(reg["pending_acks"]) == 2  # neither overwrote the other
    tids = {p for e in ledger(tmp_path) if e["kind"] == "transfer_give" for p in [e["transfer_id"]]}
    assert len(tids) == 2
    snaps = list((_fixture_dir(tmp_path) / "handoffs").iterdir())
    assert sorted(p.name for p in snaps) == sorted(f"{tid}-operator-to-codex.md" for tid in tids)
    assert run(tmp_path, "ack", "codex", "--now", frozen) == 0
    assert [p for p in registry(tmp_path)["pending_acks"].values() if not p["acknowledged"]] == []


@pytest.mark.parametrize("verb", [
    ["add", "codex", "--vendor", "codex", "--quote", "q"],
    ["give", "codex", "release", "--quote", "q"],
    ["lead", "codex", "--quote", "q"],
    ["take-back", "codex", "--quote", "q"],
    ["ack", "codex"],
])
def test_dry_run_on_an_absent_root_creates_absolutely_nothing(tmp_path, verb):
    assert run(tmp_path, *verb, "--dry-run") in (0, 2)
    assert not (tmp_path / "data").exists()  # no lock, no notebook, no ledger, no handoff


def test_dry_run_add_on_an_absent_root_prints_its_plan_and_creates_nothing(tmp_path, capsys):
    assert run(tmp_path, "add", "codex", "--vendor", "codex", "--quote", "q", "--dry-run") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["entry"]["id"] == "codex"
    assert not (tmp_path / "data").exists()


def test_dry_run_preview_follows_the_changed_registry(tmp_path, capsys):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    capsys.readouterr()
    assert run(tmp_path, "give", "codex", "release", "--quote", "q", "--tmux-bin", str(tmux), "--dry-run") == 0
    assert json.loads(capsys.readouterr().out)["from"] == ["claude-lead"]  # who holds it now
    assert run(tmp_path, "give", "codex", "release", "--quote", "q", "--tmux-bin", str(tmux)) == 0
    capsys.readouterr()
    assert run(tmp_path, "give", "claude-lead", "release", "--quote", "q", "--tmux-bin", str(tmux),
               "--dry-run") == 0
    assert json.loads(capsys.readouterr().out)["from"] == ["codex"]  # the preview moved with the source


def test_the_timeout_attempt_is_durable_before_the_queue_is_reached(tmp_path, monkeypatch):
    seen: dict = {}

    def spy(subject, summary):
        kinds = [e["kind"] for e in ledger(tmp_path)]
        seen["attempts"] = kinds.count("ack_timeout_attempt")
        seen["order"] = kinds
        return True

    monkeypatch.setattr(C, "_operator_alert", spy)
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "codex", "agents", "--quote", "q", "--tmux-bin", str(tmux),
               "--now", "2026-11-02T15:00:00Z") == 0
    assert run(tmp_path, "timeouts", "--apply", "--now", "2026-11-02T15:16:00Z") == 0
    assert seen["attempts"] == 1  # the write-ahead event was already on disk when the queue was called
    kinds = [e["kind"] for e in ledger(tmp_path)]
    assert kinds.index("ack_timeout_attempt") < kinds.index("ack_timeout")
    attempt = [e for e in ledger(tmp_path) if e["kind"] == "ack_timeout_attempt"][0]
    assert attempt["attempt"] == 1 and attempt["subject"] == "codex" and attempt["transfer_id"]


def test_a_failed_enqueue_leaves_the_attempt_visible_and_retryable(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "_operator_alert", lambda s, m: False)
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "codex", "agents", "--quote", "q", "--tmux-bin", str(tmux),
               "--now", "2026-11-02T15:00:00Z") == 0
    assert run(tmp_path, "timeouts", "--apply", "--now", "2026-11-02T15:16:00Z") == 0
    kinds = [e["kind"] for e in ledger(tmp_path)]
    assert kinds.index("ack_timeout_attempt") < kinds.index("ack_alert_failed")
    assert list(registry(tmp_path)["pending_acks"].values())[0]["alerted"] is False


def test_the_import_fallback_fires_only_for_the_missing_lib_package(monkeypatch):
    fake = types.SimpleNamespace(queue_intent=lambda **kw: {"request_id": "x"})
    monkeypatch.setitem(sys.modules, "scripts.lib.host_comms_intents", fake)
    monkeypatch.setitem(sys.modules, "scripts.lib", types.ModuleType("scripts.lib"))
    monkeypatch.setitem(sys.modules, "scripts", types.ModuleType("scripts"))
    monkeypatch.setitem(sys.modules, "lib", None)  # import of `lib` is halted → ModuleNotFoundError(name="lib")
    assert C._queue_intent_fn() is fake.queue_intent

    bad = types.ModuleType("lib.host_comms_intents")  # importable parent, missing the name → ImportError
    monkeypatch.setitem(sys.modules, "lib", types.ModuleType("lib"))
    monkeypatch.setitem(sys.modules, "lib.host_comms_intents", bad)
    with pytest.raises(ImportError):
        C._queue_intent_fn()  # a parent ImportError is never answered by the scripts.lib fallback


def test_the_banner_reading_the_same_file_follows_every_ownership_change(tmp_path, capsys):
    tmux, _ = _tmux_that_logs(tmp_path)
    d = _seed_hand_written(tmp_path)
    reg_path = d / "coordinators.json"
    reg = json.loads(reg_path.read_text())
    assert C.banner_text(reg, d).startswith(
        "[COORDINATION] Lead: codex. Coordinators: codex=lead[release,agents,ui,ops]; claude-lead=observer[none].")
    # give-all: claude-lead takes every territory; the banner changes with no second file to edit
    assert run(tmp_path, "give", "claude-lead", "all", "--quote", "claude takes it",
               "--tmux-bin", str(tmux)) == 0
    reg = json.loads(reg_path.read_text())
    banner = C.banner_text(reg, d)
    assert "claude-lead=observer" in banner and "codex=lead[none]" in banner
    assert "ui,ops]" not in banner.split("codex=")[1].split(";")[0]
    assert registry(tmp_path)["lead"] == "codex"  # top-level lead untouched by a territory give
    assert run(tmp_path, "lead", "claude-lead", "--quote", "claude leads", "--tmux-bin", str(tmux)) == 0
    reg = json.loads(reg_path.read_text())
    assert reg["lead"] == "claude-lead"
    assert C.banner_text(reg, d).startswith("[COORDINATION] Lead: claude-lead.")
    # take-back of the lead holder is refused; move the lead first, then it returns everything
    assert run(tmp_path, "take-back", "claude-lead", "--quote", "q", "--tmux-bin", str(tmux)) == 2
    assert run(tmp_path, "lead", "codex", "--quote", "codex leads", "--tmux-bin", str(tmux)) == 0
    assert run(tmp_path, "take-back", "claude-lead", "--quote", "q", "--tmux-bin", str(tmux)) == 0
    reg = json.loads(reg_path.read_text())
    assert reg["lead"] == "codex"
    by = {c["id"]: c for c in reg["coordinators"]}
    assert by["claude-lead"]["territories"] == [] and set(by["codex"]["territories"]) == {
        "release", "agents", "ui", "ops"}


def test_the_banner_line_is_exactly_the_installed_format(tmp_path):
    """The installed coord_status.py prints this literal shape from the SAME registry: no second file to edit."""
    d = _fixture_dir(tmp_path)
    expected = (f"[COORDINATION] Lead: codex. Coordinators: codex=lead[release,agents,ui,ops]; "
                f"claude-lead=observer[none]. Report to the coordinator owning your work via {d}/inbox/<id>/ "
                f"(default: inbox/codex/). Only the lead talks to the operator. Board: {d}/BOARD.md "
                f"(updated 2026-11-02T15:59:25Z).")
    assert C.banner_text(HAND_WRITTEN_SEED, d) == expected


def test_reappointing_the_lead_as_a_member_is_refused(tmp_path):
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    before = registry(tmp_path)
    assert run(tmp_path, "appoint", "--id", "claude-lead", "--vendor", "claude", "--role", "member",
               "--territories", "release", "--quote", "q") == 2
    assert registry(tmp_path) == before  # refused, never silently left with no lead


# ── recovery 2026-11-03: the CLI cannot hand the lead over unguarded, forge an event, or lose a record ────────────


def test_a_handoff_dry_run_writes_nothing(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    assert run(tmp_path, "handoff", "--from", "claude-lead", "--to", "codex-a",
               "--quote", "let codex lead now", "--dry-run") == 0
    reg = registry(tmp_path)
    assert reg["lead"] == "claude-lead"
    assert {c["id"]: c["role"] for c in reg["coordinators"]} == {"claude-lead": "lead", "codex-a": "member"}
    handoffs = tmp_path / "data" / "coordination" / "coordinator" / "handoffs"
    assert not handoffs.exists() or not list(handoffs.iterdir())


def test_a_handoff_moves_the_top_level_lead_with_the_role(tmp_path):
    """The role moved but the registry's top-level lead did not, so every later mutation was refused as divergent."""
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    assert run(tmp_path, "handoff", "--from", "claude-lead", "--to", "codex-a", "--quote", "codex leads") == 0
    reg = registry(tmp_path)
    assert reg["lead"] == "codex-a"
    # coherence_error() would refuse this if the registry were divergent
    assert run(tmp_path, "assign", "pr:2492", "release") == 0



def test_standing_down_the_lead_does_not_lock_the_registry(tmp_path):
    """Stand-down of the lead used to clear the role, after which every mutator —
    including `coord lead` and `coord appoint` — failed 'registry is divergent (no lead)'.
    Recovery verbs must still run when the only problem is the absent lead.
    """
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    assert run(tmp_path, "stand-down", "--id", "claude-lead",
               "--quote", "lead stands down for the night") == 0
    reg = registry(tmp_path)
    assert reg["lead"] is None
    assert {c["id"]: (c["role"], c["status"]) for c in reg["coordinators"]}["claude-lead"] == ("member", "stood_down")
    # recovery: appoint a new lead (or transfer lead) must not be blocked by 'no lead'
    assert run(tmp_path, "lead", "codex-a", "--quote", "codex takes the lead") == 0
    assert registry(tmp_path)["lead"] == "codex-a"


def test_the_generic_event_cannot_forge_a_transfer_kind(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    for kind in ("transfer_give", "transfer_lead", "transfer_take-back", "transfer_notified"):
        assert run(tmp_path, "event", kind, "--subject", "claude-lead") == 2
    events = C.read_events(tmp_path)
    assert not any(str(e.get("kind", "")).startswith("transfer_") for e in events)


def test_stand_down_writes_the_ledger_before_the_registry(tmp_path, monkeypatch):
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    real = C._atomic_write

    def boom(path, text):
        if str(path).endswith("coordinators.json"):
            raise OSError("synthetic registry write failure")
        return real(path, text)

    monkeypatch.setattr(C, "_atomic_write", boom)
    with pytest.raises(OSError):
        run(tmp_path, "stand-down", "--id", "codex-a", "--quote", "stop agents")
    kinds = [str(e.get("kind")) for e in C.read_events(tmp_path)]
    assert "stand_down" in kinds


def test_the_generic_event_cannot_forge_a_check_outcome(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert run(tmp_path, "check", "request", "pr:2492", "--by", "claude-lead") == 0
    assert run(tmp_path, "event", "check_ok", "--subject", "pr:2492") == 2
    assert run(tmp_path, "event", "transfer", "--subject", "claude-lead") == 2
    # the real request is still pending: nothing forged a check_ok for it
    events = C.read_events(tmp_path)
    assert not any(str(e.get("kind")) == "check_ok" for e in events)


def test_appoint_writes_the_ledger_before_the_registry(tmp_path, monkeypatch):
    """A crash between the two writes must leave the grant auditable, not silently applied."""
    real = C._atomic_write

    def boom(path, text):
        if str(path).endswith("coordinators.json"):
            raise OSError("synthetic registry write failure")
        return real(path, text)

    monkeypatch.setattr(C, "_atomic_write", boom)
    with pytest.raises(OSError):
        appoint(tmp_path, "codex-b", "member", "agents")
    kinds = [str(e.get("kind")) for e in C.read_events(tmp_path)]
    assert "appoint" in kinds


def test_two_inbox_sends_in_one_second_do_not_overwrite_each_other(tmp_path, monkeypatch):
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    monkeypatch.setattr(C, "_stamp", lambda: "20261103T120000Z")
    assert run(tmp_path, "inbox", "send", "--to", "codex-a", "--from", "claude-lead", "--text", "first") == 0
    assert run(tmp_path, "inbox", "send", "--to", "codex-a", "--from", "claude-lead", "--text", "second") == 0
    box = tmp_path / "data" / "coordination" / "coordinator" / "inbox" / "codex-a"
    files = sorted(p for p in box.iterdir() if p.is_file() and p.name != "read")
    assert len(files) == 2
    bodies = " ".join(p.read_text() for p in files)
    assert "first" in bodies and "second" in bodies


def test_an_inbox_item_that_vanishes_before_the_move_does_not_crash(tmp_path, monkeypatch):
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    assert run(tmp_path, "inbox", "send", "--to", "codex-a", "--from", "claude-lead", "--text", "note") == 0
    real_replace = C.os.replace

    def gone(src, dst):
        raise FileNotFoundError("synthetic: another reader moved it first")

    monkeypatch.setattr(C.os, "replace", gone)
    try:
        assert run(tmp_path, "inbox", "read", "--id", "codex-a") == 0
    finally:
        monkeypatch.setattr(C.os, "replace", real_replace)


# ── D49 repair 2026-11-05: the codex-cloud BLOCK at a9668e01c (CX1, CX2, CX3) ─────────────────────────

BAD_REGISTRY = '{"schema": "CoordinatorRegistry@v1", "coordinators": ['


def test_appoint_refuses_a_territory_another_coordinator_holds(tmp_path):
    """CX1 @ a9668e01c: appointing both alpha and beta over release wrote a divergent registry."""
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert run(tmp_path, "add", "codex-a", "--vendor", "codex", "--quote", "add codex") == 0
    before = registry(tmp_path)
    assert run(tmp_path, "appoint", "--id", "codex-a", "--vendor", "codex", "--role", "member",
               "--territories", "release", "--quote", "q") == 2
    assert registry(tmp_path) == before
    # The registry stayed coherent: an assignment (and a self re-appointment) still works.
    assert run(tmp_path, "assign", "pr:2492", "release") == 0
    assert appoint(tmp_path, "claude-lead", "lead", "release", quote="re-affirm the holder") == 0


def test_appoint_still_accepts_a_territory_nobody_holds(tmp_path):
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    assert run(tmp_path, "assign", "pr:2492", "agents") == 0


@pytest.mark.parametrize("verb", [
    ["assign", "pr:1", "release"],
    ["appoint", "--id", "codex-a", "--vendor", "codex", "--role", "member",
     "--territories", "agents", "--quote", "q"],
    ["give", "codex-a", "release", "--quote", "q"],
    ["lead", "codex-a", "--quote", "q"],
    ["take-back", "codex-a", "--quote", "q"],
    ["add", "codex-b", "--vendor", "codex", "--quote", "q"],
    ["ack", "codex-a"],
    ["timeouts", "--apply"],
    ["handoff", "--from", "codex-a", "--to", "codex-b", "--quote", "q"],
    ["heartbeat", "--id", "codex-a"],
    ["stand-down", "--id", "codex-a", "--quote", "q"],
    ["event", "note", "--subject", "x"],
    ["check", "request", "pr:1", "--by", "codex-a"],
    ["board"],
    ["snapshot", "--tmux-bin", "/nonexistent/tmux"],
    ["inbox", "send", "--to", "codex-a", "--from", "x", "--text", "hi"],
    ["inbox", "read", "--id", "codex-a"],
])
def test_a_malformed_registry_refuses_every_mutation_and_keeps_its_bytes(tmp_path, verb):
    """CX2 @ a9668e01c: malformed JSON used to read as a new store and be overwritten."""
    d = _fixture_dir(tmp_path)
    d.mkdir(parents=True)
    p = d / "coordinators.json"
    p.write_text(BAD_REGISTRY, encoding="utf-8")
    assert run(tmp_path, *verb) == 2
    assert p.read_text(encoding="utf-8") == BAD_REGISTRY  # bytes preserved, nothing reset


def test_a_registry_that_is_not_a_json_object_is_refused(tmp_path):
    d = _fixture_dir(tmp_path)
    d.mkdir(parents=True)
    p = d / "coordinators.json"
    p.write_text("[]", encoding="utf-8")
    assert run(tmp_path, "assign", "pr:1", "release") == 2
    assert p.read_text(encoding="utf-8") == "[]"


def test_an_absent_registry_still_bootstraps(tmp_path):
    """The refusal is for a present-but-undecodable file, never for a new store."""
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert registry(tmp_path)["lead"] == "claude-lead"


def test_status_distinguishes_an_unreadable_registry_from_an_absent_one(tmp_path, capsys):
    assert run(tmp_path, "status", "--json") == 0
    absent = json.loads(capsys.readouterr().out)
    assert absent["registry_present"] is False and absent["registry_error"] is None
    d = _fixture_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "coordinators.json").write_text(BAD_REGISTRY, encoding="utf-8")
    assert run(tmp_path, "status", "--json") == 0
    present = json.loads(capsys.readouterr().out)
    assert present["registry_present"] is True and "cannot be decoded" in present["registry_error"]


def test_a_handoff_to_the_same_coordinator_is_refused(tmp_path):
    """CX3 @ a9668e01c: --from X --to X cleared X's own territories and returned 0."""
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    before, events_before = registry(tmp_path), ledger(tmp_path)
    assert run(tmp_path, "handoff", "--from", "claude-lead", "--to", "claude-lead",
               "--quote", "q") == 2
    assert run(tmp_path, "handoff", "--from", "claude-lead", "--to", "claude-lead",
               "--quote", "q", "--dry-run") == 2
    assert registry(tmp_path) == before and ledger(tmp_path) == events_before
    assert registry(tmp_path)["coordinators"][0]["territories"] == ["release"]
    handoffs = _fixture_dir(tmp_path) / "handoffs"
    assert not handoffs.exists() or not list(handoffs.iterdir())


# ── D52 round 1 2026-11-05: the codex-cloud BLOCK at 911fbac5b (CX4 dry-run, CX5 torn tail, CX7 view) ──


def _store_bytes(root: Path) -> tuple:
    d = _fixture_dir(root)

    def read(p: Path):
        try:
            return p.read_bytes()
        except OSError:
            return None

    return (read(d / "coordinators.json"), read(d / "ledger.jsonl"), read(d / "BOARD.md"))


def _store_files(root: Path) -> list[str]:
    base = root / "data"
    return sorted(str(p) for p in base.rglob("*")) if base.exists() else []


def test_a_torn_ledger_tail_does_not_swallow_the_next_event(tmp_path):
    """CX5 @ 911fbac5b: append glued the next event onto a crash-left fragment, so read_events lost both."""
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    led = _fixture_dir(tmp_path) / "ledger.jsonl"
    torn = b'{"schema":"CoordinatorEvent@v1","ts":"2026-11-05T'
    with led.open("ab") as f:
        f.write(torn)
    assert run(tmp_path, "check", "request", "pr:2492", "--by", "claude-lead") == 0
    raw = led.read_bytes()
    assert torn + b"\n" in raw  # damaged bytes preserved and terminated, never rewritten
    events = C.read_events(tmp_path)
    assert [e.get("kind") for e in C.pending_checks(events)] == ["check_request"]
    assert any(e.get("subject") == "pr:2492" and e.get("kind") == "check_request" for e in events)


def test_appoint_dry_run_on_an_absent_root_creates_absolutely_nothing(tmp_path, capsys):
    assert run(tmp_path, "appoint", "--id", "codex-a", "--vendor", "codex", "--role", "member",
               "--territories", "agents", "--quote", "q", "--dry-run") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "CoordinatorAppointPlan@v1" and out["dry_run"] is True
    assert out["entry"]["id"] == "codex-a"
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("verb,schema", [
    (["heartbeat", "--id", "claude-lead"], "CoordinatorHeartbeatPlan@v1"),
    (["assign", "pr:2492", "release"], "CoordinatorAssignPlan@v1"),
    (["event", "note", "--subject", "pr:2492"], "CoordinatorEventPlan@v1"),
    (["check", "request", "pr:2492", "--by", "claude-lead"], "CoordinatorCheckPlan@v1"),
    (["board"], "CoordinatorBoardPlan@v1"),
    (["snapshot", "--tmux-bin", "/nonexistent/tmux"], "CoordinatorSnapshotPlan@v1"),
    (["inbox", "send", "--to", "codex-a", "--from", "claude-lead", "--text", "hi"],
     "CoordinatorInboxSendPlan@v1"),
])
def test_a_store_writer_dry_run_reports_its_plan_and_writes_nothing(tmp_path, capsys, verb, schema):
    """CX4 @ 911fbac5b: durable writers had no side-effect-free preview."""
    assert appoint(tmp_path, "claude-lead", "lead", "release") == 0
    assert run(tmp_path, "add", "codex-a", "--vendor", "codex", "--quote", "q") == 0
    before, files = _store_bytes(tmp_path), _store_files(tmp_path)
    capsys.readouterr()
    assert run(tmp_path, *verb, "--dry-run") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == schema and out["dry_run"] is True
    assert _store_bytes(tmp_path) == before and _store_files(tmp_path) == files


def test_inbox_read_dry_run_lists_without_moving(tmp_path, capsys):
    assert appoint(tmp_path, "codex-a", "member", "agents") == 0
    assert run(tmp_path, "inbox", "send", "--to", "codex-a", "--from", "claude-lead", "--text", "hold") == 0
    box = _fixture_dir(tmp_path) / "inbox" / "codex-a"
    before = sorted(p.name for p in box.iterdir() if p.is_file())
    capsys.readouterr()
    assert run(tmp_path, "inbox", "read", "--id", "codex-a", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "hold" in out and "dry run" in out
    assert sorted(p.name for p in box.iterdir() if p.is_file()) == before
    assert not (box / "read").exists()


def test_the_view_surfaces_an_unreadable_registry_instead_of_an_empty_one(tmp_path, monkeypatch):
    """CX7 @ 911fbac5b: an undecodable registry rendered as 'No coordinators appointed'."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    d = _fixture_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "coordinators.json").write_text(BAD_REGISTRY, encoding="utf-8")
    view = V.coordinators_view(tmp_path)
    assert view["registry_present"] is True and view["registry_unreadable"] is True
    assert "cannot be decoded" in view["registry_error"]
    assert view["coordinators"] == [] and view["divergent"] is True
    absent = V.coordinators_view(tmp_path / "no-store")
    assert absent["registry_present"] is False and absent["registry_error"] is None
    assert absent["registry_unreadable"] is False and absent["divergent"] is False
