"""A mention has no lifetime of its own — it inherits its document's.

`document_mentions` shipped with 40,594 rows and NO retention policy, on the same
day AGENTS.md gained "every suppression needs a shelf life". A table that only
grows is that failure in the other direction: it does not mislead, it becomes
unusable and expensive, and nobody notices until it is large.

NO MODEL RUNS IN THE PRUNER, and none should. A mention is a derived fact — *this
document mentions this issuer, in this role*. Its relevance is entirely the
document's. Asking a model "is this 90-day-old mention still relevant?" 40,000
times is expensive, non-deterministic, and answers a question a foreign key
already answers.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _pruner():
    spec = importlib.util.spec_from_file_location(
        "prune_document_mentions", ROOT / "scripts" / "prune_document_mentions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SRC = (ROOT / "scripts" / "prune_document_mentions.py").read_text(encoding="utf-8")


# ── no judgment layer here ─────────────────────────────────────────────────

def test_no_model_in_the_pruner():
    low = SRC.lower()
    for banned in ("openai", "anthropic", "deepseek", "grok", "prompt",
                   "generate_with_fallback", "llm"):
        assert banned not in low, f"retention must be deterministic; found {banned}"


def test_dry_run_is_the_default():
    assert '"--apply", action="store_true"' in SRC
    mod = _pruner()
    import inspect
    assert "apply: bool" in inspect.getsource(mod.prune)


# ── retention is INHERITED, never invented ─────────────────────────────────

def test_windows_are_read_from_db_retention_not_copied():
    """If the two could disagree, one of them is wrong and nobody would know."""
    assert "db_retention" in SRC
    assert "POLICIES" in SRC
    fn = SRC.split("def retention_windows", 1)[1].split("\ndef ", 1)[0]
    # no literal day counts in the window resolver
    import re
    assert not re.search(r"=\s*\d{2,}\s*$", fn, re.M), "a retention window was hardcoded"


def test_every_extractor_source_is_considered():
    from lib.document_mentions import SOURCES
    mod = _pruner()
    fn = SRC.split("def retention_windows", 1)[1].split("\ndef ", 1)[0]
    assert "SOURCES" in fn
    assert len(SOURCES) >= 5


def test_a_source_with_no_window_is_reported_not_guessed():
    """hermes_external_research has no policy in db_retention. Inventing one is
    the failure this whole subsystem exists to avoid; reporting it is the fix."""
    assert "unwindowed" in SRC
    assert "grows unbounded" in SRC


def test_unreadable_policies_refuse_rather_than_default(monkeypatch):
    """If db_retention cannot be read, the pruner must not fall back to a guess —
    a wrong window silently deletes evidence."""
    mod = _pruner()
    monkeypatch.setitem(sys.modules, "db_retention", None)
    fn = SRC.split("def retention_windows", 1)[1].split("\ndef ", 1)[0]
    assert "refusing to invent" in fn
    assert "return {}" in fn


# ── what gets removed ──────────────────────────────────────────────────────

class _Cur:
    def __init__(self, counts):
        self._counts = list(counts)
        self.executed = []
        self.rowcount = 0
    def execute(self, sql, params=None):
        self.executed.append(" ".join(sql.split()))
    def fetchone(self):
        return (self._counts.pop(0) if self._counts else 0,)


class _Conn:
    def __init__(self, counts): self._c = _Cur(counts)
    def cursor(self): return self._c
    def commit(self): pass


def test_orphans_are_found_by_an_explicit_not_exists():
    """The guard against deleting rows whose source still exists."""
    conn = _Conn([7] * 20)
    mod = _pruner()
    mod.plan(conn)
    joined = " ".join(conn._c.executed)
    assert "NOT EXISTS" in joined


def test_aged_rows_are_matched_against_the_SOURCE_timestamp():
    """Not observed_at on the mention — a mention written today about a 2-year-old
    article is still about a 2-year-old article."""
    conn = _Conn([0] * 20)
    mod = _pruner()
    mod.plan(conn)
    joined = " ".join(conn._c.executed)
    assert "make_interval" in joined
    assert "JOIN" in joined.upper()


def test_a_dry_run_issues_no_delete():
    conn = _Conn([3] * 20)
    mod = _pruner()
    mod.prune(conn, apply=False)
    assert not any("DELETE" in e.upper() for e in conn._c.executed)


def test_apply_issues_deletes():
    conn = _Conn([3] * 20)
    mod = _pruner()
    mod.prune(conn, apply=True)
    assert any("DELETE" in e.upper() for e in conn._c.executed)


def test_deleting_a_projection_is_documented_as_distinct_from_the_never_delete_rule():
    """AGENTS.md forbids deleting authoritative state without a tripwire. A
    mention is re-runnable from its source; once the source is gone it is a
    dangling pointer, not evidence. That distinction must be written down or the
    next reader will think this violates the rule."""
    assert "never delete" in SRC.lower() or "NEVER DELETE" in SRC
    assert "projection" in SRC.lower()
