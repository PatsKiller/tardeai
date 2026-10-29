"""Home "approval count unavailable" (2026-10-25): the approval queries named a column that does not exist.

``paper_trade_proposals`` has ``target_account``, ``final_account`` and ``proposed_account``; it has no ``account``.
``COALESCE(target_account,account)`` raised UndefinedColumn on production, ``_query_rows`` returned None, and both the
Home do-now gap ("approval count unavailable") and the Approvals Center ("Financial queues incomplete") followed.
The fake DB below refuses any column outside the production table's account columns, like Postgres does.
"""

import re
from datetime import datetime, timezone

from scripts.lib import cio_truth as truth

NOW = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)
# Captured read-only from information_schema on production, 2026-10-25 (account-related subset + used columns).
PTP_COLUMNS = {"id", "symbol", "status", "created_at", "target_account", "final_account", "proposed_account"}
SQL_WORDS = {"select", "count", "from", "where", "group", "by", "order", "limit", "coalesce", "as", "union", "all",
             "null", "text", "and", "kind", "pending", "proposals", "account"}


def _columns(fragment: str) -> set[str]:
    fragment = re.sub(r"'[^']*'|%s", "", fragment)
    fragment = re.sub(r"\bAS\s+\w+", "", fragment, flags=re.I)  # an output alias is not a column reference
    return {t for t in re.findall(r"[A-Za-z_]+", fragment) if t.lower() not in SQL_WORDS - {"account"}} - {"paper_trade_proposals"}


def _ptp_fragments(sql: str) -> list[str]:
    parts = re.split(r"UNION ALL", sql, flags=re.I)
    return [p for p in parts if "paper_trade_proposals" in p]


def _strict_db(rows_for):
    def query(sql, params=None, **kw):
        for fragment in _ptp_fragments(sql):
            unknown = _columns(fragment) - PTP_COLUMNS
            if unknown:
                raise RuntimeError(f'column "{sorted(unknown)[0]}" does not exist')
        return rows_for(sql)
    return query


def test_approval_counts_use_existing_columns():
    def rows(sql):
        return [{"kind": "actions", "count": 1, "account": None}, {"kind": "decisions", "count": 0, "account": None},
                {"kind": "proposals", "count": 2, "account": "alpaca_paper"}, {"kind": "options", "count": 0, "account": None}]
    result = truth.approvals_for(db_query=_strict_db(rows), now=NOW)
    assert result["total"] == 3
    assert result["by_type"]["paper"] == 2
    assert result.get("gap") is None


def test_financial_queue_reads_existing_columns_and_types_by_target_account():
    def rows(sql):
        if "FROM paper_trade_proposals" in sql:
            return [{"id": 7, "symbol": "SPCX", "account": "alpaca_paper", "target_account": "alpaca_paper",
                     "status": "PENDING"}]
        return []
    result = truth.financial_queue_items(db_query=_strict_db(rows), now=NOW)
    assert result["complete"], result.get("gaps")
    assert [(r["key"], r["kind"]) for r in result["items"]] == [("paper_trade_proposals:7", "paper")]


def test_the_strict_db_rejects_the_old_query():
    old = "SELECT 'proposals', COUNT(*), COALESCE(target_account,account) FROM paper_trade_proposals WHERE status='PENDING' GROUP BY 3"
    try:
        _strict_db(lambda sql: [])(old)
    except RuntimeError as exc:
        assert "account" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("old query must be refused")
