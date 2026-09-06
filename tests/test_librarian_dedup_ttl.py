"""A dedup guard with no shelf life is a permanent mute.

Measured 2026-09-06. The autonomous librarian loop had reported "0 findings" on
every run since 2026-07-14 while its own detectors matched:

    weak strategies (WR<40, n>=5)          1,673
    generic low-confidence catalysts      108,102   (threshold: >10)
    underfilled screener runs, 7 days         315   (threshold: >2)

The cause was three `research_backlog` rows filed on 2026-06-02. The catalyst
detector fires only when fewer than 2 such rows exist — there were exactly 2 —
and the screener detector only when none exist — there was 1. Both conditions
became permanently false, so three rows switched off two of four detectors for
96 days.

`hermes_advisory_events` has no other automatic producer, which is why that table
took its last write on 2026-07-14 and the advisory cache worker has been draining
an empty queue every ~10h since, reporting success each time.

Same defect as taxonomy_tagger's `no_match` sentinel: a suppression that is
correct for a day and wrong for a quarter.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "hermes_autonomous_librarian_backlog_loop.py"
TEXT = SRC.read_text(encoding="utf-8")


def _code_only() -> str:
    """Source with docstrings and comments stripped.

    A guard that greps raw text passes on a comment describing the defect — the
    trap this suite exists to avoid repeating.
    """
    tree = ast.parse(TEXT)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


CODE = _code_only()


def test_the_ttl_constant_exists_and_is_configurable():
    assert "BACKLOG_DEDUP_TTL_DAYS" in CODE
    assert "LIBRARIAN_BACKLOG_DEDUP_TTL_DAYS" in CODE, "the TTL must be overridable"


def test_the_ttl_is_a_sane_default():
    ns: dict = {}
    m = re.search(r"BACKLOG_DEDUP_TTL_DAYS\s*=\s*int\(os\.environ\.get\([^,]+,\s*\"(\d+)\"\)\)", TEXT)
    assert m, "TTL default not found"
    days = int(m.group(1))
    assert 7 <= days <= 90, f"{days}d is outside a defensible dedup window"


def test_every_backlog_dedup_query_is_time_bounded():
    """The exact defect: a COUNT over all history, with no lower bound.

    Three such queries gate the three detectors that can fire. Each must be
    bounded, or one old row mutes it forever.
    """
    counts = re.findall(
        r"SELECT COUNT\(\*\) FROM hermes_research_intelligence.*?(?=\"\)|\",\s*\()",
        CODE, re.S)
    assert counts, "no backlog dedup queries found — did the loop change shape?"
    for q in counts:
        flat = " ".join(q.split())
        assert "research_backlog" in flat
        assert "created_at" in flat and "make_interval" in flat, (
            f"unbounded dedup count, one old row mutes it forever: {flat[:120]}")


def test_the_three_detector_guards_are_all_covered():
    """Strategy, catalyst and screener — the 2026-06-02 rows hit the last two.

    Matched on the LIKE body rather than the literal, because `%` is escaped as
    `%%` for psycopg parameter substitution and the escaping is not the subject.
    """
    for marker in ("catalyst", "screener"):
        hits = [m.start() for m in re.finditer(
            r"topic LIKE '[%\s]*" + marker, CODE)]
        assert hits, f"dedup guard for {marker} vanished"
        for idx in hits:
            window = CODE[idx:idx + 400]
            assert "make_interval" in window, (
                f"{marker} dedup guard is still unbounded — one old row mutes it forever")


def test_credentials_are_not_read_from_a_tree_relative_path():
    """`(PR/'.env')` resolves inside whatever tree the code runs from, and a
    release has no .env — secrets are deliberately not deployed. This raised
    FileNotFoundError before reaching a query whenever it ran from CURRENT."""
    assert 'PR/".env"' not in CODE and "PR / '.env'" not in CODE
    assert "env_bootstrap" in CODE, "must use the canonical loader"


def test_a_missing_credential_fails_loudly():
    """Silently returning None would turn a credential fault into 0 findings —
    indistinguishable from a clean backlog, which is how this hid for 96 days."""
    assert "DB_PASSWORD not resolvable" in CODE
