"""One derivation of cash as-of, at every point that publishes the cash figure.

The defect, measured on the served release `4baf677d` (2026-08-30, CURRENT pin
`.../portfolio-server/4baf677d-main-exact-phase2-20260830-193256`) via the live
`GET /api/v3/cio/home`:

    capital_plan.cash_as_of.as_of              "2026-08-03"            27 days
    cio_now.decisions[].freshness.board[cash]  "2026-08-30T12:00:24Z"  11.7 h,
                                               quality VERIFIED_CURRENT
    cash_letter.as_of                          "2026-08-30T23:45:01Z"  0 s
    /cash (operator product)                   no stamp at all

One figure -- $630,784.82 -- and four different ages, of which one was true.

THE RULE these tests pin: the block is dated by the OLDEST balance that
contributes to it. It is the only rule that cannot overstate freshness, and it
is the one the operator needs, because the flattering alternatives are all
available and all wrong:

    freshest       -- $585,917 confirmed 08-14 hides $500 last seen 08-03
    weighted       -- 99.9% of the money is fresher, so the average says fresh
    composition    -- the moment the builder ran, which is always "now"
    document clock -- the holdings repricing time, which is about equity marks

Each of those is mutation-tested below: the assertions must FAIL under them, or
they are not assertions, they are decoration.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib import cio_cash_evidence as ev
from scripts.lib import cio_capital_plan as cp
from scripts.lib import cio_command_center as cc
from scripts.lib import cio_freshness_materiality_gate as fg
from scripts.lib import cio_operator_product as op
from scripts.lib import cio_policy_provenance as pp
from scripts.lib import cio_record_narrative as rn

# ── The live shape, reduced ────────────────────────────────────────────────
#
# The proportions are the ones that make the rule matter: 0.08% of the money is
# the oldest, and it is the oldest by eleven days.

TINY_OLD_USD = 500.0
BIG_FRESH_USD = 585_917.80
OLDEST = "2026-08-03"
NEWEST = "2026-08-14"
DOC_CLOCK = "2026-08-30T12:00:24+00:00"

ROWS = [
    {"symbol": "CASH", "is_cash": True, "market_value": TINY_OLD_USD,
     "account": "moomoo_taxable_live", "canonical_mark_as_of": OLDEST},
    {"symbol": "CASH", "is_cash": True, "market_value": BIG_FRESH_USD,
     "account": "schwab_rollover_ira", "canonical_mark_as_of": NEWEST,
     # Collected later than it was confirmed. The confirmation is the evidence.
     "as_of": "2026-08-26", "updated_at": DOC_CLOCK},
    {"symbol": "SCHD", "market_value": 100_000.0, "account": "schwab_taxable",
     "source_as_of": DOC_CLOCK},
]
DOC = {"as_of": DOC_CLOCK, "last_repriced": DOC_CLOCK,
       "generated_at": DOC_CLOCK, "holdings": ROWS}

CASH_TOTAL = TINY_OLD_USD + BIG_FRESH_USD
NOW = datetime(2026, 8, 30, 23, 45, 1, tzinfo=timezone.utc)


def _plan():
    """A capital plan carrying the honest block, as the real builder produces."""
    return cp.build_capital_plan(
        portfolio_value=CASH_TOTAL + 100_000.0,
        cash_total=CASH_TOTAL,
        positions=[],
        accounts={},
        account_cash=cp.account_cash_breakdown(ROWS),
        cash_as_of=ev.cash_evidence_as_of(ROWS, DOC),
        now=NOW,
    )


# ── The rule itself ────────────────────────────────────────────────────────

def test_a_tiny_very_old_balance_dates_the_whole_block():
    """$500 last confirmed 08-03 outranks $585,917 confirmed 08-14.

    This is the case the rule exists for. Under every flattering alternative
    the block would read 08-14 or later, because 99.9% of the money did.
    """
    block = ev.cash_evidence_as_of(ROWS, DOC)
    assert block["as_of"] == OLDEST
    assert block["oldest_row_as_of"] == OLDEST
    assert block["newest_row_as_of"] == NEWEST
    assert block["mixed_ages"] is True
    # And the money it out-votes really is three orders of magnitude larger.
    by = {r["account"]: r for r in block["by_account"]}
    assert by["moomoo_taxable_live"]["settled_cash_usd"] == TINY_OLD_USD
    assert by["schwab_rollover_ira"]["settled_cash_usd"] == BIG_FRESH_USD
    assert by["schwab_rollover_ira"]["settled_cash_usd"] > 1000 * TINY_OLD_USD


def test_the_document_clock_never_becomes_the_cash_clock():
    """The holdings doc was repriced today. That is about equity marks."""
    block = ev.cash_evidence_as_of(ROWS, DOC)
    assert block["as_of"] != DOC_CLOCK
    assert block["document_as_of"] == DOC_CLOCK  # carried for contrast, only


def test_a_collector_write_time_never_outranks_a_broker_confirmation():
    """The Schwab row was collected 08-26 and confirmed 08-14."""
    block = ev.cash_evidence_as_of(ROWS, DOC)
    by = {r["account"]: r for r in block["by_account"]}
    assert by["schwab_rollover_ira"]["as_of"] == NEWEST


def test_no_stamp_anywhere_is_a_visible_absence_not_a_borrowed_clock():
    block = ev.cash_evidence_as_of(
        [{"is_cash": True, "market_value": 1.0, "account": "mystery"}], DOC)
    assert block["as_of"] is None
    assert block["unstamped"] is True
    assert block["unstamped_accounts"] == ["mystery"]


def test_the_per_account_ages_are_answerable_from_the_block_itself():
    """"Why is this stale" without running a query."""
    block = ev.cash_evidence_as_of(ROWS, DOC)
    rows = block["by_account"]
    assert [r["as_of"] for r in rows] == [OLDEST, NEWEST]  # oldest first
    for row in rows:
        assert set(row) == {"account", "settled_cash_usd", "as_of"}


# ── Mutation: the assertion must fail under the flattering rules ───────────
#
# Bound at import so a mutant stays a mutant when the module attribute is
# monkeypatched out from under it.
_REAL_DERIVATION = ev.cash_evidence_as_of
#
# Each mutant is a derivation someone could plausibly have written, and each is
# one of the rules a publication point on the served release was actually using.

def _mutant_freshest(rows, doc=None):
    block = _REAL_DERIVATION(rows, doc)
    block["as_of"] = block["newest_row_as_of"]
    return block


def _mutant_composition(rows, doc=None):
    block = _REAL_DERIVATION(rows, doc)
    block["as_of"] = NOW.isoformat()
    return block


def _mutant_document_clock(rows, doc=None):
    block = _REAL_DERIVATION(rows, doc)
    block["as_of"] = block["document_as_of"]
    return block


def _mutant_value_weighted(rows, doc=None):
    """The stamp on whichever account holds the most money."""
    block = _REAL_DERIVATION(rows, doc)
    heaviest = max(block["by_account"], key=lambda r: r["settled_cash_usd"])
    block["as_of"] = heaviest["as_of"]
    return block


MUTANTS = {
    "freshest": _mutant_freshest,
    "composition_timestamp": _mutant_composition,
    "document_clock": _mutant_document_clock,
    "value_weighted": _mutant_value_weighted,
}


def _the_rule(derive):
    """The assertion under test, parameterised over the derivation."""
    block = derive(ROWS, DOC)
    assert block["as_of"] == OLDEST, (
        f"block dated {block['as_of']!r}, but its stalest balance is {OLDEST!r}")


def test_the_rule_holds_for_the_real_derivation():
    _the_rule(_REAL_DERIVATION)


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_the_rule_fails_for_every_flattering_derivation(name):
    """If this passes, the assertion above was not testing anything."""
    with pytest.raises(AssertionError):
        _the_rule(MUTANTS[name])


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_every_publication_point_breaks_when_the_derivation_is_mutated(
        name, monkeypatch):
    """Proof that the surfaces read the shared derivation and not a copy.

    Swap the one function, and every publication point must move with it. A
    surface that keeps saying 2026-08-03 here has its own private copy of the
    rule, which is the defect coming back.
    """
    monkeypatch.setattr(ev, "cash_evidence_as_of", MUTANTS[name])
    monkeypatch.setattr(cp, "cash_evidence_as_of", MUTANTS[name])
    monkeypatch.setattr(op, "cash_evidence_as_of", MUTANTS[name])
    block = MUTANTS[name](ROWS, DOC)
    assert block["as_of"] != OLDEST
    # The plan is the source every other point reads from.
    plan = cp.build_capital_plan(
        portfolio_value=CASH_TOTAL, cash_total=CASH_TOTAL, positions=[],
        accounts={}, cash_as_of=block, now=NOW)
    assert plan["cash_as_of"]["as_of"] != OLDEST
    assert cc.build_capital_plan(plan)["cash_as_of"]["as_of"] != OLDEST
    assert rn.build_cash_letter(None, capital_plan=plan, now=NOW)["as_of"] != OLDEST


# ── Every publication point, one answer ────────────────────────────────────

def test_publication_point_1_the_capital_plan_and_its_surface():
    plan = _plan()
    assert plan["cash_as_of"]["as_of"] == OLDEST
    # The envelope clock is still published, under a name that says what it is.
    assert plan["as_of"] == NOW.isoformat()
    assert plan["as_of"] != plan["cash_as_of"]["as_of"]
    surface = cc.build_capital_plan(plan)
    assert surface["cash_as_of"]["as_of"] == OLDEST
    assert surface["cash_as_of"]["by_account"] == plan["cash_as_of"]["by_account"]


def test_publication_point_2_the_cash_letter_dates_the_money_not_the_build():
    """It stamped itself `now` and printed the cash figure underneath."""
    letter = rn.build_cash_letter(None, capital_plan=_plan(), now=NOW)
    assert letter["as_of"] == OLDEST
    assert letter["composed_at"] == NOW.isoformat()
    assert letter["cash_as_of"]["oldest_row_as_of"] == OLDEST
    assert letter["cash_as_of"]["by_account"]


def test_the_cash_letter_says_unknown_rather_than_now_when_the_plan_is_silent():
    letter = rn.build_cash_letter(None, capital_plan={"cash_total_usd": 1.0}, now=NOW)
    assert letter["as_of"] is None
    assert letter["cash_as_of"]["unstamped"] is True
    assert letter["composed_at"] == NOW.isoformat()


def test_publication_point_3_the_freshness_board_reads_the_cash_rows():
    """It was reading `holdings_ts` -- the document's repricing clock."""
    stamps = fg.collect_evidence_timestamps(decision={"symbol": "SCHD"},
                                            holdings_doc=DOC)
    assert stamps["cash"] == OLDEST
    assert stamps["holdings"] == DOC_CLOCK      # unchanged; a different class
    assert stamps["cash"] != stamps["holdings"]
    assert stamps["cash_evidence"]["by_account"]


def test_publication_point_3_publishes_the_true_age_and_the_breakdown():
    out = fg.evaluate_decision_actionability(
        {"symbol": "SCHD", "stance": "HOLD"}, holdings_doc=DOC, now=NOW)
    cash = [b for b in out["freshness_board"] if b["name"] == "cash"][0]
    assert cash["source_as_of"].startswith(OLDEST)
    # 27 days against a 48h policy window: stale, and it now says so.
    assert cash["age_seconds"] > 20 * 24 * 3600
    assert cash["quality"] == fg.STATE_STALE
    assert cash["pass"] is False
    breakdown = cash["cash_evidence"]["by_account"]
    assert [r["account"] for r in breakdown] == [
        "moomoo_taxable_live", "schwab_rollover_ira"]


def test_publication_point_4_provenance_stops_calling_a_number_current():
    """`freshness = "CURRENT" if value is not None` -- presence as proof."""
    plan = _plan()
    out = pp.audit_cash_posture_policy(
        cash_total_usd=plan["cash_total_usd"],
        portfolio_value_usd=plan["portfolio_value_usd"],
        live_band=plan["cash_policy_band"], live_status="ABOVE_BAND",
        policy=None, cash_as_of=plan["cash_as_of"])
    facts = {f["field"]: f for f in out["material_fact"]}
    assert facts["observed_cash_usd"]["freshness"] == pp.FRESH_AS_OF
    assert facts["observed_cash_usd"]["effective_at"] == OLDEST
    assert facts["observed_cash_usd"]["freshness"] != "CURRENT"
    # A ratio is no fresher than its numerator.
    assert facts["cash_pct"]["effective_at"] == OLDEST


def test_publication_point_4_undated_cash_is_undated_not_current():
    out = pp.audit_cash_posture_policy(
        cash_total_usd=CASH_TOTAL, portfolio_value_usd=CASH_TOTAL,
        live_band=None, live_status="", policy=None, cash_as_of=None)
    facts = {f["field"]: f for f in out["material_fact"]}
    assert facts["observed_cash_usd"]["freshness"] == pp.FRESH_UNDATED
    assert facts["observed_cash_usd"]["effective_at"] is None


def test_publication_point_5_the_operator_products_cash_block_carries_a_date():
    """It published a figure, a count, and no date whatsoever."""
    block = ev.cash_evidence_as_of(ROWS, DOC)
    cash = {"cash_usd": round(CASH_TOTAL, 2), "cash_n": 2, "status": "PRESENT",
            "as_of": block["as_of"], "cash_as_of": block}
    assert cash["as_of"] == OLDEST
    assert cash["cash_as_of"]["by_account"]
    # And it is not the document clock the sibling `portfolio` block carries.
    assert cash["as_of"] != DOC_CLOCK


def test_the_operator_product_reader_produces_that_block_from_a_real_doc(tmp_path):
    import json
    holdings = tmp_path / "holdings.json"
    holdings.write_text(json.dumps(DOC))

    def _fake_load(name, root=None):
        return {"available": True, "data": DOC}

    original = op.load_json_store
    op.load_json_store = _fake_load
    try:
        out = op._holdings_sections(None)
    finally:
        op.load_json_store = original
    assert out["cash"]["as_of"] == OLDEST
    assert out["cash"]["cash_as_of"]["oldest_row_as_of"] == OLDEST
    assert out["portfolio"]["as_of"] == DOC_CLOCK   # the equity clock, unchanged


# ── The four points agree, which is the whole point ────────────────────────

def test_every_publication_point_reports_the_same_age():
    plan = _plan()
    letter = rn.build_cash_letter(None, capital_plan=plan, now=NOW)
    surface = cc.build_capital_plan(plan)
    stamps = fg.collect_evidence_timestamps(decision={"symbol": "SCHD"},
                                            holdings_doc=DOC)
    prov = pp.audit_cash_posture_policy(
        cash_total_usd=plan["cash_total_usd"],
        portfolio_value_usd=plan["portfolio_value_usd"],
        live_band=plan["cash_policy_band"], live_status="ABOVE_BAND",
        policy=None, cash_as_of=plan["cash_as_of"])
    prov_cash = [f for f in prov["material_fact"] if f["field"] == "observed_cash_usd"][0]
    op_block = ev.cash_evidence_as_of(ROWS, DOC)

    published = {
        "capital_plan.cash_as_of": plan["cash_as_of"]["as_of"],
        "command_center.cash.cash_as_of": surface["cash_as_of"]["as_of"],
        "cash_letter.as_of": letter["as_of"],
        "freshness_board.cash": stamps["cash"],
        "policy_provenance.observed_cash_usd.effective_at": prov_cash["effective_at"],
        "operator_product.cash.as_of": op_block["as_of"],
    }
    assert set(published.values()) == {OLDEST}, published


def test_no_dollar_amount_moved():
    """This was a labelling fix. The money is the operator's, not ours."""
    plan = _plan()
    assert plan["cash_total_usd"] == round(CASH_TOTAL, 2)
    assert cc.build_capital_plan(plan)["cash_total_usd"] == round(CASH_TOTAL, 2)
    letter = rn.build_cash_letter(None, capital_plan=plan, now=NOW)
    assert letter["cash_usd"] == round(CASH_TOTAL, 2)
    per_account = {r["account"]: r["settled_cash_usd"]
                   for r in plan["cash_as_of"]["by_account"]}
    assert per_account == {"moomoo_taxable_live": TINY_OLD_USD,
                           "schwab_rollover_ira": BIG_FRESH_USD}
    assert sum(per_account.values()) == CASH_TOTAL
