"""No test in the CIO/cash/portfolio suites may assert something unfalsifiable.

A green test that cannot fail is worse than no test: it occupies the slot where
a real check would go and reports success forever. Three were found on
2026-08-29, each guarding something that mattered:

  * `test_cio_whatsapp_p4` ended an assertion with `or True` on a
    `dry_run=False` send path — it passed even if a WhatsApp message had
    actually gone out, which is the one thing it existed to prevent.
  * two `test_zero_provider_calls` bodies were `assert True` under docstrings
    claiming the suite imports no provider/LLM/Telegram module.
  * a loader test read `cio_investment_product.collect_cash`, which does not
    exist, so `src` was `""` and a trailing `or True` carried it.

An AST guard already existed and is correct — but it scanned exactly two
source files and never the `tests/` tree, which is why all four survived.
This closes that gap.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

# The suites this closeout covers. Kept explicit rather than repo-wide so the
# guard is enforceable today instead of aspirational.
SCOPES = ("cash", "loader", "cio", "holdings", "portfolio", "research", "wave3",
          "secrets", "corpus", "seasonality")

# `assert True` inside these is a deliberate no-op marker, not a claim.
ALLOWLIST: dict[str, set[int]] = {}


def _in_scope(p: Path) -> bool:
    n = p.name.lower()
    return n.startswith("test_") and any(k in n for k in SCOPES)


def _files() -> list[Path]:
    return sorted(p for p in TESTS.glob("test_*.py") if _in_scope(p))


def test_scope_is_not_empty():
    assert len(_files()) > 40, "scope collapsed; the guard would pass vacuously"


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_no_or_true_in_assertions(path: Path):
    """`assert X or True` is `assert True` wearing a disguise."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.BoolOp) and isinstance(sub.op, ast.Or):
                for v in sub.values:
                    if isinstance(v, ast.Constant) and v.value is True:
                        hits.append(node.lineno)
    allowed = ALLOWLIST.get(path.name, set())
    hits = [h for h in hits if h not in allowed]
    assert not hits, f"{path.name}: `or True` in assertion at lines {hits}"


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_no_unfalsifiable_constant_assertions(path: Path):
    """`assert True` / `assert 1` / `assert "x"` can never fail."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        t = node.test
        if isinstance(t, ast.Constant) and bool(t.value) is True:
            hits.append(node.lineno)
    allowed = ALLOWLIST.get(path.name, set())
    hits = [h for h in hits if h not in allowed]
    assert not hits, (
        f"{path.name}: unfalsifiable constant assertion at lines {hits} — "
        "assert the claim the docstring makes, or delete the test")


def test_the_guard_catches_a_planted_example(tmp_path):
    """Negative control: the guard must actually fire."""
    bad = tmp_path / "test_cash_planted.py"
    bad.write_text("def test_x():\n    assert 1 == 2 or True\n", encoding="utf-8")
    tree = ast.parse(bad.read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.BoolOp) and isinstance(sub.op, ast.Or):
                    for v in sub.values:
                        if isinstance(v, ast.Constant) and v.value is True:
                            found = True
    assert found, "the or-True detector does not detect or True"


def test_existing_source_guard_still_covers_its_two_files():
    """The pre-existing AST guard is correct — it was just narrowly scoped.

    Kept passing here so this file complements it rather than replacing it.
    """
    for rel in ("scripts/run_cio_acceptance.py", "scripts/lib/cio_acceptance_v4.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                for v in node.values:
                    assert not (isinstance(v, ast.Constant) and v.value is True), rel
