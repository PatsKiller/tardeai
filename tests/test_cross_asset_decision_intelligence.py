"""Phase 1 contract tests for cross-asset decision intelligence."""
from __future__ import annotations

import json

import pytest

from scripts.lib.cross_asset_decision import (
    AppendOnlyDecisionStore,
    apply_expression_evaluation,
    build_decision_object,
    build_event,
    candidate_expressions,
    coverage_row,
    link_symbol_sources,
    replay_events,
    run_shadow,
    validate_decision_object,
)


def _decision(signal="BUY", *, held=False, shares=0):
    event = build_event(symbol="ABC", signal=signal, source="test", payload={"price": 10})
    return build_decision_object(
        event=event,
        identity={"symbol": "ABC", "security_guid": "sec-abc", "identity_status": "CONFIRMED"},
        position={"held": held, "shares": shares},
    )


def test_signal_matrix_routes_buy_and_hold_without_live_action():
    buy = _decision("BUY")
    hold = _decision("HOLD", held=True, shares=150)
    assert [x["structure"] for x in buy["expression_comparison"]["candidates"]] == [
        "shares", "cash_secured_put", "long_call", "bull_call_spread"
    ]
    assert [x["structure"] for x in hold["expression_comparison"]["candidates"]] == [
        "shares", "covered_call", "protective_put", "collar"
    ]
    assert buy["financial_action"] is False
    assert buy["expression_comparison"]["decision"] == "SHADOW_ONLY"


def test_covered_call_requires_held_position_and_100_shares():
    assert "covered_call" not in candidate_expressions("HOLD", held=False, shares=0)
    assert "covered_call" not in candidate_expressions("HOLD", held=True, shares=99)
    assert "covered_call" in candidate_expressions("HOLD", held=True, shares=100)


def test_unknown_signal_and_identity_mismatch_fail_closed():
    with pytest.raises(ValueError, match="unsupported_signal"):
        build_event(symbol="ABC", signal="BUY_MORE", source="test")
    event = build_event(symbol="ABC", signal="BUY", source="test")
    with pytest.raises(ValueError, match="identity_symbol_mismatch"):
        build_decision_object(event=event, identity={"symbol": "XYZ"})


def test_validation_rejects_authority_or_schema_mutation():
    obj = _decision()
    obj["financial_action"] = True
    errors = validate_decision_object(obj)
    assert "financial_action_must_be_false" in errors


def test_append_only_store_is_idempotent_and_preserves_rows(tmp_path):
    path = tmp_path / "shadow.jsonl"
    store = AppendOnlyDecisionStore(path)
    obj = _decision()
    assert store.append(obj) == "APPENDED"
    assert store.append(obj) == "DUPLICATE_IGNORED"
    rows = store.read()
    assert len(rows) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["evaluation_id"] == obj["evaluation_id"]


def test_coverage_row_proves_comparison_denominator():
    row = coverage_row(_decision("REENTRY"))
    assert row["expected_count"] == 3
    assert row["generated_count"] == 3
    assert row["state"] == "COVERED"


def test_source_linking_marks_conflicts_instead_of_picking_a_winner():
    linked = link_symbol_sources([
        {"symbol": "abc", "source": "watchlist", "signal": "BUY", "security_guid": "s1"},
        {"symbol": "ABC", "source": "cio", "signal": "HOLD", "security_guid": "s1"},
    ])
    assert linked["ABC"]["identity_status"] == "CONFLICTED"
    assert linked["ABC"]["conflicts"][0]["field"] == "signal"


def test_expression_evaluation_blocks_hard_risk_and_ranks_unblocked_candidates():
    obj = _decision("BUY")
    evaluated = apply_expression_evaluation(obj, {
        "shares": {"score": 5},
        "cash_secured_put": {"score": 9, "liquid": False},
        "long_call": {"score": 7, "liquid": True, "open_interest": 100},
        "bull_call_spread": {"score": 8, "liquid": True, "open_interest": 100},
    })
    assert evaluated["expression_comparison"]["winner"] == "bull_call_spread"
    csp = next(x for x in evaluated["expression_comparison"]["candidates"] if x["structure"] == "cash_secured_put")
    assert csp["state"] == "BLOCKED"
    assert "LIQUIDITY" in csp["blockers"]


def test_replay_is_sorted_and_requires_identity_without_future_data():
    events = [
        build_event(symbol="ABC", signal="HOLD", source="later", observed_at="2026-09-02T00:00:00+00:00"),
        build_event(symbol="ABC", signal="BUY", source="earlier", observed_at="2026-09-01T00:00:00+00:00"),
    ]
    out = replay_events(events, identity_by_symbol={"ABC": {"symbol": "ABC"}})
    assert [x["signal_state"]["action"] for x in out] == ["BUY", "HOLD"]
    with pytest.raises(ValueError, match="replay_identity_missing"):
        replay_events(events, identity_by_symbol={})


def test_replay_cli_writes_only_the_requested_shadow_output(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    identities_path = tmp_path / "identities.json"
    output_path = tmp_path / "shadow" / "decisions.jsonl"
    event = build_event(symbol="ABC", signal="BUY", source="fixture", observed_at="2026-09-01T00:00:00+00:00")
    events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    identities_path.write_text(json.dumps({"ABC": {"symbol": "ABC"}}), encoding="utf-8")
    from scripts import cross_asset_replay
    monkeypatch.setattr("sys.argv", ["cross_asset_replay.py", "--events", str(events_path),
                                      "--identities", str(identities_path), "--output", str(output_path)])
    assert cross_asset_replay.main() == 0
    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1


def test_shadow_run_is_idempotent_and_never_authorizes_financial_action(tmp_path):
    event = build_event(symbol="ABC", signal="BUY", source="fixture", observed_at="2026-09-01T00:00:00+00:00")
    store = AppendOnlyDecisionStore(tmp_path / "shadow.jsonl")
    kwargs = {"identity_by_symbol": {"ABC": {"symbol": "ABC"}}, "store": store}
    first = run_shadow([event], **kwargs)
    second = run_shadow([event], **kwargs)
    assert first["appended"] == 1
    assert second["duplicates"] == 1
    assert first["financial_action"] is False
    assert first["state"] == "SHADOW_ONLY"


# Historical archive replay is offline; these source facts are TEST_ONLY fixtures.
def _historical_archive(tmp_path, *, clock=None, with_facts=True):
    from datetime import datetime, timedelta, timezone

    clock = clock or datetime.now(timezone.utc).replace(microsecond=0)
    observed = clock - timedelta(days=1)
    known = observed - timedelta(minutes=1)
    archive = tmp_path / "archive"
    archive.mkdir()
    event = build_event(symbol="ABC", signal="BUY", source="fixture",
                        observed_at=observed.isoformat())
    signal = {
        "schema": "CrossAssetHistoricalReplaySignal@v1", "event": event,
        "identity": {"symbol": "ABC", "security_guid": "sec-abc",
                     "identity_status": "CONFIRMED", "as_of": known.isoformat()},
    }
    price = {"schema": "CrossAssetHistoricalPrice@v1", "symbol": "ABC",
             "security_guid": "sec-abc", "as_of": known.isoformat(), "price": 100,
             "source_ref": "fixture:archived-spot"}
    facts = {
        "schema": "CrossAssetHistoricalExpressionFacts@v1", "event_id": event["event_id"],
        "symbol": "ABC", "security_guid": "sec-abc", "as_of": known.isoformat(),
        "source_ref": "fixture:governed-evaluator-input",
        "facts_by_structure": {
            "shares": {"score": 5, "as_of": known.isoformat()},
            "cash_secured_put": {"score": 9, "liquid": False, "as_of": known.isoformat()},
            "long_call": {"score": 7, "as_of": known.isoformat()},
            "bull_call_spread": {"score": 8, "as_of": known.isoformat()},
        },
    }
    for name, row in (("signals.jsonl", signal), ("prices.jsonl", price)):
        (archive / name).write_text(json.dumps(row) + "\n", encoding="utf-8")
    if with_facts:
        (archive / "expression_facts.jsonl").write_text(json.dumps(facts) + "\n", encoding="utf-8")
    return archive, clock, signal, price, facts


def test_historical_replay_evaluates_present_valid_archives_instead_of_zero_stub(tmp_path):
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, _, _, _, _ = _historical_archive(tmp_path)
    before = {p.name: p.read_bytes() for p in archive.iterdir()}
    result = run_window(30, archive_dir=archive)
    assert result["signals_evaluated"] == 1
    assert result["scoring_winner_counts"] == {"bull_call_spread": 1}
    assert result["options_would_be_superior"] is None
    assert result["options_superior_rate"] is None
    assert result["evaluation_scope"] == "SCORING_COMPARISON_ONLY"
    assert result["evaluations"][0]["comparison"]["candidates"][1]["blockers"] == ["LIQUIDITY"]
    assert {p.name: p.read_bytes() for p in archive.iterdir()} == before


def test_historical_replay_without_option_facts_counts_signals_but_refuses_superiority(tmp_path):
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, clock, _, _, _ = _historical_archive(tmp_path, with_facts=False)
    result = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert result["signals_evaluated"] == 1
    assert result["prices_covered"] == 1
    assert result["data_quality"] == "INSUFFICIENT_DATA"
    assert result["scoring_comparisons"] == 0
    assert result["options_superior_rate"] is None
    assert "OPTION_COMPARISON_MISSING" in result["insufficient_reasons"]


def test_historical_replay_is_deterministic_with_explicit_as_of(tmp_path):
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, clock, _, _, _ = _historical_archive(tmp_path)
    first = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert first == run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert first["authority"] == "READ_ONLY_ADVISORY"
    assert first["financial_action"] is False


@pytest.mark.parametrize("filename", ["signals.jsonl", "prices.jsonl", "expression_facts.jsonl"])
def test_historical_replay_malformed_archive_is_invalid_instead_of_available(tmp_path, filename):
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, clock, _, _, _ = _historical_archive(tmp_path)
    (archive / filename).write_text("{malformed\n", encoding="utf-8")
    result = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert result["data_quality"] == "INVALID_DATA"
    assert result["signals_evaluated"] == 0
    assert filename in result["refusals"][0]["reason"]


@pytest.mark.parametrize("mutation", ["missing_asof", "naive_asof", "future_identity", "symbol_mismatch", "unresolved_identity", "nonfinite_price"])
def test_historical_replay_refuses_unproven_identity_time_and_price(tmp_path, mutation):
    from datetime import timedelta
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, clock, signal, price, _ = _historical_archive(tmp_path)
    if mutation == "missing_asof":
        signal["identity"].pop("as_of")
    elif mutation == "naive_asof":
        signal["identity"]["as_of"] = "2026-01-01T00:00:00"
    elif mutation == "future_identity":
        signal["identity"]["as_of"] = (clock + timedelta(days=1)).isoformat()
    elif mutation == "symbol_mismatch":
        signal["identity"]["symbol"] = "XYZ"
    elif mutation == "unresolved_identity":
        signal["identity"]["identity_status"] = "UNRESOLVED"
    elif mutation == "nonfinite_price":
        price["price"] = float("nan")
    (archive / "signals.jsonl").write_text(json.dumps(signal) + "\n", encoding="utf-8")
    (archive / "prices.jsonl").write_text(json.dumps(price) + "\n", encoding="utf-8")
    result = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert result["data_quality"] == "INVALID_DATA"
    assert result["signals_evaluated"] == 0
    assert result["refusals"]


def test_historical_replay_does_not_use_future_price_or_fact_snapshots(tmp_path):
    from datetime import timedelta
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, clock, signal, price, facts = _historical_archive(tmp_path)
    future = clock + timedelta(days=1)
    future_price = {**price, "as_of": future.isoformat(), "price": 10000}
    future_facts = {**facts, "as_of": future.isoformat(), "facts_by_structure": {
        "shares": {"score": 99999, "as_of": future.isoformat()}}}
    for name, row in (("prices.jsonl", future_price), ("expression_facts.jsonl", future_facts)):
        with (archive / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    result = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    evaluation = result["evaluations"][0]
    assert evaluation["event_id"] == signal["event"]["event_id"]
    assert evaluation["price"]["price"] == 100
    assert evaluation["comparison"]["winner"] == "bull_call_spread"
    assert result["future_prices_excluded"] == 1
    assert result["future_facts_excluded"] == 1


def test_historical_replay_future_only_prices_cannot_satisfy_coverage(tmp_path):
    from datetime import timedelta
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, clock, _, price, _ = _historical_archive(tmp_path)
    price["as_of"] = (clock + timedelta(days=1)).isoformat()
    (archive / "prices.jsonl").write_text(json.dumps(price) + "\n", encoding="utf-8")
    result = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert result["prices_covered"] == 0
    assert result["signals_evaluated"] == 0
    assert result["signals_skipped"] == 1
    assert result["data_quality"] == "INSUFFICIENT_DATA"


def test_historical_replay_window_boundaries_use_instants_not_string_order(tmp_path):
    from datetime import timedelta
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, clock, signal, _, _ = _historical_archive(tmp_path)
    boundary = clock - timedelta(days=30)
    events = []
    for instant in (boundary - timedelta(seconds=1), boundary, clock, clock + timedelta(seconds=1)):
        row = json.loads(json.dumps(signal))
        row["event"] = build_event(symbol="ABC", signal="BUY", source="fixture",
                                   observed_at=instant.isoformat())
        row["identity"]["as_of"] = (boundary - timedelta(days=1)).isoformat()
        events.append(row)
    (archive / "signals.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
    result = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert result["signals_in_window"] == 2
    assert result["signals_outside_window"] == 1
    assert result["future_signals_excluded"] == 1


def test_historical_replay_cli_invalid_archive_returns_failure_receipt(tmp_path, capsys):
    from scripts.ops.run_cross_asset_historical_replay import main

    archive, _, _, _, _ = _historical_archive(tmp_path)
    (archive / "signals.jsonl").write_text("[]\n", encoding="utf-8")
    out = tmp_path / "metrics.json"
    assert main(["--archive-dir", str(archive), "--out", str(out)]) == 2
    assert json.loads(out.read_text())["windows"][0]["data_quality"] == "INVALID_DATA"
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_historical_replay_refuses_output_inside_read_only_archive(tmp_path):
    from scripts.ops.run_cross_asset_historical_replay import main

    archive, _, _, _, _ = _historical_archive(tmp_path)
    price_bytes = (archive / "prices.jsonl").read_bytes()
    assert main(["--archive-dir", str(archive), "--out", str(archive / "prices.jsonl")]) == 2
    assert (archive / "prices.jsonl").read_bytes() == price_bytes


@pytest.mark.parametrize("days", [30, 60, 90])
def test_historical_replay_missing_archives_remains_insufficient_without_fake_zero_superiority(days):
    from scripts.ops.run_cross_asset_historical_replay import run_window

    result = run_window(days, archive_dir=None, as_of="2026-10-09T12:00:00Z")
    assert result["data_quality"] == "INSUFFICIENT_DATA"
    assert result["signals_evaluated"] == 0
    assert result["options_would_be_superior"] is None
    assert result["options_superior_rate"] is None


def test_historical_replay_wrong_security_price_never_satisfies_same_symbol(tmp_path):
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, clock, _, price, _ = _historical_archive(tmp_path)
    price["security_guid"] = "different-share-class"
    (archive / "prices.jsonl").write_text(json.dumps(price) + "\n", encoding="utf-8")
    result = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert result["signals_evaluated"] == 0
    assert result["signals_skipped"] == 1
    assert result["refusals"] == [{"event_id": result["refusals"][0]["event_id"],
                                   "reason": "PRICE_AS_OF_MISSING"}]


def test_historical_replay_equal_instant_conflicting_facts_fail_closed_across_offsets(tmp_path):
    from datetime import datetime, timedelta, timezone
    from scripts.ops.run_cross_asset_historical_replay import run_window

    archive, clock, _, _, facts = _historical_archive(tmp_path)
    different = json.loads(json.dumps(facts))
    different["as_of"] = datetime.fromisoformat(facts["as_of"]).astimezone(
        timezone(timedelta(hours=-4))).isoformat()
    different["facts_by_structure"]["shares"]["score"] = 999
    with (archive / "expression_facts.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(different) + "\n")
    result = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert result["data_quality"] == "INVALID_DATA"
    assert result["signals_evaluated"] == 0
    assert "conflicting_fact_snapshot" in result["refusals"][0]["reason"]


@pytest.mark.parametrize("alias_kind", ["hardlink", "input_symlink"])
@pytest.mark.parametrize("filename", ["signals.jsonl", "prices.jsonl", "expression_facts.jsonl"])
def test_historical_replay_external_output_alias_preserves_all_input_bytes(tmp_path, alias_kind, filename):
    from scripts.ops.run_cross_asset_historical_replay import main

    archive, _, _, _, _ = _historical_archive(tmp_path)
    source = archive / filename
    output = tmp_path / "external-output.json"
    if alias_kind == "hardlink":
        output.hardlink_to(source)
    else:
        source.rename(output)
        source.symlink_to(output)
    assert source.samefile(output)
    before = {p.name: p.read_bytes() for p in archive.iterdir()}
    status = main(["--archive-dir", str(archive), "--out", str(output)])
    assert {p.name: p.read_bytes() for p in archive.iterdir()} == before
    assert status == 2


def test_historical_replay_derived_score_overflow_returns_typed_invalid_data(tmp_path, capsys):
    from scripts.ops.run_cross_asset_historical_replay import main, run_window

    archive, clock, _, _, facts = _historical_archive(tmp_path)
    share_facts = facts["facts_by_structure"]["shares"]
    share_facts.pop("score")
    share_facts.update(expected_return=1e308, capital_required=1e-320)
    (archive / "expression_facts.jsonl").write_text(json.dumps(facts) + "\n", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in archive.iterdir()}
    result = run_window(30, archive_dir=archive, as_of=clock.isoformat())
    assert result["data_quality"] == "INVALID_DATA"
    assert result["signals_evaluated"] == 0
    assert result["options_would_be_superior"] is None
    assert "derived_nonfinite_comparison" in result["refusals"][0]["reason"]
    out = tmp_path / "metrics.json"
    assert main(["--archive-dir", str(archive), "--as-of", clock.isoformat(), "--out", str(out)]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert json.loads(out.read_text())["windows"][0]["data_quality"] == "INVALID_DATA"
    assert {p.name: p.read_bytes() for p in archive.iterdir()} == before
