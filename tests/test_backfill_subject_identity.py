"""Stage 0: the corpus must be joinable by identity, and it must cost nothing.

Measured 2026-09-06, ~336,000 rows could not be joined to a subject at all:
catalyst_events, hermes_external_research and research_insights had no subject_guid
column; news_articles and hermes_research_intelligence had one and had never filled it.
Anything assembling "everything we know about X" therefore read about a third of the
corpus — and under-answering looks exactly like answering.

Two properties this suite exists to hold:

FREE
    Resolution is a registry lookup, a pure function of the symbol. No model is called
    on any row. The deterministic path is precisely the one a later change is tempted
    to "improve" with a model, so it is pinned rather than trusted.

HONEST ABOUT WHAT IT DOES NOT KNOW
    Four outcomes, not two: resolved, not-applicable (cash/index), the registry does
    not know this symbol, and the registry could not be READ. The last is not a fact
    about the row. Writing it as UNRESOLVED would let a transient outage permanently
    mark good rows unresolvable — so the run stops instead.

No database: the cursor is a fake. The DB-touching path is exercised through it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCRIPT = ROOT / "scripts" / "backfill_subject_identity.py"


@pytest.fixture(scope="module")
def mod():
    return pytest.importorskip("backfill_subject_identity")


class FakeCur:
    """Enough of a cursor to drive backfill() without a database."""

    def __init__(self, columns, symbols, rowcount=7):
        self._columns = columns
        self._symbols = symbols
        self._rowcount = rowcount
        self.updates: list[tuple] = []
        self.ddl: list[str] = []
        self._result: list = []

    @property
    def rowcount(self):
        return self._rowcount

    def execute(self, sql, params=None):
        if "information_schema.columns" in sql:
            self._result = [(c,) for c in self._columns]
        elif sql.strip().upper().startswith("SELECT DISTINCT"):
            self._result = [(s,) for s in self._symbols]
        elif sql.strip().upper().startswith("UPDATE"):
            self.updates.append((sql, params))
            self._result = []
        elif "ALTER TABLE" in sql:
            self.ddl.append(sql)
            self._result = []

    def fetchall(self):
        return self._result


# ── it costs nothing ────────────────────────────────────────────────────────

def test_no_model_is_called_anywhere():
    """The whole point of stage 0 being deterministic."""
    src = SCRIPT.read_text(encoding="utf-8")
    for banned in ("llm", "chat_json", "deepseek", "openai", "anthropic",
                   "run_with_escalation", "cio_governed"):
        assert banned not in src.lower(), f"stage 0 reaches a model via {banned!r}"


def test_it_declares_zero_model_calls_in_its_result():
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"model_calls": 0' in src


# ── four outcomes, not two ──────────────────────────────────────────────────

def test_a_registry_that_cannot_be_read_stops_the_run(mod, monkeypatch):
    """The failure that must never be written as data.

    A transient registry outage that stamped rows UNRESOLVED would outlive the
    outage and be indistinguishable from a genuine miss.
    """
    monkeypatch.setattr(mod, "lookup_identity_envelope", None, raising=False)
    import scripts.lib.cio_subject_guid as csg

    monkeypatch.setattr(csg, "lookup_identity_envelope",
                        lambda s, **k: {"subject_guid": None, "identity_lookup_failed": True,
                                        "identity_lookup": "LOOKUP_FAILED",
                                        "identity_lookup_reason": "OSError"},
                        raising=False)
    cur = FakeCur(["subject_guid", "symbol"], ["AAPL"])
    with pytest.raises(RuntimeError, match="REGISTRY_UNREADABLE"):
        mod.backfill(cur, "t", "symbol", apply=True, limit=None)
    assert cur.updates == [], "it wrote rows despite an unreadable registry"


def test_unknown_and_not_applicable_are_counted_apart(mod, monkeypatch):
    """'We do not track cash' and 'we do not recognise this ticker' are different
    facts, and collapsing them hides how much of the corpus is genuinely missing."""
    import scripts.lib.cio_subject_guid as csg

    answers = {
        "CASH": {"subject_guid": None, "identity_lookup": "NOT_APPLICABLE",
                 "identity_lookup_failed": False},
        "ZZZZ": {"subject_guid": None, "identity_lookup": "UNRESOLVED",
                 "identity_lookup_failed": False},
    }
    monkeypatch.setattr(csg, "lookup_identity_envelope",
                        lambda s, **k: answers[s], raising=False)
    res = mod.backfill(FakeCur(["subject_guid", "symbol"], ["CASH", "ZZZZ"]),
                       "t", "symbol", apply=True, limit=None)
    assert res["not_applicable"] == 1
    assert res["unresolved"] == 1
    assert res["resolved"] == 0


# ── rank is one-way, and unknown is the LOWEST rank ─────────────────────────

def test_an_unknown_status_is_not_treated_as_confirmed(mod, monkeypatch):
    """The bug this file was written after.

    The guard read COALESCE(identity_status, 'CONFIRMED') <> 'CONFIRMED'. Every
    untagged row has a NULL status, which coalesced to 'CONFIRMED', so the predicate
    was always false: the backfill reported 23 symbols resolved and wrote zero rows.
    A counter that says 'resolved' while nothing lands is worse than a failure.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "COALESCE(identity_status, '') <> 'CONFIRMED'" in src
    assert "COALESCE(identity_status, %s) <> %s" not in src


def test_an_already_confirmed_row_is_protected(mod):
    """One-way rank: a backfill may raise confidence, never lower it.

    Scoped to backfill() specifically. An earlier version split on the first
    "UPDATE {table} SET" in the file, which silently became classify_remainder's
    topic update once that was added above it — a guard that keeps passing while
    pointing at the wrong statement.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    fn = src.split("def backfill(", 1)[1].split("\ndef ", 1)[0]
    update = fn.split("UPDATE {table} SET", 1)[1].split("counts[", 1)[0]
    assert "<> 'CONFIRMED'" in update


def test_the_topic_update_cannot_overwrite_a_resolved_row(mod):
    """It needs no CONFIRMED guard because it only ever fills rows that have no
    subject at all — but that predicate must actually be there."""
    src = SCRIPT.read_text(encoding="utf-8")
    fn = src.split("def classify_remainder", 1)[1]
    topic_update = fn.split("SET subject_guid=", 1)[1].split("topic_rows", 1)[0]
    assert "subject_guid IS NULL" in topic_update


def test_the_rank_order_is_written_down(mod):
    assert mod.RANK["CONFIRMED"] > mod.RANK["CANDIDATE"] > mod.RANK["UNRESOLVED"]
    assert mod.RANK[None] == 0, "unknown must be the lowest rank, not the highest"


# ── honest counting ─────────────────────────────────────────────────────────

def test_a_dry_run_reports_unmeasured_not_zero(mod, monkeypatch):
    """rows_produced=0 means 'measured, nothing to do'. A dry run measured nothing."""
    import scripts.lib.cio_subject_guid as csg

    monkeypatch.setattr(csg, "lookup_identity_envelope",
                        lambda s, **k: {"subject_guid": "g", "issuer_guid": "i",
                                        "identity_status": "CONFIRMED",
                                        "identity_lookup": "RESOLVED",
                                        "identity_lookup_failed": False},
                        raising=False)
    res = mod.backfill(FakeCur(["subject_guid", "symbol"], ["AAPL"]),
                       "t", "symbol", apply=False, limit=None)
    assert res["rows_produced"] is None
    assert res["resolved"] == 1


def test_nothing_left_to_do_reports_a_measured_zero(mod):
    res = mod.backfill(FakeCur(["subject_guid", "symbol"], []),
                       "t", "symbol", apply=True, limit=None)
    assert res["rows_produced"] == 0


def test_a_table_without_the_columns_is_skipped_not_counted_zero(mod):
    """'Cannot run here' must not read as 'ran and found nothing'."""
    res = mod.backfill(FakeCur(["symbol"], ["AAPL"]), "t", "symbol",
                       apply=True, limit=None)
    assert res["rows_produced"] is None
    assert "add-columns" in res["skipped"]


# ── schema changes are additive and repeatable ──────────────────────────────

def test_add_columns_is_idempotent(mod):
    cur = FakeCur([c for c, _ in mod.IDENTITY_COLUMNS] + ["symbol"], [])
    assert mod.add_columns(cur, "t", apply=True) == []
    assert cur.ddl == []


def test_add_columns_uses_if_not_exists(mod):
    cur = FakeCur(["symbol"], [])
    mod.add_columns(cur, "t", apply=True)
    assert cur.ddl and all("IF NOT EXISTS" in d for d in cur.ddl)


def test_the_column_shape_matches_the_table_that_already_had_it(mod):
    """A second near-miss spelling of the same idea is how one spine becomes two."""
    names = [c for c, _ in mod.IDENTITY_COLUMNS]
    assert names == ["subject_guid", "issuer_guid", "gics_sector",
                     "identity_status", "identity_tagged_at"]
    types = dict(mod.IDENTITY_COLUMNS)
    assert types["subject_guid"] == "uuid" and types["issuer_guid"] == "uuid"


def test_every_target_table_names_its_symbol_column(mod):
    assert set(mod.TARGETS) == {
        "catalyst_events", "hermes_external_research", "research_insights",
        "news_articles", "hermes_research_intelligence"}
    assert all(v for v in mod.TARGETS.values())


# ── the envelope preserves what lookup_subject established ──────────────────

def test_the_envelope_keeps_the_four_lookup_states(monkeypatch):
    """NOT_APPLICABLE needs no registry; UNRESOLVED is stubbed so the assertion does
    not depend on a registry file that CI does not have."""
    import scripts.lib.cio_subject_guid as csg

    assert csg.lookup_identity_envelope("CASH")["identity_lookup"] == "NOT_APPLICABLE"

    fake = type(sys)("scripts.lib.identity_registry")
    fake.load_cached = lambda root=None: {}
    fake.lookup_symbol = lambda reg, sym: None          # registry answered: no entity
    monkeypatch.setitem(sys.modules, "scripts.lib.identity_registry", fake)
    assert csg.lookup_identity_envelope("ZZZZ")["identity_lookup"] == "UNRESOLVED"


def test_the_envelope_carries_the_issuer_not_just_the_subject(monkeypatch):
    """The join a dossier needs: security -> issuer.

    Stubbed, not read from the live registry. The first version of this asserted
    against real AAPL data: it passed here, where the registry file exists, and
    failed in CI, where it does not — a test that only holds in the environment
    that least needs it.
    """
    import scripts.lib.cio_subject_guid as csg

    monkeypatch.setattr(csg, "lookup_subject",
                        lambda s, **k: {"subject_guid": "sub-1", "identity_status": "CONFIRMED",
                                        "identity_lookup": "RESOLVED",
                                        "identity_lookup_failed": False},
                        raising=False)
    fake = type(sys)("scripts.lib.identity_registry")
    fake.load_cached = lambda root=None: {}
    fake.lookup_symbol = lambda reg, sym: {"issuer_guid": "iss-1", "security_guid": "sec-1",
                                           "listing_guid": "lst-1"}
    monkeypatch.setitem(sys.modules, "scripts.lib.identity_registry", fake)

    env = csg.lookup_identity_envelope("AAPL")
    assert env["subject_guid"] == "sub-1"
    assert env["issuer_guid"] == "iss-1"
    assert env["subject_guid"] != env["issuer_guid"]


def test_a_failed_enrichment_does_not_discard_a_good_subject(monkeypatch):
    """The subject resolved; only the second read failed. Throwing away a correct
    answer because an optional enrichment failed would be the wrong trade."""
    import scripts.lib.cio_subject_guid as csg

    monkeypatch.setattr(csg, "lookup_subject",
                        lambda s, **k: {"subject_guid": "sub-1", "identity_status": "CONFIRMED",
                                        "identity_lookup": "RESOLVED",
                                        "identity_lookup_failed": False},
                        raising=False)
    monkeypatch.setitem(sys.modules, "scripts.lib.identity_registry", None)
    env = csg.lookup_identity_envelope("AAPL")
    assert env["subject_guid"] == "sub-1"
    assert env["issuer_guid"] is None


def test_the_envelope_never_mints():
    src = (ROOT / "scripts" / "lib" / "cio_subject_guid.py").read_text(encoding="utf-8")
    fn = src.split("def lookup_identity_envelope", 1)[1].split("\ndef ", 1)[0]
    assert "uuid5" not in fn and "register" not in fn, "lookup-only means lookup-only"


def test_the_script_parses():
    ast.parse(SCRIPT.read_text(encoding="utf-8"))


# ── topics are subjects too, and the remainder is classified not abandoned ──
#
# The unresolved population was never "symbols we failed to look up". It was two
# populations wearing one column:
#
#   d107_energy_transition, su_industry_insurance_brokers  — research THEMES, filed
#     under `symbol` because the catalyst engine has one column for both.
#   ASSET, NEW, NEED, TO, STUDY, FIND                      — English words a ticker
#     extractor mistook for symbols. An upstream defect.
#
# Giving a theme a SECURITY guid fabricates identity. Leaving either NULL makes the
# rows permanently unjoinable AND indistinguishable from rows nobody examined yet.

def test_a_topic_gets_a_deterministic_guid_of_its_own(mod):
    a = mod.topic_guid("d107_energy_transition")
    b = mod.topic_guid("d107_energy_transition")
    assert a == b, "same topic must always mint the same guid"
    assert a != mod.topic_guid("d98_consumer_defensive")


def test_a_topic_guid_is_not_a_security_guid(mod):
    """Different namespace. A theme must never collide with a company."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'f"tradeai:{TOPIC_NAMESPACE}:{topic_id}"' in src
    assert mod.TOPIC_NAMESPACE == "topic"


def test_examined_and_unresolvable_is_recorded_not_left_null(mod):
    """The whole point: identity_status IS NULL must mean exactly one thing —
    nobody has looked at this row yet. A column that cannot separate 'looked and
    could not resolve' from 'never looked' cannot measure its own coverage."""
    src = SCRIPT.read_text(encoding="utf-8")
    fn = src.split("def classify_remainder", 1)[1]
    assert "identity_status IS NULL" in fn
    assert "UNRESOLVABLE" in fn


def test_a_limited_pass_never_marks_the_remainder_unresolvable(mod):
    """Under --limit the remainder has NOT been examined. Marking it unresolvable
    would be a lie that every later run inherits and never revisits."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "not args.limit" in src
    guard = src.split("if not res.get(\"skipped\") and not args.limit", 1)[1][:400]
    assert "classify_remainder" in guard


def test_a_dry_run_classifies_nothing(mod):
    class Cur(FakeCur):
        def execute(self, sql, params=None):
            if "to_regclass" in sql:
                self._result = [(None,)]
            else:
                super().execute(sql, params)

    cur = Cur(["subject_guid", "symbol"], [])
    res = mod.classify_remainder(cur, "t", "symbol", apply=False)
    assert res["unresolvable_rows"] == 0
    assert cur.updates == []


def test_a_missing_topic_table_is_survived_not_fatal(mod):
    """Not every deployment has topic_monitor. Its absence means 'no topics to
    resolve', not 'this run failed'."""
    class Cur(FakeCur):
        def execute(self, sql, params=None):
            if "to_regclass" in sql:
                self._result = [(None,)]
            else:
                super().execute(sql, params)

    res = mod.classify_remainder(Cur(["subject_guid", "symbol"], []), "t", "symbol",
                                 apply=True)
    assert res["topics"] == 0
