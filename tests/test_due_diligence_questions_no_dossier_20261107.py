"""due-diligence-questions: five dossier-less rows at the head of the queue starved 1,426 changes.

LQ-20261107-142 (audit78_result4). Measured on the live database 2026-11-07, read-only:

* 1,426 ``material_changes`` rows were pending (``questioned_at IS NULL`` and not UNCORROBORATED);
* the loop took the top 5 by magnitude — XRPN, SNYR, MB, BF-B, ALIT — and every one of them had NO
  linked evidence, so ``dossier()`` returned nothing and the row was skipped;
* a skipped row keeps ``questioned_at`` NULL, so the next run fetched the same five. The highest-ranked
  change that DID have evidence was **rank 6**, i.e. permanently unreachable, and the lane had written no
  question since the cutover;
* every one of those runs wrote ``ok=true, empty_reason="nothing_due"`` — a green receipt over 1,426 rows
  of work the lane saw and could not do (the log holds the identical block on run after run).

What is pinned here:

* the run scans past the curated cap and curates changes that HAVE evidence, in magnitude order;
* the prefilter ORDERS the queue; it is not the authority — ``dossier()`` is, so a window the prefilter
  calls unlinked is still attempted (a prefilter that silently disagreed with the dossier would be the
  same starvation by another route);
* a run that took changes and could reason about none of them is ``ok=false / no_dossier_evidence``, never
  ``nothing_due``; a genuinely empty queue is still ``ok / nothing_due``;
* the prefilter asks about every source ``dossier()`` reads (a drift alarm: adding a dossier source without
  adding it here would re-create the starvation).

Hermetic: module executed from source, DB/DDL/curation/researcher replaced with stubs, state root in
``tmp_path``. No DB, provider, lock or live state.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load() -> types.ModuleType:
    path = ROOT / "scripts" / "due_diligence_questions.py"
    mod = types.ModuleType("ddq_no_dossier_under_test")
    mod.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), mod.__file__, "exec"), mod.__dict__)
    return mod


def _receipt(tmp_path: Path) -> Path:
    return tmp_path / "state" / "data" / "runtime" / "due-diligence-questions_last.json"


class _Cur:
    rowcount = 0

    def __init__(self):
        self.executed: list = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return (1,)

    def fetchall(self):
        return []

    def set_session(self, **k):
        return None


class _Conn:
    def __init__(self):
        self.cur = _Cur()

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        return None

    def close(self):
        return None


def _stub_ddl_guard(monkeypatch):
    stub = types.ModuleType("scripts.lib.ddl_guard")
    stub.apply_ddl = lambda cur, ddl: None
    monkeypatch.setitem(sys.modules, "scripts.lib.ddl_guard", stub)


#: The five rows the live queue actually served, in magnitude order. None of them has a dossier.
_HEAD = [{"change_guid": f"c{i}", "subject_guid": f"g{i}", "symbol": s, "kind": "sector_move",
          "magnitude": 9 - i} for i, s in enumerate(["XRPN", "SNYR", "MB", "BF-B", "ALIT"])]
#: The changes behind them (the live rank-6 onwards): these DO have evidence.
_TAIL = [{"change_guid": f"c1{i}", "subject_guid": f"e{i}", "symbol": s, "kind": "news_burst",
          "magnitude": 4 - i / 10} for i, s in enumerate(["PWR", "NVDA", "AAPL", "V", "MSFT"])]


def _wire(mod, monkeypatch, *, rows, evidence, dossier, ask_model):
    _stub_ddl_guard(monkeypatch)
    mod._db = _Conn
    mod.cap_env_warning = lambda: None
    mod.reconcile_answers = lambda cur, apply=True: {}
    mod.pending_changes = lambda cur, limit: rows[:limit]
    mod.evidence_subjects = evidence
    mod.dossier = dossier
    mod.ask_model = ask_model
    mod.ground = lambda parsed, items: ([], [{"question": "is the thesis intact?"}], {})
    mod.persist = lambda cur, ch, narrative, questions, meta, n: (None, 1)
    mod.route = lambda cur, limit: {"routed": 0}
    mod.MAX_ROUTED = 0


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))


def test_the_head_of_the_queue_cannot_starve_the_changes_behind_it(tmp_path, monkeypatch):
    """The live defect: 5 unlinked rows first, 1,426 pending behind them, 0 questions written."""
    _env(tmp_path, monkeypatch)
    mod = _load()
    asked: list[str] = []

    def _ask(ch, items):
        asked.append(ch["symbol"])
        return {"parsed": {}, "lane": "stub"}

    _wire(mod, monkeypatch, rows=_HEAD + _TAIL,
          evidence=lambda cur, guids: {str(g) for g in guids if str(g).startswith("e")},
          dossier=lambda cur, guid: [{"id": "d-1", "date": "2026-11-06", "text": "linked"}]
          if str(guid).startswith("e") else [],
          ask_model=_ask)

    assert mod.main(["--apply"]) == 0

    assert asked == ["PWR", "NVDA", "AAPL", "V", "MSFT"], (
        f"the run curated the dossier-less head instead of the work behind it: {asked}")
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "ok" and doc["exit"] == 0, doc
    assert doc["produced_count"] == 5, doc
    assert doc.get("empty_reason") is None, doc


def test_a_run_that_could_reason_about_none_of_its_changes_is_not_nothing_due(tmp_path, monkeypatch):
    """Every change it took had nothing linked: a coverage gap the desk must see, not an empty lane.

    The live lane wrote `ok / nothing_due` on 40+ consecutive runs in exactly this state.
    """
    _env(tmp_path, monkeypatch)
    mod = _load()
    asked: list[str] = []

    _wire(mod, monkeypatch, rows=list(_HEAD),
          evidence=lambda cur, guids: set(),
          dossier=lambda cur, guid: [],
          ask_model=lambda ch, items: asked.append(ch["symbol"]))

    assert mod.main(["--apply"]) == 1, "a run that skipped all its work reported success"

    assert asked == [], "a dossier-less change reached the model"
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "failed" and doc["exit"] == 1, doc
    assert not doc.get("ok_at"), f"a starved run advanced ok_at: {doc}"
    assert doc.get("empty_reason") is None, f"a starved run reported an empty lane: {doc}"
    assert doc["error"] == "no_dossier_evidence", doc
    assert doc["produced_count"] == 0, doc


def test_a_genuinely_empty_queue_is_still_nothing_due(tmp_path, monkeypatch):
    """The honest green case must not be lost in the fix for the dishonest one."""
    _env(tmp_path, monkeypatch)
    mod = _load()

    _wire(mod, monkeypatch, rows=[], evidence=lambda cur, guids: set(),
          dossier=lambda cur, guid: [], ask_model=lambda ch, items: None)

    assert mod.main(["--apply"]) == 0
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "ok" and doc["exit"] == 0, doc
    assert doc["empty_reason"] == "nothing_due", doc
    assert doc["produced_count"] == 0, doc


def test_the_scan_window_is_wider_than_the_curated_cap(tmp_path, monkeypatch):
    """The cap counts changes CURATED; the window bounds how many rows a run may examine to find them."""
    _env(tmp_path, monkeypatch)
    mod = _load()
    seen: list[int] = []

    def _pending(cur, limit):
        seen.append(limit)
        return []

    _wire(mod, monkeypatch, rows=[], evidence=lambda cur, guids: set(),
          dossier=lambda cur, guid: [], ask_model=lambda ch, items: None)
    mod.pending_changes = _pending
    mod.SCAN_MULTIPLIER, mod.SCAN_MAX = 20, 500

    assert mod.main(["--apply"]) == 0
    assert seen == [100], f"a --limit of 5 examined {seen} rows; the window must look past the head"

    seen.clear()
    assert mod.main(["--apply", "--limit", "40"]) == 0
    assert seen == [500], "the window is not bounded by SCAN_MAX"


def test_the_prefilter_orders_the_queue_but_dossier_is_the_authority(tmp_path, monkeypatch):
    """A prefilter that calls a change unlinked must not bury it: the run still takes it and asks.

    `dossier()` is the only thing that decides a change has nothing to say. If this were not true, a
    prefilter that disagreed with the dossier would re-create the very starvation being fixed.
    """
    _env(tmp_path, monkeypatch)
    mod = _load()
    asked: list[str] = []

    _wire(mod, monkeypatch, rows=list(_HEAD),
          evidence=lambda cur, guids: set(),  # the prefilter knows nothing about these
          dossier=lambda cur, guid: [{"id": "d-1", "date": "2026-11-06", "text": "linked"}],
          ask_model=lambda ch, items: (asked.append(ch["symbol"]), {"parsed": {}, "lane": "s"})[1])

    assert mod.main(["--apply"]) == 0
    assert asked == [r["symbol"] for r in _HEAD], f"the prefilter buried work dossier() found: {asked}"


class _EvCur:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self.rows


def test_evidence_subjects_carries_the_guids_and_returns_the_strings():
    mod = _load()
    cur = _EvCur([("g-1",)])
    assert mod.evidence_subjects(cur, ["g-1", "g-2"]) == {"g-1"}
    assert cur.params == (["g-1", "g-2"],), cur.params

    never = _EvCur([])
    assert mod.evidence_subjects(never, []) == set()
    assert never.sql is None, "an empty window still queried the database"


def test_the_prefilter_asks_about_every_source_the_dossier_reads():
    """Drift alarm: a source added to `dossier()` but not here would hide those rows from the window.

    It cannot STARVE them (dossier() is still the authority, and the queue is topped up), but it would
    order the queue on stale knowledge — so the two definitions are pinned together.
    """
    mod = _load()
    src = (ROOT / "scripts" / "due_diligence_questions.py").read_text(encoding="utf-8")
    dossier_src = src.split("def dossier(", 1)[1].split("\ndef ", 1)[0]
    prefilter = mod.EVIDENCE_SUBJECTS_SQL
    for table in ("news_articles", "catalyst_events", "document_mentions",
                  "hermes_external_research", "research_insights"):
        assert table in dossier_src, f"dossier no longer reads {table}: update this test"
        assert table in prefilter, f"the prefilter forgot {table}, which dossier() reads"
