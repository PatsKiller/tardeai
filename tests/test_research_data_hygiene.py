from __future__ import annotations

from scripts.lib.health_learning_engine import HealthLearningEngine
from scripts.lib.research_data_quality import assess_prompt_context, validate_research_output
from scripts.repair_hermes_backlog_taxonomy import repair_payload


class _ThresholdCursor:
    def __init__(self, conn):
        self.conn = conn
        self.row = None

    def execute(self, sql, params=()):
        self.conn.sql.append(sql)
        if "SELECT id FROM hermes_research_intelligence" in sql:
            self.row = (42,) if self.conn.inserted else None
        elif "INSERT INTO hermes_research_intelligence" in sql:
            self.conn.inserted = True
            self.conn.insert_params = params

    def fetchone(self):
        return self.row

    def close(self):
        return None


class _ThresholdConn:
    def __init__(self):
        self.inserted = False
        self.insert_params = ()
        self.sql = []
        self.commits = 0

    def cursor(self):
        return _ThresholdCursor(self)

    def commit(self):
        self.commits += 1


def test_threshold_proposal_is_deduped_and_never_claims_config_mutation():
    conn = _ThresholdConn()
    engine = HealthLearningEngine(conn)
    assert engine.stage_threshold_adjustment("analyst_consensus", 48, 24, 1.0) == 24.0
    assert engine.stage_threshold_adjustment("analyst_consensus", 48, 24, 1.0) is None
    assert conn.commits == 1
    assert "Threshold proposal:" in conn.insert_params[4]
    assert '"config_mutated": false' in conn.insert_params[-1]
    insert_sql = next(sql for sql in conn.sql if "INSERT INTO hermes_research_intelligence" in sql)
    assert "threshold_adjusted" in insert_sql
    assert "false" in insert_sql


def test_market_input_zero_sentinels_block_provider_call():
    result = assess_prompt_context({
        "deterministic_current_data": {
            "price": 0,
            "week52_high_pct": 0,
            "week52_low_pct": 0,
        }
    })
    assert result["status"] == "BLOCK"
    assert result["provider_call_allowed"] is False
    assert "invalid_price" in result["reason_codes"]
    assert "invalid_zero_52week_range" in result["reason_codes"]


def test_missing_valuation_is_not_coerced_to_zero():
    result = assess_prompt_context({
        "deterministic_current_data": {"price": None, "pe": None}
    })
    assert result["status"] == "PASS"
    assert result["provider_call_allowed"] is True


def test_placeholder_market_facts_reject_research_output():
    result = validate_research_output("P/E 0.0 and 52-week range $0-$0")
    assert result["accepted"] is False
    assert result["reason_codes"] == [
        "placeholder_zero_pe",
        "placeholder_zero_52week_range",
    ]
    assert validate_research_output("P/E DATA_UNAVAILABLE; range DATA_UNAVAILABLE")["accepted"] is True


def test_librarian_backlog_taxonomy_repair_is_deterministic():
    raw = [{
        "type": "autonomous_librarian_finding",
        "finding_type": "backtest_weak_strategy",
        "priority": "high",
        "owner_agent": "unknown",
        "backlog_type": "unknown",
    }]
    repaired, changed = repair_payload(raw)
    assert changed is True
    assert repaired[0]["owner_agent"] == "strategy_research_agent"
    assert repaired[0]["backlog_type"] == "strategy_validation"
    assert repaired[0]["research_questions"]
    again, changed_again = repair_payload(repaired)
    assert changed_again is False
    assert again == repaired


def test_health_inspector_has_no_local_generative_runtime_path():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "scripts/hermes_health_inspector.py").read_text()
    assert "/api/generate" not in source
    assert "/api/chat" not in source
    assert "gemma" not in source.lower()
