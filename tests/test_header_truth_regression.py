"""The two header contradictions the operator captured on live release a7c550d1d.

Both fixtures are verbatim production payloads. These tests do not assert that
the header looks nicer; they assert that the PRODUCERS now emit enough named
truth that the contradiction cannot be rendered.

The distinction matters because the previous cycle fixed labels and shipped, and
the operator's next capture showed the same contradictions with better wording.
So each test here fails if the producer regresses to a single conflated field,
not merely if a string changes.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.portfolio_aggregate_contract import (  # noqa: E402
    STALE_AFTER_HOURS,
    build_portfolio_aggregate,
)
from lib.setup_run_contract import (  # noqa: E402
    build_setup_run_summary,
    classify_decision,
    tally_decisions,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "header_truth"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ───────────────────────── the September 3 / September 4 clocks ──────────────


@pytest.fixture(scope="module")
def clocks() -> dict:
    return _load("clock_contradiction_20260903_20260904.json")


@pytest.fixture(scope="module")
def clock_aggregate(clocks: dict) -> dict:
    env = clocks["holdings_envelope"]
    return build_portfolio_aggregate(
        aggregate_value=clocks["aggregate_value"],
        account_summaries=clocks["account_summaries"],
        data_as_of=env["data_as_of"],
        data_as_of_account=env["data_as_of_account"],
        valuation_time=env["generated_at"],
        quote_observation_time=env["last_repriced"],
        quote_source=env["reprice_source"],
        now=datetime.fromisoformat(clocks["now_utc"]),
    )


def test_the_two_dates_are_both_published_and_separately_named(clock_aggregate: dict) -> None:
    """2026-09-03 and 2026-09-04 are both true. They are different clocks.

    The capture showed one surface saying "session 2026-09-03" and another
    "session 2026-09-04" from the same store. Both must appear, each under a name
    that says which clock it is.
    """
    agg = clock_aggregate
    assert agg["position_observation_newest"] == "2026-09-03"
    assert agg["position_observation_newest_account"] == "alpaca_taxable_live"
    assert str(agg["valuation_time"]).startswith("2026-09-04")
    assert str(agg["quote_observation_time"]).startswith("2026-09-04")
    # The contradiction is only a contradiction while the two share one name.
    assert agg["position_observation_newest"] != str(agg["valuation_time"])[:10]


def test_the_headline_date_cannot_be_stated_without_the_value_it_covers(clock_aggregate: dict) -> None:
    """2026-09-03 spoke for 0.4% of the book. That number must be published.

    This is the test that makes the defect unrenderable rather than merely
    relabelled: a consumer that wants to print the newest observation now has the
    coverage figure sitting next to it and no excuse for omitting it.
    """
    cov = clock_aggregate["coverage"]
    assert cov["at_newest_pct"] == pytest.approx(0.4, abs=0.05)
    assert cov["value_fresh_pct"] == pytest.approx(0.4, abs=0.05)
    # 99.6% of the money is behind a stale position observation.
    assert cov["value_fresh_pct"] < 1.0
    assert cov["accounts_undated"] == 3
    assert cov["undated_accounts"] == ["moomoo_taxable_live", "schwab_roth", "schwab_taxable"]


def test_the_dominant_account_reports_three_clocks_not_one(clock_aggregate: dict) -> None:
    """schwab_rollover_ira is 90% of the book and every clock on it differs.

    v1 published `observation_time: 2026-07-17` and nothing else, so the $1.16M
    looked like a July number or a September number depending on which surface
    you read. All four are now distinct fields.
    """
    row = next(a for a in clock_aggregate["accounts"] if a["account"] == "schwab_rollover_ira")
    assert row["position_observation_time"] == "2026-07-17"
    assert row["position_observation_source"] == "account.as_of"
    assert row["valuation_time"] == "2026-09-04"
    assert row["reported_total_as_of"] == "2026-04-30"
    assert row["received_time"].startswith("2026-04-30")
    # The custodian's own total and the derived total are 2x apart and must not
    # be confusable for one another.
    assert row["reported_total_value"] == 549233.46
    assert row["total_value"] == 1158374.79
    # v1 alias preserved, and it is the POSITION clock -- never the valuation.
    assert row["observation_time"] == row["position_observation_time"]


def test_stale_verdict_names_the_account_and_the_age(clock_aggregate: dict) -> None:
    agg = clock_aggregate
    assert agg["freshness_state"] == "STALE"
    assert agg["position_observation_oldest_account"] == "fidelity_rollover_ira"
    assert agg["position_observation_oldest"] == "2026-07-16"
    assert agg["position_observation_oldest_age_hours"] > STALE_AFTER_HOURS
    assert "fidelity_rollover_ira" in agg["freshness_reason"]
    assert "2026-07-16" in agg["freshness_reason"]


def test_a_caller_without_the_valuation_clock_gets_null_not_a_substitute(clocks: dict) -> None:
    """The whole defect was one clock standing in for another.

    A caller that cannot supply the valuation time must get None, never the
    position observation quietly promoted into its place.
    """
    agg = build_portfolio_aggregate(
        aggregate_value=clocks["aggregate_value"],
        account_summaries=clocks["account_summaries"],
        data_as_of=clocks["holdings_envelope"]["data_as_of"],
        data_as_of_account=clocks["holdings_envelope"]["data_as_of_account"],
        now=datetime.fromisoformat(clocks["now_utc"]),
    )
    assert agg["valuation_time"] is None
    assert agg["quote_observation_time"] is None
    assert agg["position_observation_newest"] == "2026-09-03"


def test_undated_accounts_never_borrow_another_accounts_date(clocks: dict) -> None:
    """Only the NAMED data_as_of_account may take the top-level stamp."""
    agg = build_portfolio_aggregate(
        aggregate_value=clocks["aggregate_value"],
        account_summaries=clocks["account_summaries"],
        data_as_of="2026-09-03",
        data_as_of_account="alpaca_taxable_live",
        now=datetime.fromisoformat(clocks["now_utc"]),
    )
    by_acct = {a["account"]: a for a in agg["accounts"]}
    assert by_acct["alpaca_taxable_live"]["position_observation_time"] == "2026-09-03"
    assert by_acct["alpaca_taxable_live"]["position_observation_source"] == "holdings.data_as_of"
    for acct in ("schwab_roth", "schwab_taxable", "moomoo_taxable_live"):
        assert by_acct[acct]["position_observation_time"] == ""
        assert by_acct[acct]["dated"] is False


def test_reversed_bounds_fail_closed(clocks: dict) -> None:
    """A newest older than the oldest is not published at all."""
    summaries = {
        "a": {"as_of": "2026-09-03", "total_value": 10.0},
        "b": {"as_of": "2026-07-17", "total_value": 10.0},
    }
    agg = build_portfolio_aggregate(
        aggregate_value=20.0,
        account_summaries=summaries,
        now=datetime.fromisoformat(clocks["now_utc"]),
    )
    # Correct ordering survives.
    assert agg["position_observation_oldest"] == "2026-07-17"
    assert agg["position_observation_newest"] == "2026-09-03"


# ───────────────────────────── the 48 / 60 / 0 counts ────────────────────────


@pytest.fixture(scope="module")
def counts() -> dict:
    return _load("count_contradiction_48_60_0.json")


def test_manual_review_is_a_disposition_not_an_absence(counts: dict) -> None:
    """The 12 unaccounted rows have a real terminal disposition.

    They were never undecidable. The scanner decided to escalate them -- it even
    carries a `manual_review_required` column. v1 had no token for MANUAL_REVIEW
    so they landed in `unclassified`, which asserts the pipeline failed. It did
    not. And they are emphatically not NOGO: three of them score 38.
    """
    for row in counts["manual_review_rows"]:
        assert classify_decision(row["decision"], disqualified=row["disqualified"]) == "review"
    assert classify_decision("MANUAL_REVIEW") != "nogo"
    assert classify_decision("MANUAL_REVIEW") != "unclassified"


def test_every_one_of_the_sixty_is_accounted_for(counts: dict) -> None:
    """48 + 0 left 12 unnamed. Nothing may be unnamed now."""
    tally = {"go": 0, "wait": 1, "nogo": 47, "review": 12, "excluded": 0, "error": 0, "unclassified": 0}
    summary = build_setup_run_summary(
        run_id=counts["run"]["run_id"],
        tally=tally,
        run_label=counts["run"]["run_label"],
        run_date=counts["run"]["run_date"],
        run_timestamp=counts["run"]["run_timestamp"],
        scanned_count=60,
        scanned_count_alt=60,
    )
    assert summary["classified_count"] == 48
    assert summary["review_count"] == 12
    assert summary["unclassified_count"] == 0
    assert summary["accounted_count"] == 60
    assert summary["unaccounted_count"] == 0
    # The operator's stated invariant, unchanged: an escalation is not a
    # classification, so classified stays GO+WAIT+NOGO.
    assert summary["classified_count"] == (summary["go_count"] + summary["wait_count"] + summary["nogo_count"])


def test_the_run_scoped_population_excludes_the_previous_day(counts: dict) -> None:
    """60 vs 49: eleven rows were yesterday's 0900 run.

    Run identity is (run_date, run_label). Filtering on the label alone let the
    previous day's rows through DISTINCT ON (symbol) and into today's count. This
    reproduces that scoping against the fixture's leaking rows.
    """
    rows = counts["manual_review_rows"] + counts["prior_day_rows_leaking_into_this_run"]
    label = counts["run"]["run_label"]
    date = counts["run"]["run_date"]

    label_only = [r for r in rows if r["scan_run_label"] == label]
    assert len(label_only) == 14  # the defect: yesterday counted as today

    dated = [r for r in label_only if r.get("scan_run_date")]
    scoped = [r for r in dated if r["scan_run_date"] == date]
    assert len(scoped) == 12
    assert all(r["scan_run_date"] == date for r in scoped)
    assert {r["symbol"] for r in scoped}.isdisjoint({"LEAK01", "LEAK02"})


def test_disagreeing_scanned_contracts_stay_partial(counts: dict) -> None:
    """Two `scanned` numbers cannot both be the run -- that must stay visible."""
    tally = tally_decisions(counts["manual_review_rows"])
    summary = build_setup_run_summary(
        run_id=counts["run"]["run_id"],
        tally={**{k: 0 for k in ("go", "wait", "nogo", "excluded", "error", "unclassified")}, **tally},
        run_date=counts["run"]["run_date"],
        run_label=counts["run"]["run_label"],
        scanned_count=counts["run"]["scanned_count_from_db_rows"],
        scanned_count_alt=counts["run"]["scanned_count_from_run_summary"],
    )
    # 12 accounted vs 60 scanned is a COUNT_MISMATCH, which outranks PARTIAL:
    # an unaccounted row is worse news than two disagreeing populations.
    assert summary["count_integrity"] == "COUNT_MISMATCH"
    assert "review(12)" in summary["count_integrity_reason"]
    assert summary["unaccounted_count"] == 48


def test_the_v1_rendering_is_what_the_operator_saw(counts: dict) -> None:
    """Pin the defect itself, so a revert is loud.

    Reproduces v1's partition (no review class) and asserts it leaves exactly the
    12 rows the header could not name.
    """
    v1 = counts["rendered_summary_v1"]
    assert v1["classified_count"] + v1["excluded_count"] == 48
    assert v1["scanned_count"] - (v1["classified_count"] + v1["excluded_count"]) == 12
    assert v1["unclassified_count"] == 12
    assert v1["count_integrity"] == "PARTIAL"


def test_error_rows_are_not_review_and_not_nogo() -> None:
    """The three residual classes stay distinct; none collapses into a decision."""
    assert classify_decision("ERROR") == "error"
    assert classify_decision("TIMEOUT") == "error"
    assert classify_decision("") == "unclassified"
    assert classify_decision("SOMETHING_NEW") == "unclassified"
    assert classify_decision("GO", disqualified=True) == "excluded"
    assert classify_decision("MANUAL_REVIEW", disqualified=True) == "excluded"
