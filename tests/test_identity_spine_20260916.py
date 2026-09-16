"""Controls for P1 — an existing id joins the spine WITHOUT becoming a new id.

A question had five identities and no join key: `DataGap.gap_id`,
`ResearchGap.gap_id`, the `data_gap_registry` integer, two unrelated
`question_guid`s, and `cio_goals.goal_id`. P1's claim is narrow and must stay
narrow: every one of those ids keeps its value, and gains an edge row on the
`narrative_subjects` table that already exists.

Each control below must go red if the corresponding guarantee is removed.
Offline: fake cursors, no database, no registry.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_identity_spine as spine  # noqa: E402
from scripts.lib.cio_narrative_subjects import build_links  # noqa: E402
from scripts.lib.cio_narrative_write import row_guid_for  # noqa: E402

GAP_UUID = "0f1e2d3c-4b5a-5f6e-8d9c-0a1b2c3d4e5f"
SGUID = "subject-guid-HPE"


class FakeCursor:
    def __init__(self, fail: bool = False, rows=None):
        self.calls: list[tuple[str, tuple]] = []
        self.fail = fail
        self.rowcount = 1
        self._rows = rows or []

    def execute(self, sql, params=None):
        if self.fail:
            raise RuntimeError("write refused")
        self.calls.append((" ".join(str(sql).split()), params))

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- the property the whole phase rests on ----------------------------------

def test_the_id_itself_is_never_changed():
    """`source_id` carries the producer's id verbatim. No renumbering, ever."""
    link = spine.build_spine_link(
        source_table="research_gaps", source_id=GAP_UUID,
        subject_guid=SGUID, semantic_subject="HPE")
    assert link["source_id"] == GAP_UUID
    assert link["subject_guid"] == SGUID


def test_a_uuid_id_is_its_own_row_guid_and_an_int_id_gets_the_spine_convention():
    """No sixth id scheme: reuse the id when it IS a guid, else the spine's uuid5."""
    assert spine.row_guid_of("research_gaps", GAP_UUID) == GAP_UUID
    assert spine.row_guid_of("data_gap_registry", 81) == row_guid_for("data_gap_registry", 81)
    assert spine.row_guid_of("cio_goals", "goal_695a5dbe2401") == row_guid_for(
        "cio_goals", "goal_695a5dbe2401")


def test_the_link_guid_is_the_one_build_links_would_mint():
    """A wrapper, not a second definition of NarrativeSubjectLink."""
    expected, _ = build_links(
        row_guid=GAP_UUID, source_table="research_gaps", source_id=GAP_UUID,
        subjects=[{"entity_type": "SECURITY", "value": "HPE", "relationship": "subject"}],
        symbol_lookup=lambda s, root=None: {"subject_guid": SGUID,
                                            "identity_status": "CANDIDATE"})
    link = spine.build_spine_link(
        source_table="research_gaps", source_id=GAP_UUID,
        subject_guid=SGUID, semantic_subject="HPE")
    assert link["link_guid"] == expected[0]["link_guid"]
    assert link["schema_version"] == expected[0]["schema_version"]


def test_registration_is_idempotent_for_the_same_triple():
    """link_guid is a pure function of (row, subject, relationship)."""
    a = spine.build_spine_link(source_table="research_gaps", source_id=GAP_UUID,
                               subject_guid=SGUID, semantic_subject="HPE")
    b = spine.build_spine_link(source_table="research_gaps", source_id=GAP_UUID,
                               subject_guid=SGUID, semantic_subject="HPE")
    assert a["link_guid"] == b["link_guid"]


# --- the write ---------------------------------------------------------------

def test_the_write_is_additive_and_delete_free():
    """One INSERT, ON CONFLICT DO NOTHING. Nothing else may touch this table."""
    cur = FakeCursor()
    lg = spine.register_on_spine("research_gaps", GAP_UUID, SGUID, cur=cur,
                                 semantic_subject="HPE")
    assert lg
    assert len(cur.calls) == 1
    sql, params = cur.calls[0]
    assert sql.startswith("INSERT INTO narrative_subjects")
    assert "ON CONFLICT (link_guid) DO NOTHING" in sql
    assert not any(word in sql.upper() for word in ("DELETE", "DROP", "TRUNCATE"))
    assert params[0] == lg and params[3] == GAP_UUID


def test_a_failed_link_never_reaches_the_producer():
    """Fail-safe, not fail-closed: the gap is written, the link is lost, no raise."""
    assert spine.register_on_spine("research_gaps", GAP_UUID, SGUID,
                                   cur=FakeCursor(fail=True)) is None


def test_no_database_means_no_claim():
    """Without credentials nothing is written and nothing is pretended."""
    assert spine.register_on_spine("research_gaps", GAP_UUID, SGUID) is None


def test_the_flag_switches_registration_off_without_a_deploy():
    cur = FakeCursor()
    assert spine.register_on_spine("research_gaps", GAP_UUID, SGUID, cur=cur,
                                   env={"CIO_IDENTITY_SPINE": "0"}) is None
    assert cur.calls == []


def test_an_incomplete_edge_is_refused_rather_than_written_null():
    """A link with no subject joins to nothing and would misreport coverage."""
    cur = FakeCursor()
    assert spine.register_on_spine("research_gaps", GAP_UUID, "", cur=cur) is None
    assert spine.register_on_spine("", GAP_UUID, SGUID, cur=cur) is None
    assert spine.register_on_spine("research_gaps", None, SGUID, cur=cur) is None
    assert cur.calls == []


def test_a_minted_subject_that_disagrees_with_the_supplied_one_is_refused():
    """The sector_move defect must not return in a new costume."""
    assert spine.build_spine_link(
        source_table="cio_goals", source_id="goal_1", subject_guid="not-the-minted-guid",
        entity_type="SECTOR", semantic_subject="Energy") is None


def test_an_unknown_symbol_registers_nothing(monkeypatch):
    """`register_symbol_on_spine` never mints an identity the registry lacks."""
    import scripts.lib.cio_subject_guid as sg

    monkeypatch.setattr(sg, "lookup_subject", lambda s, root=None: {})
    cur = FakeCursor()
    assert spine.register_symbol_on_spine("cio_goals", "goal_1", "ZZZZ", cur=cur) is None
    assert cur.calls == []


def test_a_resolved_symbol_is_registered_under_the_registry_guid(monkeypatch):
    import scripts.lib.cio_subject_guid as sg

    monkeypatch.setattr(sg, "lookup_subject",
                        lambda s, root=None: {"subject_guid": SGUID,
                                              "identity_status": "CONFIRMED"})
    cur = FakeCursor()
    lg = spine.register_symbol_on_spine("gap_resolver_gaps", GAP_UUID, "hpe", cur=cur)
    assert lg and len(cur.calls) == 1
    params = cur.calls[0][1]
    assert params[5] == SGUID and params[6] == "HPE" and params[8] == "CONFIRMED"


def test_register_many_does_not_lose_nine_links_to_one_bad_row():
    cur = FakeCursor()
    out = spine.register_many([
        {"source_table": "operator_questions", "source_id": GAP_UUID,
         "subject_guid": SGUID, "semantic_subject": "HPE"},
        {"source_table": "operator_questions", "source_id": GAP_UUID,
         "subject_guid": "", "semantic_subject": "BAD"},
        {"source_table": "operator_questions", "source_id": "11111111-2222-5333-8444-555555555555",
         "subject_guid": "subject-guid-NOC", "semantic_subject": "NOC"},
    ], cur=cur)
    assert len(out) == 2 and len(cur.calls) == 2


# --- the six schemes ---------------------------------------------------------

def test_all_six_id_schemes_have_a_declared_source_table():
    assert set(spine.SOURCE_TABLES) == {
        "gap_resolver_gaps", "research_gaps", "data_gap_registry",
        "operator_questions", "due_diligence_questions", "cio_goals",
    }


def test_two_stores_naming_one_subject_join_on_the_subject_guid():
    """The point of the phase: a gap and a question meet without sharing an id."""
    gap = spine.build_spine_link(source_table="research_gaps", source_id=GAP_UUID,
                                 subject_guid=SGUID, semantic_subject="HPE")
    question = spine.build_spine_link(
        source_table="due_diligence_questions",
        source_id="11111111-2222-5333-8444-555555555555",
        subject_guid=SGUID, semantic_subject="HPE")
    assert gap["subject_guid"] == question["subject_guid"]
    assert gap["source_id"] != question["source_id"]     # ids untouched
    assert gap["link_guid"] != question["link_guid"]     # separate edges


# --- the lint ----------------------------------------------------------------

def test_the_lint_names_the_prefix_collision_and_never_fails():
    import check_identity_spine as lint

    rep = lint.report()
    collision = next(f for f in rep["findings"] if f["finding"] == "GAP_PREFIX_COLLISION")
    assert collision["prefix"] == "tradeai:gap:"
    assert collision["collides"] is True
    assert len(set(collision["same_gap_two_guids"].values())) == 2
    assert all(s["line"] for s in collision["sites"])
    assert lint.main.__doc__ is None or True
    assert rep["reports_only"] is True


def test_the_lint_names_the_two_question_guid_signatures():
    import check_identity_spine as lint

    finding = next(f for f in lint.report()["findings"]
                   if f["finding"] == "QUESTION_GUID_INCOMPATIBLE")
    assert finding["incompatible_arguments"] is True
    params = [s["parameters"] for s in finding["sites"]]
    assert ["chat_id", "message_id", "text"] in params
    assert ["subject_guid", "change_guid", "text"] in params


def test_the_lint_exits_zero(capsys):
    import check_identity_spine as lint

    assert lint.main.__module__ == "check_identity_spine"
    sys.argv = ["check_identity_spine.py", "--json"]
    assert lint.main() == 0
    assert "GAP_PREFIX_COLLISION" in capsys.readouterr().out


# --- the defect P1 fixes -----------------------------------------------------

def test_the_desk_can_now_feed_the_one_working_state_machine():
    """`missing_research` returned None, so the desk fed data_gap_registry nothing.

    Live receipt, data/cio/cio_operator_gap_requests.jsonl 2026-09-14:
    gap_type missing_research for HPE -> `"registered": 0, "not_registered": 1`.
    """
    import lib.cio_operator_desk_loop as desk

    live_gap = {"domain": "hermes_research", "symbol": "HPE", "field": "research",
                "reason": "no promoted research for HPE", "gap_type": "missing_research"}
    assert desk._registry_gap_type(live_gap) == "stale_news"


def test_the_mapped_type_is_one_the_writer_and_the_resolver_both_accept():
    """A type outside the vocabulary would be rejected at the rail and sit unworked."""
    import lib.cio_operator_desk_loop as desk
    from lib.writers.data_gap_registry_writer import GAP_TYPES

    mapped = desk._registry_gap_type(
        {"domain": "hermes_research", "symbol": "HPE", "gap_type": "missing_research"})
    assert mapped in GAP_TYPES


def test_a_research_gap_with_no_symbol_is_still_refused():
    """The symbol rail is unchanged: BOOK-level asks are not queueable."""
    import lib.cio_operator_desk_loop as desk

    assert desk._registry_gap_type(
        {"domain": "hermes_research", "symbol": None, "gap_type": "missing_research"}) is None
