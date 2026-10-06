"""Canonical options journal projection; fixtures are not live performance evidence."""
from scripts.lib.options_journal_read import enrich, filters, summary


def entry(spid, account="fixture-a", right="call", strike=100):
    return {"strategy_position_id": spid, "account_key": account, "underlying": "TEST",
            "strategy_type": "long_" + right, "roll_root_id": spid, "status": "closed",
            "outcome_validity": "closed_outcome_recorded", "realized_pnl": 200,
            "latest_snapshot": {"underlying_price": 110, "quote_timestamp": "2026-10-05T15:00:00Z"},
            "legs": [{"option_type": right, "strike": strike, "opening_price": 2, "multiplier": 100}],
            "events": [{"event": "PARTIAL_FILL", "ref": f"fill-{spid}"}, {"event": "CLOSE", "ref": f"close-{spid}"}]}


def test_call_put_moneyness_requires_timestamped_underlying():
    assert enrich(entry(1))["legs"][0]["moneyness"] == "ITM"
    assert enrich(entry(2, right="put"))["legs"][0]["moneyness"] == "OTM"
    row = entry(3)
    row["latest_snapshot"]["quote_timestamp"] = None
    assert enrich(row)["legs"][0]["moneyness"] == "UNKNOWN"


def test_same_symbol_date_accounts_and_strategies_remain_distinct():
    rows = [entry(1), entry(2), entry(3, "fixture-b"), entry(4, right="put")]
    result = [enrich(r) for r in rows]
    assert len({r["strategy_position_id"] for r in result}) == 4
    assert len({r["deep_link"] for r in result}) == 4


def test_unknown_basis_and_unrecorded_outcome_remain_unknown():
    r = entry(1)
    r["legs"][0]["opening_price"] = None
    r["outcome_validity"] = "closed_no_outcome_row"
    out = enrich(r)
    assert out["basis_status"] == "unknown" and not out["completed_trade"]


def test_aggregates_cover_complete_filtered_dataset_not_one_page():
    calls = []
    def query(sql, params, fetch="all"):
        calls.append((sql, params))
        if "COUNT(*) AS total_strategies" in sql:
            assert "LIMIT" not in sql
            return {"total_strategies": 80, "known_outcomes": 60, "wins": 30, "known_realized_pnl": 500}
        if "FROM v_options_journal v" in sql:
            assert "LIMIT %s OFFSET %s" in sql
            return [{"entry": entry(26)}]
        return []
    result = summary(query, account="fixture-a", limit=1, offset=25)
    assert result["total"] == 80 and result["has_more"] and len(result["entries"]) == 1
    assert result["summary"]["win_rate"] == 50
    assert result["aggregation_scope"] == "complete filtered dataset"
    assert calls[0][1][1] == "fixture-a"


def test_export_all_rows_preserves_rolls_events_and_neutralizes_formulas():
    a, b = entry(1), entry(2)
    a["underlying"] = "=FORMULA()"
    b["roll_root_id"] = 1
    def query(sql, params, fetch="all"):
        if "COUNT(*)" in sql:
            return {"total_strategies": 2}
        if "FROM v_options_journal v" in sql:
            assert "LIMIT" not in sql
            return [{"entry": a}, {"entry": b}]
        return []
    result = summary(query, export=True, limit=1)
    assert result["exported_rows"] == 2
    assert "'=FORMULA()" in result["csv"]
    assert "PARTIAL_FILL" in result["csv"] and result["entries"][1]["roll_root_id"] == 1


def test_filters_are_parameterized():
    sql, params = filters(account="x'; DROP TABLE x; --", strategy="long_call", spid="3", roll_root="1")
    assert "DROP" not in sql and params[1] == "x'; DROP TABLE x; --"
