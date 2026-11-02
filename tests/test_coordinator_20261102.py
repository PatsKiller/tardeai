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
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import coordinator as C  # noqa: E402
from lib import coordination_view as V  # noqa: E402


def run(root: Path, *args: str) -> int:
    return C.main(["--state-root", str(root), *args])


def appoint(root: Path, cid: str = "claude-lead", role: str = "lead", terr: str = "release",
            session: str | None = None, vendor: str = "claude", quote: str = "appoint this one") -> int:
    return run(root, "appoint", "--id", cid, "--vendor", vendor, "--session", session or f"s-{cid}",
               "--territories", terr, "--role", role, "--quote", quote)


def registry(root: Path) -> dict:
    return json.loads((root / "data" / "coordination" / "coordinators.json").read_text())


def ledger(root: Path) -> list[dict]:
    p = root / "data" / "coordination" / "coordinator" / "ledger.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


# ── registry ──────────────────────────────────────────────────────────────────────────────────────────


def test_appoint_requires_the_operator_quote(tmp_path):
    assert run(tmp_path, "appoint", "--id", "x", "--vendor", "codex", "--territories", "agents",
               "--role", "member", "--quote", "   ") == 2
    assert not (tmp_path / "data" / "coordination" / "coordinators.json").exists()


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
    assert run(tmp_path, "stand-down", "--id", "codex-a") == 0
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
    (tmp_path / "data" / "coordination" / "coordinators.json").write_text(json.dumps(reg))
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
    assert run(tmp_path, "handoff", "--from", "claude-lead", "--to", "codex-a") == 0
    reg = registry(tmp_path)
    by = {c["id"]: c for c in reg["coordinators"]}
    assert by["codex-a"]["role"] == "lead" and by["claude-lead"]["role"] == "member"
    assert set(by["codex-a"]["territories"]) == {"agents", "release"} and by["claude-lead"]["territories"] == []
    snaps = list((tmp_path / "data" / "coordination" / "coordinator" / "handoffs").iterdir())
    assert len(snaps) == 1 and "Handoff claude-lead -> codex-a" in snaps[0].read_text()


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
    (tmp_path / "data" / "coordination" / "coordinators.json").write_text(json.dumps(reg))
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
    assert any("operator-to-codex-give" in p.name for p in snaps)


def test_ack_timeout_alerts_once_through_the_chokepoint(tmp_path, monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(C, "_operator_alert", lambda subject, summary: calls.append((subject, summary)) or True)
    tmux, _ = _tmux_that_logs(tmp_path)
    _seed_lead_and_codex(tmp_path, tmux)
    assert run(tmp_path, "give", "codex", "agents", "--quote", "q", "--tmux-bin", str(tmux),
               "--now", "2026-11-02T15:00:00Z") == 0
    assert run(tmp_path, "status", "--now", "2026-11-02T15:05:00Z") == 0  # inside the 15-minute window
    assert calls == []
    assert run(tmp_path, "status", "--now", "2026-11-02T15:16:00Z") == 0
    assert len(calls) == 1 and calls[0][0] == "codex"
    assert run(tmp_path, "status", "--now", "2026-11-02T16:30:00Z") == 0
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
