"""Provider-billing alarm + OAuth soft fallback for risk/steph/tax (2026-09-19).

Both controls exist because of the same outage: the DeepSeek account ran to -$0.09 on
2026-09-17, every deepseek-flash call returned HTTP 402 for three days, risk_agent/steph/
tax_agent produced ZERO output, and nothing alarmed. Maria survived only because she alone
could reach the free OAuth lanes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# C1 firing coverage — the alarm must be OBSERVED reaching the transport. The file is
# declared whole: it has exactly one send_telegram site and every path reaches it through
# main(), which test_billing_stop_reaches_the_transport drives end to end.
COVERS = [
    "scripts/check_llm_provider_health.py",
]


@pytest.fixture
def capture_transport(monkeypatch):
    captured: list[tuple] = []

    def _send(msg, *a, **k):
        captured.append((msg, dict(k)))
        return True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", _send)
    return captured


# --------------------------------------------------------------------------- alarm


def test_billing_and_auth_errors_are_classified_apart_from_transport():
    from lib.provider_health import classify_error

    assert classify_error("HTTP_402: policy=FAST model=deepseek-flash returned=None HTTP 402") == "BILLING"
    assert classify_error("Insufficient Balance") == "BILLING"
    assert classify_error("HTTP_401: invalid api key") == "AUTH"
    assert classify_error("502 Server Error: Bad Gateway for url: http://127.0.0.1:8646") == "TRANSPORT"
    assert classify_error("NETWORK_ERROR: policy=FAST") == "TRANSPORT"
    assert classify_error(None) is None
    assert classify_error("") is None


def test_single_billing_failure_alarms_without_waiting_for_a_rate():
    """One 402 is already the whole account — waiting for five wastes five more calls."""
    from lib.provider_health import evaluate

    rows = [
        {
            "model_name": "deepseek-flash",
            "process_id": "watchlist_risk_flash_narrative",
            "success": False,
            "error_message": "HTTP_402: HTTP 402",
        }
    ]
    rows += [
        {"model_name": "deepseek-flash", "process_id": "p", "success": True, "error_message": None} for _ in range(50)
    ]
    findings = evaluate(rows)
    assert len(findings) == 1
    assert findings[0].kind == "BILLING"
    assert findings[0].severity == "CRITICAL"


def test_healthy_lane_and_isolated_transport_blip_do_not_alarm():
    from lib.provider_health import evaluate

    healthy = [{"model_name": "grok", "process_id": "p", "success": True, "error_message": None} for _ in range(20)]
    assert evaluate(healthy) == []
    blip = healthy + [
        {"model_name": "grok", "process_id": "p", "success": False, "error_message": "504 gateway timeout"}
    ]
    assert evaluate(blip) == []


def test_fully_dead_transport_lane_alarms_at_warn():
    """The chatgpt-oauth bridge failing every call is real, but it is not a billing page."""
    from lib.provider_health import evaluate

    rows = [
        {
            "model_name": "chatgpt",
            "process_id": "oauth_lane_keepalive",
            "success": False,
            "error_message": "502 Server Error: Bad Gateway",
        }
        for _ in range(10)
    ]
    findings = evaluate(rows)
    assert len(findings) == 1
    assert findings[0].kind == "TRANSPORT"
    assert findings[0].severity == "WARN"
    assert findings[0].fail_rate == 1.0


def test_a_lane_that_recovered_is_reported_but_never_paged():
    """The operator fixed it; do not page them for it again.

    Measured 2026-09-19: the last 402 landed at 19:15:06 and the account was topped up by
    19:46, yet the 3h window still reported CRITICAL with the lane answering normally. An
    alarm that re-fires on a resolved incident is how pages get ignored.
    """
    from datetime import datetime, timedelta

    from lib.provider_health import evaluate, pageable

    t0 = datetime(2026, 9, 19, 19, 15, 6)
    rows = [
        {
            "model_name": "deepseek-flash",
            "process_id": "watchlist_risk_flash_narrative",
            "success": False,
            "error_message": "HTTP_402: HTTP 402",
            "created_at": t0 - timedelta(minutes=m),
        }
        for m in range(9)
    ]
    rows += [
        {
            "model_name": "deepseek-flash",
            "process_id": "hermes_cloud_json",
            "success": True,
            "error_message": None,
            "created_at": t0 + timedelta(minutes=m),
        }
        for m in range(1, 8)
    ]

    findings = evaluate(rows)
    assert len(findings) == 1, "the outage is still reported — silence would lose the record"
    assert findings[0].kind == "BILLING"
    assert findings[0].recovered is True
    assert pageable(findings) == []


def test_a_still_dead_lane_is_paged_even_beside_a_recovered_one():
    from datetime import datetime, timedelta

    from lib.provider_health import evaluate, pageable

    t0 = datetime(2026, 9, 19, 19, 15, 6)
    rows = [
        {
            "model_name": "deepseek-flash",
            "process_id": "p",
            "success": False,
            "error_message": "HTTP_402: HTTP 402",
            "created_at": t0,
        }
    ]
    rows += [
        {
            "model_name": "deepseek-flash",
            "process_id": "p",
            "success": True,
            "error_message": None,
            "created_at": t0 + timedelta(minutes=m),
        }
        for m in range(1, 5)
    ]
    # The chatgpt bridge is still returning 502 with no success after it.
    rows += [
        {
            "model_name": "chatgpt",
            "process_id": "oauth_lane_keepalive",
            "success": False,
            "error_message": "502 Server Error: Bad Gateway",
            "created_at": t0 + timedelta(minutes=m),
        }
        for m in range(10)
    ]

    live = pageable(evaluate(rows))
    assert [f.lane for f in live] == ["chatgpt"]


def test_one_stray_success_does_not_count_as_recovery():
    """A partial outage lets the occasional call through; that is not a fix."""
    from datetime import datetime, timedelta

    from lib.provider_health import evaluate, pageable

    t0 = datetime(2026, 9, 19, 19, 0, 0)
    rows = [
        {
            "model_name": "deepseek-flash",
            "process_id": "p",
            "success": False,
            "error_message": "HTTP_402: HTTP 402",
            "created_at": t0 + timedelta(minutes=m),
        }
        for m in range(20)
    ]
    rows.append(
        {
            "model_name": "deepseek-flash",
            "process_id": "p",
            "success": True,
            "error_message": None,
            "created_at": t0 + timedelta(minutes=30),
        }
    )
    findings = evaluate(rows)
    assert findings[0].recovered is False
    assert len(pageable(findings)) == 1


def test_rows_without_timestamps_keep_the_loud_behaviour():
    """A caller that supplies no created_at must not be silently de-escalated."""
    from lib.provider_health import evaluate, pageable

    rows = [
        {"model_name": "deepseek-flash", "process_id": "p", "success": False, "error_message": "HTTP_402: HTTP 402"}
    ]
    rows += [
        {"model_name": "deepseek-flash", "process_id": "p", "success": True, "error_message": None} for _ in range(20)
    ]
    findings = evaluate(rows)
    assert findings[0].recovered is False
    assert len(pageable(findings)) == 1


def test_critical_findings_sort_first_and_name_the_remedy():
    from lib.provider_health import evaluate, format_alert

    rows = [
        {
            "model_name": "chatgpt",
            "process_id": "oauth_lane_keepalive",
            "success": False,
            "error_message": "502 Bad Gateway",
        }
        for _ in range(10)
    ]
    rows += [
        {
            "model_name": "deepseek-flash",
            "process_id": "watchlist_steph_flash_narrative",
            "success": False,
            "error_message": "HTTP_402: HTTP 402",
        }
        for _ in range(5)
    ]
    findings = evaluate(rows)
    assert [f.kind for f in findings] == ["BILLING", "TRANSPORT"]
    msg = format_alert(findings, window_hours=3, balance={"total_balance": "-0.09", "is_available": False})
    assert "deepseek-flash" in msg
    assert "watchlist_steph_flash_narrative" in msg
    assert "-0.09" in msg
    assert "Top up" in msg


def test_alarm_script_never_sends_under_dry_run_and_probes_no_secret():
    src = (ROOT / "scripts/check_llm_provider_health.py").read_text()
    # The send is gated on `not args.dry_run` — a dry run must stay silent. It is gated
    # on `live`, not `findings`: a recovered lane is reported and never paged.
    assert "if live and not args.dry_run:" in src
    assert "send_telegram" in src
    # The key is read, never printed or returned.
    assert 'os.environ.get("deepseek_tradeai")' in src
    for leak in ("print(key", 'f"{key}"', '"key": key'):
        assert leak not in src


# ------------------------------------------------------- OAuth soft fallback


def test_review_agents_share_the_fallback_pool_and_maria_keeps_her_own():
    from lib.maria_oauth_priority import (
        AGENT_OAUTH_FALLBACK_PROCESS_ID,
        MARIA_OAUTH_PROCESS_ID,
        OAUTH_FALLBACK_AGENTS,
        OAUTH_FALLBACK_TASK_TYPES,
        oauth_fallback_process_id,
    )

    assert oauth_fallback_process_id("maria") == MARIA_OAUTH_PROCESS_ID
    for agent in ("risk_agent", "steph", "tax_agent"):
        assert agent in OAUTH_FALLBACK_AGENTS
        assert oauth_fallback_process_id(agent) == AGENT_OAUTH_FALLBACK_PROCESS_ID
    assert OAUTH_FALLBACK_TASK_TYPES == {"risk_review", "steph_review", "tax_review"}


def test_fallback_pool_is_registered_and_cannot_spend_deepseek():
    reg = json.loads((ROOT / "config/llm_process_registry.json").read_text())
    entry = next(p for p in reg["processes"] if p["id"] == "watchlist_agent_oauth_fallback")
    # OAuth lanes only: no deepseek policy means the pool structurally cannot bill DeepSeek.
    assert entry["lane_policy"] == "either"
    assert "deepseek_allowed_policies" not in entry
    assert entry["daily_soft_cap"] >= 400  # covers risk 220 + steph 180 on a full outage day

    from lib.llm_consumption import get_process_config

    cfg = get_process_config("watchlist_agent_oauth_fallback")
    assert cfg["registered"] is True
    assert "grok" in cfg["allowed_lanes"] and "chatgpt" in cfg["allowed_lanes"]
    assert not any("deepseek" in lane for lane in cfg["allowed_lanes"])


def test_oauth_still_may_not_preempt_governed_flash_for_the_review_agents():
    """The new path is a fallback AFTER Flash failed, never a pre-emption before it."""
    src = (ROOT / "scripts/process_watchlist_agent_jobs.py").read_text()
    assert '_try_oauth_lane(fallback_reason="EXPLICIT_OAUTH_LANE", preempt=True)' in src
    assert '_try_oauth_lane(fallback_reason="FLASH_SOFT_FAILURE")' in src
    # Eligibility: pre-empt returns False for everyone but Maria.
    assert "if preempt:\n            return False" in src
    # The soft path is reached only through oauth_soft_fallback_permitted, which refuses
    # hard policy failures (budget/global cap) — those must not be routed around.
    assert "if oauth_soft_fallback_permitted(job_lane, err):" in src


def test_run_burst_guard_and_daily_cap_apply_to_the_fallback_pool():
    src = (ROOT / "scripts/process_watchlist_agent_jobs.py").read_text()
    assert "_AGENT_OAUTH_FALLBACK_RUN_CALLS >= AGENT_OAUTH_FALLBACK_RUN_CAP" in src
    assert "if over_daily_cap(process_id):" in src


# ------------------------------------------------------------------ firing


def test_billing_stop_reaches_the_transport(capture_transport, monkeypatch, tmp_path):
    """The three-day outage, replayed: 402s in the ledger must page the operator."""
    import check_llm_provider_health as c

    monkeypatch.setattr(c, "STATE_PATH", tmp_path / "alert.json")
    monkeypatch.setattr(c, "_deepseek_balance", lambda: {"total_balance": "-0.09", "is_available": False})
    # No production DB: the ledger window is supplied.
    monkeypatch.setattr(
        c,
        "_rows",
        lambda hours: [
            {
                "model_name": "deepseek-flash",
                "process_id": "watchlist_risk_flash_narrative",
                "success": False,
                "error_message": "HTTP_402: policy=FAST model=deepseek-flash HTTP 402",
            }
            for _ in range(8)
        ],
    )
    monkeypatch.setattr(sys, "argv", ["check_llm_provider_health.py", "--hours", "3"])

    assert c.main() == 0
    assert len(capture_transport) == 1
    msg = capture_transport[0][0]
    assert "deepseek-flash" in msg and "Top up" in msg
    assert "-0.09" in msg


def test_second_run_inside_the_window_does_not_repage(capture_transport, monkeypatch, tmp_path):
    """A billing stop lasts until the operator acts; paging every cron tick trains them to ignore it."""
    import check_llm_provider_health as c

    monkeypatch.setattr(c, "STATE_PATH", tmp_path / "alert.json")
    monkeypatch.setattr(c, "_deepseek_balance", lambda: None)
    monkeypatch.setattr(
        c,
        "_rows",
        lambda hours: [
            {"model_name": "deepseek-flash", "process_id": "p", "success": False, "error_message": "HTTP_402: HTTP 402"}
        ],
    )
    monkeypatch.setattr(sys, "argv", ["check_llm_provider_health.py"])

    assert c.main() == 0
    assert c.main() == 0
    assert len(capture_transport) == 1


def test_dry_run_sends_nothing(capture_transport, monkeypatch, tmp_path):
    import check_llm_provider_health as c

    monkeypatch.setattr(c, "STATE_PATH", tmp_path / "alert.json")
    monkeypatch.setattr(c, "_deepseek_balance", lambda: None)
    monkeypatch.setattr(
        c,
        "_rows",
        lambda hours: [
            {"model_name": "deepseek-flash", "process_id": "p", "success": False, "error_message": "HTTP_402: HTTP 402"}
        ],
    )
    monkeypatch.setattr(sys, "argv", ["check_llm_provider_health.py", "--dry-run", "--strict"])

    assert c.main() == 1  # strict: a CRITICAL finding is a non-zero exit
    assert capture_transport == []


# ------------------------------------------------------------------ scheduling


def test_the_monitor_is_scheduled_and_declared_as_a_lane():
    """An alarm nobody runs is the outage it was written for, one level up.

    2026-10-07: the hourly cron line was absorbed by the health tick (cron consolidation rank 3), so the
    lane row is RETIRED and names its successor; the schedule must then be provable on the successor's
    step table, not assumed. The durable artifact is unchanged either way.
    """
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    lanes = {l["lane_id"]: l for l in reg["lanes"]}
    lane = lanes.get("llm-provider-health")
    assert lane, "config/lane_registry.json must declare llm-provider-health"
    # A lane is verified by a durable artifact, never by an exit code.
    assert lane["output_signal"]["kind"] == "file_mtime"
    assert lane["output_signal"]["path"] == "data/runtime/llm_provider_health.json"
    assert lane["expected_cadence_hours"] <= 3
    if lane["state"] == "ACTIVE":
        assert lane["scheduler"]["kind"] == "cron"
        assert "check_llm_provider_health.py" in lane["scheduler"]["match"]
        return
    assert lane["state"] == "RETIRED" and lane.get("superseded_by"), lane["state"]
    successor = lanes[lane["superseded_by"]]
    assert successor["state"] == "ACTIVE", "the successor of a retired alarm lane must itself be scheduled"
    steps = json.loads((ROOT / "config" / "health_tick_steps.json").read_text())["steps"]
    step = next((st for st in steps if any("check_llm_provider_health.py" in str(a) for a in st["command"])), None)
    assert step, "the health tick step table must carry check_llm_provider_health.py"
    assert step["cadence_minutes"] <= 180


def test_an_undeliverable_alert_is_recorded_not_just_logged(monkeypatch, tmp_path):
    """A dead lane and an undeliverable alert look identical from outside: silence.

    So a failed send lands on the heartbeat — the durable artifact the lane registry
    watches — and not only in a cron log. C3 (tests/test_no_swallowed_alarms.py) is the
    generalisation of this; it caught exactly this handler on 2026-09-19.
    """
    import check_llm_provider_health as c
    import telegram_alert

    monkeypatch.setattr(c, "STATE_PATH", tmp_path / "alert.json")
    monkeypatch.setattr(c, "HEARTBEAT_PATH", tmp_path / "health.json")
    monkeypatch.setattr(c, "_deepseek_balance", lambda: None)
    monkeypatch.setattr(
        c,
        "_rows",
        lambda hours: [
            {
                "model_name": "deepseek-flash",
                "process_id": "watchlist_risk_flash_narrative",
                "success": False,
                "error_message": "HTTP_402: HTTP 402",
            }
        ],
    )

    def _boom(msg, *a, **k):
        raise RuntimeError("telegram unreachable")

    monkeypatch.setattr(telegram_alert, "send_telegram", _boom)
    monkeypatch.setattr(sys, "argv", ["check_llm_provider_health.py"])
    c.main()

    beat = json.loads((tmp_path / "health.json").read_text())
    assert beat["alert_delivery"]["ok"] is False
    assert "telegram unreachable" in beat["alert_delivery"]["reason"]
    assert beat["alert_delivery"]["undelivered"] == ["deepseek-flash:BILLING"]
    # The finding itself is still on the heartbeat, not replaced by the delivery error.
    assert beat["worst_severity"] == "CRITICAL"
    # And an undelivered alert must NOT mark the dedupe state, or the retry never happens.
    assert not (tmp_path / "alert.json").exists()


def test_a_send_that_returns_false_is_also_recorded(monkeypatch, tmp_path):
    """send_telegram reports failure by return value too, not only by raising."""
    import check_llm_provider_health as c
    import telegram_alert

    monkeypatch.setattr(c, "STATE_PATH", tmp_path / "alert.json")
    monkeypatch.setattr(c, "HEARTBEAT_PATH", tmp_path / "health.json")
    monkeypatch.setattr(c, "_deepseek_balance", lambda: None)
    monkeypatch.setattr(
        c,
        "_rows",
        lambda hours: [
            {"model_name": "deepseek-flash", "process_id": "p", "success": False, "error_message": "HTTP_402: HTTP 402"}
        ],
    )
    monkeypatch.setattr(telegram_alert, "send_telegram", lambda msg, *a, **k: False)
    monkeypatch.setattr(sys, "argv", ["check_llm_provider_health.py"])
    c.main()

    beat = json.loads((tmp_path / "health.json").read_text())
    assert beat["alert_delivery"]["ok"] is False
    assert "falsy" in beat["alert_delivery"]["reason"]
    assert not (tmp_path / "alert.json").exists()


def test_every_real_run_leaves_proof_it_ran(capture_transport, monkeypatch, tmp_path):
    """Including the quiet ones — a monitor that only writes when it fires cannot be
    told apart from a monitor that has stopped."""
    import check_llm_provider_health as c

    monkeypatch.setattr(c, "STATE_PATH", tmp_path / "alert.json")
    monkeypatch.setattr(c, "HEARTBEAT_PATH", tmp_path / "health.json")
    monkeypatch.setattr(c, "_deepseek_balance", lambda: None)
    monkeypatch.setattr(
        c,
        "_rows",
        lambda hours: [{"model_name": "deepseek-flash", "process_id": "p", "success": True, "error_message": None}],
    )
    monkeypatch.setattr(sys, "argv", ["check_llm_provider_health.py"])

    assert c.main() == 0
    assert capture_transport == [], "a healthy window must not page"
    beat = json.loads((tmp_path / "health.json").read_text())
    assert beat["worst_severity"] == "OK"
    assert beat["calls_examined"] == 1
    assert beat["checked_at"]


def test_dry_run_leaves_no_trace(monkeypatch, tmp_path):
    import check_llm_provider_health as c

    monkeypatch.setattr(c, "STATE_PATH", tmp_path / "alert.json")
    monkeypatch.setattr(c, "HEARTBEAT_PATH", tmp_path / "health.json")
    monkeypatch.setattr(c, "_deepseek_balance", lambda: None)
    monkeypatch.setattr(c, "_rows", lambda hours: [])
    monkeypatch.setattr(sys, "argv", ["check_llm_provider_health.py", "--dry-run"])

    assert c.main() == 0
    assert not (tmp_path / "health.json").exists()


# ------------------------------------------------- stalls (2026-10-15 DeepSeek hold)
#
# From 00:33Z DeepSeek held every bridge call to the deadline or answered 503, and
# llm_provider_health.json said OK: the bridge logs only SERVED calls to llm_consumption_log,
# and a 3 h / 90 % aggregate cannot see a 30 minute burst. Stalls are judged from the
# provider_cost event ledger over a short window.

from datetime import datetime, timedelta, timezone  # noqa: E402

STALL_NOW = datetime(2026, 10, 15, 1, 20, tzinfo=timezone.utc)
ROUTING = {
    "default_policy_id": "default",
    "policies": {
        "default": {
            "processes": {
                "hermes_cloud_json": {"primary": {"provider": "deepseek"}},
                "n8n_lane_failure_diagnosis": {
                    "transport_failover": True,
                    "primary": {"provider": "grok"},
                    "secondary": {"provider": "chatgpt"},
                    "fallback": {"provider": "deepseek"},
                },
            }
        }
    },
}


def _ev(
    minutes_ago,
    outcome="possibly_billable_attempt",
    error_class="TIMEOUT",
    process="hermes_cloud_json",
    provider="deepseek",
):
    return {
        "provider": provider,
        "outcome": outcome,
        "error_class": None if outcome == "success" else error_class,
        "source_process": process,
        "usage_start": (STALL_NOW - timedelta(minutes=minutes_ago)).isoformat(),
        "is_test": False,
    }


def _incident():
    """The 10-15 ledger, condensed: successes, then the hold."""
    return [
        _ev(50, "success"),
        _ev(46, "success"),
        _ev(45, "success"),
        _ev(33),
        _ev(32),
        _ev(19),
        _ev(17, error_class="HTTP_503"),
    ]


def test_config_carries_every_stall_threshold():
    from lib.provider_health import DEFAULT_STALL_POLICY

    cfg = json.loads((ROOT / "config/llm_provider_health.json").read_text())["stall"]
    assert set(DEFAULT_STALL_POLICY) <= set(cfg)
    assert cfg["priority_degraded"] == "P3" and cfg["priority_all_lanes_down"] == "P1"


def test_timeouts_and_503s_after_successes_are_a_critical_stall_for_a_deepseek_only_row():
    from lib.provider_health import evaluate_stalls

    out = evaluate_stalls(_incident(), now=STALL_NOW, routing_doc=ROUTING)
    assert len(out) == 1
    f = out[0]
    assert f.provider == "deepseek" and f.consecutive_stalls == 4
    assert f.error_classes == {"TIMEOUT": 3, "HTTP_503": 1}
    # hermes_cloud_json has no lane but DeepSeek: that is a page, not a digest.
    assert f.severity == "CRITICAL" and f.all_lanes_down_processes == ["hermes_cloud_json"]
    assert not f.recovered


def test_a_stall_that_leaves_another_lane_open_is_degraded_not_critical():
    from lib.provider_health import evaluate_stalls

    events = [_ev(m, process="n8n_lane_failure_diagnosis") for m in (25, 20, 15)]
    (f,) = evaluate_stalls(events, now=STALL_NOW, routing_doc=ROUTING)
    assert f.severity == "DEGRADED" and f.all_lanes_down_processes == []


def test_two_stalls_are_not_yet_a_finding_and_other_failures_are_not_stalls():
    from lib.provider_health import evaluate_stalls

    assert evaluate_stalls([_ev(40, "success"), _ev(20), _ev(10)], now=STALL_NOW, routing_doc=ROUTING) == []
    noise = [_ev(m, error_class="JSON_INVALID") for m in (25, 20, 15, 10)]
    assert evaluate_stalls(noise, now=STALL_NOW, routing_doc=ROUTING) == []


def test_the_ratio_rule_fires_when_most_of_the_window_stalled():
    from lib.provider_health import evaluate_stalls

    # Never three in a row, but 4 of 6 attempts in 30 minutes stalled (> 50 %).
    events = [_ev(28), _ev(26), _ev(24, "success"), _ev(20), _ev(18), _ev(5, "success")]
    (f,) = evaluate_stalls(events, now=STALL_NOW, routing_doc=ROUTING)
    assert f.consecutive_stalls == 0 and f.window_stalls == 4 and f.window_events == 6
    # The threshold is config, not code: raise it and the same window is quiet.
    assert evaluate_stalls(events, now=STALL_NOW, routing_doc=ROUTING, policy={"ratio_threshold": 0.7}) == []


def test_a_recovered_provider_is_reported_but_not_paged():
    from lib.provider_health import evaluate_stalls

    # 4 of 7 attempts in the window still stalled (> 50 %), but the newest three succeeded.
    events = [_ev(m) for m in (28, 26, 24, 22)] + [_ev(m, "success") for m in (6, 4, 2)]
    out = evaluate_stalls(events, now=STALL_NOW, routing_doc=ROUTING)
    assert out and out[0].recovered and out[0].severity == "DEGRADED"
    assert out[0].all_lanes_down_processes == []
    # Two successes are not recovery (a partial outage lets one through).
    out = evaluate_stalls(events[:-1], now=STALL_NOW, routing_doc=ROUTING)
    assert out and not out[0].recovered and out[0].severity == "CRITICAL"


def _stall_run(monkeypatch, tmp_path, events):
    import check_llm_provider_health as c

    ledger = tmp_path / "events.jsonl"
    ledger.write_text("".join(json.dumps(e) + "\n" for e in events))
    routing = tmp_path / "routing.json"
    routing.write_text(json.dumps(ROUTING))
    monkeypatch.setenv("PROVIDER_COST_EVENT_LOG", str(ledger))
    monkeypatch.setenv("TRADEAI_LLM_ROUTING_POLICY", str(routing))
    monkeypatch.setattr(c, "STATE_PATH", tmp_path / "alert.json")
    monkeypatch.setattr(c, "HEARTBEAT_PATH", tmp_path / "health.json")
    monkeypatch.setattr(c, "_deepseek_balance", lambda: pytest.fail("a stall must not probe the provider"))
    monkeypatch.setattr(c, "_rows", lambda hours: [])
    monkeypatch.setattr(sys, "argv", ["check_llm_provider_health.py"])
    return c


def _shift(events):
    """Re-anchor fixture events to the real clock, which main() reads."""
    delta = datetime.now(timezone.utc) - STALL_NOW
    out = []
    for e in events:
        e = dict(e)
        e["usage_start"] = (datetime.fromisoformat(e["usage_start"]) + delta).isoformat()
        out.append(e)
    return out


def test_a_stall_with_no_lane_left_pages_at_p1_and_marks_the_heartbeat(capture_transport, monkeypatch, tmp_path):
    c = _stall_run(monkeypatch, tmp_path, _shift(_incident()))
    assert c.main() == 0
    assert len(capture_transport) == 1
    msg, kw = capture_transport[0]
    assert kw["priority"] == "P1" and "deepseek" in msg and "hermes_cloud_json" in msg
    beat = json.loads((tmp_path / "health.json").read_text())
    assert beat["worst_severity"] == "CRITICAL" and beat["stall_worst"] == "CRITICAL"
    assert beat["stall_findings"][0]["error_classes"] == {"TIMEOUT": 3, "HTTP_503": 1}
    # Kept out of `findings`, which the bridge's lane-health gate reads.
    assert beat["findings"] == []
    # Deduped: the next tick does not page again.
    assert c.main() == 0 and len(capture_transport) == 1


def test_a_fallback_lane_stall_goes_to_the_digest(capture_transport, monkeypatch, tmp_path):
    events = _shift([_ev(m, process="n8n_lane_failure_diagnosis") for m in (25, 20, 15)])
    c = _stall_run(monkeypatch, tmp_path, events)
    assert c.main() == 0
    assert [kw["priority"] for _m, kw in capture_transport] == ["P3"]
    assert json.loads((tmp_path / "health.json").read_text())["stall_worst"] == "DEGRADED"


def test_a_stall_alert_that_cannot_be_delivered_is_recorded(monkeypatch, tmp_path):
    import telegram_alert

    c = _stall_run(monkeypatch, tmp_path, _shift(_incident()))
    monkeypatch.setattr(telegram_alert, "send_telegram", lambda *a, **k: False)
    c.main()
    beat = json.loads((tmp_path / "health.json").read_text())
    assert beat["alert_delivery"]["undelivered"] == ["stall:deepseek:CRITICAL"]
    assert not (tmp_path / "alert.json").exists()


def test_pytest_never_reads_the_live_cost_ledger(monkeypatch):
    import check_llm_provider_health as c

    monkeypatch.delenv("PROVIDER_COST_EVENT_LOG", raising=False)
    assert c._events_path() is None and c._provider_events(1024) == []
