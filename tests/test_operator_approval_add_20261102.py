"""`claim --add ... --operator-approval <url>` must persist the URL, or refuse before it mutates.

Coordinator review of #2474 at 7160aef1b, 2026-11-02: the real CLI exited 0 and added the path,
yet the approval appeared in neither the claim note nor the worklog — `cmd_claim` computed the
note and the `--add` arm dropped it. The eight existing tests passed and could not see it, because
they exercised `operator_approval` in isolation and never ran the CLI against a store.

These tests run the **real CLI** against an isolated claims dir and read the **real store**.

The producer modules are loaded by file path and registered in `sys.modules` (AGENTS.md §7): the
repository carries both `lib.x` and `scripts.lib.x`, so a module-name import can hand a test a
second, shadow copy of the code under test.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts" / "agent_claim.py"

GOOD = "https://github.com/PatsKiller/tardeai/pull/2474#issuecomment-1234567890"
OTHER = "https://github.com/PatsKiller/tardeai/pull/2474#issuecomment-9999999999"


def _load(name: str, rel: str):
    """Load a module by file path and register it in sys.modules (AGENTS.md §7)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


BOARD = _load("review_claim_board_20261102", "scripts/lib/agent_claim_board.py")


def cli(tmp_path: Path, *args: str, session: str = "sess-under-test") -> subprocess.CompletedProcess:
    env = dict(os.environ, AGENT_CLAIM_SESSION=session)
    return subprocess.run(
        [sys.executable, str(CLI), "--claims-dir", str(tmp_path), "--no-gh", *args],
        cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=120,
    )


def stored(tmp_path: Path, claim_id: str) -> dict:
    return json.loads((tmp_path / f"{claim_id}.json").read_text(encoding="utf-8"))


def new_claim(tmp_path: Path, *extra: str) -> tuple[subprocess.CompletedProcess, str]:
    r = cli(tmp_path, "claim", "--task", "review fixture", "--paths", "config/n8n_run_allowlist.json", *extra)
    assert r.returncode == 0, r.stderr
    claim_id = r.stdout.strip().split()[0]
    return r, claim_id


# ------------------------------------------------------------------ the regression itself
def test_add_persists_the_operator_approval_in_the_store(tmp_path):
    _, cid = new_claim(tmp_path)
    r = cli(tmp_path, "claim", "--add", "config/llm_process_registry.json", "--operator-approval", GOOD)
    assert r.returncode == 0, r.stderr
    doc = stored(tmp_path, cid)
    assert "config/llm_process_registry.json" in doc["paths"]
    assert doc.get("note", "").startswith("Operator-approval: " + GOOD), doc.get("note")


def test_new_claim_persists_the_operator_approval_in_the_store(tmp_path):
    _, cid = new_claim(tmp_path, "--operator-approval", GOOD)
    assert stored(tmp_path, cid).get("note", "").startswith("Operator-approval: " + GOOD)


def test_extension_keeps_an_existing_note_and_prepends_the_approval(tmp_path):
    _, cid = new_claim(tmp_path, "--note", "prior context")
    before = stored(tmp_path, cid)
    assert before.get("note") == "prior context"
    r = cli(tmp_path, "claim", "--add", "config/llm_consumption.json", "--operator-approval", GOOD)
    assert r.returncode == 0, r.stderr
    note = stored(tmp_path, cid).get("note", "")
    assert note.startswith("Operator-approval: " + GOOD) and "prior context" in note


# ------------------------------------------------------------- refusal preserves state exactly
def test_an_invalid_reference_is_refused_before_any_path_is_added(tmp_path):
    _, cid = new_claim(tmp_path)
    before = stored(tmp_path, cid)
    r = cli(tmp_path, "claim", "--add", "config/llm_process_registry.json", "--operator-approval", "free text")
    assert r.returncode == 2
    assert "not a GitHub comment URL" in r.stderr
    assert stored(tmp_path, cid) == before, "a refused approval must not touch the claim"


def test_an_approval_for_another_repository_is_refused_before_any_path_is_added(tmp_path):
    _, cid = new_claim(tmp_path)
    before = stored(tmp_path, cid)
    r = cli(tmp_path, "claim", "--add", "config/llm_process_registry.json",
            "--operator-approval", "https://github.com/other/repo/pull/1#issuecomment-2")
    assert r.returncode == 2
    assert stored(tmp_path, cid) == before


def test_a_foreign_session_cannot_extend_or_write_an_approval(tmp_path):
    _, cid = new_claim(tmp_path)
    before = stored(tmp_path, cid)
    r = cli(tmp_path, "claim", "--claim", cid, "--add", "config/llm_process_registry.json",
            "--operator-approval", OTHER, session="someone-else")
    assert r.returncode in (1, 2), r.stdout + r.stderr
    assert stored(tmp_path, cid) == before, "another session must not change this claim"


# ------------------------------------------------------------------- the store, directly
def test_the_store_extend_writes_note_under_the_same_locked_call(tmp_path):
    board = BOARD.ClaimBoard(tmp_path)
    doc = board.claim(vendor="v", session="s1", agent=None, task="t", paths=["config/a.json"],
                      branch="wt/t", pr=None, note=None, worktree=str(ROOT), head_sha="0" * 40, policy={})
    assert doc.get("note") is None
    board.extend(doc["claim_id"], ["config/b.json"], session="s1", note="Operator-approval: " + GOOD)
    fresh = json.loads((tmp_path / f"{doc['claim_id']}.json").read_text(encoding="utf-8"))
    assert fresh["note"] == "Operator-approval: " + GOOD
    assert "config/b.json" in fresh["paths"]


def test_extend_still_accepts_no_note_and_leaves_one_untouched(tmp_path):
    board = BOARD.ClaimBoard(tmp_path)
    doc = board.claim(vendor="v", session="s1", agent=None, task="t", paths=["config/a.json"],
                      branch="wt/t", pr=None, note="kept", worktree=str(ROOT), head_sha="0" * 40, policy={})
    board.extend(doc["claim_id"], ["config/c.json"], session="s1")
    fresh = json.loads((tmp_path / f"{doc['claim_id']}.json").read_text(encoding="utf-8"))
    assert fresh["note"] == "kept" and "config/c.json" in fresh["paths"]
