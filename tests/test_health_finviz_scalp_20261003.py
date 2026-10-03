"""Two health-agent criticals that were false on 2026-10-03.

1. "Finviz cookie/screener failure ... screener ingestion dead": the data_source_health
   row still carried Friday's cookie-only verdict (written before the Elite API token
   backstop, #1397), and the agent never tried the token. With a working token it is
   an info-level rotation reminder; it is critical only when cookie AND token fail.
2. "GO scan rows but 0 momentum_scalp proposals" was CRITICAL because three skip
   reasons that are policy gates by their own reason codes were missing from the
   policy list: SKIPPED_NO_CATALYST (contract.require_catalyst), SKIPPED_CRITIC_BLOCK
   (critic=BLOCK) and SKIPPED_NOT_GO (scan decision NO_GO/WAIT).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _by_path(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ha = _by_path("health_agent_20261003", "scripts/health_agent.py")


def test_cookie_failure_with_working_token_is_info_not_critical(monkeypatch):
    monkeypatch.setattr(ha, "_finviz_token_backstop", lambda: (True, "4 screener rows"))
    f = ha._finviz_cookie_finding("finviz", "Zero rows returned — cookie may be expired", 43 * 60,
                                  "Zero rows returned — cookie may be expired")
    assert f["severity"] == "info"
    assert f["type"] == "finviz_cookie_expired_token_ok"
    assert "token works" in f["message"] and "dead" not in f["message"]


def test_cookie_and_token_both_failing_stays_critical(monkeypatch):
    monkeypatch.setattr(ha, "_finviz_token_backstop", lambda: (False, "HTTP 401"))
    f = ha._finviz_cookie_finding("finviz", "Zero rows returned — cookie may be expired", 43 * 60, "login page")
    assert f["severity"] == "critical"
    assert f["type"] == "finviz_cookie_expired"
    assert "both failing" in f["message"]


def test_token_backstop_never_echoes_the_token(monkeypatch):
    import types
    secret = "tok_SECRET_value_123456"
    sv = types.SimpleNamespace(_key=lambda name: secret, _finviz_token=lambda k: (False, "HTTP 403"))
    monkeypatch.setitem(sys.modules, "secret_validators", sv)
    ok, detail = ha._finviz_token_backstop()
    assert ok is False and secret not in detail
    sv_missing = types.SimpleNamespace(_key=lambda name: None, _finviz_token=lambda k: (True, "x"))
    monkeypatch.setitem(sys.modules, "secret_validators", sv_missing)
    assert ha._finviz_token_backstop() == (False, "FINVIZ_API_TOKEN not set")


def test_prod_skip_census_is_policy_only_so_warning():
    # Exact census from the live health agent, 2026-10-03.
    skips = {"SKIPPED_CRITIC_BLOCK": 17, "SKIPPED_CRITIC_DOWNGRADE": 17, "SKIPPED_DUPLICATE": 38,
             "SKIPPED_LIQUIDITY": 21, "SKIPPED_LOW_SCORE": 83, "SKIPPED_NO_CATALYST": 56,
             "SKIPPED_NOT_GO": 12, "SKIPPED_PREPROMOTION": 62}
    a = ha._assess_go_conversion(5, 0, skips, 5)
    assert a["finding"] is True and a["severity"] == "warning"


def test_an_unexpected_skip_reason_still_escalates():
    a = ha._assess_go_conversion(5, 0, {"SKIPPED_NO_CATALYST": 3, "SKIPPED_UNKNOWN_BUG": 1}, 5)
    assert a["severity"] == "critical"
