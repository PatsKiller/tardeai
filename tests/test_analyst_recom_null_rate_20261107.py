"""LQ-20261107-185 — a column a producer stopped writing must not audit as green.

ANCHOR: ANALYST_RECOM_NULL_RATE_20261107.

``analyst_consensus_history.recom_score`` had exactly one plausibility contract: a 1-5 ``range``
rule. A range rule treats NULL as "absent data, a different problem from wrong data", which is
right — until the producer stops writing the column at all. Then every row passes the range rule
vacuously and the daily audit reports OK while the value is gone.

Measured live 2026-11-07 (read-only):

    last non-NULL recom_score            2026-08-18
    finviz rows, last 30 days            1,512, of which NULL recom_score: 1,512
    last finviz row written              2026-10-20
    live enrichment cache                6,704 records, 0 with recom_score, 7 stale percentages

Cause: after the 2026-09-13 header-keyed rewrite no configured Finviz view returns a "Recom"
column, so the enrichment never collects one, and the consensus writer skips every record that has
no recommendation, rating, score or target — silently, because a skip returned a receipt nobody
read and printed nothing.

These tests pin the three halves of the fix: the ``null_rate`` rule (presence), the optional
column map that lets a Recom column in ANY saved view start feeding ``recom_score`` without a
deploy, and the writer's receipt counting what it skipped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import data_plausibility_monitor as dpm  # noqa: E402
import finviz_enrichment as fe  # noqa: E402

CONTRACTS = json.loads((ROOT / "config" / "data_plausibility_contracts.json").read_text())["contracts"]

MOTIVATING = {
    "table": "analyst_consensus_history",
    "column": "recom_score",
    "rule": "null_rate",
    "window_column": "snapshot_date",
    "window_days": 30,
    "max_null_pct": 80.0,
    "min_rows": 20,
    "where": "source = 'finviz'",
    "severity": "BLOCK",
}


class _Cursor:
    """Answers the information_schema probe, then one prepared (nulls, total) row. Records SQL."""

    def __init__(self, nulls, total, *, present=True):
        self.row = (nulls, total)
        self.present = present
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        if "information_schema.columns" in self.sql[-1][0]:
            return (1,) if self.present else None
        return self.row

    def fetchall(self):
        return []


# ── the contract ─────────────────────────────────────────────────────────────


def test_the_recom_score_column_has_a_presence_contract_next_to_its_scale_contract():
    same = [c for c in CONTRACTS
            if c["table"] == "analyst_consensus_history" and c["column"] == "recom_score"]
    rules = {c["rule"] for c in same}
    assert rules == {"range", "null_rate"}, (
        "the scale contract alone cannot see a producer that stopped writing the column"
    )
    presence = next(c for c in same if c["rule"] == "null_rate")
    assert presence["severity"] == "BLOCK"
    assert presence["window_column"] == "snapshot_date"
    assert int(presence["min_rows"]) > 0, (
        "without min_rows an empty window has a 0% null rate and the contract fails open"
    )


# ── the SQL ──────────────────────────────────────────────────────────────────


def test_null_rate_sql_is_windowed_filtered_and_quotes_the_column():
    sql = dpm._null_rate_sql(MOTIVATING)
    assert '"recom_score" IS NULL' in sql
    assert '"snapshot_date" > now() - interval \'30 days\'' in sql
    assert "source = 'finviz'" in sql, "the contract is about the producer that must supply the value"
    assert sql.startswith("SELECT count(*) FILTER")


def test_a_where_clause_that_could_end_the_statement_is_refused():
    """The clause is config, but it is still text — one SELECT is what this monitor runs."""
    with pytest.raises(ValueError):
        dpm._null_rate_sql(dict(MOTIVATING, where="source = 'finviz'; DROP TABLE analyst_consensus_history"))
    with pytest.raises(ValueError):
        dpm._null_rate_sql(dict(MOTIVATING, where="source = 'finviz' -- and the rest"))


def test_null_rate_has_no_per_row_predicate():
    assert dpm._violation_predicate({"column": "recom_score", "rule": "null_rate"}) == ""


# ── the threshold ────────────────────────────────────────────────────────────


def test_a_fully_null_column_in_the_window_is_a_violation():
    r = dpm._check_null_rate(_Cursor(1512, 1512), MOTIVATING)
    assert r["violations"] == 1512
    assert "100.0%" in r["detail"]


def test_a_minority_of_nulls_stays_quiet():
    r = dpm._check_null_rate(_Cursor(100, 1512), MOTIVATING)
    assert r["violations"] == 0


def test_an_empty_window_is_a_violation_when_min_rows_is_declared():
    """The fail-open half: no rows at all is also a 0% null rate."""
    r = dpm._check_null_rate(_Cursor(0, 0), MOTIVATING)
    assert r["violations"] == 1
    assert "wrote nothing" in r["detail"]


def test_a_thin_window_reports_at_most_the_rows_it_saw():
    """A violation count above the row count renders as nonsense ('15 of 5 rows, 300%')."""
    r = dpm._check_null_rate(_Cursor(0, 5), MOTIVATING)
    assert r["violations"] == 5 and r["total"] == 5


def test_an_empty_window_without_min_rows_is_quiet_and_that_is_why_min_rows_exists():
    r = dpm._check_null_rate(_Cursor(0, 0), {k: v for k, v in MOTIVATING.items() if k != "min_rows"})
    assert r["violations"] == 0


def test_the_check_dispatch_measures_the_rule_and_reports_its_status():
    from_test = dpm._check(_Cursor(1512, 1512), MOTIVATING, dpm.window_policy(None))
    assert from_test["rule"] == "null_rate"
    assert from_test["status"] == "VIOLATION"
    assert from_test["severity"] == "BLOCK"


def test_an_absent_column_is_reported_rather_than_measured():
    out = dpm._check(_Cursor(0, 0, present=False), MOTIVATING, dpm.window_policy(None))
    assert out["status"] == "COLUMN_ABSENT"


# ── the collection gap: no view carries a Recom column, and any view may supply one ──


def test_recom_is_accepted_from_any_view_and_never_demanded():
    """The collected headers (2026-09-13) have no Recom in any view, so requiring it would be drift noise."""
    for view, col_map in fe.VIEWS.items():
        assert "Recom" not in col_map, f"view {view} does not return Recom; demanding it prints SCHEMA DRIFT daily"
    merged = fe._with_optional_columns(fe.VIEWS[141])
    assert merged["Recom"] == "recom"
    # the required map is untouched: absent optional columns are not drift
    assert "Recom" not in fe.VIEWS[141]


def test_a_view_that_maps_its_own_recom_field_keeps_it():
    merged = fe._with_optional_columns({"Recom (1-5)": "recom"})
    assert merged == {"Recom (1-5)": "recom"}


def test_no_fetched_view_supplying_recom_is_a_finding_not_a_blank():
    assert fe.recom_collecting_views({}) == []
    assert fe.recom_collecting_views({111: {"AAA": {"ticker": "AAA"}}, 141: {}}) == []
    assert fe.recom_collecting_views({111: {}, 121: {"AAA": {"recom": "2.1"}}}) == [121]


CSV_WITH_RECOM = (
    '"No.","Ticker","Company","Sector","Industry","Country","Market Cap","P/E","Recom",'
    '"Price","Change","Volume"\r\n'
    '1,"AAA","Acme Corp","Technology","Software","USA","1.2B","12.4","2.10","101.50","1.20%","3,000,000"\r\n'
)


def _fake_response(text):
    class _R:
        ok = True
        status_code = 200
        headers: dict = {}

        def __init__(self, body):
            self.text = body

    return _R(text)


def _stub_fetch(monkeypatch, body):
    monkeypatch.setattr(fe, "_load_env", lambda *_a, **_k: None)
    monkeypatch.setattr(fe, "_env", lambda *_a, **_k: "test-token")
    monkeypatch.setattr(fe.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(fe.requests, "get", lambda *a, **k: _fake_response(body))


def test_a_recom_header_in_any_saved_view_reaches_the_record(monkeypatch):
    """End to end through the real parser: no network, no deploy, one header away from working."""
    _stub_fetch(monkeypatch, CSV_WITH_RECOM)
    out = fe._fetch_view(["AAA"], 111, ROOT)
    assert out["AAA"]["recom"] == "2.10", "a Recom column in the view must be collected, not ignored"
    assert out["AAA"]["company"] == "Acme Corp"


def test_a_view_without_recom_still_parses_and_reports_nothing_missing(monkeypatch, capsys):
    body = (
        '"No.","Ticker","Company","Sector","Industry","Country","Market Cap","P/E",'
        '"Price","Change","Volume"\r\n'
        '1,"AAA","Acme Corp","Technology","Software","USA","1.2B","12.4","101.50","1.20%","3,000,000"\r\n'
    )
    _stub_fetch(monkeypatch, body)
    out = fe._fetch_view(["AAA"], 111, ROOT)
    assert out["AAA"]["company"] == "Acme Corp"
    assert "recom" not in out["AAA"]
    assert "SCHEMA DRIFT" not in capsys.readouterr().out, (
        "an optional column must not be reported as drift; that is how a real drift warning gets ignored"
    )


# ── the writer: "wrote nothing" must be a fact in the receipt, not a silence ──


def test_the_writer_counts_what_it_skipped_and_what_it_had():
    import db_adapter as dba

    cache = {
        "AAA": {"ticker": "AAA", "perf_week_pct": 1.2},  # no recommendation, rating, score or target
        "BBB": {"ticker": "BBB", "recom": "2.0", "recom_score": 2.0, "analyst_rating": "Buy"},
        "_meta": {"note": "ignored"},
    }
    rows, receipt = dba.build_analyst_consensus_rows("2026-11-07", cache, {})
    assert receipt["considered"] == 2, "the _meta key is not a record"
    assert receipt["skipped_no_analyst_data"] == 1
    assert receipt["rows_prepared"] == 1
    assert receipt["with_recom"] == 1 and receipt["with_recom_score"] == 1
    assert len(rows) == 1


def test_a_writer_that_persists_nothing_says_why(monkeypatch, capsys):
    import db_adapter as dba

    monkeypatch.setattr(dba, "USE_DB", True)
    receipt = dba.save_analyst_consensus_history("2026-11-07", {"AAA": {"ticker": "AAA"}}, {})
    assert receipt["storage_status"] == "no_rows"
    out = capsys.readouterr().out
    assert "NO ROWS persisted" in out
    assert "1 carried no recommendation" in out


# ── the backfill: classify by cause, and have no way to write ─────────────────


def test_the_backfill_classifies_each_null_row_by_what_the_raw_value_actually_is():
    import backfill_analyst_recom_score_dryrun as bf

    assert bf.classify("-95.44%") == bf.CAUSE_PERCENT_VALUE, (
        "a percentage is the 2026-09 view shift, not a rating on a 1-5 scale"
    )
    assert bf.classify("1317.18%") == bf.CAUSE_PERCENT_VALUE
    assert bf.classify("2.0") == bf.CAUSE_RECOVERABLE
    assert bf.classify("7.4") == bf.CAUSE_OFF_SCALE
    assert bf.classify(None) == bf.CAUSE_NOT_COLLECTED
    assert bf.classify("-") == bf.CAUSE_NOT_COLLECTED


def test_the_backfill_counts_a_window_without_touching_it():
    import backfill_analyst_recom_score_dryrun as bf

    out = bf.report(["-95.44%", "1317.18%", None, "2.0"], 90)
    assert out["null_rows"] == 4
    assert out["by_cause"][bf.CAUSE_PERCENT_VALUE] == 2
    assert out["by_cause"][bf.CAUSE_NOT_COLLECTED] == 1
    assert out["recoverable"] == 1
    assert out["write_path"].startswith("none")


def test_the_backfill_has_no_apply_flag_at_all():
    """A fill-it-anyway script is the incident again; the absence of a write path is the safety property."""
    src = (ROOT / "scripts" / "backfill_analyst_recom_score_dryrun.py").read_text()
    flags = [ln for ln in src.splitlines() if "add_argument" in ln]
    assert flags and not any("--apply" in ln for ln in flags), (
        "the docstring explains why there is no --apply; no flag may exist either"
    )
    assert "default_transaction_read_only=on" in src
