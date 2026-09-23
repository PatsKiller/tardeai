"""The two maturity gates that were provably wrong, pinned against measurement.

WHY THIS SUITE EXISTS
---------------------
Two gates in ``MATURITY_PLAN_4_TO_8.5_2026-09-21_ENHANCED.md`` could not be
passed or could not be compared, for reasons that had nothing to do with the
system's behaviour:

1. **Phase 1** froze the storm baseline at **1,673** — a count taken mid-day on
   2026-09-21 — and then compared it against a *per-day* target. Part of one day
   measured against all of another. The full 09-21 day is **7,627**.

2. **Phase 2** required ">=95% of last-7-day **alerts**" to carry a provider
   message id. 97.67% of rows in ``communication_deliveries`` are ``SUPPRESSED``
   and are deliberately never sent, so no provider id can exist for them. The
   ceiling under that denominator is **2.1%**. The gate was unpassable by any
   amount of correct work, and a gate that cannot be passed teaches nothing.

A restatement is only honest if it cannot also be a loosening. So every check
below is paired with a control that fails when the restatement is softened,
reverted, or made vacuous:

* ``test_all_alerts_denominator_is_mathematically_unreachable`` — proves the OLD
  gate's ceiling is below its own threshold, which is the whole justification
  for touching it.
* ``test_restatement_did_not_lower_the_threshold`` — the 95% bar is unchanged.
* ``test_restated_gate_reports_a_worse_number_than_the_24h_slice`` — the honest
  7-day denominator must not be quietly swapped for the flattering window.
* ``test_corrected_storm_baseline_makes_the_gate_harder`` — 7,627 demands a
  bigger reduction than 1,673 did.
* ``test_a_legal_status_passes_the_same_check`` — keeps the ``SETTLED`` check
  from passing vacuously.
* ``test_old_phase1_wording_is_rejected`` / ``test_old_phase2_wording_is_rejected``
  — the doc predicates are run against the exact superseded text. Without these
  a predicate that returns ``True`` for everything would pass.

Every number here was measured on 2026-09-22 and the command is quoted beside
it. The suite is hermetic: no database, no log, no network.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLAN_DOC = REPO / "docs" / "architecture" / "MATURITY_PLAN_4_TO_8.5_2026-09-21_ENHANCED.md"
STATUS_DOC = REPO / "docs" / "architecture" / "MATURITY_STATUS_2026-09-22.md"

# ---------------------------------------------------------------------------
# Measured 2026-09-22 — storm
#
#   for d in 2026-09-18 ... 2026-09-22; do
#     grep -c "^$d.*exhausted after" \
#       /home/johnclaw/trade-ai-releases/persistent-state/logs/claude_escalation.log
#   done
#
# The log is unrotated back to 2026-08-27 (head -1), so each full date below is
# complete. 09-22 is partial: the log's last line at measurement time was
# 11:40:03 EDT.
# ---------------------------------------------------------------------------
STORM_FULL_DAYS = {
    "2026-09-18": 3682,
    "2026-09-19": 2278,
    "2026-09-20": 6110,
    "2026-09-21": 7627,
}
STORM_BASELINE_DATE = "2026-09-21"
STORM_BASELINE_FULL_DAY = 7627
STORM_PARTIAL_2026_09_22 = 1433
SUPERSEDED_PARTIAL_BASELINE = 1673
STORM_GATE_TARGET_PER_DAY = 20

# ---------------------------------------------------------------------------
# Measured 2026-09-22 — delivery, 7-day window
#
#   SELECT status, count(*), count(provider_message_id)
#   FROM communication_deliveries
#   WHERE reserved_at >= now() - interval '7 days'
#   GROUP BY status;
# ---------------------------------------------------------------------------
DELIVERY_MIX_7D = {
    "SUPPRESSED": 44182,
    "LEGACY_DELIVERED": 885,
    "RESERVED": 112,
    "SENT": 57,
}
WITH_ID_7D_TOTAL = 55          # all 55 sit on SENT rows
WITH_ID_7D_ON_DELIVERED = 55
DPI_7D_ON_DELIVERED = 18       # destination_policy_id non-null

# 24-hour slice, same query with interval '24 hours'. Kept only as the control
# that the flattering window was not substituted for the one the gate names.
DELIVERED_24H = 138
WITH_ID_24H = 19

# status IN (...) — the two terminal success states the schema actually admits.
DELIVERED_STATUSES = frozenset({"SENT", "LEGACY_DELIVERED"})

# communication_deliveries_status_check, read from \d on 2026-09-22.
LEGAL_DELIVERY_STATUSES = frozenset({
    "RESERVED", "SENDING", "SENT", "DELIVERED", "ACKNOWLEDGED", "FAILED",
    "BOUNCED", "SUPPRESSED", "EXPIRED", "CANCELLED", "UNKNOWN",
    "LEGACY_DELIVERED",
})

GATE_THRESHOLD_PCT = 95.0


# ---------------------------------------------------------------------------
# Pure helpers — the arithmetic the gate wording implies
# ---------------------------------------------------------------------------
def denominator(mix: dict[str, int], statuses: frozenset[str] | None = None) -> int:
    """Rows counted by a gate. ``None`` means the original all-rows denominator."""
    if statuses is None:
        return sum(mix.values())
    return sum(n for s, n in mix.items() if s in statuses)


def coverage_pct(with_id: int, denom: int) -> float:
    return round(100.0 * with_id / denom, 1) if denom else 0.0


def ceiling_pct(mix: dict[str, int], denom_statuses: frozenset[str] | None) -> float:
    """Best coverage reachable if EVERY sendable message carried an id.

    A suppressed row is never handed to a provider, so it can never acquire an
    id. That is the fact the original denominator ignored.
    """
    denom = denominator(mix, denom_statuses)
    return round(100.0 * denominator(mix, DELIVERED_STATUSES) / denom, 1) if denom else 0.0


def required_reduction_pct(baseline: int, target: int) -> float:
    return round(100.0 * (1 - target / baseline), 2)


def is_full_day_baseline(count: int) -> bool:
    """A daily baseline must be a full-day count from the measured record."""
    return count in set(STORM_FULL_DAYS.values())


# ---------------------------------------------------------------------------
# Doc predicates — deliberately written so a stale doc returns False
# ---------------------------------------------------------------------------
def phase1_gate_is_restated(text: str) -> bool:
    return (
        "7,627" in text
        and "full day" in text.lower()
        and "partial" in text.lower()
        and "**1,673**, measured by the identical command" not in text
    )


def phase2_gate_is_restated(text: str) -> bool:
    return (
        "status IN ('SENT','LEGACY_DELIVERED')" in text
        and "97.67%" in text
        and "**Gate:** ≥95% of last-7-day alerts carry" not in text
    )


# The exact superseded wording, kept verbatim as the negative control.
OLD_PHASE1_TEXT = (
    "**Gate:** escalation notifications/day **< 20** against the frozen baseline\n"
    "**1,673**, measured by the identical command before and after:\n"
)
OLD_PHASE2_TEXT = (
    "**Gate:** ≥95% of last-7-day alerts carry a `telegram_message_id`; `SETTLED`\n"
    "≥95%; `destination_policy_id` non-null ≥95%.\n"
)


# ===========================================================================
# Phase 1 — the storm baseline
# ===========================================================================
def test_baseline_is_the_full_day_count() -> None:
    assert STORM_FULL_DAYS[STORM_BASELINE_DATE] == STORM_BASELINE_FULL_DAY == 7627


def test_superseded_baseline_was_not_a_full_day() -> None:
    """1,673 matches no measured full day — it was a mid-day slice."""
    assert not is_full_day_baseline(SUPERSEDED_PARTIAL_BASELINE)
    assert SUPERSEDED_PARTIAL_BASELINE < STORM_BASELINE_FULL_DAY


def test_partial_day_count_is_rejected_as_a_baseline() -> None:
    """NEGATIVE CONTROL: today's partial count must never be frozen as daily."""
    assert not is_full_day_baseline(STORM_PARTIAL_2026_09_22)
    assert is_full_day_baseline(STORM_BASELINE_FULL_DAY)


def test_corrected_storm_baseline_makes_the_gate_harder() -> None:
    """NEGATIVE CONTROL against loosening: the bar rose, it did not fall."""
    corrected = required_reduction_pct(STORM_BASELINE_FULL_DAY, STORM_GATE_TARGET_PER_DAY)
    superseded = required_reduction_pct(SUPERSEDED_PARTIAL_BASELINE, STORM_GATE_TARGET_PER_DAY)
    assert corrected == 99.74
    assert superseded == 98.8
    assert corrected > superseded


def test_storm_target_itself_is_unchanged() -> None:
    assert STORM_GATE_TARGET_PER_DAY == 20


# ===========================================================================
# Phase 2 — the delivery denominator
# ===========================================================================
def test_delivered_denominator_is_sent_plus_legacy_delivered() -> None:
    assert denominator(DELIVERY_MIX_7D, DELIVERED_STATUSES) == 942


def test_restated_gate_value_is_five_point_eight_percent() -> None:
    delivered = denominator(DELIVERY_MIX_7D, DELIVERED_STATUSES)
    assert coverage_pct(WITH_ID_7D_ON_DELIVERED, delivered) == 5.8


def test_all_alerts_denominator_is_mathematically_unreachable() -> None:
    """NEGATIVE CONTROL: the ORIGINAL gate could not be passed by any work.

    This is the justification for restating it. If this ever stops holding --
    because suppression fell away -- the restatement needs revisiting, and this
    test is where that shows up.
    """
    all_rows = denominator(DELIVERY_MIX_7D, None)
    assert all_rows == 45236
    assert ceiling_pct(DELIVERY_MIX_7D, None) == 2.1
    assert ceiling_pct(DELIVERY_MIX_7D, None) < GATE_THRESHOLD_PCT
    # ... while the restated denominator CAN reach the bar.
    assert ceiling_pct(DELIVERY_MIX_7D, DELIVERED_STATUSES) == 100.0


def test_suppressed_share_is_why_the_old_denominator_failed() -> None:
    all_rows = denominator(DELIVERY_MIX_7D, None)
    pct = round(100.0 * DELIVERY_MIX_7D["SUPPRESSED"] / all_rows, 2)
    assert pct == 97.67


def test_restatement_did_not_lower_the_threshold() -> None:
    """NEGATIVE CONTROL: only the denominator moved. 95% still means 95%."""
    assert GATE_THRESHOLD_PCT == 95.0
    delivered = denominator(DELIVERY_MIX_7D, DELIVERED_STATUSES)
    assert coverage_pct(WITH_ID_7D_ON_DELIVERED, delivered) < GATE_THRESHOLD_PCT


def test_restated_gate_reports_a_worse_number_than_the_24h_slice() -> None:
    """NEGATIVE CONTROL: the flattering window must not be substituted.

    The gate names 7 days. The 7-day figure is worse than the 24-hour one, so a
    restatement that quietly switched windows would be a loosening.
    """
    seven_day = coverage_pct(
        WITH_ID_7D_ON_DELIVERED, denominator(DELIVERY_MIX_7D, DELIVERED_STATUSES)
    )
    twenty_four_hour = coverage_pct(WITH_ID_24H, DELIVERED_24H)
    assert twenty_four_hour == 13.8
    assert seven_day == 5.8
    assert seven_day < twenty_four_hour


def test_destination_policy_id_restated_on_the_same_denominator() -> None:
    delivered = denominator(DELIVERY_MIX_7D, DELIVERED_STATUSES)
    assert coverage_pct(DPI_7D_ON_DELIVERED, delivered) == 1.9


def test_settled_is_not_a_legal_delivery_status() -> None:
    """The withdrawn clause demanded >=95% of a value the schema forbids."""
    assert "SETTLED" not in LEGAL_DELIVERY_STATUSES


def test_a_legal_status_passes_the_same_check() -> None:
    """NEGATIVE CONTROL: keeps the SETTLED assertion from passing vacuously."""
    for status in DELIVERED_STATUSES:
        assert status in LEGAL_DELIVERY_STATUSES
    assert "SUPPRESSED" in LEGAL_DELIVERY_STATUSES


def test_every_measured_status_is_one_the_schema_admits() -> None:
    assert set(DELIVERY_MIX_7D) <= LEGAL_DELIVERY_STATUSES


# ===========================================================================
# The documents must carry the restatement
# ===========================================================================
def test_plan_doc_phase1_gate_is_restated() -> None:
    assert phase1_gate_is_restated(PLAN_DOC.read_text(encoding="utf-8"))


def test_plan_doc_phase2_gate_is_restated() -> None:
    assert phase2_gate_is_restated(PLAN_DOC.read_text(encoding="utf-8"))


def test_old_phase1_wording_is_rejected() -> None:
    """NEGATIVE CONTROL: the predicate rejects the exact superseded text."""
    assert not phase1_gate_is_restated(OLD_PHASE1_TEXT)


def test_old_phase2_wording_is_rejected() -> None:
    """NEGATIVE CONTROL: the predicate rejects the exact superseded text."""
    assert not phase2_gate_is_restated(OLD_PHASE2_TEXT)


def test_plan_doc_names_the_superseded_figure_as_partial() -> None:
    """The correction must be visible, not silently applied."""
    text = PLAN_DOC.read_text(encoding="utf-8")
    assert "1,673" in text          # still named ...
    assert "PARTIAL day" in text    # ... and labelled for what it was


OLD_STATUS_HEADLINE = (
    "**All six phases are BUILT and INTEGRATED. Nothing is pushed. "
    "Nothing is deployed."
)


def status_doc_records_deployment(text: str) -> bool:
    """True only when the doc ASSERTS deployment.

    The superseded claim is still quoted in the doc on purpose -- a correction
    that erases what it corrects is not a correction. So this rejects the old
    *headline* rather than the phrase, which would also reject the quotation.
    """
    return (
        "f9c77fe1b" in text
        and "MERGED and DEPLOYED" in text
        and OLD_STATUS_HEADLINE not in text
    )


def test_status_doc_records_the_deployment() -> None:
    assert status_doc_records_deployment(STATUS_DOC.read_text(encoding="utf-8"))


def test_old_status_headline_is_rejected() -> None:
    """NEGATIVE CONTROL: the predicate rejects the exact superseded headline."""
    assert not status_doc_records_deployment(
        OLD_STATUS_HEADLINE + "\nNothing is scheduled or armed.**\n"
    )


def test_status_doc_still_quotes_what_it_corrected() -> None:
    """A correction that erases the superseded claim cannot be audited."""
    assert "Nothing is deployed" in STATUS_DOC.read_text(encoding="utf-8")


def test_status_doc_carries_the_measured_test_count() -> None:
    """151 was measured; 157 and 185 were not reproducible."""
    text = STATUS_DOC.read_text(encoding="utf-8")
    assert "151" in text
