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


def _position_rows(clocks: dict) -> list[dict]:
    """Expand the captured per-account row counts into holdings rows."""
    out: list[dict] = []
    for acct, meta in clocks["position_rows_by_account"].items():
        if acct.startswith("_"):
            continue
        for _ in range(int(meta["rows"])):
            out.append(
                {
                    "account": acct,
                    "broker_position_as_of": meta["broker_position_as_of"],
                    "source": meta["source"],
                    "updated_at": meta["updated_at"],
                }
            )
    return out


@pytest.fixture(scope="module")
def summaries_only_aggregate(clocks: dict) -> dict:
    """What v2 built: account_summaries alone, with no position rows.

    This is the defective reading, kept so the correction below is measurable
    against it rather than merely asserted.
    """
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


@pytest.fixture(scope="module")
def clock_aggregate(clocks: dict) -> dict:
    """The corrected reading: the maintained position rows date the accounts."""
    env = clocks["holdings_envelope"]
    return build_portfolio_aggregate(
        aggregate_value=clocks["aggregate_value"],
        account_summaries=clocks["account_summaries"],
        positions=_position_rows(clocks),
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
    # Both dates the operator saw are present, each under the clock it belongs
    # to: 2026-09-03 is when alpaca's positions were last observed, 2026-09-04
    # is when schwab's were AND when the book was valued.
    assert agg["position_observation_oldest"] == "2026-09-03"
    assert agg["position_observation_oldest_account"] == "alpaca_taxable_live"
    assert agg["position_observation_newest"] == "2026-09-04"
    assert str(agg["valuation_time"]).startswith("2026-09-04")
    assert str(agg["quote_observation_time"]).startswith("2026-09-04")
    # The position bound and the valuation clock remain separate fields even
    # when they happen to agree on a date -- that is what stops one standing in
    # for the other the next time they diverge.
    assert agg["position_observation_oldest"] != str(agg["valuation_time"])[:10]


def test_the_headline_date_cannot_be_stated_without_the_value_it_covers(
    clock_aggregate: dict, summaries_only_aggregate: dict
) -> None:
    """Coverage must travel with the date -- and be computed from the LIVE copy.

    Reading account_summaries.as_of alone made the book look 0.4% observed. That
    number was an artifact: portfolio_loader never updates that field, so it held
    2026-07-17 for an account whose positions had been re-synced that morning.
    Both readings are pinned, because the gap between them IS the defect.
    """
    stale_read = summaries_only_aggregate["coverage"]
    assert stale_read["at_newest_pct"] == pytest.approx(0.4, abs=0.05)
    assert stale_read["value_fresh_pct"] == pytest.approx(0.4, abs=0.05)

    live = clock_aggregate["coverage"]
    assert live["value_dated_pct"] == 100.0
    assert live["value_fresh_pct"] == 100.0
    assert live["at_newest_pct"] == pytest.approx(99.6, abs=0.05)
    assert live["accounts_undated"] == 0

    # Empty accounts are named, not counted as unobserved coverage.
    assert live["accounts_contributing"] == 4
    assert live["non_contributing_accounts"] == ["fidelity_rollover_ira", "moomoo_taxable_live"]


def test_the_two_copies_of_the_position_clock_are_both_published(clock_aggregate: dict) -> None:
    """Never auto-remediate a divergent store: report both and say which governs."""
    row = next(a for a in clock_aggregate["accounts"] if a["account"] == "schwab_rollover_ira")
    assert row["position_observation_time"] == "2026-09-04"
    assert row["position_observation_source"] == "holdings.broker_position_as_of"
    assert row["summary_as_of"] == "2026-07-17"
    assert row["observation_divergence"] is not None
    assert "2026-09-04" in row["observation_divergence"]
    assert "2026-07-17" in row["observation_divergence"]

    reported = {d["account"] for d in clock_aggregate["observation_divergences"]}
    assert "schwab_rollover_ira" in reported


def test_the_dominant_account_reports_every_clock_separately(clock_aggregate: dict) -> None:
    """schwab_rollover_ira is 90% of the book and every clock on it differs.

    v1 published `observation_time: 2026-07-17` and nothing else, so the $1.16M
    looked like a July number or a September number depending on which surface
    you read.
    """
    row = next(a for a in clock_aggregate["accounts"] if a["account"] == "schwab_rollover_ira")
    assert row["position_observation_time"] == "2026-09-04"  # from the live rows
    assert row["summary_as_of"] == "2026-07-17"  # the abandoned mirror
    assert row["valuation_time"] == "2026-09-04"
    assert row["reported_total_as_of"] == "2026-04-30"
    assert row["received_time"].startswith("2026-04-30")
    assert row["position_row_count"] == 14
    # The custodian's own total and the derived total are 2x apart and must not
    # be confusable for one another.
    assert row["reported_total_value"] == 549233.46
    assert row["total_value"] == 1158374.79
    # v1 alias preserved, and it is the POSITION clock -- never the valuation.
    assert row["observation_time"] == row["position_observation_time"]


def test_an_empty_account_cannot_date_the_book(clock_aggregate: dict, summaries_only_aggregate: dict) -> None:
    """fidelity_rollover_ira holds $0 and no rows, and was pinning the book STALE.

    It was merged into schwab_rollover_ira on 2026-07-16 and its stranded stamp
    outlived it. Being the oldest is only meaningful among accounts that
    contribute something.
    """
    # Reading the abandoned mirror still yields a July bound and a STALE book.
    assert summaries_only_aggregate["position_observation_oldest"] == "2026-07-17"
    assert summaries_only_aggregate["freshness_state"] == "STALE"
    # fidelity is excluded from the bound by the contributor rule alone, so it
    # is no longer the named oldest even on the defective reading.
    assert summaries_only_aggregate["position_observation_oldest_account"] != "fidelity_rollover_ira"

    agg = clock_aggregate
    assert agg["position_observation_oldest_account"] == "alpaca_taxable_live"
    assert agg["position_observation_oldest"] == "2026-09-03"
    assert agg["position_observation_newest"] == "2026-09-04"
    assert agg["freshness_state"] == "COMPLETE"
    # The reason counts contributors, not rows in the dict.
    assert "4 of 6" in agg["freshness_reason"]
    assert "2 hold nothing" in agg["freshness_reason"]

    empty = next(a for a in agg["accounts"] if a["account"] == "fidelity_rollover_ira")
    assert empty["contributes"] is False
    assert empty["holds_positions"] is False
    assert empty["position_row_count"] == 0
    # Still published -- excluded from the bound, never dropped from the list.
    assert empty["position_observation_time"] == "2026-07-16"


def test_a_genuinely_stale_contributor_still_trips_stale(clocks: dict) -> None:
    """Negative control: excluding empty accounts must not mute a real one.

    An account with VALUE and an old observation is exactly what STALE is for.
    """
    agg = build_portfolio_aggregate(
        aggregate_value=100_000.0,
        account_summaries={"old_money": {"as_of": "2026-06-01", "total_value": 100_000.0}},
        positions=[{"account": "old_money", "broker_position_as_of": "2026-06-01"}],
        now=datetime.fromisoformat(clocks["now_utc"]),
    )
    assert agg["freshness_state"] == "STALE"
    assert agg["position_observation_oldest_account"] == "old_money"
    assert agg["coverage"]["value_fresh_pct"] == 0.0


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


# ─────────────────────── quote coverage (defect E) ───────────────────────────


def test_a_degraded_quote_aggregate_states_its_extent() -> None:
    """ "quotes DEGRADED (price_cache_nav(1))" named a fault and not its size.

    One fallback row out of 20 and twenty out of 20 rendered identically. The
    per-provider tallies were already in hand; the contract discarded them.
    """
    from lib.quote_selection_contract import project_quote_selection

    q = project_quote_selection(
        reprice_source="finviz_live",
        last_repriced="2026-09-04 15:00:02 ET",
        source_counts={"finviz": 19, "price_cache_nav": 1},
        has_any_price=True,
    )
    assert q["status"] == "DEGRADED"
    assert q["total_symbols"] == 20
    assert q["covered_symbols"] == 19
    assert q["degraded_symbol_count"] == 1
    assert q["coverage_pct"] == 95.0
    assert q["symbols_by_source"] == {"finviz": 19, "price_cache_nav": 1}
    # The session is separable from the observation instant.
    assert q["session_date"] == "2026-09-04"
    assert q["selected_observation_time"] == "2026-09-04 15:00:02 ET"


def test_total_vendor_failure_does_not_read_like_one_stale_row() -> None:
    """The distinction the bare DEGRADED label could not make."""
    from lib.quote_selection_contract import project_quote_selection

    one_bad = project_quote_selection(reprice_source="finviz_live", source_counts={"finviz": 19, "price_cache_nav": 1})
    all_bad = project_quote_selection(reprice_source="finviz_live", source_counts={"price_cache_nav": 20})
    assert one_bad["status"] == all_bad["status"] == "DEGRADED"
    # Same verdict, and now plainly different situations.
    assert one_bad["coverage_pct"] == 95.0
    assert all_bad["coverage_pct"] == 0.0
    assert all_bad["degraded_symbol_count"] == 20


def test_coverage_is_absent_not_invented_when_counts_are_unknown() -> None:
    """No source counts means no coverage claim -- never a reassuring 100%."""
    from lib.quote_selection_contract import project_quote_selection

    q = project_quote_selection(reprice_source="finviz_live", source_counts={})
    assert q["total_symbols"] is None
    assert q["covered_symbols"] is None
    assert q["coverage_pct"] is None
    assert q["degraded_symbol_count"] == 0


# ──────────────── today's P&L: empty is not missing (defect C) ────────────────


def _today_pnl():
    """Load the producer out of api_v2 without importing the whole server."""
    import ast

    src = (ROOT / "scripts" / "api_v2.py").read_text()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_today_pnl_provenance")
    ns: dict = {"Any": object}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<api_v2>", "exec"), ns)
    return ns["_today_pnl_provenance"]


def test_an_empty_account_is_not_a_missing_one(clocks: dict) -> None:
    """TODAY warned "2 acct(s) missing" and flagged STALE over $0 accounts.

    PORTFOLIO called the same two "empty" in the same header. One fact, two
    characterisations -- and one of them claimed data was absent when only
    holdings were.
    """
    fn = _today_pnl()
    out = fn(
        clocks["holdings_envelope"],
        today_by_account={
            "schwab_taxable": {"change": -143.4},
            "alpaca_taxable_live": {"change": 0.0},
        },
        account_summaries=clocks["account_summaries"],
        positions=_position_rows(clocks),
        total_change=-143.4,
    )
    assert out["empty_accounts"] == ["fidelity_rollover_ira", "moomoo_taxable_live"]
    # A flat account is represented, not missing: a real 0 is data.
    assert out["zero_change_accounts"] == ["alpaca_taxable_live"]
    assert out["contributing_accounts"] == ["schwab_taxable"]
    # schwab_roth and schwab_rollover_ira HOLD positions and did not report.
    assert out["missing_accounts"] == ["schwab_rollover_ira", "schwab_roth"]
    assert out["complete"] is False
    assert out["funded_account_count"] == 4


def test_a_funded_account_that_does_not_report_still_breaks_completeness(clocks: dict) -> None:
    """Negative control: the empty/missing split must not mute a real gap."""
    fn = _today_pnl()
    every = {
        "schwab_rollover_ira": {"change": -3255.28},
        "schwab_roth": {"change": -335.51},
        "schwab_taxable": {"change": -143.4},
        "alpaca_taxable_live": {"change": 0.0},
    }
    complete = fn(
        clocks["holdings_envelope"],
        today_by_account=every,
        account_summaries=clocks["account_summaries"],
        positions=_position_rows(clocks),
        total_change=-3734.19,
    )
    assert complete["complete"] is True
    assert complete["missing_accounts"] == []
    assert "2 empty" in complete["coverage_reason"]

    # Drop one FUNDED account and completeness must fail.
    partial = fn(
        clocks["holdings_envelope"],
        today_by_account={k: v for k, v in every.items() if k != "schwab_roth"},
        account_summaries=clocks["account_summaries"],
        positions=_position_rows(clocks),
        total_change=-3398.68,
    )
    assert partial["complete"] is False
    assert partial["missing_accounts"] == ["schwab_roth"]
    assert "MISSING schwab_roth" in partial["coverage_reason"]
