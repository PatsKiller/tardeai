"""Stage 2 discovery tests — mocks and fixtures only (no real broker calls, no DB).

Run: .venv/bin/python -m pytest tests/test_active_trader_stage2_discovery.py -q
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader.contracts import CapabilityState, ContractViolation, Environment  # noqa: E402
from active_trader.discovery import (  # noqa: E402
    CAPABILITY_DIMENSIONS, DiscoveredAccount, MoomooDiscovery, WRITE_CAPABILITIES,
    build_projection, make_capability, mask_identifier,
)
from active_trader import discovery_alpaca, discovery_schwab  # noqa: E402

NOW = datetime(2026, 7, 22, 18, 0, tzinfo=timezone.utc)


# ---------------- capability factory / expiry rules
def test_runtime_read_probe_is_short_lived():
    cap = make_capability("alpaca", "a", Environment.SIMULATION, "READ_ACCOUNT",
                          CapabilityState.SUPPORTED, "RUNTIME_READ_PROBE", NOW)
    assert cap.expires_at == NOW + timedelta(hours=24)
    assert cap.effective_state(NOW + timedelta(hours=25)) is CapabilityState.UNKNOWN


def test_existing_adapter_requires_version_stamp():
    with pytest.raises(ContractViolation, match="adapter version"):
        make_capability("schwab", "a", Environment.LIVE, "CANCEL_ORDER",
                        CapabilityState.RESTRICTED, "EXISTING_ADAPTER", NOW)


def test_documentation_requires_review_date_and_override_requires_expiry():
    with pytest.raises(ContractViolation, match="review date"):
        make_capability("alpaca", "a", Environment.SIMULATION, "SHORT_SELL",
                        CapabilityState.UNKNOWN, "DOCUMENTATION", NOW)
    with pytest.raises(ContractViolation, match="explicit expiry"):
        make_capability("alpaca", "a", Environment.SIMULATION, "SHORT_SELL",
                        CapabilityState.SUPPORTED, "OPERATOR_OVERRIDE", NOW)


def test_write_capability_can_never_come_from_read_probe():
    for wcap in sorted(WRITE_CAPABILITIES)[:3]:
        with pytest.raises(ContractViolation, match="read probe"):
            make_capability("alpaca", "a", Environment.SIMULATION, wcap,
                            CapabilityState.SUPPORTED, "RUNTIME_READ_PROBE", NOW)


def test_unknown_dimension_and_source_rejected():
    with pytest.raises(ContractViolation):
        make_capability("alpaca", "a", Environment.SIMULATION, "TELEPORT",
                        CapabilityState.UNKNOWN, "DOCUMENTATION", NOW, review_date=NOW)
    with pytest.raises(ContractViolation):
        make_capability("alpaca", "a", Environment.SIMULATION, "READ_ACCOUNT",
                        CapabilityState.UNKNOWN, "GUESSWORK", NOW)


def test_mask_identifier_never_returns_input():
    assert mask_identifier("PA3ABCDE12345") == "***2345"
    assert mask_identifier("12") == "***2"
    assert mask_identifier(None) == "***"
    with pytest.raises(ContractViolation):
        DiscoveredAccount("alpaca", "x", "12345678", Environment.SIMULATION.value,
                          "paper", "ACTIVE", "OK", "OK")


# ---------------- alpaca discovery (mock HTTP; no network)
PAPER_ENV = {"ALPACA_PAPER_API_KEY": "PKTESTFAKE", "ALPACA_PAPER_SECRET_KEY": "FAKESECRET"}


@pytest.fixture(autouse=True)
def _no_env_autoload(monkeypatch):
    """env_bootstrap.ensure_loaded re-injects the real production env inside
    resolve_credentials; disable it so slot tests are hermetic."""
    lib_dir = str(Path(__file__).resolve().parents[1] / "scripts" / "lib")
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    try:
        import env_bootstrap
        monkeypatch.setattr(env_bootstrap, "ensure_loaded", lambda *a, **k: None)
    except ImportError:
        pass
    yield


def fake_http(status_map):
    def _get(base, path, key, secret, timeout):
        body = None
        if path == "/v2/account":
            body = {"account_number": "PA9990001234", "status": "ACTIVE", "buying_power": "100"}
        elif path == "/v2/positions":
            body = []
        elif path.startswith("/v2/orders"):
            body = []
        elif path == "/v2/clock":
            body = {"is_open": False}
        elif path.startswith("/v2/assets"):
            body = {"tradable": True}
        return status_map.get(base, 200), body
    return _get


def test_alpaca_paper_fixture_discovery(monkeypatch):
    for k, v in PAPER_ENV.items():
        monkeypatch.setenv(k, v)
    for k in ("ALPACA_TAXABLE_API_KEY", "ALPACA_TAXABLE_SECRET_KEY",
              "ALPACA_IRA_API_KEY", "ALPACA_IRA_SECRET_KEY",
              "ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    res = discovery_alpaca.discover(http_get=fake_http({}), now=NOW)
    paper = next(a for a in res.accounts if a.account_label == "alpaca_paper")
    assert paper.read_state == "OK" and paper.authentication_state == "OK"
    assert paper.masked_account_id == "***1234"
    reads = {c.capability for c in paper.capabilities if c.state is CapabilityState.SUPPORTED}
    assert {"READ_ACCOUNT", "READ_POSITIONS", "READ_OPEN_ORDERS", "READ_BALANCES",
            "SYMBOL_TRADABILITY"} <= reads
    # missing live credential slots reported explicitly, not guessed
    tax = next(a for a in res.accounts if a.account_label == "alpaca_taxable_live")
    ira = next(a for a in res.accounts if a.account_label == "alpaca_ira_live")
    assert tax.status == ira.status == "NOT_CONFIGURED"
    assert tax.authentication_state == "NOT_CONFIGURED"
    assert res.account_discovery == "PARTIAL"


def test_alpaca_paper_write_grades_do_not_leak_to_live(monkeypatch):
    for k, v in PAPER_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ALPACA_TAXABLE_API_KEY", "FAKELIVEKEY")
    monkeypatch.setenv("ALPACA_TAXABLE_SECRET_KEY", "FAKELIVESECRET")
    monkeypatch.delenv("ALPACA_IRA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_IRA_SECRET_KEY", raising=False)
    res = discovery_alpaca.discover(http_get=fake_http({}), now=NOW)
    paper = next(a for a in res.accounts if a.account_label == "alpaca_paper")
    live = next(a for a in res.accounts if a.account_label == "alpaca_taxable_live")
    paper_place = next(c for c in paper.capabilities if c.capability == "PLACE_LIMIT_RTH")
    live_place = next(c for c in live.capabilities if c.capability == "PLACE_LIMIT_RTH")
    assert paper_place.state is CapabilityState.SUPPORTED      # existing paper lane evidence
    assert live_place.state is CapabilityState.UNSUPPORTED     # paper NEVER implies live
    # read supported on live slot does not imply write anywhere
    assert next(c for c in live.capabilities if c.capability == "READ_ACCOUNT").state \
        is CapabilityState.SUPPORTED


def test_alpaca_expired_auth(monkeypatch):
    for k, v in PAPER_ENV.items():
        monkeypatch.setenv(k, v)
    for k in ("ALPACA_TAXABLE_API_KEY", "ALPACA_TAXABLE_SECRET_KEY",
              "ALPACA_IRA_API_KEY", "ALPACA_IRA_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    res = discovery_alpaca.discover(
        http_get=lambda b, p, k, s, t: (401, None), now=NOW)
    paper = next(a for a in res.accounts if a.account_label == "alpaca_paper")
    assert paper.authentication_state == "EXPIRED" and paper.read_state == "UNAVAILABLE"


def test_alpaca_module_has_no_write_method():
    assert not any(n.startswith(("submit", "post", "cancel", "replace", "close"))
                   for n in dir(discovery_alpaca))


# ---------------- schwab discovery (fake transport; proves read-only usage)
class FakeTransport:
    """Only read methods exist — if discovery touched anything else it would raise."""
    def __init__(self, behaviors):
        self.behaviors = behaviors

    def get_account(self, key):
        return self.behaviors.get(key, {}).get("account", {"status": "error", "error": "auth expired"})

    def get_positions(self, key):
        return self.behaviors.get(key, {}).get("positions", {"status": "error", "error": "x"})

    def get_orders(self, key):
        return self.behaviors.get(key, {}).get("orders", {"status": "error", "error": "x"})

    def get_market_hours(self, account_key=None):
        return {"equity": {"isOpen": False}}


GOOD = {"account": {"account_number": "998877665", "balances": {"cash": 1}},
        "positions": [], "orders": []}


def test_schwab_multi_account_discovery_and_mapping():
    t = FakeTransport({"schwab_rollover_ira": GOOD, "schwab_roth": GOOD,
                       "schwab_taxable": {"account": {"status": "needs_mapping"}}})
    res = discovery_schwab.discover(transport=t, now=NOW)
    assert len(res.accounts) == 3
    ira = next(a for a in res.accounts if a.account_label == "schwab_rollover_ira")
    assert ira.read_state == "OK" and ira.masked_account_id == "***7665"
    tax = next(a for a in res.accounts if a.account_label == "schwab_taxable")
    assert tax.status == "NEEDS_MAPPING"
    assert res.account_discovery == "PARTIAL"


def test_schwab_expired_auth_and_partial_outage():
    t = FakeTransport({"schwab_rollover_ira": GOOD})
    res = discovery_schwab.discover(transport=t, now=NOW)
    roth = next(a for a in res.accounts if a.account_label == "schwab_roth")
    assert roth.authentication_state == "EXPIRED" and roth.read_state == "UNAVAILABLE"
    ira = next(a for a in res.accounts if a.account_label == "schwab_rollover_ira")
    assert ira.read_state == "OK"          # one account's failure does not spread


def test_schwab_write_capabilities_fence_derived_only():
    t = FakeTransport({"schwab_rollover_ira": GOOD})
    res = discovery_schwab.discover(transport=t, now=NOW)
    ira = next(a for a in res.accounts if a.account_label == "schwab_rollover_ira")
    states = {c.capability: c.state for c in ira.capabilities}
    assert states["PLACE_LIMIT_RTH"] is CapabilityState.RESTRICTED
    assert states["CANCEL_ORDER"] is CapabilityState.RESTRICTED
    assert states["ELECTRONIC_ENTRY_ELIGIBILITY"] is CapabilityState.UNKNOWN  # needs a rejection to prove
    assert states["NATIVE_CLOSE_ALL"] is CapabilityState.UNKNOWN
    # adapter method existing in source proves nothing SUPPORTED:
    assert not any(c.state is CapabilityState.SUPPORTED and c.capability in WRITE_CAPABILITIES
                   for c in ira.capabilities)


def test_schwab_fake_transport_never_asked_for_writes():
    t = FakeTransport({"schwab_rollover_ira": GOOD, "schwab_roth": GOOD, "schwab_taxable": GOOD})
    discovery_schwab.discover(transport=t, now=NOW)  # would AttributeError on any write call
    assert not hasattr(t, "place_order") and not hasattr(t, "cancel_order")


# ---------------- moomoo placeholder
def test_moomoo_not_installed_and_fleet_survives():
    res = MoomooDiscovery().discover(now=NOW)
    assert res.connector_state == "NOT_INSTALLED"
    assert res.account_discovery == "UNAVAILABLE"
    assert res.errors == []
    acct = res.accounts[0]
    assert acct.authentication_state == "NOT_CONFIGURED"
    assert all(c.state is CapabilityState.UNKNOWN for c in acct.capabilities)


# ---------------- projection / discrepancies
def _acct(broker, label, env=Environment.LIVE.value, auth="OK", caps=(), status="ACTIVE"):
    return DiscoveredAccount(broker, label, "***123", env, "t", status, "OK", auth,
                             capabilities=list(caps), observed_at=NOW.isoformat())


def _res(broker, accounts):
    from active_trader.discovery import BrokerDiscoveryResult
    return BrokerDiscoveryResult(broker, "AVAILABLE", "OK", accounts, [], NOW.isoformat())


def test_projection_discrepancies():
    configured = [
        {"broker": "schwab", "account_key": "schwab_roth", "active": True},
        {"broker": "schwab", "account_key": "schwab_ghost", "active": True},
        {"broker": "alpaca", "account_key": "alpaca_paper", "account_id": "paper", "read_only": False},
        {"broker": "snaptrade", "account_key": "fidelity_ro", "active": True},  # excluded broker retained
    ]
    sup_write = make_capability("alpaca", "alpaca_paper", Environment.SIMULATION,
                                "PLACE_LIMIT_RTH", CapabilityState.SUPPORTED,
                                "EXISTING_ADAPTER", NOW, adapter_version="v")
    discovered = [
        _res("schwab", [_acct("schwab", "schwab_roth", auth="EXPIRED"),
                        _acct("schwab", "schwab_new")]),
        _res("alpaca", [_acct("alpaca", "alpaca_paper", env=Environment.LIVE.value,
                              caps=[sup_write])]),
    ]
    proj = build_projection(configured, discovered)
    kinds = sorted(d["kind"] for d in proj["discrepancies"])
    assert "configured_but_not_returned_by_broker" in kinds       # schwab_ghost
    assert "returned_by_broker_but_not_configured" in kinds       # schwab_new
    assert "expired_authentication" in kinds                       # schwab_roth
    assert "paper_live_mismatch" in kinds                          # alpaca paper marked LIVE
    assert not any(d.get("broker") == "snaptrade" for d in proj["discrepancies"])


def test_projection_duplicate_mapping():
    discovered = [_res("schwab", [_acct("schwab", "dup"), _acct("schwab", "dup")])]
    proj = build_projection([], discovered)
    assert any(d["kind"] == "duplicate_account_mapping" for d in proj["discrepancies"])


def test_projection_no_accounts():
    proj = build_projection([], [_res("alpaca", [])])
    assert proj["accounts"] == [] and proj["discrepancies"] == []


# ---------------- probe runner safety
def test_probe_runner_dry_run_and_allowlist():
    import subprocess
    repo = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(repo / "scripts/active_trader/probe_brokers.py"),
                        "--dry-run"], capture_output=True, text=True)
    assert r.returncode == 0 and "METHOD PLAN" in r.stdout and "dry-run" in r.stdout
    assert "POST" not in r.stdout and "DELETE" not in r.stdout
    r2 = subprocess.run([sys.executable, str(repo / "scripts/active_trader/probe_brokers.py"),
                         "--brokers", "tastytrade", "--dry-run"], capture_output=True, text=True)
    assert r2.returncode == 2 and "allowlist" in r2.stderr
