"""The downsampler must not delete unless asked, and must keep every daily close.

HONEST LIMIT, STATED UP FRONT
-----------------------------
There is no database in CI, so these are STRUCTURAL assertions over the source:
dry-run is the default, no DELETE can run outside the --apply path, and the
keep-query is shaped so every (symbol, day) retains its closing quote. That is a
weaker claim than "the right rows survived a real run", and it is labelled as
such rather than dressed up as end-to-end.

The live proof is the dry run quoted in the PR, which reports the plan against
the real 34.2M-row table without touching it.

WHY THE SHAPE MATTERS
---------------------
Two consumers read this table and BOTH want one row per symbol per day:

    sector_rs_daily.py:46    DISTINCT ON (upper(symbol), fetched_at::date)
                             ORDER BY ..., fetched_at DESC   -> the day's LAST quote
    rotation_ladders.py:121  DISTINCT ON (symbol) ... ORDER BY fetched_at ASC
                             -> earliest DAILY CLOSE in a 21/63/126+7 day window

Keeping the last row per (symbol, day) satisfies both. Dropping to 7 days --
which I recommended before reading rotation_ladders -- would have broken all
three momentum windows.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "scripts" / "market_quotes_downsample.py"


@pytest.fixture
def source() -> str:
    if not TARGET.is_file():
        pytest.skip("downsampler not present in this tree")
    return TARGET.read_text(encoding="utf-8")


def test_dry_run_is_the_default(source: str) -> None:
    """--apply must be opt-in. A destructive default is how data vanishes."""
    tree = ast.parse(source)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = getattr(node.func, "attr", None)
        if fn != "add_argument":
            continue
        args = [a.value for a in node.args if isinstance(a, ast.Constant)]
        if "--apply" in args:
            found = True
            kw = {k.arg: getattr(k.value, "value", None) for k in node.keywords}
            assert kw.get("action") == "store_true", "--apply must be a flag, not a value"
    assert found, "no --apply flag exists at all"
    assert "if not a.apply:" in source, "the dry-run branch must return before any delete"


def test_no_delete_outside_the_apply_path(source: str) -> None:
    """Every DELETE must live in the function the --apply branch guards.

    AGENTS §0 rule 6: never delete. This script is the exception the operator
    asked for, so the exception must be narrow and obvious.
    """
    tree = ast.parse(source)
    deleting_funcs = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "DELETE FROM" in node.value.upper():
                    deleting_funcs.add(fn.name)
    assert deleting_funcs == {"_delete_batches"}, (
        f"DELETE appears outside _delete_batches: {sorted(deleting_funcs)}"
    )


def test_every_symbol_day_keeps_its_close(source: str) -> None:
    """The keep-set must be DISTINCT ON (symbol, date) ordered by fetched_at DESC.

    DESC is load-bearing: ASC would keep the day's FIRST quote, and
    sector_rs_daily explicitly reads the last. Getting this backwards would
    silently shift every close by a full session.
    """
    assert "DISTINCT ON (upper(symbol), fetched_at::date)" in source
    assert "ORDER BY upper(symbol), fetched_at::date, fetched_at DESC" in source, (
        "the keep-query must take the day's LAST quote, not its first"
    )


def test_deletes_are_batched(source: str) -> None:
    """A 34M-row table must never be locked in one transaction."""
    assert "LIMIT %s" in source, "the delete is unbounded"
    assert "conn.commit()" in source, "no per-batch commit"


def test_the_seven_day_trap_is_documented(source: str) -> None:
    """Guard the correction, not just the code.

    I recommended a 7-day retention cut before reading rotation_ladders, which
    reads 21/63/126-day lookbacks out of this table. Anyone revisiting this must
    meet that fact before they touch the window.
    """
    assert "rotation_ladders" in source
    assert "126" in source, "the 6-month lookback must be named"


def test_the_detector_can_fail() -> None:
    """Positive control: the DELETE-location check must reject a bad layout."""
    bad = (
        "def main():\n"
        "    cur.execute('DELETE FROM market_quotes WHERE 1=1')\n"
    )
    tree = ast.parse(bad)
    offenders = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        for node in ast.walk(fn)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "DELETE FROM" in node.value.upper()
    }
    assert offenders == {"main"}, f"detector missed an unguarded delete: {offenders}"
