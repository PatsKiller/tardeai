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
