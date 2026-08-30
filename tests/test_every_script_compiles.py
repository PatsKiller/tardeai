"""Every script must COMPILE, not merely parse.

On 2026-08-30 `cio_event_lifecycle_census.py` spent 10 hours unable to run:
commit aa21559c ("declare NO_CONSUMER_REASON on diligence census CLIs") inserted
a module-level assignment at line 1, above the shebang and docstring, which put
a statement before `from __future__ import annotations` — a SyntaxError.

Two scoreboard metrics derived from that script were presented as current state
during the window, and at least eight diligence documents were published in it.

WHY A PARSE SWEEP MISSED IT. `ast.parse()` does NOT enforce `__future__`
placement; that rule is applied at COMPILE time. A gate built on ast.parse
passes files Python refuses to import — the documented-versus-runtime gap in
miniature. This test uses compile().
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Known-unfixable or intentionally non-Python-3 files go here WITH a reason.
# Empty is the correct state.
COMPILE_EXEMPT: dict[str, str] = {}


def _python_files():
    for sub in ("scripts", "scripts/lib"):
        for p in sorted((ROOT / sub).glob("*.py")):
            yield p


def test_every_script_compiles():
    broken = []
    for p in _python_files():
        rel = str(p.relative_to(ROOT))
        if rel in COMPILE_EXEMPT:
            continue
        try:
            compile(p.read_text(encoding="utf-8", errors="replace"), rel, "exec")
        except SyntaxError as e:
            broken.append(f"{rel}: {e.msg} (line {e.lineno})")
    assert not broken, "scripts that cannot be imported:\n  " + "\n  ".join(broken)


def test_the_census_specifically_compiles():
    """The file that was unrunnable for 10 hours while its numbers were quoted."""
    p = ROOT / "scripts" / "cio_event_lifecycle_census.py"
    compile(p.read_text(encoding="utf-8"), str(p), "exec")


def test_no_statement_precedes_a_future_import():
    """The exact shape of the break, named directly.

    A file may declare NO_CONSUMER_REASON. It may not declare it ABOVE
    `from __future__`, which is what turns a declaration into an outage.

    Uses ast on the module body — a line-level `=` heuristic false-positives on
    every docstring containing an equals sign, which is most of them.
    """
    import ast
    offenders = []
    for p in _python_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        if "from __future__" not in text:
            continue
        try:
            tree = ast.parse(text)          # parses even when compile() refuses
        except SyntaxError:
            continue                        # covered by test_every_script_compiles
        for node in tree.body:
            if (isinstance(node, ast.ImportFrom)
                    and node.module == "__future__"):
                break
            if isinstance(node, ast.Expr) and isinstance(
                    getattr(node, "value", None), ast.Constant) and isinstance(
                    node.value.value, str):
                continue                    # module docstring is allowed
            offenders.append(
                f"{p.relative_to(ROOT)}: {type(node).__name__} at line "
                f"{node.lineno} precedes the __future__ import")
            break
    assert not offenders, "\n  ".join(offenders)


def test_no_file_starts_with_a_bom():
    """`atm_position_reconciler.py` carried U+FEFF at line 1 and would not compile."""
    bad = [str(p.relative_to(ROOT)) for p in _python_files()
           if p.read_bytes().startswith(b"\xef\xbb\xbf")]
    assert not bad, f"UTF-8 BOM breaks compilation: {bad}"


def test_the_exempt_list_is_empty():
    """Every exemption is a script nobody can run. Keep it at zero."""
    assert COMPILE_EXEMPT == {}, f"unrunnable scripts tolerated: {COMPILE_EXEMPT}"
