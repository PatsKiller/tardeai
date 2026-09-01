"""The wake-hit consult must reach the artifact, not just the return value.

#839 made `decide_after_load` consult the retained `hits[]` and compute
`last_hit_at`, `last_hit_decision`, `last_hit_readable` and
`duplicate_research_suspected`. The entrypoint recorded none of them, so on
every `*/5` fire the consult ran and left no trace -- computed, and observed by
nothing. AGENTS.md 9.1: a verdict that reaches only a log file has not reached
the operator; this one did not reach even the log.

Asserted over the AST, never by grep. The change deliberately carries comments
naming all four fields, so a substring search would pass on the comments alone
-- exactly the code-vs-comment trap in AGENTS.md 7.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENTRYPOINT = ROOT / "scripts" / "cio_wake_dispatch_entrypoint.py"
CONSULT_FIELDS = (
    "last_hit_at",
    "last_hit_decision",
    "last_hit_readable",
    "duplicate_research_suspected",
)


def _tree() -> ast.Module:
    src = ENTRYPOINT.read_bytes()
    compile(src, str(ENTRYPOINT), "exec")   # compile(), never a bare ast.parse
    return ast.parse(src)


def _research_row_dicts() -> list[ast.Dict]:
    """Every dict literal appended to `research_rows`."""
    out: list[ast.Dict] = []
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "append"):
            continue
        if not (isinstance(f.value, ast.Name) and f.value.id == "research_rows"):
            continue
        if node.args and isinstance(node.args[0], ast.Dict):
            out.append(node.args[0])
    return out


def _keys(d: ast.Dict) -> dict:
    return {k.value: v for k, v in zip(d.keys, d.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def test_there_are_research_rows_to_inspect():
    rows = _research_row_dicts()
    assert len(rows) >= 2, (
        f"expected the success row and the error row, found {len(rows)}"
    )


@pytest.mark.parametrize("field", CONSULT_FIELDS)
def test_every_research_row_carries_the_consult_field(field):
    """Both the success row AND the error row.

    If only the success row carried them, a consult that raised would be
    indistinguishable from one that found nothing -- the same two-states-cannot-
    express-no-input defect the fields exist to avoid.
    """
    for i, row in enumerate(_research_row_dicts()):
        assert field in _keys(row), (
            f"research_rows dict #{i} does not carry {field!r}; the consult "
            f"would run and leave no trace on that path"
        )


@pytest.mark.parametrize("field", CONSULT_FIELDS)
def test_the_success_row_reads_the_field_from_the_decision(field):
    """Presence is not correctness: the value must come from `research`, the
    decide_after_load return, not be hardcoded or read from something else."""
    rows = _research_row_dicts()
    # the success row is the one that already sourced `decision` from research
    success = [r for r in rows
               if isinstance(_keys(r).get("decision"), ast.Call)]
    assert success, "no research_rows dict sources `decision` from a call"
    value = _keys(success[0])[field]
    assert isinstance(value, ast.Call), f"{field} must be read, not hardcoded"
    fn = value.func
    assert isinstance(fn, ast.Attribute) and fn.attr == "get", (
        f"{field} must be read via research.get(...)"
    )
    assert isinstance(fn.value, ast.Name) and fn.value.id == "research", (
        f"{field} must come from the decide_after_load return, not {ast.dump(fn.value)[:60]}"
    )
    assert value.args and isinstance(value.args[0], ast.Constant)
    assert value.args[0].value == field, (
        f"{field} must be read from the same key, not {value.args[0].value!r} "
        f"-- reading one field into another is how a surface reports the wrong number"
    )


def test_the_log_line_reports_the_consult():
    """The log is the only surface a running cron leaves between artifact
    overwrites. It must name the consult, not only the gate decision."""
    fmts = []
    for node in ast.walk(_tree()):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "info" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and "research_gate" in node.args[0].value):
            fmts.append(node.args[0].value)
    assert fmts, "the research_gate log line disappeared"
    fmt = fmts[0]
    for field in ("last_hit_at", "last_hit_readable", "duplicate_research_suspected"):
        assert field in fmt, f"research_gate log line does not report {field}"


def test_extra_row_keys_do_not_break_the_hits_retention(tmp_path):
    """#832 regression guard.

    `is_hit` and `hit_from_cycle` read specific keys off each research row.
    Adding keys must stay additive: a cycle that qualified as a hit before must
    still qualify, and the subjects/decisions it extracts must be unchanged.
    """
    from scripts.lib.wake_research_persist import hit_from_cycle, is_hit

    lean = {"research_called": 1, "persisted": 1, "as_of": "2026-09-01T17:00:00+00:00",
            "dispatched": 1, "unattended": True,
            "research": [{"subject_key": "EXIT:WLDS", "decision": "flash",
                          "reason": "x"}]}
    rich = {**lean, "research": [{**lean["research"][0],
                                  "last_hit_at": "2026-09-01T16:00:00+00:00",
                                  "last_hit_decision": "flash",
                                  "last_hit_readable": True,
                                  "duplicate_research_suspected": True}]}
    assert is_hit(lean) is True and is_hit(rich) is True
    a, b = hit_from_cycle(lean), hit_from_cycle(rich)
    assert a["subjects"] == b["subjects"] == ["EXIT:WLDS"]
    assert a["decisions"] == b["decisions"] == ["flash"]


def test_entrypoint_line_endings_unchanged():
    """This file is CRLF. write_text() would silently convert it to LF and turn
    a 20-line change into a 400-line diff (AGENTS.md 7)."""
    raw = ENTRYPOINT.read_bytes()
    assert b"\r\n" in raw, "entrypoint is CRLF; the edit must preserve that"
    assert raw.count(b"\n") == raw.count(b"\r\n"), "no lone LF may be introduced"
    assert b"\r\r" not in raw, "no doubled CR (the conditional-converter defect)"
