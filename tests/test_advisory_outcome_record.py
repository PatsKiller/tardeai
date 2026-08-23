from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.advisory_outcome_record import (
    EVALUATED,
    FROZEN,
    evaluate_frozen_prediction,
    freeze_prediction,
    run_outcome_cycle,
)

T0 = datetime(2026, 1, 2, 21, tzinfo=timezone.utc)


def _decision(**overrides):
    row = {
        "schema": "DecisionPayload@v1",
        "decision_id": "dec_noc_1",
        "symbol": "NOC",
        "thesis_version": "symbol_noc@v2",
        "current_action": "HOLD",
        "as_of": T0.isoformat(),
        "inputs_digest": "ctx_abc",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }
    row.update(overrides)
    return row


def _quote(symbol, price, when=T0, **extra):
    return {
        "symbol": symbol,
        "price": price,
        "as_of": when.isoformat(),
        "source": "verified_fixture",
        **extra,
    }


def test_prediction_freeze_is_immutable_and_deduped(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    first = freeze_prediction(
        _decision(),
        horizon_days=30,
        starting_quote=_quote("NOC", 100),
        benchmark_quote=_quote("SPY", 500),
        path=path,
        frozen_at=T0 + timedelta(minutes=2),
    )
    second = freeze_prediction(
        _decision(current_action="ADD"),
        horizon_days=30,
        starting_quote=_quote("NOC", 999),
        benchmark_quote=_quote("SPY", 999),
        path=path,
        frozen_at=T0 + timedelta(minutes=3),
    )
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1
    assert first["status"] == FROZEN
    assert second["deduped"] is True
    assert second["advisory_stance"] == "HOLD"
    assert second["starting_quote"]["price"] == 100
    assert first["prediction_hash"] == second["prediction_hash"]
    assert first["financial_action"] is False


def test_retroactive_prediction_freeze_is_forbidden(tmp_path):
    with pytest.raises(ValueError, match="retroactive_freeze_forbidden"):
        freeze_prediction(
            _decision(),
            horizon_days=30,
            starting_quote=_quote("NOC", 100),
            benchmark_quote=_quote("SPY", 500),
            path=tmp_path / "outcomes.jsonl",
            frozen_at=T0 + timedelta(days=2),
        )


def test_outcome_is_benchmarked_and_candidate_only(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    frozen = freeze_prediction(
        _decision(),
        horizon_days=30,
        starting_quote=_quote("NOC", 100),
        benchmark_quote=_quote("SPY", 500),
        sector_benchmark_quote=_quote("XLI", 200),
        path=path,
        frozen_at=T0,
    )
    out = evaluate_frozen_prediction(
        frozen,
        ending_quote=_quote("NOC", 110, T0 + timedelta(days=30), low=90),
        benchmark_quote=_quote("SPY", 525, T0 + timedelta(days=30)),
        sector_benchmark_quote=_quote("XLI", 204, T0 + timedelta(days=30)),
        catalyst_correct=True,
        invalidation_occurred=False,
        path=path,
        evaluated_at=T0 + timedelta(days=30),
    )
    assert out["status"] == EVALUATED
    assert out["future_return_pct"] == 10.0
    assert out["benchmark_return_pct"] == 5.0
    assert out["benchmark_relative_return_pct"] == 5.0
    assert out["sector_relative_return_pct"] == 8.0
    assert out["drawdown_pct"] == -10.0
    assert out["thesis_result"] == "CATALYST_CONFIRMED"
    assert out["prediction_hash"] == frozen["prediction_hash"]
    for key in ("lesson_candidate", "memory_candidate", "hypothesis_candidate"):
        assert out[key]["status"] == "CANDIDATE"
        assert out[key]["auto_promote"] is False
    assert out["financial_action"] is False


def test_outcome_window_cannot_be_scored_early(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    frozen = freeze_prediction(
        _decision(),
        horizon_days=30,
        starting_quote=_quote("NOC", 100),
        benchmark_quote=_quote("SPY", 500),
        path=path,
        frozen_at=T0,
    )
    with pytest.raises(ValueError, match="outcome_window_not_due"):
        evaluate_frozen_prediction(
            frozen,
            ending_quote=_quote("NOC", 101, T0 + timedelta(days=1)),
            benchmark_quote=_quote("SPY", 501, T0 + timedelta(days=1)),
            path=path,
            evaluated_at=T0 + timedelta(days=1),
        )


def test_automatic_cycle_freezes_current_decision_once(tmp_path):
    trace_path = tmp_path / "data/cio/agent_run_traces.jsonl"
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(json.dumps({"decision": _decision()}) + "\n")

    def quote_loader(_root, symbol, when):
        return _quote(symbol, 100 if symbol == "NOC" else 500, when)

    first = run_outcome_cycle(root=tmp_path, now=T0 + timedelta(minutes=5), horizons=(30,), quote_loader=quote_loader)
    second = run_outcome_cycle(root=tmp_path, now=T0 + timedelta(minutes=6), horizons=(30,), quote_loader=quote_loader)
    assert first["predictions_frozen"] == 1
    assert second["predictions_frozen"] == 0
    assert first["outcomes_evaluated"] == 0
    assert first["financial_action"] is False
