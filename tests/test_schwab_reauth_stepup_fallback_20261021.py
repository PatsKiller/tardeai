"""Schwab reauth page vs. the CC step-up gate (2026-10-21).

config/cc_auth.yaml puts GET /api/v2/brokers/schwab/reauth-url and POST .../exchange-code behind
step-up, and require_step_up() always refuses ("TOTP unlock not yet enabled"). The /v3/system/
schwab-reauth page offered that flow anyway and showed only the raw refusal, while token-health told
the operator to "renew via Command Center". These tests pin the fix: the gate is UNCHANGED (still
refuses), token-health reports the CC path blocked and names the CLI + Telegram paths, and the page
renders that fallback.

Hermetic: temp cc_auth config only; no DB, no network, no token or credential file, no Schwab call,
and no authorize URL is ever built.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import cc_auth  # noqa: E402

PAGE = ROOT / "apps" / "command-center-v3" / "src" / "pages" / "SchwabReauthHub.tsx"
REAUTH = ("GET", "/api/v2/brokers/schwab/reauth-url")
EXCHANGE = ("POST", "/api/v2/brokers/schwab/exchange-code")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for k in (cc_auth.ENFORCE_ENV, cc_auth.REPORT_ONLY_ENV, cc_auth.CONFIG_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(cc_auth.TOKEN_FILE_ENV, str(tmp_path / "absent_cc_service_token"))


def _write_cfg(tmp_path, step_up_mode: str) -> Path:
    import yaml

    raw = yaml.safe_load((ROOT / "config" / "cc_auth.yaml").read_text(encoding="utf-8"))
    raw["cc_auth"]["step_up"]["mode"] = step_up_mode
    raw["cc_auth"]["decision_log"] = str(tmp_path / "decisions.jsonl")
    p = tmp_path / "cc_auth.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return p


def test_gate_itself_still_refuses_schwab_reauth():
    """The fix must not weaken step-up: the committed policy still gates both reauth routes."""
    cfg = cc_auth.load_config(ROOT / "config" / "cc_auth.yaml")
    assert cfg.step_up_mode == "enforce"
    for m, p in (REAUTH, EXCHANGE):
        assert cc_auth.step_up_action(cfg, m, p) == "schwab_reauth"
        assert cc_auth.step_up_blocks_route(cfg, m, p) == "schwab_reauth"
    d = cc_auth.require_step_up(None, "schwab_reauth")
    assert not d.allowed and d.status == 403 and d.reason == cc_auth.STEP_UP_MESSAGE


def test_step_up_blocks_route_is_a_faithful_mirror(tmp_path):
    cfg = cc_auth.load_config(_write_cfg(tmp_path, "off"))
    assert cc_auth.step_up_blocks_route(cfg, *REAUTH) is None
    cfg = cc_auth.load_config(_write_cfg(tmp_path, "report_only"))
    assert cc_auth.step_up_blocks_route(cfg, *REAUTH) is None
    cfg = cc_auth.load_config(_write_cfg(tmp_path, "enforce"))
    # the read-only status route is never gated
    assert cc_auth.step_up_blocks_route(cfg, "GET", "/api/v2/brokers/schwab/token-health") is None


def test_token_health_reports_cc_path_blocked_and_names_cli(monkeypatch, tmp_path):
    import api_v2

    monkeypatch.setenv(cc_auth.CONFIG_ENV, str(_write_cfg(tmp_path, "enforce")))
    out = api_v2._schwab_reauth_operator_paths("schwab_taxable")
    assert out["cc_reauth_blocked"] is True
    assert out["cc_reauth_blocked_reason"] == cc_auth.STEP_UP_MESSAGE
    assert out["reauth_command"] == "python3 scripts/schwab_token_manager.py reauth-url schwab_taxable"
    assert out["exchange_command"].startswith("python3 scripts/schwab_token_manager.py exchange-code schwab_taxable ")
    assert out["telegram_paste_supported"] is True

    monkeypatch.setenv(cc_auth.CONFIG_ENV, str(_write_cfg(tmp_path, "off")))
    out = api_v2._schwab_reauth_operator_paths("schwab_taxable")
    assert out["cc_reauth_blocked"] is False and out["cc_reauth_blocked_reason"] is None


def test_token_health_wires_operator_paths_and_honest_message():
    src = (SCRIPTS / "api_v2.py").read_text(encoding="utf-8")
    body = src.split("def _schwab_token_health(", 1)[1].split("\ndef ", 1)[0]
    assert "_schwab_reauth_operator_paths(" in body and "**_paths" in body
    assert "renew from the host CLI or Telegram" in body


def test_reauth_page_renders_step_up_fallback():
    src = PAGE.read_text(encoding="utf-8")
    assert "cc_reauth_blocked" in src
    assert "isStepUpRefusal(r.status, j)" in src
    assert src.count("isStepUpRefusal(r.status, j)") == 2  # request-URL and submit-code paths
    assert 'data-testid="schwab-reauth-stepup-fallback"' in src
    assert "reauth_command" in src and "exchange_command" in src
    assert "Telegram" in src
