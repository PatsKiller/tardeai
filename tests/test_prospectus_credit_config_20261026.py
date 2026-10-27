"""[shared-infra] credit/config for the Ticker Prospectus (operator 2026-10-26).

Daily cap override ($25/UTC day 2026-10-26..28, then $10), renewal block, presence-only Admin API verification,
Fable 5.1 in the model registry and pricing, Sonnet 5.5 cache read fixed to $0.20 in all three price configs, the two
prospectus processes (declared caps, anthropic-only, premium tier restricted), and Fable's omitted thinking parameter.
No network, no real journal: every CreditBook lives under tmp_path.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.anthropic_credit import CreditBook, CreditDenied  # noqa: E402
from scripts.lib.anthropic_transport import AnthropicError, AnthropicTransport, load_policy  # noqa: E402

D26 = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
D28 = datetime(2026, 10, 28, 23, 59, tzinfo=timezone.utc)
D29 = datetime(2026, 10, 29, 0, 1, tzinfo=timezone.utc)


def _json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def policy(**over):
    return dict(deepcopy(load_policy()), enabled=True, **over)


def test_policy_carries_override_renewal_admin_and_premium_tier():
    p = _json("config/anthropic_credit_policy.json")
    assert p["daily_cap_usd"] == "10"
    assert [{k: o[k] for k in ("usd", "from", "until")} for o in p["daily_cap_overrides"]] == [
        {"usd": "25", "from": "2026-10-26", "until": "2026-10-29"},
        # operator 2026-10-26 "I rather finish right now": UTC day 10-26 only, last match wins
        {"usd": "40", "from": "2026-10-26", "until": "2026-10-27"}]
    assert {k: p["renewal"][k] for k in ("mode", "monthly_allowance_usd", "renews_on_day")} == {
        "mode": "one_time", "monthly_allowance_usd": "190", "renews_on_day": None}
    assert p["admin_cost_verification"]["env_key_name"] == "ANTHROPIC_ADMIN_API_KEY"
    assert p["models"]["premium"] == "claude-fable-5-1" and p["models"]["long_form"] == "claude-opus-5-5"
    assert p["process_tiers"] == {"prospectus_writer": "long_form", "prospectus_writer_premium": "premium",
                                  "prospectus_fact_check": "bulk",  # data-quality gate read (Haiku), 2026-10-26
                                  "prospectus_accuracy_review": "long_form"}  # monthly accuracy sample (Opus), 2026-10-26
    assert p["premium_tier_processes"] == ["prospectus_writer_premium"]
    assert set(p["anthropic_only_processes"]) == {"prospectus_writer", "prospectus_writer_premium", "prospectus_fact_check",
                                                  "prospectus_accuracy_review", "cio_ask_reanswer"}
    assert p["thinking_controls"]["claude-fable-5-1"]["enabled"] == {"thinking": None, "output_config": {"effort": "high"}}


def test_fable_pricing_and_sonnet_cache_read_consistent_in_all_three_price_configs():
    # Official pricing page re-fetched 2026-10-26: Fable 5.1 cache hits $0.25; Sonnet 5.5 cache hits $0.10
    # (0.05x base). The contract asked for $0.20; the verified page wins (AGENTS.md section 0 rule 10).
    p = _json("config/anthropic_credit_policy.json")["pricing"]
    assert p["claude-fable-5-1"] == {"input": "10", "output": "50", "cache_read": "0.25", "cache_write_5m": "12.50",
                                     "cache_write_1h": "20", "batch_multiplier": "0.5"}
    assert p["claude-sonnet-5-5"]["cache_read"] == "0.10"
    sched = {r["model"]: r for r in _json("config/provider_pricing_schedules.json")["schedules"]
             if r.get("provider") == "anthropic"}
    assert sched["claude-sonnet-5-5"]["input_cache_hit"] == 0.1
    assert (sched["claude-fable-5-1"]["input_cache_miss"], sched["claude-fable-5-1"]["output"],
            sched["claude-fable-5-1"]["input_cache_hit"]) == (10.0, 50.0, 0.25)
    models = _json("config/llm_model_registry.json")["providers"]["anthropic"]["models"]
    assert models["anthropic_sonnet"]["pricing_snapshot_usd_per_million_tokens"]["cache_hit_input"] == 0.1
    fable = models["anthropic_fable"]
    assert fable["model_id"] == "claude-fable-5-1" and fable["enabled"] is True
    assert fable["restricted_to_processes"] == ["prospectus_writer_premium"]
    assert fable["pricing_snapshot_usd_per_million_tokens"] == {"cache_hit_input": 0.25, "cache_miss_input": 10.0,
                                                                "cache_write_5m": 12.5, "cache_write_1h": 20.0, "output": 50.0}


@pytest.mark.parametrize("now,cap", [(D26, "40.00"), (D28, "25.00"), (D29, "10.00"),
                                     (datetime(2026, 10, 25, 23, tzinfo=timezone.utc), "10.00")])
def test_daily_cap_override_window_is_utc_and_until_exclusive(tmp_path, now, cap):
    snap = CreditBook(tmp_path, policy()).snapshot(now=now)
    assert snap["daily_cap_usd"] == cap and snap["daily_cap_base_usd"] == "10.00"
    assert snap["daily_cap_override_active"] is (cap != "10.00")


def test_override_lets_the_day_spend_past_the_base_cap_then_pauses(tmp_path):
    book = CreditBook(tmp_path, policy())
    for i in range(6):
        book.reserve(f"r{i}", "prospectus_writer", Decimal("2.00"), tier="long_form", now=D26)
        book.settle(f"r{i}", Decimal("2.00"), now=D26)
    assert book.snapshot(now=D26)["status"] == "OK"  # $12 used: past the $10 base, inside the $25 override
    with pytest.raises(CreditDenied) as exc:
        later = CreditBook(tmp_path, policy(daily_cap_overrides=[]))
        later.reserve("over", "prospectus_writer", Decimal("1"), tier="long_form", now=D26)
    assert exc.value.reason == "PAUSED_TODAY"


@pytest.mark.parametrize("bad", [
    {"daily_cap_overrides": {"usd": "25"}},
    {"daily_cap_overrides": [{"usd": "25", "from": "2026-10-29", "until": "2026-10-26"}]},
    {"daily_cap_overrides": [{"usd": "0", "from": "2026-10-26", "until": "2026-10-29"}]},
    {"daily_cap_overrides": [{"usd": "25", "from": "bad", "until": "2026-10-29"}]},
    {"renewal": {"mode": "weekly"}},
    {"renewal": {"mode": "monthly", "monthly_allowance_usd": None, "renews_on_day": None}},
    {"renewal": {"mode": "monthly", "monthly_allowance_usd": "190", "renews_on_day": 31}},
])
def test_invalid_override_or_renewal_refuses_configuration(tmp_path, bad):
    with pytest.raises(CreditDenied) as exc:
        CreditBook(tmp_path, policy(**bad))
    assert exc.value.reason == "CREDIT_CONFIGURATION_INVALID"


def test_monthly_renewal_starts_a_fresh_period_and_keeps_the_journal(tmp_path):
    monthly = {"mode": "monthly", "monthly_allowance_usd": "5", "renews_on_day": None}
    p = policy(renewal=monthly, daily_cap_overrides=[], expires_at="2027-06-01T00:00:00Z")
    book = CreditBook(tmp_path, p)
    oct30 = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    for i in range(2):
        book.reserve(f"m{i}", "prospectus_writer", Decimal("2.00"), tier="long_form", now=oct30)
        book.settle(f"m{i}", Decimal("2.00"), now=oct30)
    with pytest.raises(CreditDenied) as exc:
        book.reserve("m3", "prospectus_writer", Decimal("2.00"), tier="long_form",
                     now=datetime(2026, 10, 31, 1, tzinfo=timezone.utc))
    assert exc.value.reason == "EXHAUSTED"
    nov = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    snap = book.snapshot(now=nov)
    assert snap["status"] == "OK" and snap["credit_used_usd"] == "0.00" and snap["total_cap_usd"] == "5.00"
    assert snap["renewal_mode"] == "monthly" and snap["period_start"].startswith("2026-11-01")
    assert len(book._read()) == 4  # earlier period stays in the journal
    assert CreditBook(tmp_path, policy()).snapshot(now=D26)["renewal_mode"] == "one_time"


def test_period_start_respects_renews_on_day():
    p = policy(renewal={"mode": "monthly", "monthly_allowance_usd": "190", "renews_on_day": 15})
    book = CreditBook(Path("/nonexistent-prospectus-test"), p)
    assert book.period_start(datetime(2026, 11, 10, tzinfo=timezone.utc)).isoformat().startswith("2026-10-15")
    assert book.period_start(datetime(2027, 1, 3, tzinfo=timezone.utc)).isoformat().startswith("2026-12-15")


def test_monitoring_snapshot_shows_config_and_admin_presence_only(tmp_path, monkeypatch):
    from scripts.lib import anthropic_monitoring as mon
    monkeypatch.delenv("ANTHROPIC_ADMIN_API_KEY", raising=False)
    snap = mon.snapshot(tmp_path, policy=policy(), now=D26, configured=True)
    cfg = snap["credit_config"]
    assert cfg["daily_cap_usd"] == "40.00" and cfg["daily_cap_override_active"] is True
    assert cfg["renewal"]["mode"] == "one_time" and cfg["models"]["premium"] == "claude-fable-5-1"
    assert cfg["admin_verification"] == {"enabled": True, "key_name": "ANTHROPIC_ADMIN_API_KEY", "configured": False,
                                         "status": "SKIPPED_NO_KEY", "last": None}
    assert "UTC daily $0.00/$40.00" in snap["digest_line"]
    monkeypatch.setenv("ANTHROPIC_ADMIN_API_KEY", "sk-ant-admin-SYNTHETIC-never-printed")
    admin = mon.snapshot(tmp_path, policy=policy(), now=D26, configured=True)["credit_config"]["admin_verification"]
    assert admin["configured"] is True and admin["status"] == "NOT_RUN"
    assert "SYNTHETIC" not in json.dumps(mon.snapshot(tmp_path, policy=policy(), now=D26, configured=True))


def test_cost_verify_skips_without_key_and_compares_with_stubbed_report(tmp_path):
    import scripts.anthropic_cost_verify as cv
    assert cv.verify(tmp_path, policy(), env={}, now=D26)["status"] == "SKIPPED_NO_KEY"
    book = CreditBook(tmp_path, policy())
    book.reserve("a", "prospectus_writer", Decimal("1.00"), tier="long_form", now=D26)
    book.settle("a", Decimal("1.00"), now=D26)
    seen = {}

    def fetch(path, query, *, key):
        seen.update(path=path, key_len=len(key), query=query)
        return {"data": [{"results": [{"currency": "USD", "amount": "120.7"}]}], "has_more": False}

    env = {"ANTHROPIC_ADMIN_API_KEY": "synthetic"}
    assert cv.verify(tmp_path, policy(), env=env, fetch=fetch, now=D26)["status"] == "DRY_RUN" and not seen
    out = cv.verify(tmp_path, policy(), env=env, fetch=fetch, now=D26, apply=True)
    assert seen["path"] == "/v1/organizations/cost_report" and out["reported_usd"] == "1.21"
    assert out["status"] == "MATCH" and out["ledger_usd"] == "1.00"
    written = json.loads((tmp_path / "data/runtime/provider_cost/anthropic_admin_cost.json").read_text())
    assert "synthetic" not in json.dumps(written)


class _Fixture:
    def __init__(self, tmp_path, p):
        self.sent = []
        self.book = CreditBook(tmp_path, p)

    def request(self, method, path, payload, *, key, timeout):
        self.sent.append((path, deepcopy(payload)))
        if path.endswith("count_tokens"):
            return 200, {"input_tokens": 50}, {}
        return 200, {"id": "msg_fixture", "model": payload["model"], "stop_reason": "end_turn",
                     "content": [{"type": "text", "text": "{}"}],
                     "usage": {"input_tokens": 50, "output_tokens": 20}}, {}

    def transport(self):
        return AnthropicTransport(book=self.book, env={"ANTHROPIC_API_KEY": "fixture"}, request=self.request,
                                  now=lambda: D26, record_usage=lambda *a: True, reserve_process=lambda *a: None,
                                  record_attempt=lambda *a: True, settle_process=lambda *a: None)


def test_fable_payload_omits_thinking_with_high_effort_and_is_restricted(tmp_path):
    fx = _Fixture(tmp_path, policy())
    out = fx.transport().generate([{"role": "user", "content": "hi"}], "claude-fable-5-1", client_request_id="f1",
                                  process_id="prospectus_writer_premium", credit_tier="premium", thinking="enabled",
                                  max_tokens=1000)
    payload = fx.sent[-1][1]
    assert "thinking" not in payload and payload["output_config"] == {"effort": "high"}
    assert out["model"] == "claude-fable-5-1"
    with pytest.raises(AnthropicError) as exc:
        fx.transport().generate([{"role": "user", "content": "hi"}], "claude-fable-5-1", client_request_id="f2",
                                process_id="prospectus_writer", credit_tier="premium", thinking="enabled")
    assert exc.value.code == "MODEL_DISABLED"


def test_opus_long_form_uses_adaptive_thinking_high_effort(tmp_path):
    fx = _Fixture(tmp_path, policy())
    fx.transport().generate([{"role": "user", "content": "hi"}], "claude-opus-5-5", client_request_id="o1",
                            process_id="prospectus_writer", credit_tier="long_form", thinking="enabled", max_tokens=1000)
    payload = fx.sent[-1][1]
    assert payload["thinking"] == {"type": "adaptive"} and payload["output_config"] == {"effort": "high"}


def test_processes_registered_with_declared_caps_and_anthropic_only_routing():
    from scripts.lib import anthropic_routing as promo
    reg = {p["id"]: p for p in _json("config/llm_process_registry.json")["processes"]}
    for pid in ("prospectus_writer", "prospectus_writer_premium"):
        row = reg[pid]
        assert row["anthropic_first"] is True and row["daily_cost_cap_usd"] > 0 and row["daily_soft_cap"] > 0
        assert row["advisory_only"] is True and row["tools_allowed"] is False and row["fallback_allowed"] is False
        routing = _json("config/llm_routing_policy.json")["policies"]["default"]["processes"][pid]
        assert routing["anthropic_only"] is True
    p = policy()
    assert promo.tier_for("PRO_THINK", process_id="prospectus_writer", policy=p) == "long_form"
    assert promo.tier_for("PRO_THINK", process_id="prospectus_writer_premium", policy=p) == "premium"
    assert promo.tier_for("PRO_THINK", process_id="some_other", policy=p) == "high"
    cfg = {"registered": True, "anthropic_first": True, "daily_cost_cap_usd": 22, "daily_soft_cap": 80}
    plan = promo.configured_plan("prospectus_writer", cfg, {"requested_policy": "PRO_THINK", "credit_tier": "long_form"},
                                 enabled={"anthropic", "grok", "chatgpt", "deepseek"},
                                 model_for_provider=lambda prov, name: f"{prov}-model",
                                 env={"ANTHROPIC_API_KEY": True}, policy=p, now=D26)
    assert plan[0]["provider"] == "anthropic" and plan[0]["skip"] is None and plan[0]["model_id"] == "claude-opus-5-5"
    assert [c["skip"] for c in plan[1:]] == ["anthropic_only_process"] * 3
    other = promo.configured_plan("x", cfg, {"requested_policy": "FAST", "credit_tier": "standard"},
                                  enabled={"anthropic", "grok", "chatgpt", "deepseek"},
                                  model_for_provider=lambda prov, name: "m", env={"ANTHROPIC_API_KEY": True},
                                  policy=p, now=D26)
    assert all(c["skip"] is None for c in other)


def test_anthropic_only_process_refuses_the_legacy_lane_when_credit_unusable(monkeypatch):
    from scripts.lib import anthropic_routing as promo
    from scripts.lib import llm_consumption as lc
    monkeypatch.setattr(promo, "active", lambda *a, **k: False)

    def no_db():
        raise RuntimeError("no DB in tests")
    monkeypatch.setattr(lc, "ensure_schema", no_db)
    monkeypatch.setattr(lc, "_conn", no_db)
    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "automated"})
    with pytest.raises(RuntimeError) as exc:
        lc.gate_and_generate("synthetic prompt", process_id="prospectus_writer", lane="pro_think")
    assert str(exc.value).startswith("ANTHROPIC_CREDIT_UNAVAILABLE")
    with pytest.raises(RuntimeError) as exc:
        lc.gate_and_generate("synthetic prompt", process_id="prospectus_writer", lane="pro_think",
                             metadata={"provider_pinned": True})
    assert str(exc.value).startswith("ANTHROPIC_CREDIT_UNAVAILABLE")
