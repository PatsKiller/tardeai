import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/fidelity_manual_stop_ticket.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fidelity_manual_stop_ticket", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_fidelity_creates_manual_ticket_only():
    mod = load_module()
    t = mod.build_ticket(
        account="fidelity_rollover_ira",
        symbol="SCHD",
        shares=2000,
        order_type="STOP",
        current_price=31.82,
        stop_price=30.65,
        rationale="income ETF floor",
        source_timestamp="2026-06-30T13:50:00Z",
    )
    assert t["status"] == "MANUAL_PENDING"
    assert "Manual Fidelity ticket only — no API submit from Trade AI." in t["copy_text"]
    assert "Action: SELL" in t["copy_text"]
    assert "Stop price: $30.65" in t["copy_text"]
    assert "place_order" not in SCRIPT.read_text()
    assert "submit_order" not in SCRIPT.read_text()


def test_fidelity_trailing_ticket_copy_text_includes_required_fields():
    mod = load_module()
    t = mod.build_ticket(
        account="fidelity_rollover_ira",
        symbol="JEPQ",
        shares=1000.25,
        order_type="TRAILING_STOP",
        current_price=60.96,
        trail_pct=5.6,
        rationale="covered call ETF trail",
    )
    assert "Order type: TRAILING_STOP" in t["copy_text"]
    assert "Trailing percent: 5.60%" in t["copy_text"]
    assert "Residual: 0.250000 shares remain monitored/manual." in t["copy_text"]
    assert t["whole_qty"] == 1000
    assert t["residual_qty"] == 0.25


def test_fidelity_manual_status_transitions_are_auditable():
    mod = load_module()
    t = mod.build_ticket(account="fidelity_rollover_ira", symbol="SCHG", shares=2000, order_type="STOP", stop_price=31.79)
    placed = mod.transition_status(t, "MANUAL_PLACED", operator="operator", note="placed in Fidelity")
    skipped = mod.transition_status(t, "MANUAL_SKIPPED", operator="operator", note="quote stale")
    assert placed["status"] == "MANUAL_PLACED"
    assert placed["audit_event"] == "fidelity_manual_stop_status"
    assert skipped["status"] == "MANUAL_SKIPPED"
    assert skipped["operator"] == "operator"


def test_fidelity_funds_are_not_applicable():
    mod = load_module()
    t = mod.build_ticket(
        account="fidelity_rollover_ira",
        symbol="SPAXX",
        shares=265060.43,
        order_type="STOP",
        instrument_type="money_market_fund",
    )
    assert t["status"] == "MANUAL_NOT_APPLICABLE"
    assert t["controls_hidden"] is True
    assert "rebalance" in t["note"]
