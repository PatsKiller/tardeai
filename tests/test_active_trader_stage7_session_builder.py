"""Stage 7 tests — session builder (pure) + dev write plane (lab DB)."""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from active_trader.contracts import ContractViolation, Environment, FlagMode  # noqa: E402
from active_trader.session_builder import (  # noqa: E402
    AccountRole, AccountSelection, QuickAddUnit, QUICK_ADD_PRESETS, SessionDraftV2,
    SizingMode, compute_sizing, validate_feature_change, validate_quick_add,
)


def make_draft(**over):
    base = dict(
        draft_id="d1", draft_version=1, environment=Environment.SIMULATION, session_name="s",
        start="09:30", end="16:00", entry_cutoff="15:55", symbol_policy={"symbols": ["TESTA"]},
        account_roles=[AccountSelection("alpaca", "alpaca_paper", AccountRole.PRIMARY,
                                        capability_state="SUPPORTED")],
        quantity_policy={"mode": "SHARES"}, gross_notional_cap=1000, per_symbol_caps={},
        per_account_caps={}, risk_cap=100, trade_count_cap=3, daily_loss_cap=50,
        fallback_policy={}, quick_add_config={"unit": "SHARES", "presets": list(QUICK_ADD_PRESETS)},
        runner_policy={}, feature_policy_versions={"candidate_rule": "v1"}, created_by="op")
    base.update(over)
    return SessionDraftV2(**base)


# ---- versioning / clone / hash
def test_edit_bumps_version_and_prior_immutable_by_construction():
    d1 = make_draft()
    d2 = d1.edit(daily_loss_cap=75)
    assert d2.draft_version == 2 and d1.draft_version == 1
    assert d2.daily_loss_cap == 75 and d1.daily_loss_cap == 50


def test_clone_starts_at_version_1_new_id():
    c = make_draft().clone("d2", "op2")
    assert c.draft_id == "d2" and c.draft_version == 1 and c.created_by == "op2"


def test_canonical_hash_authority_only():
    d = make_draft()
    h = d.hash
    # non-authority fields (name/notes/version) do NOT change the authority hash
    assert d.edit(session_name="renamed", notes="x").hash == h
    same = make_draft(session_name="different", notes="different")
    assert same.hash == h
    # an authority change DOES change the hash
    assert make_draft(daily_loss_cap=999).hash != h


def test_hash_deterministic_and_account_order_independent():
    a = make_draft(account_roles=[
        AccountSelection("alpaca", "a1", AccountRole.PRIMARY, "SUPPORTED"),
        AccountSelection("schwab", "s1", AccountRole.FALLBACK, "RESTRICTED")])
    b = make_draft(account_roles=[
        AccountSelection("schwab", "s1", AccountRole.FALLBACK, "RESTRICTED"),
        AccountSelection("alpaca", "a1", AccountRole.PRIMARY, "SUPPORTED")])
    assert a.hash == b.hash


# ---- account roles / capability gating
def test_unsupported_capability_cannot_be_primary():
    with pytest.raises(ContractViolation, match="cannot be selected"):
        AccountSelection("schwab", "s", AccountRole.PRIMARY, capability_state="UNSUPPORTED")
    with pytest.raises(ContractViolation, match="cannot be selected"):
        AccountSelection("alpaca", "a", AccountRole.FALLBACK, capability_state="UNKNOWN")
    # DISABLED is fine regardless
    AccountSelection("schwab", "s", AccountRole.DISABLED, capability_state="UNKNOWN")


def test_moomoo_cannot_be_live():
    with pytest.raises(ContractViolation, match="moomoo cannot be selected for LIVE"):
        make_draft(environment=Environment.LIVE,
                   account_roles=[AccountSelection("moomoo", "m", AccountRole.PRIMARY, "SUPPORTED")])
    # moomoo DISABLED in SIMULATION is fine
    make_draft(account_roles=[AccountSelection("moomoo", "m", AccountRole.DISABLED, "UNKNOWN")])


# ---- sizing
def test_sizing_modes_and_rounding():
    assert compute_sizing(SizingMode.SHARES, requested_shares=10)["shares"] == 10
    s = compute_sizing(SizingMode.DOLLAR_NOTIONAL, notional=1000, price=30)
    assert s["shares"] == 33 and s["remainder"] > 0            # floor to whole shares
    r = compute_sizing(SizingMode.RISK_BASED, risk_dollars=100, per_share_risk=0.5)
    assert r["shares"] == 200
    frac = compute_sizing(SizingMode.DOLLAR_NOTIONAL, notional=1000, price=30, allow_fractions=True)
    assert abs(frac["shares"] - 33.3333) < 0.01


def test_sizing_invalid_inputs():
    for kw in (dict(mode=SizingMode.DOLLAR_NOTIONAL, notional=100, price=0),
               dict(mode=SizingMode.RISK_BASED, risk_dollars=100, per_share_risk=0),
               dict(mode=SizingMode.SHARES, requested_shares=-1)):
        with pytest.raises(ContractViolation):
            compute_sizing(**kw)


def test_quick_add_presets_and_caps():
    ok = validate_quick_add(100, QuickAddUnit.SHARES, price=4.0, per_share_risk=0.5,
                            caps={"max_shares": 500, "max_notional": 5000})
    assert ok["shares"] == 100 and not ok["blocked"]
    blocked = validate_quick_add(1000, QuickAddUnit.SHARES, price=4.0, per_share_risk=0.5,
                                 caps={"max_shares": 500})
    assert blocked["blocked"] and "share cap" in blocked["violations"][0]
    dollars = validate_quick_add(200, QuickAddUnit.DOLLARS, price=4.0, per_share_risk=0.5,
                                 caps={"gross_notional_remaining": 100})
    assert dollars["shares"] == 50 and dollars["blocked"]      # 50*4=200 > 100 remaining


def test_bad_quick_add_config_rejected():
    with pytest.raises(ContractViolation):
        make_draft(quick_add_config={"unit": "BANANAS"})
    with pytest.raises(ContractViolation):
        make_draft(quick_add_config={"unit": "SHARES", "presets": [-5]})


# ---- feature controls
def test_feature_modes_reject_live_canary():
    validate_feature_change("quick_add", FlagMode.SHADOW)
    validate_feature_change("smart_entry", FlagMode.SIMULATION)
    with pytest.raises(ContractViolation, match="LIVE_CANARY"):
        validate_feature_change("quick_add", FlagMode.LIVE_CANARY)
    with pytest.raises(ContractViolation):
        validate_feature_change("not_a_flag", FlagMode.OFF)


# ---- dev write plane (lab DB)
DSN = os.environ.get("ACTIVE_TRADER_TEST_DATABASE_DSN", "")


@pytest.mark.skipif(not DSN, reason="lab write DSN required")
class TestDevWritePlane:
    def _app(self, env="SHADOW"):
        from active_trader.dev_write_api import DevWriteApp
        import subprocess
        subprocess.run([sys.executable, str(REPO / "scripts/active_trader/migrate.py"), "up"],
                       capture_output=True, env={**os.environ, "ACTIVE_TRADER_TEST_DATABASE_DSN": DSN})
        return DevWriteApp(DSN, environment=env, identities=("test-op",))

    ID = {"x-at-test-identity": "test-op"}

    def test_env_and_prod_guards(self):
        from active_trader.dev_write_api import DevWriteApp, DevApiError
        from active_trader.migrate import MigrationError
        with pytest.raises(DevApiError):
            DevWriteApp(DSN, environment="LIVE")
        with pytest.raises(MigrationError):
            DevWriteApp("postgresql://u:p@localhost:5432/trade_ai", environment="SHADOW")

    def test_auth_and_audit_required(self):
        app = self._app()
        # no identity
        s, _, b = app.request("POST", "/api/v3/active-trader/dev/session/draft", {"draft_id": "x"}, {})
        assert s == 401
        # missing audit reason
        s2, _, b2 = app.request("POST", "/api/v3/active-trader/dev/session/draft",
                                {"draft_id": "x"}, self.ID)
        assert s2 == 400 and b2["error"]["code"] == "AUDIT_REQUIRED"

    def test_save_load_and_optimistic_conflict(self):
        app = self._app()
        import uuid
        did = str(uuid.uuid4())
        body = {"draft_id": did, "environment": "SIMULATION", "session_name": "t",
                "account_roles": [{"broker": "alpaca", "account_label": "alpaca_paper",
                                   "role": "PRIMARY", "capability_state": "SUPPORTED"}],
                "gross_notional_cap": 1000, "risk_cap": 100, "daily_loss_cap": 50,
                "trade_count_cap": 3, "quick_add_config": {"unit": "SHARES"},
                "audit_reason": "test save"}
        s, _, b = app.request("POST", "/api/v3/active-trader/dev/session/draft", body, self.ID)
        assert s == 200 and b["data"]["draft_version"] == 1
        s2, _, b2 = app.request("POST", "/api/v3/active-trader/dev/session/draft",
                                {**body, "expected_prev_version": 1}, self.ID)
        assert s2 == 200 and b2["data"]["draft_version"] == 2
        s3, _, b3 = app.request("POST", "/api/v3/active-trader/dev/session/draft",
                                {**body, "expected_prev_version": 1}, self.ID)  # stale
        assert s3 == 409 and b3["error"]["code"] == "OPTIMISTIC_CONFLICT"
        sl, _, bl = app.request("GET", f"/api/v3/active-trader/dev/session/{did}", None, self.ID)
        assert sl == 200 and len(bl["data"]["versions"]) == 2 and bl["data"]["versions"][0]["immutable"]

    def test_feature_set_rejects_live_canary_via_api(self):
        app = self._app()
        s, _, b = app.request("POST", "/api/v3/active-trader/dev/features",
                              {"flag_name": "quick_add", "mode": "LIVE_CANARY", "audit_reason": "x"}, self.ID)
        assert s == 422
        s2, _, b2 = app.request("POST", "/api/v3/active-trader/dev/features",
                               {"flag_name": "quick_add", "mode": "SHADOW", "audit_reason": "enable shadow"}, self.ID)
        assert s2 == 200 and b2["data"]["authorizes_trading"] is False
