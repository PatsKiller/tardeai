"""investment-costs: the fee reconciliation names what it cannot explain.

Live finding 2026-11-07: `investment-costs` runs every weekday at 17:05 ET, but its
receipt has said `status: failed, ok_at: null, consecutive_failures: 11` because one
check compared two totals — `sum(trade_transactions.fees)` = 115.99 against the
normalized `investment_cost_events.amount` = 116.77. The $0.78 was six normalized
charges (VTAK, IBIO, GWH, AIRE, NERV, SHFS) whose `trade_transactions` row no longer
exists after a trade-ledger re-import. Nothing was lost in normalization; the
aggregate simply could not say which side was short.

The replacement compares the ledger row by row (so a dropped or altered fee fails on
that row, not on a sum that can cancel), and it explains the totals with the named
orphan set instead of rounding the difference away. Orphans are never deleted: this
store is the record of cash actually paid.
"""
from scripts.investment_costs import costs_reconciliation, ledger_event_key


class FakeCursor:
    def __init__(self, responses):
        self.responses = responses
        self.rows = []
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        for needle, rows in self.responses:
            if needle in sql:
                self.rows = rows
                return
        raise AssertionError(f"unexpected query: {sql[:120]}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


def _cur(*, coverage, raw=0.0, norm=0.0, orphans=(0, 0.0, "")):
    return FakeCursor([
        ("FROM trade_transactions t", coverage),
        ("SELECT COALESCE(sum(fees),0) FROM trade_transactions", [(raw,)]),
        ("SELECT COALESCE(sum(amount),0) FROM investment_cost_events", [(norm,)]),
        ("FROM investment_cost_events e", [orphans]),
        ("FROM options_fill_evidence e\n", []),
        ("FROM options_fill_evidence", [(0,)]),
        ("FROM options_lifecycle_outcomes", [(0,)]),
        ("FROM trade_instances t", [(0, 0)]),
        ("count(DISTINCT dedupe_key)", [(1, 1)]),
        ("'EMBEDDED_FUND_COST_ESTIMATE' AND cash_or_embedded", [(0,)]),
    ])


def _check(result, name):
    return next(c for c in result["checks"] if c["check"] == name)


def test_a_fully_normalized_ledger_passes_both_checks():
    result = costs_reconciliation(_cur(coverage=[(1.0, 1.0), (0.5, 0.5)], raw=1.5, norm=1.5))
    assert _check(result, "ledger_rows_normalized")["ok"] is True
    assert _check(result, "ledger_fees_vs_normalized")["ok"] is True
    assert result["all_ok"] is True


def test_a_ledger_fee_with_no_event_fails_on_that_row():
    result = costs_reconciliation(_cur(coverage=[(1.0, 1.0), (0.5, None)], raw=1.5, norm=1.0))
    rows = _check(result, "ledger_rows_normalized")
    assert rows["ok"] is False
    assert rows["unmatched_rows"] == 1
    assert result["all_ok"] is False


def test_a_changed_event_amount_fails_on_that_row():
    result = costs_reconciliation(_cur(coverage=[(1.0, 0.5)], raw=1.0, norm=0.5))
    rows = _check(result, "ledger_rows_normalized")
    assert rows["ok"] is False
    assert rows["amount_mismatches"] == 1
    assert result["all_ok"] is False


def test_a_difference_explained_by_named_orphans_passes_and_names_them():
    result = costs_reconciliation(_cur(
        coverage=[(115.99, 115.99)], raw=115.99, norm=116.77,
        orphans=(6, 0.78, "txn:2025-09-24|Sell|SHFS, txn:2025-10-10|Sell|GWH")))
    totals = _check(result, "ledger_fees_vs_normalized")
    assert totals["ok"] is True
    assert totals["orphaned_events"] == 6
    assert totals["orphaned_amount"] == 0.78
    assert "SHFS" in totals["orphaned_keys"]
    assert result["all_ok"] is True


def test_a_difference_the_orphans_do_not_explain_still_fails():
    """Orphans explain the gap; they never excuse a different one."""
    result = costs_reconciliation(_cur(
        coverage=[(1.0, 1.0)], raw=1.0, norm=2.0, orphans=(1, 0.78, "txn:x")))
    assert _check(result, "ledger_fees_vs_normalized")["ok"] is False
    assert result["all_ok"] is False


def test_the_writer_and_the_reconciliation_use_the_same_event_key():
    assert ledger_event_key("abc") == "txn:abc"
    cur = _cur(coverage=[])
    costs_reconciliation(cur)
    joined = [(sql, args) for sql, args in cur.executed
              if "|| t.dedupe_key" in sql or "%s || t.dedupe_key" in sql]
    assert joined, "both join queries must carry the prefix"
    assert {args for _, args in joined} == {("txn:",)}
