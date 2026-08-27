"""Tests for rebalance_verifier.py's SSDI/IRMAA/tax compliance check.

Audit finding H1 (docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md): the weekly
Sonnet verifier only ever checks `rebalance_analysis_results` rows tagged
`analysis_tier='gemma3_monthly'` — a separate, monthly-cadence system with no
connection to portfolio_rebalancer.py's daily drift orders, which is the
surface an operator actually sees via Telegram. Those daily orders were never
checked for compliance by anything.

IMPORTANT: a real ANTHROPIC_API_KEY is present in this environment. Every
test here either uses dry_run=True (never reaches the API-key check) or
monkeypatches `sys.modules["anthropic"]` with a fake before calling — no
test in this file may make a real, billed network call.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rebalance_verifier as rv  # noqa: E402


class _FakeMessages:
    def __init__(self, text: str, *, raise_error: Exception | None = None):
        self._text = text
        self._raise_error = raise_error

    def create(self, **kwargs):
        if self._raise_error:
            raise self._raise_error
        return SimpleNamespace(
            content=[SimpleNamespace(text=self._text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )


class _FakeClient:
    def __init__(self, text: str, *, raise_error: Exception | None = None):
        self.messages = _FakeMessages(text, raise_error=raise_error)


def _install_fake_anthropic(monkeypatch, text: str, *, raise_error: Exception | None = None):
    fake_module = SimpleNamespace(Anthropic=lambda api_key: _FakeClient(text, raise_error=raise_error))
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)


# ── build_compliance_prompt ─────────────────────────────────────────────────

def test_prompt_includes_ssdi_irmaa_constraints():
    prompt = rv.build_compliance_prompt(executive_summary="test", recs_text="- BUY SCHD\n")
    assert "SSDI" in prompt and "IRMAA" in prompt and "MAGI" in prompt


def test_prompt_includes_recommendations_text():
    prompt = rv.build_compliance_prompt(executive_summary="", recs_text="  - Rollover: SELL $50,000 bonds\n")
    assert "SELL $50,000 bonds" in prompt


def test_prompt_falls_back_when_no_recommendations():
    prompt = rv.build_compliance_prompt(executive_summary="", recs_text="")
    assert "No recommendations" in prompt


# ── call_sonnet_compliance_check ────────────────────────────────────────────

def test_dry_run_never_touches_api_key_or_network(monkeypatch):
    """dry_run=True must short-circuit before the ANTHROPIC_API_KEY check —
    this is what makes it safe to call in an environment with a real key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = rv.call_sonnet_compliance_check("irrelevant prompt", dry_run=True)
    assert result == {"dry_run": True}


def test_no_api_key_skips_without_raising(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = rv.call_sonnet_compliance_check("prompt")
    assert result == {"skipped": True, "reason": "no_api_key"}


def test_successful_response_is_parsed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    _install_fake_anthropic(monkeypatch, '{"verification_passed": true, "critical_flags": [], '
                                        '"warnings": [], "irmaa_risk": "none", "ssdi_risk": "none", '
                                        '"notes": "clean"}')
    result = rv.call_sonnet_compliance_check("prompt")
    assert result["verification_passed"] is True
    assert result["critical_flags"] == []


def test_critical_flags_survive_parsing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    _install_fake_anthropic(monkeypatch, '{"verification_passed": false, '
                                        '"critical_flags": ["MAGI would exceed IRMAA threshold"], '
                                        '"warnings": [], "irmaa_risk": "high", "ssdi_risk": "low", '
                                        '"notes": "flagged"}')
    result = rv.call_sonnet_compliance_check("prompt")
    assert result["verification_passed"] is False
    assert result["critical_flags"] == ["MAGI would exceed IRMAA threshold"]


def test_malformed_response_fails_closed_not_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    _install_fake_anthropic(monkeypatch, "not json at all")
    result = rv.call_sonnet_compliance_check("prompt")  # must not raise
    assert result["verification_passed"] is None
    assert "Parse error" in result["warnings"][0]


def test_api_exception_returns_error_not_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    _install_fake_anthropic(monkeypatch, "", raise_error=RuntimeError("rate limited"))
    result = rv.call_sonnet_compliance_check("prompt")  # must not raise
    assert "error" in result and "rate limited" in result["error"]


# ── verify_daily_rebalance_orders (the actual H1 fix) ──────────────────────

def _order(account="Rollover IRA", action="SELL", amount_usd=250000, bucket="bonds", note="Drift +12.0%"):
    return {"account": account, "action": action, "amount_usd": amount_usd, "bucket": bucket, "note": note}


def test_reproduces_the_h1_gap_with_dry_run(monkeypatch):
    """The actual audit scenario: a daily drift order well over the $200k
    Telegram trigger, checked via the new function instead of never."""
    result = rv.verify_daily_rebalance_orders([_order(amount_usd=250000)],
                                              total_to_rebalance=250000, dry_run=True)
    assert result == {"dry_run": True}


def test_order_fields_reach_the_prompt(monkeypatch):
    captured = {}

    def _capture(prompt, **kwargs):
        captured["prompt"] = prompt
        return {"dry_run": True}

    monkeypatch.setattr(rv, "call_sonnet_compliance_check", _capture)
    rv.verify_daily_rebalance_orders([_order(account="Roth IRA", action="BUY", amount_usd=75000,
                                             bucket="equities", note="Drift -8.0% vs 40% target")],
                                     total_to_rebalance=75000)
    assert "Roth IRA" in captured["prompt"]
    assert "BUY" in captured["prompt"]
    assert "75,000" in captured["prompt"]
    assert "equities" in captured["prompt"]


def test_empty_orders_does_not_crash():
    result = rv.verify_daily_rebalance_orders([], total_to_rebalance=0, dry_run=True)
    assert result == {"dry_run": True}


def test_total_to_rebalance_reaches_executive_summary(monkeypatch):
    captured = {}
    monkeypatch.setattr(rv, "call_sonnet_compliance_check", lambda p, **k: captured.setdefault("prompt", p) or {})
    rv.verify_daily_rebalance_orders([_order()], total_to_rebalance=312500)
    assert "312,500" in captured["prompt"]


# ── run_verification regression: the no-api-key early return must survive the refactor ──

class _FakeCursor:
    def __init__(self, row):
        self._row = row
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, cursor_factory=None):
        return self._cursor

    def commit(self):
        self.committed = True


def test_run_verification_no_api_key_does_not_touch_db(monkeypatch):
    """Regression guard for the refactor: originally a missing API key
    returned before any UPDATE; call_sonnet_compliance_check's shared
    'skipped' shape must still short-circuit run_verification the same way,
    not fall through into the UPDATE/commit block with a None payload."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    row = {"id": 42, "generated_at": "2026-08-27", "portfolio_value": 1000000,
           "executive_summary": "test", "recommendations": [], "v_concentration_plan": ""}
    cur = _FakeCursor(row)
    conn = _FakeConn(cur)

    result = rv.run_verification(conn, dry_run=False)

    assert result.get("skipped") is True
    assert result.get("result_id") == 42
    assert conn.committed is False
    assert not any("UPDATE rebalance_analysis_results" in (sql or "") for sql, _ in cur.executed)
