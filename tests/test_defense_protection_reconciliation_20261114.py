"""DR-D02 (sprint 8H-2, S4 defense-reentry): the protection reconciliation the Defense page needs.

The page merged "no stop" and "planned level only" into one headline ("3 without a broker stop"), while
Portfolio called two unprotected and Risk distinguished two no-stop positions from one planned-only one.
Those are compatible scopes only if the total is decomposed; a merged label asserts one truth where the
sources answer three questions. This pins the published decomposition and that it survives the
DefenseStopsSlice@v1 round trip the production build actually reads.

Synthetic fixtures only: the repository is public.
"""
from __future__ import annotations

from scripts.lib import defense_engine as de

AT = "2031-03-07T14:59:00Z"


def _row(symbol: str, cat: str | None, value: float, *, counted: bool = True, protection: dict | None = None) -> dict:
    row = {"symbol": symbol, "account_id": "acct_1", "account_label": "Account 1",
           "counted": counted, "market_value": value}
    if cat is not None:
        row["stop_category"] = cat
    if protection is not None:
        row["protection"] = protection
    return row


def _truth() -> dict:
    rows = [
        *[_row(f"ACT{i}", "active", 1000.0) for i in range(3)],
        *[_row(f"PEN{i}", "pending_activation", 2000.0) for i in range(5)],
        _row("PLANNED", "planned", 3000.0),
        _row("NOSTOP1", "none", 1200.0),
        _row("NOSTOP2", "none", 800.0),
        _row("FUNDX", "unknown", 5500.0, protection={
            "state": "UNKNOWN", "cause": "No Stop Read", "source": "none", "counted": True,
            "reason": "No stop read source for this broker; protection cannot be verified"}),
        _row("TINY", None, 42.0, counted=False),
        _row("EXEMPT1", None, 900.0, counted=False, protection={
            "state": "EXEMPT", "cause": None, "source": "policy", "counted": False,
            "reason": "Exempt: mutual fund policy"}),
    ]
    breakdown = {cat: {"count": sum(1 for r in rows if r.get("stop_category") == cat and r.get("counted")),
                       "value_usd": round(sum(r["market_value"] for r in rows
                                              if r.get("stop_category") == cat and r.get("counted")), 2)}
                 for cat in ("active", "pending_activation", "planned", "none", "unknown", "filled")}
    return {"generated_at": AT, "positions": {"rows": rows, "stop_breakdown": breakdown}}


def _section(truth: dict | None = None) -> dict:
    return de._stops_section(truth if truth is not None else _truth(), 5.0, 20, None)


def test_counts_are_decomposed_not_merged():
    rec = _section()["reconciliation"]
    assert rec["counted_positions"] == 12  # 3 active + 5 pending + 1 planned + 2 none + 1 unknown
    by = rec["by_state"]
    assert by["active"]["count"] == 3 and by["active"]["value_usd"] == 3000.0
    assert by["pending_activation"]["count"] == 5 and by["pending_activation"]["value_usd"] == 10000.0
    assert by["planned_only"]["count"] == 1 and by["planned_only"]["value_usd"] == 3000.0
    assert by["no_stop"]["count"] == 2 and by["no_stop"]["value_usd"] == 2000.0
    assert by["unknown"]["count"] == 1 and by["unknown"]["value_usd"] == 5500.0
    # the merged figure the old headline printed, now named for what it is and decomposable
    assert rec["no_resting_order"]["count"] == 3 and rec["no_resting_order"]["value_usd"] == 5000.0
    assert rec["resting_or_pending"]["count"] == 8 and rec["resting_or_pending"]["value_usd"] == 13000.0
    assert rec["coverage"] == "measured"


def test_excluded_positions_are_counted_and_valued():
    rec = _section()["reconciliation"]
    assert rec["excluded"]["count"] == 2
    assert rec["excluded"]["value_usd"] == 942.0
    # the split between the count floor and a policy exemption is not in the stop rows: say so, never guess
    assert rec["excluded"]["by_reason"] is None
    assert "not published" in rec["excluded"]["note"]


def test_unproven_positions_are_listed_with_their_cause():
    sec = _section()
    rows = sec["unknown_rows"]
    assert [r["symbol"] for r in rows] == ["FUNDX"]
    assert rows[0]["cause"] == "No Stop Read"
    assert "cannot be verified" in rows[0]["reason"]
    assert rows[0]["state"] == "UNKNOWN" and rows[0]["value_usd"] == 5500.0


def test_partial_quantities_are_declared_not_guessed():
    rec = _section()["reconciliation"]
    assert rec["partial_quantities"]["known"] is False
    assert "quantity" in rec["partial_quantities"]["reason"]


def test_the_slice_round_trip_keeps_the_reconciliation_fields():
    doc = de.stops_slice(_truth())
    assert doc["schema"] == de.STOPS_SLICE_SCHEMA
    assert "protection" in de.STOPS_SLICE_ROW_FIELDS, "the slice drops the protection record the rec reads"
    truth, gap = de.truth_from_slice(doc)
    assert gap is None
    sec = de._stops_section(truth, 5.0, 20, None)
    assert sec["reconciliation"]["counted_positions"] == 12
    assert sec["unknown_rows"][0]["symbol"] == "FUNDX"


def test_no_breakdown_publishes_no_reconciliation():
    truth = {"generated_at": AT, "positions": {"rows": [_row("A", "active", 100.0)], "stop_breakdown": None}}
    sec = _section(truth)
    assert sec["reconciliation"] is None
    assert sec["stale_reason"] and "stop breakdown" in sec["stale_reason"]
