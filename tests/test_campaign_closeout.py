"""Phase 5 — the terminal marker must be impossible to reach by accident.

Almost every test here tries to obtain READY illegitimately and asserts it is
refused. That is the point: a closeout is only worth having if the green word is
hard to say.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.campaign_closeout import (
    MARKER_BLOCKED,
    MARKER_READY,
    MARKER_ROLLED_BACK,
    CloseoutError,
    Item,
    build_attestation,
    decide_marker,
    probe_provider_limits_not_invented,
    probe_single_search_ledger,
)

ROOT = Path(__file__).resolve().parents[1]


def closed(key="k", pri="P0"):
    return Item(key, pri, "a claim", "CLOSED", "measured: 3 rows, exit 0")


# ── the only way to READY ────────────────────────────────────────────────────

def test_ready_requires_every_item_to_close():
    d = decide_marker([closed("a"), closed("b")])
    assert d["marker"] == MARKER_READY
    assert d["blocking"] == []


@pytest.mark.parametrize("bad", ["PARTIAL", "OPEN", "UNMEASURED", "CONTRADICTED"])
def test_a_single_non_closing_item_blocks_the_whole_campaign(bad):
    """Nine closed items and one unmeasured is not 90% ready. It is blocked."""
    items = [closed(f"ok{i}") for i in range(9)]
    items.append(Item("odd", "P1", "a claim", bad, "why"))
    d = decide_marker(items)
    assert d["marker"] == MARKER_BLOCKED
    assert d["blocking"] == ["odd"]
    assert bad in d["reason"]


def test_unmeasured_blocks_exactly_like_a_known_failure():
    """Absent evidence is not neutral. This is the whole thesis of the module."""
    a = decide_marker([closed("x"), Item("y", "P0", "c", "UNMEASURED", "no access")])
    b = decide_marker([closed("x"), Item("y", "P0", "c", "CONTRADICTED", "disagrees")])
    assert a["marker"] == b["marker"] == MARKER_BLOCKED


def test_an_empty_closeout_is_blocked_not_ready():
    """Assessing nothing must not be indistinguishable from passing everything."""
    d = decide_marker([])
    assert d["marker"] == MARKER_BLOCKED
    assert "empty" in d["reason"]


# ── things a closeout is not allowed to say ─────────────────────────────────

def test_an_item_cannot_be_closed_without_evidence():
    with pytest.raises(CloseoutError, match="requires evidence"):
        Item("k", "P0", "a claim", "CLOSED", "")
    with pytest.raises(CloseoutError, match="requires evidence"):
        Item("k", "P0", "a claim", "NOT_APPLICABLE", "   ")


def test_an_unknown_disposition_is_refused_rather_than_treated_as_blocking():
    """Fail loudly. A typo silently blocking would be survivable; a typo silently
    CLOSING would not, and neither should be possible."""
    with pytest.raises(CloseoutError, match="is not a disposition"):
        Item("k", "P0", "a claim", "PROBABLY_FINE", "vibes")


def test_there_is_no_disposition_that_accepts_risk_into_ready():
    """An operator may accept a risk. A program may not spell that as READY."""
    from scripts.lib.campaign_closeout import CLOSING_DISPOSITIONS
    assert CLOSING_DISPOSITIONS == {"CLOSED", "NOT_APPLICABLE"}
    for word in ("ACCEPTED_RISK", "WAIVED", "DEFERRED", "ACKNOWLEDGED"):
        with pytest.raises(CloseoutError):
            Item("k", "P0", "c", word, "e")


def test_rolled_back_is_stated_never_inferred():
    """'We could not prove it worked' and 'we undid it' are different outcomes."""
    items = [Item("y", "P0", "c", "OPEN", "unfinished")]
    assert decide_marker(items)["marker"] == MARKER_BLOCKED
    assert decide_marker(items, rolled_back=True)["marker"] == MARKER_ROLLED_BACK


def test_rolled_back_still_reports_what_was_blocking():
    """A rollback must not erase the record of why."""
    d = decide_marker([closed("a"), Item("b", "P1", "c", "OPEN", "e")], rolled_back=True)
    assert d["marker"] == MARKER_ROLLED_BACK
    assert d["blocking"] == ["b"]


# ── the attestation envelope ────────────────────────────────────────────────

def test_the_attestation_grants_nothing():
    att = build_attestation("c", [closed("a")])
    assert "READ_ONLY_ADVISORY" in att["authority"]
    assert "authorizes no deployment" in att["authority"]


def test_counts_and_items_survive_into_the_record():
    att = build_attestation("c", [closed("a"), Item("b", "P1", "c", "OPEN", "e")])
    assert att["counts"] == {"CLOSED": 1, "OPEN": 1}
    assert {i["key"] for i in att["items"]} == {"a", "b"}
    assert att["marker"] == MARKER_BLOCKED


# ── the probes must measure the claim they state ────────────────────────────

def test_provider_limit_probe_ignores_docstrings_that_quote_the_defect():
    """Documenting a removed defect must not read as committing it.

    The first version scanned raw lines, so the docstrings explaining the fix
    flagged as the fix's absence. Comments and docstrings are different token
    types and must be told apart.
    """
    disposition, evidence = probe_provider_limits_not_invented(ROOT)
    assert disposition == "CLOSED", evidence


def test_single_ledger_probe_reports_closed_on_this_tree():
    disposition, evidence = probe_single_search_ledger(ROOT)
    assert disposition == "CLOSED", evidence
    assert "try_consume" in evidence or "reserves" in evidence


def test_single_ledger_probe_trips_when_the_second_writer_returns(tmp_path):
    """Negative control: a tree with a live legacy writer must not read CLOSED."""
    fake = tmp_path / "scripts"
    fake.mkdir()
    (fake / "brave_search.py").write_text(
        "def _record_call(c):\n"
        "    budget = {}\n"
        "    _save_budget(budget)\n"
        "def _save_budget(d):\n"
        "    _save_budget(d)\n"
        "try_consume = None\n_refund = None\n",
        encoding="utf-8")
    disposition, evidence = probe_single_search_ledger(tmp_path)
    assert disposition == "OPEN", evidence
    assert "still counts" in evidence
