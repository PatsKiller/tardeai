"""2026-09-15: watch jobs must not sit idle in transaction holding row locks.

Measured 09-15 09:0x ET: hermes_subject_enhance.py sessions idle in transaction 80-114 s and the
directive staging drain holding RowExclusiveLock on watch_directives, while watch_directives_service
and the Finviz screener failed with "canceling statement due to lock timeout".
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fn_src(path: Path, name: str) -> str:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{name} not found in {path}")


def test_subject_enhance_connection_is_autocommit():
    body = _fn_src(ROOT / "scripts" / "hermes_subject_enhance.py", "_conn")
    assert "conn.autocommit = True" in body


def test_directive_service_commits_each_directive_not_once_per_run():
    body = _fn_src(ROOT / "scripts" / "watch_directives_service.py", "main")
    loop_start = body.index("for d in directives:")
    loop_end = body.index("_drain_curation_sources(c, cur, dry, report, evaluate, _resolve)")
    loop = body[loop_start:loop_end]
    touch = loop.index("_wd.touch_watch_directive_serviced(cur, did")
    assert "c.commit()" in loop[touch:], "commit must follow the per-directive serviced touch"


def test_directive_service_commits_orphan_drain_before_the_loop():
    body = _fn_src(ROOT / "scripts" / "watch_directives_service.py", "main")
    drain = body.index("_drain_orphan_staging(cur, dry, report)")
    select = body.index("SELECT * FROM watch_directives WHERE status='active'")
    assert "c.commit()" in body[drain:select]


def test_dry_run_never_commits_inside_the_loop():
    body = _fn_src(ROOT / "scripts" / "watch_directives_service.py", "main")
    loop = body[body.index("for d in directives:"):body.index("_drain_curation_sources(c, cur")]
    for i, line in enumerate(loop.splitlines()):
        if "c.commit()" in line:
            prior = "\n".join(loop.splitlines()[max(0, i - 8):i])
            assert "if not dry:" in prior
