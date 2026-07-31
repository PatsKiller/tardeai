from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def order(symbol, account_order_id, status="WORKING", order_type="STOP", qty=10, stop_price=90.0, children=None):
    o = {
        "orderId": account_order_id,
        "status": status,
        "orderType": order_type,
        "orderLegCollection": [{
            "instruction": "SELL",
            "quantity": qty,
            "instrument": {"symbol": symbol},
        }],
    }
    if stop_price is not None:
        o["stopPrice"] = stop_price
    if children is not None:
        o["childOrderStrategies"] = children
    return o


def trailing(symbol, order_id, status="AWAITING_STOP_CONDITION", qty=10, order_type="TRAILING_STOP"):
    o = order(symbol, order_id, status=status, order_type=order_type, qty=qty, stop_price=None)
    o["stopPriceOffset"] = 6.9
    o["stopPriceLinkType"] = "PERCENT"
    return o


def install_fake_schwab(monkeypatch, orders_by_account):
    fake = types.SimpleNamespace()
    calls = []

    def get_orders_raw(account):
        calls.append(account)
        return orders_by_account.get(account, {"status": "degraded"})

    fake.get_orders_raw = get_orders_raw
    monkeypatch.setitem(sys.modules, "schwab_transport", fake)
    return calls


def fresh_oti():
    import open_trades_intelligence as oti
    oti = importlib.reload(oti)
    oti._BSTOP_CACHE.update(
        ts=0.0,
        map={},
        key=None,
        fetched_at=None,
        read_ok=set(),
        read_errors={},
        read_attempted=set(),
        flat_count=0,
        nested_count=0,
        statuses_observed=set(),
        expected_accounts=set(),
        capability_available=True,
        complete=False,
        degraded=False,
        safe_error_code=None,
        safe_error_summary=None,
        cache_status="empty",
        last_good_map={},
        last_good_fetched_at=None,
        last_good_key=None,
    )
    return oti


def test_all_three_schwab_accounts_roth_mapping_and_duplicate_symbol(monkeypatch):
    oti = fresh_oti()
    calls = install_fake_schwab(monkeypatch, {
        "schwab_rollover_ira": [order("V", "r1", status="PENDING_ACTIVATION")],
        "schwab_roth": {"status": "needs_account_hash"},
        "schwab_roth_ira": [order("V", "roth1", status="AWAITING_STOP_CONDITION")],
        "schwab_taxable": [order("SCHD", "t1", status="AWAITING_STOP_CONDITION")],
    })

    out = oti._broker_protective_stops(["schwab_rollover_ira", "schwab_roth", "schwab_taxable"])

    assert set(out) == {
        ("schwab_rollover", "V"),
        ("schwab_roth", "V"),
        ("schwab_taxable", "SCHD"),
    }
    assert out[("schwab_roth", "V")]["account"] == "schwab_roth"
    assert calls == ["schwab_rollover_ira", "schwab_roth", "schwab_roth_ira", "schwab_taxable"]
    status = oti.broker_stop_read_status()
    assert status["accounts_read_ok"] == 3
    assert status["accounts_failed"] == 0



def test_schwab_account_number_enumeration_reads_child_hashes_in_memory(monkeypatch):
    oti = fresh_oti()

    class Resp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code
        def json(self):
            return self._payload

    class Client:
        def __init__(self):
            self.order_hashes = []
        def get_account_numbers(self):
            return Resp([
                {"accountNumber": "XXXX258", "hashValue": "hash-roll"},
                {"accountNumber": "XXXX415", "hashValue": "hash-roth"},
                {"accountNumber": "XXXX469", "hashValue": "hash-tax"},
            ])
        def get_orders_for_account(self, account_hash, **_kwargs):
            self.order_hashes.append(account_hash)
            payload = {
                "hash-roll": [order("V", "r1", status="PENDING_ACTIVATION")],
                "hash-roth": [order("V", "roth1", status="AWAITING_STOP_CONDITION")],
                "hash-tax": [order("SCHD", "t1", status="QUEUED")],
            }[account_hash]
            return Resp(payload)

    client = Client()
    fake = types.SimpleNamespace(build_client=lambda _account: (client, None))
    monkeypatch.setitem(sys.modules, "schwab_transport", fake)

    out = oti._broker_protective_stops(["schwab_rollover_ira", "schwab_roth_ira", "schwab_taxable"])

    assert set(out) == {("schwab_rollover", "V"), ("schwab_roth", "V"), ("schwab_taxable", "SCHD")}
    assert client.order_hashes == ["hash-roll", "hash-roth", "hash-tax"]
    status = oti.broker_stop_read_status()
    assert status["accounts_read_ok"] == 3
    assert status["read_error_accounts"] == []

def test_live_statuses_types_and_trailing_without_stop_price(monkeypatch):
    oti = fresh_oti()
    install_fake_schwab(monkeypatch, {
        "schwab_rollover_ira": [
            order("WORK", "1", status="WORKING"),
            order("QUE", "2", status="QUEUED"),
            order("ASC", "3", status="AWAITING_STOP_CONDITION"),
            order("SL", "4", status="ACCEPTED", order_type="STOP_LIMIT"),
            trailing("TRAIL", "5", order_type="TRAILING_STOP"),
            trailing("TRAILL", "6", order_type="TRAILING_STOP_LIMIT"),
            order("CANC", "7", status="CANCELED"),
            order("FILL", "8", status="FILLED"),
            order("EXP", "9", status="EXPIRED"),
        ]
    })

    out = oti._broker_protective_stops(["schwab_rollover_ira"])

    assert {sym for (_acct, sym) in out} == {"WORK", "QUE", "ASC", "SL", "TRAIL", "TRAILL"}
    assert out[("schwab_rollover", "TRAIL")]["stop_price"] is None
    assert out[("schwab_rollover", "TRAIL")]["trail_offset"] == 6.9
    assert out[("schwab_rollover", "TRAILL")]["order_type"] == "TRAILING_STOP_LIMIT"


def test_nested_child_orders_and_canceled_children(monkeypatch):
    oti = fresh_oti()
    live_child = order("OCO", "c1", status="AWAITING_PARENT_ORDER", qty=5)
    trailing_child = trailing("TRIG", "c2", status="AWAITING_CONDITION", qty=6)
    canceled_child = order("DEAD", "c3", status="CANCELED")
    live_parent_canceled_child = order("PARENT", "p2", status="WORKING", order_type="LIMIT", children=[canceled_child])
    canceled_parent_live_child = order("PARENT", "p3", status="CANCELED", order_type="LIMIT", children=[live_child])
    install_fake_schwab(monkeypatch, {
        "schwab_taxable": [
            order("PARENT", "p1", status="WORKING", order_type="LIMIT", children=[live_child, trailing_child]),
            live_parent_canceled_child,
            canceled_parent_live_child,
        ]
    })

    out = oti._broker_protective_stops(["schwab_taxable"])

    assert ("schwab_taxable", "OCO") in out
    assert ("schwab_taxable", "TRIG") in out
    assert ("schwab_taxable", "DEAD") not in out
    assert out[("schwab_taxable", "OCO")]["nested"] is True
    status = oti.broker_stop_read_status()
    assert status["nested_count"] == 3
    assert status["flat_count"] == 0


def test_per_account_failure_does_not_erase_successes(monkeypatch):
    oti = fresh_oti()
    install_fake_schwab(monkeypatch, {
        "schwab_rollover_ira": [order("V", "r1", status="AWAITING_STOP_CONDITION")],
        "schwab_taxable": {"status": "degraded"},
        "schwab_taxable_ira": {"status": "degraded"},
    })

    out = oti._broker_protective_stops(["schwab_rollover_ira", "schwab_taxable"])

    assert set(out) == {("schwab_rollover", "V")}
    status = oti.broker_stop_read_status()
    assert status["read_ok_accounts"] == ["schwab_rollover"]
    assert status["read_error_accounts"] == ["schwab_taxable"]
    assert status["accounts_failed"] == 1


def test_live_stops_endpoint_keys_and_degraded_metadata(monkeypatch):
    import api_v2
    import open_trades_intelligence as oti
    api_v2 = importlib.reload(api_v2)
    oti = importlib.reload(oti)

    monkeypatch.setattr(api_v2, "_load_json", lambda _p: {"holdings": [
        {"symbol": "V", "account": "schwab_rollover_ira"},
        {"symbol": "V", "account": "schwab_roth"},
        {"symbol": "SCHD", "account": "schwab_taxable"},
    ]})
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    monkeypatch.setattr(api_v2, "_resolve_protective_account_key", lambda a: "schwab_roth_ira" if a == "schwab_roth" else a)
    monkeypatch.setattr(oti, "_broker_protective_stops", lambda _accounts, **_kwargs: {
        ("schwab_rollover", "V"): {"symbol": "V", "account": "schwab_rollover_ira", "order_type": "STOP", "status": "working", "qty": 10, "stop_price": 90, "order_id": "r"},
        ("schwab_roth", "V"): {"symbol": "V", "account": "schwab_roth", "order_type": "STOP", "status": "working", "qty": 8, "stop_price": 88, "order_id": "ro"},
    })
    monkeypatch.setattr(oti, "broker_stops_fetched_at", lambda: "2026-07-29T20:00:00+00:00")
    monkeypatch.setattr(oti, "broker_stop_read_status", lambda: {
        "read_ok_accounts": ["schwab_rollover", "schwab_roth"],
        "read_attempted_accounts": ["schwab_rollover", "schwab_roth", "schwab_taxable"],
        "read_error_accounts": ["schwab_taxable"],
        "accounts_read_ok": 2,
        "accounts_failed": 1,
    })

    out = api_v2._holdings_live_stops()

    assert sorted(out["by_key"]) == ["V:schwab_rollover_ira", "V:schwab_roth"]
    assert out["degraded"] is True
    assert out["unverified_accounts"] == ["schwab_taxable"]
    assert out["broker_stop_read_ok_accounts"] == ["schwab_rollover_ira", "schwab_roth"]


def test_endpoint_successful_empty_read_is_no_stop_not_unverifiable(monkeypatch):
    import api_v2
    import open_trades_intelligence as oti
    api_v2 = importlib.reload(api_v2)
    oti = importlib.reload(oti)

    monkeypatch.setattr(api_v2, "_load_json", lambda _p: {"holdings": [{"symbol": "QCOM", "account": "schwab_rollover_ira"}]})
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    monkeypatch.setattr(api_v2, "_resolve_protective_account_key", lambda a: a)
    monkeypatch.setattr(oti, "_broker_protective_stops", lambda _accounts, **_kwargs: {})
    monkeypatch.setattr(oti, "broker_stops_fetched_at", lambda: "2026-07-29T20:00:00+00:00")
    monkeypatch.setattr(oti, "broker_stop_read_status", lambda: {
        "read_ok_accounts": ["schwab_rollover"],
        "read_attempted_accounts": ["schwab_rollover"],
        "read_error_accounts": [],
        "accounts_read_ok": 1,
        "accounts_failed": 0,
    })

    out = api_v2._holdings_live_stops()

    assert out["by_key"] == {}
    assert out["degraded"] is False
    assert out["unverified_accounts"] == []


def test_no_broker_write_method_is_imported_or_called():
    source = (ROOT / "scripts" / "open_trades_intelligence.py").read_text()
    reader = source[source.index("def _broker_protective_stops"):source.index("def broker_stop_read_ok")]
    assert "place_order" not in reader
    assert "cancel_order" not in reader
    assert "request-approval" not in reader


def test_failed_refresh_returns_last_good_as_degraded_not_verified_empty(monkeypatch):
    oti = fresh_oti()

    class Resp:
        status_code = 200
        def __init__(self, payload):
            self._payload = payload
        def json(self):
            return self._payload

    class GoodClient:
        def get_account_numbers(self):
            return Resp([{"accountNumber": "XXXX258", "hashValue": "hash-roll"}])
        def get_orders_for_account(self, _hash, **_kwargs):
            return Resp([order("V", "r1", status="AWAITING_STOP_CONDITION")])

    monkeypatch.setitem(sys.modules, "schwab_transport", types.SimpleNamespace(build_client=lambda _a: (GoodClient(), None)))
    first = oti._broker_protective_stops(["schwab_rollover_ira"], force=True)
    assert set(first) == {("schwab_rollover", "V")}
    assert oti.broker_stop_read_result()["complete"] is True

    monkeypatch.setitem(sys.modules, "schwab_transport", types.SimpleNamespace(build_client=lambda _a: (None, {"status": "NOT_PROVEN"})))
    second = oti._broker_protective_stops(["schwab_rollover_ira"], force=True)
    result = oti.broker_stop_read_result()

    assert set(second) == {("schwab_rollover", "V")}
    assert result["complete"] is False
    assert result["degraded"] is True
    assert result["cache_status"] == "stale_last_good"
    assert result["failed_accounts"] == ["schwab_rollover"]


def test_failure_then_recovery_refreshes_complete_cache(monkeypatch):
    oti = fresh_oti()
    monkeypatch.setitem(sys.modules, "schwab_transport", types.SimpleNamespace(build_client=lambda _a: (None, {"status": "NOT_PROVEN"})))
    assert oti._broker_protective_stops(["schwab_rollover_ira"], force=True) == {}
    assert oti.broker_stop_read_result()["degraded"] is True

    class Resp:
        status_code = 200
        def __init__(self, payload):
            self._payload = payload
        def json(self):
            return self._payload

    class GoodClient:
        def get_account_numbers(self):
            return Resp([{"accountNumber": "XXXX258", "hashValue": "hash-roll"}])
        def get_orders_for_account(self, _hash, **_kwargs):
            return Resp([])

    monkeypatch.setitem(sys.modules, "schwab_transport", types.SimpleNamespace(build_client=lambda _a: (GoodClient(), None)))
    assert oti._broker_protective_stops(["schwab_rollover_ira"], force=True) == {}
    result = oti.broker_stop_read_result()
    assert result["complete"] is True
    assert result["degraded"] is False
    assert result["cache_status"] == "refresh_complete"


def test_endpoint_refresh_parameter_bypasses_live_stop_cache(monkeypatch):
    import api_v2
    import open_trades_intelligence as oti
    api_v2 = importlib.reload(api_v2)
    oti = importlib.reload(oti)
    calls = []

    monkeypatch.setattr(api_v2, "_load_json", lambda _p: {"holdings": [{"symbol": "QCOM", "account": "schwab_rollover_ira"}]})
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    monkeypatch.setattr(api_v2, "_resolve_protective_account_key", lambda a: a)
    def fake_broker(accounts, **kwargs):
        calls.append(kwargs.get("force"))
        return {}
    monkeypatch.setattr(oti, "_broker_protective_stops", fake_broker)
    monkeypatch.setattr(oti, "broker_stops_fetched_at", lambda: "2026-07-29T20:00:00+00:00")
    monkeypatch.setattr(oti, "broker_stop_read_status", lambda: {
        "read_ok_accounts": ["schwab_rollover"],
        "read_attempted_accounts": ["schwab_rollover"],
        "read_error_accounts": [],
    })
    monkeypatch.setattr(oti, "broker_stop_read_result", lambda: {"complete": True, "degraded": False, "cache_status": "refresh_complete"})

    api_v2._holdings_live_stops({"refresh": ["1"]})
    assert calls == [True]


def test_reconcile_dry_run_keeps_duplicate_symbols_account_aware(monkeypatch, tmp_path):
    import broker_stop_reconcile as rec
    rec = importlib.reload(rec)

    class Resp:
        status_code = 200
        def __init__(self, payload):
            self._payload = payload
        def json(self):
            return self._payload

    orders = {
        "hash-roll": [order("V", "r-v"), order("SCHD", "r-schd"), order("A", "r-a"), order("B", "r-b"), order("C", "r-c"), order("D", "r-d"), order("E", "r-e"), order("F", "r-f"), trailing("XLB", "r-xlb")],
        "hash-roth": [order("V", "ro-v")],
        "hash-tax": [order("SCHD", "t-schd"), order("G", "t-g"), order("H", "t-h"), order("I", "t-i")],
    }

    class Client:
        def get_account_numbers(self):
            return Resp([
                {"accountNumber": "XXXX258", "hashValue": "hash-roll"},
                {"accountNumber": "XXXX415", "hashValue": "hash-roth"},
                {"accountNumber": "XXXX469", "hashValue": "hash-tax"},
            ])
        def get_orders_for_account(self, h, **_kwargs):
            return Resp(orders[h])

    monkeypatch.setitem(sys.modules, "schwab_transport", types.SimpleNamespace(build_client=lambda _a: (Client(), None)))
    monkeypatch.setattr(rec, "STOPS_JSON", tmp_path / "stops.json")
    rec.STOPS_JSON.write_text(json.dumps({"V": {"source": "manual", "stop": 1}}, indent=2))

    report = rec.reconcile(apply=False)

    assert report["ok"] is True
    assert report["broker_stops_found"] == 14
    assert "V:schwab_rollover_ira" in report["account_aware_keys"]
    assert "V:schwab_roth" in report["account_aware_keys"]
    assert "SCHD:schwab_rollover_ira" in report["account_aware_keys"]
    assert "SCHD:schwab_taxable" in report["account_aware_keys"]
    assert "XLB:schwab_rollover_ira" in report["account_aware_keys"]
    assert "V" in report["kept_manual"]
    assert json.loads(rec.STOPS_JSON.read_text()) == {"V": {"source": "manual", "stop": 1}}


def test_live_stops_exception_envelope_is_fail_closed(monkeypatch):
    """Exception path must not look like verified empty (false-empty regression)."""
    import importlib
    import api_v2
    api_v2 = importlib.reload(api_v2)

    def boom(*a, **k):
        raise RuntimeError("simulated live-stops failure")

    monkeypatch.setattr(api_v2, "_load_json", boom)
    out = api_v2._holdings_live_stops()
    assert out.get("by_key") == {}
    assert out.get("degraded") is True
    assert out.get("broker_stop_read_ok_accounts") == []
    assert out.get("unverified_accounts")
    assert out.get("complete") is False
    assert out.get("capability_available") is False
    assert out.get("safe_error_code") == "live_stops_exception"
    assert "error" in out
