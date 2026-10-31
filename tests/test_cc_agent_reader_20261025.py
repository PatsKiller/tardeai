"""Read-only agent identity for automated checks of authenticated pages (2026-10-25).

Adversarial by design: the reader may GET on the loopback service listener and nothing else. It never becomes an
operator, never rides report_only into a write, never bypasses step-up, is ignored on the tailnet listener, and
every reader decision is logged. Hermetic: temp token files, temp decision log, no network.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import cc_auth  # noqa: E402

SERVICE = "s" * 48
READER = "r" * 48
WRITES = ("POST", "PUT", "PATCH", "DELETE")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for k in (cc_auth.ENFORCE_ENV, cc_auth.REPORT_ONLY_ENV, cc_auth.CONFIG_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(cc_auth.TOKEN_FILE_ENV, str(tmp_path / "absent_service"))
    monkeypatch.setenv(cc_auth.READER_TOKEN_FILE_ENV, str(tmp_path / "absent_reader"))
    cc_auth._READER_STORES.clear()
    yield
    cc_auth._READER_STORES.clear()
    cc_auth.set_request_principal("")


def _cfg(tmp_path, *, enforce=True, report_only=False, enabled=True, reader_value=READER, step_up_get=False):
    import yaml

    raw = yaml.safe_load((ROOT / "config/cc_auth.yaml").read_text(encoding="utf-8"))
    sec = raw["cc_auth"]
    sec["enforce"], sec["report_only"] = enforce, report_only
    svc = tmp_path / "service_token"
    svc.write_text(SERVICE + "\n")
    os.chmod(svc, 0o600)
    sec["service_token"]["file"] = str(svc)
    rd = tmp_path / "reader_token"
    if reader_value is not None:
        rd.write_text(reader_value + "\n")
        os.chmod(rd, 0o600)
    sec["agent_reader"] = {**sec["agent_reader"], "enabled": enabled, "file": str(rd)}
    sec["decision_log"] = str(tmp_path / "decisions.jsonl")
    if step_up_get:
        sec["step_up"]["mode"] = "enforce"
        sec["step_up"]["routes"] = [{"action": "probe", "methods": ["GET"], "pattern": r"^/api/v2/probe-step-up$"}]
    cfg = cc_auth.config_from_mapping(raw, source="test", apply_env=False)
    return cfg, cc_auth.ServiceTokenStore(cfg.token_file, cfg.token_min_length)


def _eval(cfg, store, method="GET", path="/api/v2/governance/policy", listener=cc_auth.LISTENER_SERVICE, **headers):
    hdrs = {cfg.reader_header: READER, **headers}
    hdrs = {k: v for k, v in hdrs.items() if v is not None}
    return cc_auth.evaluate_request(cfg, listener, method, path, hdrs, store)


def _log(tmp_path):
    path = tmp_path / "decisions.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_committed_config_declares_a_separate_reader(monkeypatch):
    monkeypatch.delenv(cc_auth.READER_TOKEN_FILE_ENV)
    monkeypatch.delenv(cc_auth.TOKEN_FILE_ENV)
    cfg = cc_auth.load_config(ROOT / "config/cc_auth.yaml")
    assert cfg.reader_enabled is True
    assert cfg.reader_header == "X-TradeAI-Agent-Reader"
    assert cfg.reader_token_file is not None and cfg.reader_token_file != cfg.token_file
    assert "tradeai/agent_reader" in str(cfg.reader_token_file)


def test_reader_get_is_allowed_attributed_and_logged(tmp_path):
    cfg, store = _cfg(tmp_path)
    d = _eval(cfg, store)
    assert (d.allowed, d.would_deny, d.principal) == (True, False, cc_auth.AGENT_READER)
    assert cc_auth.authenticated_principal(d) == cc_auth.AGENT_READER
    cc_auth.set_request_principal(cc_auth.authenticated_principal(d))
    assert cc_auth.is_agent_reader() and not cc_auth.current_principal().startswith("tailnet:")
    cc_auth.record_decision(cfg, d, "GET", "/api/v2/governance/policy?x=1", client="127.0.0.1")
    (row,) = _log(tmp_path)
    assert (row["outcome"], row["kind"], row["principal"], row["path"]) == (
        "allow",
        "agent_reader",
        "agent-reader",
        "/api/v2/governance/policy",
    )
    assert READER not in json.dumps(row)


@pytest.mark.parametrize("method", WRITES)
@pytest.mark.parametrize(
    "mode",
    [
        dict(enforce=True, report_only=False),
        dict(enforce=True, report_only=True),
        dict(enforce=False, report_only=True),
    ],
)
def test_reader_can_never_write(tmp_path, method, mode):
    cfg, store = _cfg(tmp_path, **mode)
    for path in (
        "/api/v2/governance/approvals/x/decide",
        "/api/v2/governance/policy/feedback",
        "/api/v2/ops-controls/apply",
        "/api/v2/cio/ask",
    ):
        d = _eval(cfg, store, method=method, path=path)
        assert (d.allowed, d.status, d.kind) == (False, 403, "agent_reader"), (method, path, mode)
        assert cc_auth.authenticated_principal(d) == ""
    # Even a wrong/garbage reader value on a write is refused (not softened by report_only).
    d = _eval(cfg, store, method=method, **{cfg.reader_header: "nope"})
    assert (d.allowed, d.status) == (False, 403)


def test_wrong_missing_or_disabled_reader_is_refused_even_in_report_only(tmp_path):
    cfg, store = _cfg(tmp_path, report_only=True)
    assert (_eval(cfg, store, **{cfg.reader_header: "x" * 48}).status, _eval(cfg, store).allowed) == (401, True)
    cfg, store = _cfg(tmp_path / "a", report_only=True, reader_value=None) if (tmp_path / "a").mkdir() is None else None
    assert _eval(cfg, store).status == 401
    cfg, store = _cfg(tmp_path / "b", report_only=True, enabled=False) if (tmp_path / "b").mkdir() is None else None
    assert _eval(cfg, store).status == 401


def test_reader_with_service_token_or_equal_to_it_is_refused(tmp_path):
    cfg, store = _cfg(tmp_path)
    assert _eval(cfg, store, **{cfg.token_header: SERVICE}).status == 403
    cfg, store = _cfg(tmp_path / "same", reader_value=SERVICE) if (tmp_path / "same").mkdir() is None else None
    d = _eval(cfg, store, **{cfg.reader_header: SERVICE})
    assert (d.allowed, d.status) == (False, 403)


def test_tailnet_listener_ignores_the_reader_header(tmp_path):
    cfg, store = _cfg(tmp_path)
    d = _eval(cfg, store, listener=cc_auth.LISTENER_SERVE_PROXY)
    assert d.principal != cc_auth.AGENT_READER and not d.allowed  # no tailnet identity -> 403 as before
    d = _eval(cfg, store, method="POST", listener=cc_auth.LISTENER_SERVE_PROXY)
    assert d.principal != cc_auth.AGENT_READER and not d.allowed


def test_reader_never_bypasses_step_up(tmp_path):
    cfg, store = _cfg(tmp_path, step_up_get=True)
    d = _eval(cfg, store, path="/api/v2/probe-step-up")
    assert (d.allowed, d.kind) == (False, "step_up")


def test_every_operator_command_check_rejects_the_reader():
    from scripts.lib import cio_ask_api, operator_approvals_api, ops_controls_api, work_pipeline_commands

    ctx = types.SimpleNamespace(
        principal=lambda: cc_auth.AGENT_READER,
        listener=lambda: "serve_proxy",
        allowed_logins=frozenset({"agent-reader", "operator@example.test"}),
    )
    assert operator_approvals_api._operator(ctx) is None
    assert ops_controls_api._operator(ctx) is None
    assert cio_ask_api._operator(ctx) is None
    assert work_pipeline_commands.operator_of(ctx) is None


def test_governance_decisions_refuse_the_reader(tmp_path):
    from scripts.lib import operator_approvals_api as oaa

    ctx = oaa.Ctx(
        principal=lambda: cc_auth.AGENT_READER,
        listener=lambda: "service",
        csrf=lambda m, p: (True, ""),
        allowed_logins=frozenset({"operator@example.test"}),
        sources={},
        ledger=None,
        policy=lambda: {},
        can_read=lambda: True,
    )
    for sub in ("/approvals/x/decide", "/approvals/x/open", "/approvals/x/read", "/policy/feedback"):
        status, payload = oaa.handle("/api/v2/governance" + sub, "POST", {}, ctx=ctx)
        assert (status, payload["error"]) == (403, "AGENT_CALLER_REFUSED"), sub


def test_mint_is_exclusive_private_and_never_prints_the_value(tmp_path, capsys):
    cfg, _ = _cfg(tmp_path, reader_value=None)
    assert cc_auth.mint_agent_reader_token(cfg) == 0
    value = cfg.reader_token_file.read_text().strip()
    assert len(value) >= 48 and oct(cfg.reader_token_file.stat().st_mode & 0o777) == "0o600"
    first = capsys.readouterr().out
    assert value not in first and "minted" in first
    assert cc_auth.mint_agent_reader_token(cfg) == 0
    assert cfg.reader_token_file.read_text().strip() == value  # never overwritten
    assert "exists" in capsys.readouterr().out
