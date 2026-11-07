"""A refused model lane must say so — in the result, in the exit code and in the receipt.

WORK-QUEUE item 7, 2026-11-07. The weekly lane (``multi-tier-trade-reviewer-weekly``) had run
``2 failures in a row`` / ``status=ok_unverified grade=FAILED`` with, as its entire cause,

    Governed ChatGPT lane gpt-4o-mini failed: manual approval required for
    multi_tier_trade_reviewer (chatgpt)

That sentence was in a log line and nowhere else. Every generator swallowed its exception and
returned ``None``, so the caller could not tell a lane REFUSAL from an empty completion: both became
``{"success": False, "error": "empty_response"}`` and the receipt said only "one or more trade
reviews failed". The monthly tier was worse — it writes no per-trade results at all, so a refused
monthly summary left ``run_outcome`` with nothing to fail on and the receipt reported exit 0 with
``trades_reviewed > 0`` and no summary.

Three claims are tested here, hermetically (synthetic fixtures, no DB, no network, no API key use):

  1. each governed lane raises ``LaneRefused`` carrying the gate's own words;
  2. ``review_trade`` passes that reason through, and a genuinely empty completion still says so;
  3. ``run_outcome`` and the receipt fail on a refused SUMMARY, and the receipt names the reason.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import multi_tier_trade_reviewer as mtr   # noqa: E402

GATE_WORDS = "manual approval required for multi_tier_trade_reviewer (chatgpt)"


def _fake_llm_lane(exc):
    mod = types.ModuleType("llm_lane")

    def generate(prompt, **kw):
        raise exc

    mod.generate = generate
    return mod


# ── 1. the lanes raise the refusal instead of returning None ────────────────

def test_the_chatgpt_refusal_keeps_the_gates_own_words(monkeypatch):
    monkeypatch.setitem(sys.modules, "llm_lane", _fake_llm_lane(RuntimeError(GATE_WORDS)))
    with pytest.raises(mtr.LaneRefused) as exc:
        mtr._generate_openai("prompt", "gpt-4o-mini")
    assert exc.value.lane == "chatgpt"
    assert exc.value.reason == f"chatgpt lane refused: {GATE_WORDS}"
    # the exact log line the weekly lane printed for weeks, now on an object rather than a log
    assert GATE_WORDS in str(exc.value)


def test_the_deepseek_refusal_is_raised_too(monkeypatch):
    monkeypatch.setitem(sys.modules, "llm_lane", _fake_llm_lane(RuntimeError("lane capped")))
    with pytest.raises(mtr.LaneRefused) as exc:
        mtr._generate_deepseek("prompt")
    assert exc.value.lane == "deepseek-flash" and "lane capped" in exc.value.reason


def test_an_anthropic_lane_without_a_key_is_a_refusal_not_an_empty_answer(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(mtr.LaneRefused) as exc:
        mtr._generate_anthropic("prompt", "claude-sonnet-4-6")
    assert exc.value.lane == "anthropic" and "ANTHROPIC_API_KEY" in exc.value.reason


def test_a_lane_error_is_chained_so_the_traceback_survives(monkeypatch):
    cause = RuntimeError(GATE_WORDS)
    monkeypatch.setitem(sys.modules, "llm_lane", _fake_llm_lane(cause))
    with pytest.raises(mtr.LaneRefused) as exc:
        mtr._generate_openai("prompt", "gpt-4o-mini")
    assert exc.value.__cause__ is cause


# ── 2. review_trade: the reason reaches the result ──────────────────────────

def _trade():
    return {"id": 7, "symbol": "TEST", "strategy_id": "s1", "entry_price": 10.0,
            "exit_price": 11.0, "stop_loss": 9.5, "target_1": 11.5, "pnl": 1.0,
            "r_multiple": 2.0, "shares": 10}


@pytest.fixture
def _offline_review(monkeypatch):
    """No DB, no prompt context, no advisory cloud call — only the generator boundary is under test."""
    monkeypatch.setattr(mtr, "_get_existing_reviews", lambda conn, trade_id: [])
    saved = []
    monkeypatch.setattr(mtr, "_save_review", lambda *a, **kw: saved.append(a))
    monkeypatch.setattr(mtr, "_cloud_review_trade", lambda *a, **kw: None)
    return saved


def test_a_refused_review_reports_the_reason_and_the_symbol(monkeypatch, _offline_review):
    def refuse(prompt, tier):
        raise mtr.LaneRefused("chatgpt", GATE_WORDS)

    monkeypatch.setattr(mtr, "_generate", refuse)
    result = mtr.review_trade(conn=None, trade=_trade(), tier="weekly")
    assert result["success"] is False
    assert result["symbol"] == "TEST" and result["tier"] == "weekly"
    assert result["error"] == f"chatgpt lane refused: {GATE_WORDS}"
    assert _offline_review == []          # nothing was written for a review that never happened


def test_an_empty_completion_still_says_empty_response(monkeypatch, _offline_review):
    monkeypatch.setattr(mtr, "_generate", lambda prompt, tier: "")
    result = mtr.review_trade(conn=None, trade=_trade(), tier="weekly")
    assert result["success"] is False and result["error"] == "empty_response"
    assert result["symbol"] == "TEST"


def test_a_successful_review_is_unchanged(monkeypatch, _offline_review):
    monkeypatch.setattr(mtr, "_generate", lambda prompt, tier: '{"summary": "fine"}')
    result = mtr.review_trade(conn=None, trade=_trade(), tier="weekly")
    assert result["success"] is True and result["parsed"] is True
    assert len(_offline_review) == 1


# ── 3. run_outcome + the receipt: a refused summary is a failure ────────────

def test_a_refused_summary_fails_the_run():
    """The monthly tier writes no per-trade results — before this, that receipt was exit 0."""
    ok, code = mtr.run_outcome({"tier": "monthly", "trades_reviewed": 3,
                                "summary_error": "chatgpt lane refused: manual approval required"})
    assert (ok, code) == (False, 1)


def test_review_failures_still_fail_the_run():
    ok, code = mtr.run_outcome({"tier": "weekly", "trades_reviewed": 2,
                                "results": [{"success": True}, {"success": False}]})
    assert (ok, code) == (False, 1)


def test_no_closed_trades_is_still_a_clean_no_op():
    assert mtr.run_outcome({"trades_reviewed": 0}) == (True, 0)


def test_failed_reasons_are_distinct_and_bounded():
    results = [{"success": True, "error": "ignored"}] + [
        {"success": False, "error": f"reason {i}"} for i in range(9)
    ] + [{"success": False, "error": "reason 0"}, {"success": False, "error": None}, None]
    assert mtr._failed_reasons(results) == [f"reason {i}" for i in range(5)]


def test_the_receipt_names_the_gate(monkeypatch, capsys):
    """End of the chain: the same run that reported exit 1 now writes the reason to its receipt."""
    refused = f"chatgpt lane refused: {GATE_WORDS}"
    monkeypatch.setattr(mtr, "_load_env", lambda: None)
    monkeypatch.setattr(mtr, "run_tier", lambda tier, trade_id, dry_run: {
        "tier": tier, "trades_reviewed": 2,
        "results": [{"success": False, "symbol": "AAA", "error": refused},
                    {"success": False, "symbol": "BBB", "error": refused}],
        "summary_error": refused})
    written = {}
    monkeypatch.setattr(mtr, "_receipt", lambda tier, **kw: written.update(kw, tier=tier))

    code = mtr.main(["--tier", "weekly"])
    assert code == 1
    assert written["ok"] is False and written["exit_code"] == 1
    assert written["error"] == refused
    assert written["summary"]["failed"] == 2
    assert written["summary"]["failed_reasons"] == [refused]
    assert written["summary"]["summary_error"] == refused
    assert refused in capsys.readouterr().out          # the run's own JSON output carries it too


# ── 4. the summary path itself never sees the exception ─────────────────────

class _FakeConn:
    def __init__(self):
        self.closed = False

    def cursor(self):
        return _FakeCursor()

    def close(self):
        self.closed = True


class _FakeCursor:
    description = [("x",)]

    def execute(self, *a, **kw):
        pass

    def fetchall(self):
        return []


def _summary_run(monkeypatch, tier):
    monkeypatch.setattr(mtr, "_get_conn", lambda: _FakeConn())
    monkeypatch.setattr(mtr, "_get_closed_trades", lambda conn, **kw: [dict(_trade())])
    monkeypatch.setattr(mtr, "_get_existing_reviews", lambda conn, trade_id: [])
    monkeypatch.setattr(mtr, "review_trade", lambda *a, **kw: {"success": True})
    monkeypatch.setattr(mtr, "_build_weekly_prompt", lambda *a, **kw: "prompt")
    monkeypatch.setattr(mtr, "_save_weekly_summary", lambda *a, **kw: None)
    monkeypatch.setattr(mtr, "_generate", lambda prompt, t: (_ for _ in ()).throw(
        mtr.LaneRefused("anthropic" if tier == "monthly" else "chatgpt", GATE_WORDS)))
    return mtr.run_tier(tier)


def test_a_refused_weekly_summary_is_reported_not_swallowed(monkeypatch):
    out = _summary_run(monkeypatch, "weekly")
    assert out["summary_error"] == f"chatgpt lane refused: {GATE_WORDS}"
    assert out["results"] == [{"success": True}]
    assert mtr.run_outcome(out) == (False, 1)


def test_a_refused_monthly_summary_is_reported_not_swallowed(monkeypatch):
    out = _summary_run(monkeypatch, "monthly")
    assert out["summary_error"] == f"anthropic lane refused: {GATE_WORDS}"
    assert "results" not in out
    assert mtr.run_outcome(out) == (False, 1)


def test_an_empty_summary_completion_is_reported_too(monkeypatch):
    monkeypatch.setattr(mtr, "_get_conn", lambda: _FakeConn())
    monkeypatch.setattr(mtr, "_get_closed_trades", lambda conn, **kw: [dict(_trade())])
    monkeypatch.setattr(mtr, "_get_existing_reviews", lambda conn, trade_id: [])
    monkeypatch.setattr(mtr, "review_trade", lambda *a, **kw: {"success": True})
    monkeypatch.setattr(mtr, "_build_weekly_prompt", lambda *a, **kw: "prompt")
    monkeypatch.setattr(mtr, "_save_weekly_summary", lambda *a, **kw: None)
    monkeypatch.setattr(mtr, "_generate", lambda prompt, t: None)
    out = mtr.run_tier("weekly")
    assert out["summary_error"] == "openai lane returned an empty completion"
    assert mtr.run_outcome(out) == (False, 1)
