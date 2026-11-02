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
