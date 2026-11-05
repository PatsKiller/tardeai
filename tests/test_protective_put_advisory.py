"""Synthetic, offline contract tests for per-contract advisory economics (FQ-142)."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "lib.options_pipeline.protective_put_advisory",
    ROOT / "scripts/lib/options_pipeline/protective_put_advisory.py",
)
adv = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adv
SPEC.loader.exec_module(adv)
NOW = date(2030, 1, 7)


def position(**over):
    row = {
        "symbol": "AAA",
        "account": "DEMO",
        "quantity": 100,
        "price": 100.0,
        "market_value": 10000.0,
        "asset_class": "stock",
    }
    row.update(over)
    return row


def chain(*, dte=15, put=True, call=True, strike=90.0, ask=2.1):
    strikes = []
    if put:
        strikes.append({"side": "put", "strike": strike, "bid": min(1.9, ask), "ask": ask})
    if call:
        strikes.append({"side": "call", "strike": 115.0, "bid": 3.0, "ask": 3.2})
    return {"expirations": [{"exp": "2030-01-22" if dte == 15 else "2030-01-14", "dte": dte, "strikes": strikes}]}


def suggest(row=None, *, quotes=None, days=10, cfg=None):
    return adv.suggest_for_position(
        position() if row is None else row,
        book_value=500000.0,
        event={"days_to_event": days},
        chain=quotes,
        cfg=dict(adv.DEFAULTS) if cfg is None else cfg,
        now=NOW,
    )


def cli_module():
    spec = importlib.util.spec_from_file_location(
        "protective_advisory_cli_test", ROOT / "scripts/protective_put_advisory.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_at_the_threshold_and_below():
    assert suggest(position(market_value=9999.0))[1] == "below_size_threshold"
    assert suggest()[1] is None
    assert suggest(position(market_value=10001.0))[0]["pct_of_book"] > 2.0


def test_default_config_honors_disabled_repository_file(tmp_path, monkeypatch):
    module = tmp_path / "scripts/lib/options_pipeline/protective_put_advisory.py"
    monkeypatch.setattr(adv, "__file__", str(module))
    target = tmp_path / "config/protective_put_advisory.json"
    target.parent.mkdir()
    target.write_bytes(b'{"enabled": false}')
    assert adv.load_config()["enabled"] is False
    assert suggest(cfg=adv.load_config())[1] == "advisory_disabled"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        b"",
        b"{broken",
        b"null",
        b"[]",
        b'{"enabled":"false"}',
        b'{"min_days_to_expiry":999,"max_days_to_expiry":7}',
    ],
)
def test_unusable_config_is_explicit(tmp_path, raw):
    p = tmp_path / "config.json"
    if raw is not None:
        p.write_bytes(raw)
    with pytest.raises(ValueError):
        adv.load_config(p)


@pytest.mark.parametrize("quantity", [None, "bad", float("nan"), True])
def test_unknown_quantity_never_becomes_a_known_long_or_floor(quantity):
    assert suggest(position(quantity=quantity), quotes=chain()) == (None, "position_quantity_unknown")


@pytest.mark.parametrize("quantity", [-300, -1, 0])
def test_only_known_longs(quantity):
    assert suggest(position(quantity=quantity))[1] == "not_a_long_position"


@pytest.mark.parametrize("symbol,asset", [("CASH", "cash"), ("AAA OPTION", "option")])
def test_non_equity_rows_are_not_suggested(symbol, asset):
    assert suggest(position(symbol=symbol, asset_class=asset))[1] == "not_a_single_stock"


def test_event_window_and_date_only_input():
    assert suggest(days=11)[1] == "outside_event_window"
    assert suggest(days=-3)[1] == "outside_event_window"
    assert suggest(days=-2)[1] is None
    assert (
        adv.suggest_for_position(position(), book_value=500000.0, event={"event_date": "2030-01-17"}, now=NOW)[1]
        is None
    )
    assert adv.suggest_for_position(position(), book_value=500000.0, now=NOW)[1] == "no_event"


def test_expiry_must_reach_known_event():
    assert suggest(quotes=chain(dte=7), days=10) == (None, "no_expiry_covers_event")
    assert suggest(quotes=chain(dte=15), days=10)[0]["expiry"] == "2030-01-22"


@pytest.mark.parametrize("quotes,reason", [({}, "no_expiry_covers_event"), (chain(put=False), "no_usable_put_quote")])
def test_supplied_unusable_chain_is_not_called_absent(quotes, reason):
    assert suggest(quotes=quotes) == (None, reason)


def test_forty_share_collar_is_withheld():
    got, why = suggest(position(quantity=40), quotes=chain())
    assert why is None
    assert "collar_per_contract" not in got
    assert got["collar_unavailable_reason"] == "insufficient_shares_for_standard_covered_call"
    assert "contracts" not in got


@pytest.mark.parametrize("quantity", [40, 100, 140, 250])
def test_unit_economics_never_select_order_quantity_or_imply_position_floor(quantity):
    got, why = suggest(position(quantity=quantity), quotes=chain())
    assert why is None
    assert got["economics_basis"] == "per_contract"
    assert got["cost_per_contract_usd"] == 210.0
    assert got["cost_per_covered_share"] == 2.1
    assert got["floor_per_covered_share_after_premium"] == 87.9
    assert got["position_floor_after_cost"] is None
    assert got["coverage_status"] == "not_selected"
    assert "contracts" not in got and "worst_case_per_share" not in got
    assert "floor_after_cost" not in got  # old unqualified field is unsafe for partial holdings
    assert got["placed_by_system"] is False and got["advisory_only"] is True


def test_fully_owned_contract_has_only_unit_collar_economics():
    got, _ = suggest(quotes=chain())
    collar = got["collar_per_contract"]
    assert collar["net_cost_per_contract_usd"] == -90.0
    assert collar["required_owned_shares_per_contract"] == 100
    assert collar["net_is_credit"] is True
    assert "contracts" not in collar


def test_absent_chain_has_only_labeled_cost_estimate_no_quoted_floor():
    got, _ = suggest()
    assert got["cost_is_estimate"] is True
    assert got["floor_price"] is None and got["expiry"] is None
    assert got["floor_per_covered_share_after_premium"] is None
    assert got["cost_per_contract_usd"] == 250.0
    assert "no option chain was supplied" in got["cost_basis"]


def test_strike_distance_and_premium_guards_are_preserved():
    got, _ = suggest(position(stop_price=95.0), quotes=chain(strike=50.0))
    assert got["floor_target"] == 95.0 and got["floor_distance"] == 45.0
    assert got["floor_strike_far_from_target"] is True and got["floor_warning"]
    assert suggest(quotes=chain(strike=225.0, ask=126.0))[1] == "cost_exceeds_position_value"
    assert suggest(quotes=chain(strike=90.0, ask=2.1))[0]["floor_strike_far_from_target"] is False


@pytest.mark.parametrize("payload", [None, b"", b"{broken", b"null", b"[]", b"{}", b'{"holdings":[null]}'])
def test_cli_damaged_store_is_unavailable(tmp_path, capsys, payload):
    p = tmp_path / "fixture.json"
    if payload is not None:
        p.write_bytes(payload)
    assert cli_module().main(["--holdings", str(p), "--json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "unavailable" and "examined" not in report


def test_cli_valid_empty_and_nonempty_and_text_output(tmp_path, capsys):
    holdings = tmp_path / "fixture.json"
    events = tmp_path / "events.json"
    quotes = tmp_path / "quotes.json"
    holdings.write_bytes(b'{"holdings":[]}')
    cli = cli_module()
    assert cli.main(["--holdings", str(holdings), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["examined"] == 0
    holdings.write_bytes(json.dumps({"holdings": [position()]}).encode())
    events.write_bytes(b'{"AAA":{"days_to_event":10}}')
    quotes.write_bytes(json.dumps({"AAA": chain()}).encode())
    args = ["--holdings", str(holdings), "--events", str(events), "--chains", str(quotes)]
    assert cli.main(args + ["--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok" and len(result["suggestions"]) == 1
    assert cli.main(args) == 0
    text = capsys.readouterr().out
    assert "per contract" in text and "quantity is not selected" in text


def test_no_broker_writer_or_sizing_import_path():
    source = (ROOT / "scripts/lib/options_pipeline/protective_put_advisory.py").read_text()
    tree = compile(source, "advisory", "exec", ast.PyCF_ONLY_AST)
    imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any(
        any(x in name for x in ("broker", "requests", "sqlite", "cio_instrument_record")) for name in imports
    )
    assert "def _contracts(" not in source


def test_behavior_write_rail_still_refuses():
    from lib import cio_instrument_record as ir

    with pytest.raises(ir.BehaviorWriteRefused):
        ir.apply_cognition({}, size_usd=25000)


def test_premium_at_or_above_strike_withholds_unit_floor():
    got, reason = suggest(quotes=chain(strike=1.0, ask=2.1))
    assert reason is None
    assert got["floor_per_covered_share_after_premium"] is None
    assert "no positive" in got["floor_after_premium_note"]


def test_cli_config_error_is_not_an_enabled_fallback(tmp_path, capsys):
    holdings = tmp_path / "positions.json"
    config = tmp_path / "config.json"
    holdings.write_bytes(b'{"holdings":[]}')
    config.write_bytes(b'{"enabled":"false"}')
    assert cli_module().main(["--holdings", str(holdings), "--config", str(config), "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "unavailable" and result["input"] == "config"


# D50 F1: an unknown holding is not a known zero in the implicit book denominator.
def run_book_cli(tmp_path, capsys, rows, *extra):
    holdings = tmp_path / "book-fixture.json"
    events = tmp_path / "book-events.json"
    quotes = tmp_path / "book-quotes.json"
    holdings.write_bytes(json.dumps({"holdings": rows}).encode())
    events.write_bytes(b'{"AAA":{"days_to_event":10}}')
    quotes.write_bytes(json.dumps({"AAA": chain()}).encode())
    rc = cli_module().main(
        ["--holdings", str(holdings), "--events", str(events), "--chains", str(quotes), "--json", *extra]
    )
    return rc, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    "unknown",
    [
        {"quantity": 100, "price": None, "market_value": None},
        {"shares": 100, "price": None, "market_value": None},
        {"quantity": 100, "price": None, "market_value": True},
        {"quantity": 100, "price": None, "market_value": float("nan")},
        {"quantity": 100, "price": None, "market_value": float("inf")},
        {"quantity": 100, "price": None, "market_value": "bad"},
        {"quantity": True, "price": 100, "market_value": None},
        {"quantity": "bad", "price": 100, "market_value": None},
        {"quantity": 100, "price": float("nan"), "market_value": None},
        {"quantity": 100, "price": float("inf"), "market_value": None},
        {"quantity": 100, "price": True, "market_value": None},
        {"quantity": 100, "price": None, "current_price": 100, "market_value": None},
    ],
)
def test_implicit_book_never_drops_an_unvalued_row(tmp_path, capsys, unknown):
    rc, report = run_book_cli(tmp_path, capsys, [position(), {"symbol": "BBB", **unknown}])
    assert rc == 2 and report["status"] == "unavailable"
    assert report["input"] == "book_value" and "incomplete" in report["reason"]
    assert not report.get("suggestions")


def test_explicit_book_can_qualify_known_row_without_claiming_complete_values(tmp_path, capsys):
    rows = [position(), {"symbol": "BBB", "quantity": 100, "price": None, "market_value": None}]
    rc, report = run_book_cli(tmp_path, capsys, rows, "--book-value=25000")
    assert rc == 0 and report["status"] == "ok"
    assert report["suggestions"][0]["symbol"] == "AAA"
    assert report["suggestions"][0]["pct_of_book"] == 40.0
    assert report["skipped"] == [{"symbol": "BBB", "account": None, "skipped": "position_value_unknown"}]
    assert report["book_value"] == 25000.0 and report["book_value_basis"] == "explicit"
    assert report["position_valuations_complete"] is False and report["unvalued_positions"] == 1


@pytest.mark.parametrize(
    "zero",
    [
        {"quantity": 100, "market_value": 0, "price": None},
        {"quantity": 0, "market_value": None, "price": None},
        {"shares": 0, "market_value": None, "price": None},
    ],
)
def test_known_zero_stays_a_complete_valuation(tmp_path, capsys, zero):
    rc, report = run_book_cli(tmp_path, capsys, [position(), {"symbol": "BBB", **zero}])
    assert rc == 0 and report["position_valuations_complete"] is True
    assert report["unvalued_positions"] == 0 and report["book_value"] == 10000.0
    assert report["suggestions"][0]["pct_of_book"] == 100.0


@pytest.mark.parametrize(
    "row,value",
    [
        ({"market_value": 0}, 0.0),
        ({"market_value": "0"}, 0.0),
        ({"quantity": 0}, 0.0),
        ({"shares": 0}, 0.0),
        ({"price": 100, "shares": 10}, 1000.0),
        ({"price": 100, "quantity": None, "shares": 10}, 1000.0),
        ({"price": 100, "market_value": "bad", "quantity": 10}, 1000.0),
        ({"price": 100, "market_value": float("nan"), "quantity": 10}, 1000.0),
        ({"price": 0, "quantity": 10}, 0.0),
        ({"price": -100, "quantity": 10}, None),
        ({"price": True, "quantity": 10}, None),
        ({"price": 100, "quantity": True}, None),
        ({"price": 1e308, "quantity": 1e308}, None),
        ({"market_value": 10**400}, None),
    ],
)
def test_value_availability_zero_alias_and_fallback_classes(row, value):
    assert adv.position_value(row) == value


@pytest.mark.parametrize("book", ["nan", "inf", "-inf", "-1", "0"])
def test_invalid_explicit_book_is_unavailable_for_positive_holdings(tmp_path, capsys, book):
    rc, report = run_book_cli(tmp_path, capsys, [position()], "--book-value=" + book)
    assert rc == 2 and report["status"] == "unavailable" and report["input"] == "book_value"


def test_implicit_total_overflow_is_not_a_known_book(tmp_path, capsys):
    rows = [position(market_value=1e308), position(symbol="BBB", market_value=1e308)]
    rc, report = run_book_cli(tmp_path, capsys, rows)
    assert rc == 2 and report["status"] == "unavailable" and report["input"] == "book_value"


@pytest.mark.parametrize("explicit", [False, True])
def test_valid_empty_and_zero_book_remain_measured(tmp_path, capsys, explicit):
    rc, report = run_book_cli(tmp_path, capsys, [], *(["--book-value=0"] if explicit else []))
    assert rc == 0 and report["status"] == "ok" and report["examined"] == 0
    assert report["position_valuations_complete"] is True and report["book_value"] == 0.0


@pytest.mark.parametrize("book", [None, True, float("nan"), float("inf"), -1, 0])
def test_pure_report_does_not_call_invalid_denominator_available(book):
    report = adv.suggest_for_book([position()], book_value=book, events={"AAA": {"days_to_event": 10}})
    assert report["status"] == "unavailable" and not report["suggestions"]


@pytest.mark.parametrize("value,book,expected", [(1e308, 1e308, 100.0), (1e308, 1e-308, None)])
def test_finite_book_percentage_never_overflows_into_a_known_percentage(value, book, expected):
    assert adv.pct_of_book(value, book) == expected


@pytest.mark.parametrize(
    "row",
    [position(quantity=1, price=1e308, market_value=1e308), position(quantity=1e-308, price=None, market_value=10000)],
)
def test_unrepresentable_reference_unit_is_skipped_without_nonfinite_json(row):
    report = adv.suggest_for_book([row], book_value=row["market_value"], events={"AAA": {"days_to_event": 10}})
    assert not report["suggestions"]
    assert report["skipped"][0]["skipped"] == "unit_economics_not_finite"
    json.dumps(report, allow_nan=False)


def test_unrepresentable_call_credit_does_not_corrupt_usable_put():
    quotes = chain()
    call = quotes["expirations"][0]["strikes"][1]
    call.update(bid=1e308, ask=1e308)
    result, reason = suggest(quotes=quotes)
    assert reason is None and result["structure"] == "protective_put"
    assert "collar_per_contract" not in result
    assert result["collar_unavailable_reason"] == "call_unit_economics_not_finite"
    json.dumps(result, allow_nan=False)


# Cloud P1: legacy price may be the entire value of a fractional holding.
@pytest.mark.parametrize("quantity_key", ["quantity", "shares"])
def test_fractional_cli_uses_named_per_share_mark_before_strike_selection(tmp_path, capsys, quantity_key):
    row = {
        "symbol": "AAA",
        quantity_key: 0.5,
        "price": 50,
        "market_value": 50,
        "canonical_mark": 100,
        "canonical_mark_source": "synthetic_quote",
        "canonical_mark_as_of": "2030-01-07T12:00:00Z",
    }
    rc, report = run_book_cli(tmp_path, capsys, [row], "--book-value=500")
    result = report["suggestions"][0]
    assert rc == 0 and result["floor_target"] == 90.0 and result["floor_price"] == 90.0
    assert result["reference_price"] == 100.0 and result["reference_price_source"] == "synthetic_quote"
    assert result["reference_price_as_of"] == "2030-01-07T12:00:00Z"
    assert result["reference_price_basis"] == "named_canonical_mark"
    assert result["coverage_status"] == "not_selected" and result["position_floor_after_cost"] is None
    assert "collar_per_contract" not in result


@pytest.mark.parametrize("quantity_key", ["quantity", "shares"])
def test_stuffed_total_uses_existing_canonical_classification_and_labels_implied(quantity_key):
    row = {"symbol": "AAA", quantity_key: 0.5, "price": 50, "market_value": 50}
    result, reason = adv.suggest_for_position(row, book_value=500, event={"days_to_event": 10}, now=NOW)
    assert reason is None and result["floor_target"] == 90.0
    assert result["reference_price"] == 100.0 and result["reference_price_basis"] == "implied_from_mv"
    assert result["reference_price_source"] == "implied_from_mv"
    assert result["cost_per_contract_usd"] == 250.0


def test_named_mark_drives_unit_economics_instead_of_independent_book_value():
    row = position(quantity=0.5, price=50, market_value=50, canonical_mark=200)
    result, reason = adv.suggest_for_position(row, book_value=500, event={"days_to_event": 10}, now=NOW)
    assert reason is None and result["floor_target"] == 180.0
    assert result["cost_per_contract_usd"] == 500.0 and result["pct_of_book"] == 10.0


@pytest.mark.parametrize("field", ["canonical_mark", "mark", "last", "official_close"])
def test_sanctioned_mark_can_value_a_row_without_legacy_price(field):
    row = {"symbol": "AAA", "shares": 0.5, field: 100}
    assert adv.position_value(row) == 50.0
    result, reason = adv.suggest_for_position(row, book_value=500, event={"days_to_event": 10}, now=NOW)
    assert reason is None and result["reference_price"] == 100.0
    assert result["floor_target"] == 90.0 and result["cost_per_contract_usd"] == 250.0


@pytest.mark.parametrize("mark", [None, "bad", True, float("nan"), float("inf"), -1, 0])
def test_explicit_unusable_named_mark_never_reverts_to_ambiguous_price(mark):
    row = position(quantity=0.5, price=50, market_value=50, canonical_mark=mark)
    assert adv.suggest_for_position(row, book_value=500, event={"days_to_event": 10}) == (
        None,
        "per_share_mark_unknown",
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"price": 50},
        {"price": None, "current_price": 100},
        {"price": None, "mark": True},
        {"price": None, "mark": float("nan")},
        {"price": None, "mark": float("inf")},
    ],
)
def test_unknown_fractional_per_share_price_is_not_invented(extra):
    row = {"symbol": "AAA", "quantity": 0.5, **extra}
    assert adv.position_value(row) is None


@pytest.mark.parametrize(
    "extra", [{"conflicted": True}, {"not_for_valuation": True}, {"proxy": True}, {"price": 100, "mark": 120}]
)
def test_conflicted_or_nonvaluation_marks_are_not_protective_references(extra):
    row = position(canonical_mark=100, **extra)
    assert suggest(row)[1] == "per_share_mark_unknown"


def test_neutral_canonical_helper_recognizes_synthetic_stuffed_fractional_shape():
    from lib.cio_canonical_quote import apply_canonical_quote_fields

    named = apply_canonical_quote_fields({"symbol": "AAA", "shares": 0.5, "price": 50, "market_value": 50, "mark": 100})
    assert named["price_field_role"] == "market_value" and named["canonical_mark"] == 100
    assert named["conflicted"] is False


def test_config_notes_describe_the_emitted_v2_units_and_deliberately_unselected_coverage():
    notes = json.loads((ROOT / "config/protective_put_advisory.json").read_bytes())["notes"]
    assert "100 reference shares" in notes["cost"] and "per contract" in notes["cost"]
    assert "floor_per_covered_share_after_premium" in notes["floor_after_cost"]
    assert "floor_after_premium_note" in notes["floor_after_cost"]
    assert "floor_after_cost_negative" not in notes["floor_after_cost"]
    assert "coverage_status" in notes["partial_coverage"] and "not_selected" in notes["partial_coverage"]
    assert "No contract count" in notes["partial_coverage"] and "worst-case-per-share" in notes["partial_coverage"]


def test_quoted_strike_selection_uses_named_mark_with_competing_legacy_value_strike():
    quotes = chain(call=False)
    quotes["expirations"][0]["strikes"].append({"side": "put", "strike": 45.0, "bid": 0.4, "ask": 0.5})
    row = position(quantity=0.5, price=50, market_value=50, canonical_mark=100)
    result, reason = adv.suggest_for_position(row, book_value=500, event={"days_to_event": 10}, chain=quotes, now=NOW)
    assert reason is None and result["floor_target"] == 90.0 and result["floor_price"] == 90.0
    assert result["cost_per_contract_usd"] == 210.0


@pytest.mark.parametrize("extra", [{"quantity": 0.5}, {"quantity": None, "shares": 0.5}])
def test_named_mark_values_fractional_aliases_without_a_total_value(extra):
    row = {"symbol": "AAA", "price": 50, "canonical_mark": "100", **extra}
    assert adv.position_value(row) == 50.0


def test_unambiguous_fractional_price_agrees_with_existing_value_and_is_not_divided_again():
    row = {"symbol": "AAA", "shares": 0.5, "price": 100, "market_value": 50}
    result, reason = adv.suggest_for_position(row, book_value=500, event={"days_to_event": 10}, now=NOW)
    assert reason is None and result["reference_price"] == 100 and result["floor_target"] == 90
    assert result["reference_price_as_of"] is None
