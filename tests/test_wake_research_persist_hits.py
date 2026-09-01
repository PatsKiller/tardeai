"""WakeResearchPersist@v1 retains research hits across idle overwrites.

Acceptance (no live cron, no production entrypoint):
  * idle write  → current updates, hits unchanged
  * hit write   → current updates, hits += 1
  * 21 hits     → 20 remain (oldest drop)
  * legacy load → no throw, hits=[]
  * mutation: bare write_text of a current-only document → test red
  * strip comments before any "does not overwrite" scan

M5 stays CANDIDATE. Does not invoke cio_wake_dispatch_entrypoint.py live.
Does not change decide_after_load / next_eligible_at math.
"""
from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

import pytest

from scripts.lib.wake_research_persist import (
    HITS_CAP,
    SCHEMA,
    hit_from_cycle,
    is_hit,
    load_document,
    write_cycle,
)

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "cio_wake_dispatch_entrypoint.py"
HELPER = ROOT / "scripts" / "lib" / "wake_research_persist.py"


def _idle_cycle(*, as_of: str = "2026-09-01T19:00:00+00:00") -> dict:
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "as_of": as_of,
        "unattended": True,
        "entrypoint": "cron: */5 * * * * cio_wake_dispatch_entrypoint.py",
        "dispatched": 2,
        "research_called": 0,
        "persisted": 0,
        "cognition_noop": 0,
        "no_record": 0,
        "research": [],
        "persist": [
            {"subject_key": None, "persisted": False, "reason": "no_subject"},
            {"subject_key": None, "persisted": False, "reason": "no_subject"},
        ],
    }


def _hit_cycle(
    *,
    as_of: str = "2026-09-01T17:35:00+00:00",
    research_called: int = 3,
    persisted: int = 1,
    decision: str = "flash",
    reason: str = "free_sources_exhausted_first_pass",
    subject: str = "EXIT:WLDS",
) -> dict:
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "as_of": as_of,
        "unattended": True,
        "entrypoint": "cron: */5 * * * * cio_wake_dispatch_entrypoint.py",
        "dispatched": 4,
        "research_called": research_called,
        "persisted": persisted,
        "cognition_noop": 2,
        "no_record": 0,
        "research": [
            {
                "subject_key": subject,
                "decision": decision,
                "reason": reason,
                "decide_called": True,
                "record_loaded": True,
            }
        ],
        "persist": [
            {
                "subject_key": subject,
                "persisted": bool(persisted),
                "reason": "persisted" if persisted else "cognition_noop",
                "changed": ["next_eligible_at"] if persisted else [],
            }
        ],
    }


# ── unit: is_hit ──────────────────────────────────────────────────────


def test_is_hit_research_called():
    assert is_hit(_hit_cycle(research_called=1, persisted=0))


def test_is_hit_persisted():
    c = _idle_cycle()
    c["persisted"] = 1
    c["research"] = [{"subject_key": "X", "decision": "skip",
                      "reason": "cadence_not_due"}]
    assert is_hit(c)


def test_is_hit_non_idle_decision():
    c = _idle_cycle()
    c["research"] = [{"subject_key": "X", "decision": "flash",
                      "reason": "free_sources_exhausted_first_pass"}]
    # research_called still 0 — decision alone qualifies
    assert is_hit(c)


def test_idle_skip_cadence_only_is_not_hit():
    c = _idle_cycle()
    c["research_called"] = 0
    c["persisted"] = 0
    c["research"] = [
        {"subject_key": "EXIT:WLDS", "decision": "skip",
         "reason": "cadence_not_due"},
        {"subject_key": "EXIT:WLDS", "decision": "skip",
         "reason": "cadence_not_due"},
    ]
    assert not is_hit(c)


def test_empty_idle_is_not_hit():
    assert not is_hit(_idle_cycle())


# ── acceptance: write behaviour ───────────────────────────────────────


def test_idle_write_updates_current_hits_unchanged(tmp_path: Path):
    p = tmp_path / "wake_research_persist.json"
    hit = _hit_cycle(as_of="2026-09-01T17:35:00+00:00")
    write_cycle(p, hit)
    before = load_document(p)
    assert len(before["hits"]) == 1

    idle = _idle_cycle(as_of="2026-09-01T19:20:00+00:00")
    write_cycle(p, idle)
    after = load_document(p)

    assert after["current"]["as_of"] == "2026-09-01T19:20:00+00:00"
    assert after["current"]["research_called"] == 0
    assert len(after["hits"]) == 1
    assert after["hits"][0]["as_of"] == "2026-09-01T17:35:00+00:00"
    assert after["hits"][0]["research_called"] == 3
    assert after["hits"][0]["persisted"] == 1
    assert after["hits"][0]["subjects"] == ["EXIT:WLDS"]


def test_hit_write_appends(tmp_path: Path):
    p = tmp_path / "wake_research_persist.json"
    write_cycle(p, _hit_cycle(as_of="2026-09-01T17:35:00+00:00"))
    write_cycle(p, _hit_cycle(as_of="2026-09-01T18:00:00+00:00",
                              subject="EXIT:OTHER", decision="flash"))
    doc = load_document(p)
    assert doc["current"]["as_of"] == "2026-09-01T18:00:00+00:00"
    assert len(doc["hits"]) == 2
    assert doc["hits"][1]["subjects"] == ["EXIT:OTHER"]


def test_hits_cap_twenty_oldest_drop(tmp_path: Path):
    p = tmp_path / "wake_research_persist.json"
    for i in range(21):
        write_cycle(
            p,
            _hit_cycle(
                as_of=f"2026-09-01T12:{i:02d}:00+00:00",
                subject=f"SYM:{i}",
            ),
        )
    doc = load_document(p)
    assert len(doc["hits"]) == HITS_CAP == 20
    assert doc["hits"][0]["subjects"] == ["SYM:1"]   # SYM:0 dropped
    assert doc["hits"][-1]["subjects"] == ["SYM:20"]


def test_legacy_load_no_throw_hits_empty(tmp_path: Path):
    p = tmp_path / "wake_research_persist.json"
    legacy = _idle_cycle(as_of="2026-09-01T19:19:57+00:00")
    # Legacy shape: last-cycle-only, no current/hits envelope.
    p.write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")
    doc = load_document(p)
    assert doc["schema"] == SCHEMA
    assert doc["hits"] == []
    assert doc["current"]["as_of"] == "2026-09-01T19:19:57+00:00"
    assert doc["current"]["research_called"] == 0
    # A subsequent idle write must not throw and must keep hits=[].
    write_cycle(p, _idle_cycle(as_of="2026-09-01T19:25:00+00:00"))
    after = load_document(p)
    assert after["hits"] == []
    assert after["current"]["as_of"] == "2026-09-01T19:25:00+00:00"


def test_missing_file_load_is_empty():
    doc = load_document("/tmp/wake_research_persist_does_not_exist_xyz.json")
    assert doc == {"schema": SCHEMA, "current": None, "hits": []}


def test_hit_from_cycle_shape():
    h = hit_from_cycle(_hit_cycle())
    assert set(h) == {
        "as_of", "dispatched", "research_called", "persisted",
        "subjects", "decisions", "unattended",
    }
    assert "migration:deterministic" not in json.dumps(h)


def test_atomic_write_leaves_no_tmp(tmp_path: Path):
    p = tmp_path / "wake_research_persist.json"
    write_cycle(p, _hit_cycle())
    leftovers = list(tmp_path.glob(".wake_research_persist.json.*.tmp"))
    assert leftovers == []


# ── source / mutation guards ──────────────────────────────────────────


def _strip_python_comments(src: str) -> str:
    """Strip comments (and preserve strings) via tokenize — required before
    any 'does not overwrite' scan so a comment cannot fake the contract."""
    out = io.StringIO()
    tokens = tokenize.generate_tokens(io.StringIO(src).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            continue
        out.write(tok.string)
        # tokenize drops the trailing newline of NL/NEWLINE in .string for
        # some versions; re-emit NEWLINE explicitly when needed.
        if tok.type in (tokenize.NEWLINE, tokenize.NL) and not tok.string.endswith("\n"):
            out.write("\n")
    return out.getvalue()


def test_entrypoint_calls_write_cycle_not_bare_write_text():
    """Mutation: a bare write_text of a current-only document must go red.

    The live path must call write_cycle. A flat `_p.write_text(json.dumps({
    "schema": "WakeResearchPersist@v1", ...}))` without the hits envelope is
    the defect LITMUS_WAKE named.
    """
    src = ENTRYPOINT.read_text(encoding="utf-8")
    stripped = _strip_python_comments(src)
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "main")

    called = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                called.add(f.id)
            elif isinstance(f, ast.Attribute):
                called.add(f.attr)

    assert "write_cycle" in called, (
        "main() must call write_cycle so hits survive idle overwrites; "
        f"calls={sorted(called)}"
    )

    # After comment strip: no bare write_text targeting wake_research_persist
    # with an inline schema dump (the old last-cycle-only shape).
    assert "wake_research_persist.json" in stripped
    # The helper owns the write; entrypoint must not call write_text on that path.
    # Allow write_text elsewhere (record_consult artifact).
    # Fail if write_text appears in a window that also names WakeResearchPersist
    # schema dump without write_cycle.
    window = re.search(
        r"wake_research_persist\.json(.{0,800})",
        stripped,
        flags=re.DOTALL,
    )
    assert window, "entrypoint must still name wake_research_persist.json"
    chunk = window.group(0)
    assert "write_cycle" in chunk, (
        "within the wake_research_persist write site, write_cycle must appear"
    )
    assert "write_text" not in chunk, (
        "bare write_text at the wake_research_persist site is the overwrite defect; "
        "use write_cycle (atomic + hits)"
    )


def test_helper_does_not_stamp_migration_deterministic():
    """No writer stamp is emitted on hit/current rows (code, not docs)."""
    src = HELPER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Skip module/function docstrings (first stmt Expr string).
            continue
        if isinstance(node, ast.Constant) and node.value == "migration:deterministic":
            raise AssertionError("helper must not emit migration:deterministic")
    # Executable string literals used as dict keys/values:
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                for side in (k, v):
                    if isinstance(side, ast.Constant) and side.value == "migration:deterministic":
                        raise AssertionError("hit/current payload must not stamp migration")


def test_decide_after_load_math_untouched_by_this_module():
    """This PR must not import or call decide_after_load / touch eligibility."""
    src = HELPER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name)
            if node.asname:
                names.add(node.asname)
    assert "decide_after_load" not in names
    assert "next_eligible_at" not in names
