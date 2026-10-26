"""Delivery failure alerts (AGENTS.md §29 PROPOSED): every trigger fires, renders one line + link, reaches the right
channels, dedupes, rate-limits, and never sends in a dry run. Hermetic: temp state roots, stubbed senders/systemd."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import delivery_failure_alerts as DFA  # noqa: E402

COVERS = ["scripts/lib/delivery_failure_alerts.py"]

NOW = datetime(2026, 10, 25, 22, 0, tzinfo=timezone.utc)  # Sun 18:00 ET
SHA = "a" * 40
SHA2 = "b" * 40
SMS_ENV = {"ENABLE_SMS": "true", "OPERATOR_SMS_EMAIL": "fixture-not-a-real-address"}
MAIL_ENV = {"REPORT_EMAIL_TO": "fixture", "SMTP_HOST": "fixture"}


def _w(p: Path, doc) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)
    return p


def _ctx(tmp_path: Path, **kw) -> DFA.Context:
    cfg = DFA.load_config()
    return DFA.Context(
        state_root=tmp_path / "state",
        release_state_dir=tmp_path / "rw",
        deploy_state_dir=tmp_path / "deploy",
        now=kw.pop("now", NOW),
        config=cfg,
        systemd_timers=kw.pop("systemd_timers", lambda: []),
        **kw,
    )


class Capture:
    def __init__(self, fail: tuple[str, ...] = ()):
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    def senders(self):
        def mk(ch):
            def send(msg, identity):
                self.calls.append((ch, msg))
                if ch in self.fail:
                    raise RuntimeError(f"{ch} provider down")
                return {"ok": True}

            return send

        return {ch: mk(ch) for ch in DFA.CHANNELS}


# ── triggers ──────────────────────────────────────────────────────────────────────────────────────


def test_main_ci_red_from_fresh_receipt(tmp_path):
    ctx = _ctx(tmp_path)
    _w(
        ctx.state_root / DFA.MAIN_CI_RECEIPT_REL,
        {
            "summary": {
                "state": "FAILURE",
                "head_sha": SHA,
                "checked_at": (NOW - timedelta(minutes=5)).isoformat(),
                "workflows": [{"name": "cio-hardening", "state": "FAILURE", "url": "https://github.com/x/runs/1"}],
            }
        },
    )
    inc = DFA.detect_main_ci(ctx)
    assert [i.key for i in inc] == [f"main_ci_red:{SHA}"]
    assert "cio-hardening" in inc[0].line and SHA[:9] in inc[0].line


def test_main_ci_stale_receipt_uses_reader_and_green_is_silent(tmp_path):
    ctx = _ctx(tmp_path, ci_reader=lambda: {"state": "SUCCESS", "head_sha": SHA})
    _w(
        ctx.state_root / DFA.MAIN_CI_RECEIPT_REL,
        {"summary": {"state": "FAILURE", "head_sha": SHA, "checked_at": (NOW - timedelta(hours=3)).isoformat()}},
    )
    assert DFA.detect_main_ci(ctx) == []
    ctx2 = _ctx(tmp_path, ci_reader=lambda: (_ for _ in ()).throw(RuntimeError("gh down")))
    assert DFA.detect_main_ci(ctx2) == [] and any("unreadable" in n for n in ctx2.notes)


@pytest.mark.parametrize(
    "outcome,skips_telegram",
    [
        ("ROLLED_BACK", True),
        ("ROLLBACK_FAILED", True),
        ("MERGED_NOT_LIVE", True),
        ("STOPPED", False),
        ("FAILED_PRE_MERGE", False),
    ],
)
def test_train_outcomes(tmp_path, outcome, skips_telegram):
    ctx = _ctx(tmp_path)
    _w(
        ctx.release_state_dir / "trains" / "rt-20261025-1800-abcd" / "outcome.json",
        {
            "train_id": "rt-20261025-1800-abcd",
            "outcome": outcome,
            "finished_at": NOW.isoformat(),
            "candidate_sha": SHA,
            "notes": "verify_failed: health",
        },
    )
    inc = DFA.detect_train_outcomes(ctx)
    assert len(inc) == 1 and outcome in inc[0].line
    assert ("telegram" in inc[0].skip_channels) is skips_telegram


def test_train_success_noop_and_old_outcomes_are_silent(tmp_path):
    ctx = _ctx(tmp_path)
    _w(
        ctx.release_state_dir / "trains" / "a" / "outcome.json",
        {"outcome": "RELEASED_VERIFIED", "finished_at": NOW.isoformat()},
    )
    _w(
        ctx.release_state_dir / "trains" / "b" / "outcome.json",
        {"outcome": "ROLLED_BACK", "finished_at": (NOW - timedelta(days=3)).isoformat()},
    )
    assert DFA.detect_train_outcomes(ctx) == []


def test_controller_p1_outcomes_match_controller_alert_priority():
    from scripts.lib import release_train_controller as RTC

    assert DFA.CONTROLLER_P1_OUTCOMES == {k for k, v in RTC.ALERT_PRIORITY.items() if v == "P1"}


def test_train_receipts_live_refused_and_failed_but_never_drills(tmp_path):
    ctx = _ctx(tmp_path)
    base = ctx.release_state_dir / "train_requests" / "receipts"
    common = {"finished_at": NOW.isoformat()}
    _w(
        base / "rtw-20261025-1800-win.json",
        {
            **common,
            "request_id": "rtw-20261025-1800-win",
            "state": "REFUSED",
            "shadow": False,
            "mode": "live",
            "refusal": {"code": "STOP_SET", "detail": "latched"},
        },
    )
    _w(
        base / "rtw-20261025-1200-win.json",
        {
            **common,
            "request_id": "rtw-20261025-1200-win",
            "state": "FAILED",
            "shadow": False,
            "mode": "live",
            "refusal": {"code": "CONTROLLER_ERROR", "detail": "x"},
        },
    )
    _w(
        base / "rtw-20261025-0000-win.json",
        {
            **common,
            "request_id": "d1",
            "state": "REFUSED",
            "shadow": True,
            "mode": "simulate",
            "refusal": {"code": "STOP_UNREADABLE"},
        },
    )
    _w(
        base / "rtw-20261025-0600-win.json",
        {
            **common,
            "request_id": "d2",
            "state": "REFUSED",
            "shadow": False,
            "mode": "live",
            "refusal": {"code": "DUPLICATE_WINDOW"},
        },
    )
    keys = sorted(i.key for i in DFA.detect_train_receipts(ctx))
    assert keys == ["train_receipt:rtw-20261025-1200-win", "train_receipt:rtw-20261025-1800-win"]


@pytest.mark.parametrize("content,state", [('{"reason": "operator stop"}', "SET"), ("{not json", "UNREADABLE")])
def test_stop_latch(tmp_path, content, state):
    ctx = _ctx(tmp_path)
    _w(ctx.release_state_dir / "STOP.json", content)
    inc = DFA.detect_stop_latch(ctx)
    assert len(inc) == 1 and f"STOP {state}" in inc[0].line


def test_stop_absent_is_silent(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.release_state_dir.mkdir(parents=True)
    assert DFA.detect_stop_latch(ctx) == []


def _history(ctx, rows):
    _w(ctx.deploy_state_dir / "deploy_receipt_history.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")


def test_manual_release_failure_rollback_and_train_cross_dedupe(tmp_path):
    ctx = _ctx(tmp_path)
    at = NOW.isoformat()
    _history(
        ctx,
        [
            {"mode": "promote", "ok": True, "rolled_back": False, "sha": SHA, "at": at},
            {
                "mode": "promote",
                "ok": False,
                "rolled_back": True,
                "sha": SHA2,
                "at": at,
                "extra": "rolled_back_to_prev",
            },
            {
                "mode": "promote",
                "ok": False,
                "rolled_back": False,
                "sha": SHA,
                "at": at,
                "extra": "post_merge_ci_refused",
            },
            {"mode": "prepare", "ok": False, "sha": SHA, "at": at},
        ],
    )
    inc = DFA.detect_manual_release(ctx)
    assert len(inc) == 2 and any("rolled back" in i.line for i in inc) and any("FAILED" in i.line for i in inc)
    assert len(DFA.detect_manual_release(ctx, train_shas={SHA2})) == 1


def test_post_release_and_nightly_receipts(tmp_path):
    ctx = _ctx(tmp_path)
    d = ctx.state_root / DFA.TESTER_DIR_REL
    _w(
        d / "last_api.json",
        {
            "status": "FAILED",
            "release_sha": SHA,
            "run_id": "r1",
            "finished_at": NOW.isoformat(),
            "checks": [{"name": "health", "ok": False, "detail": "HTTP 502"}],
        },
    )
    _w(d / "last_light.json", {"status": "PASSED", "release_sha": SHA, "run_id": "r2", "finished_at": NOW.isoformat()})
    _w(
        d / "last_nightly.json",
        {
            "status": "FAILED",
            "run_id": "n1",
            "finished_at": NOW.isoformat(),
            "broken": [{"kind": "console_error"}, {"kind": "console_error"}, {"kind": "route_crash"}],
            "summary_path": "/x/summary.md",
        },
    )
    pr = DFA.detect_post_release(ctx)
    assert len(pr) == 1 and "health: HTTP 502" in pr[0].line
    ns = DFA.detect_nightly_sweep(ctx)
    assert len(ns) == 1 and "3 broken" in ns[0].line and "console_error 2" in ns[0].line


def _systemd(
    calendar="{ OnCalendar=*-*-* 18:00:00 ; next_elapse=Mon 2026-10-26 18:00:00 EDT }",
    last="Sun 2026-10-25 18:00:01 EDT",
    active="active",
    result="success",
):
    props = {
        "tradeai-release-train-request@1800.timer": {
            "LoadState": "loaded",
            "UnitFileState": "enabled",
            "ActiveState": active,
            "TimersCalendar": calendar,
            "LastTriggerUSec": last,
        },
        "tradeai-release-train-request@1800.service": {
            "Result": result,
            "ExecMainStatus": "0" if result == "success" else "1",
        },
    }
    return (lambda: ["tradeai-release-train-request@1800.timer", "other.timer"], lambda unit, ps: props.get(unit, {}))


@pytest.mark.parametrize(
    "case,expect",
    [
        ("fired_with_request", None),
        ("not_fired", "did not fire"),
        ("no_request", "wrote no request"),
        ("service_failed", "FAILED"),
        ("inside_grace", None),
        ("weekday_only_on_sunday", None),
    ],
)
def test_request_slot_missed(tmp_path, case, expect):
    now = NOW + timedelta(minutes=30)  # Sun 18:30 ET, 30 min after the slot
    kw = {}
    if case == "not_fired":
        kw["last"] = "Sat 2026-10-24 18:00:01 EDT"
    if case == "service_failed":
        kw["result"] = "exit-code"
    if case == "inside_grace":
        now = NOW + timedelta(minutes=5)
    if case == "weekday_only_on_sunday":
        kw["calendar"] = "{ OnCalendar=Mon..Fri *-*-* 18:00:00 America/New_York ; next_elapse=x }"
        kw["last"] = "Fri 2026-10-23 18:00:01 EDT"
    timers, show = _systemd(**kw)
    ctx = _ctx(tmp_path, now=now, systemd_timers=timers, systemd_show=show)
    if case != "no_request":
        _w(ctx.release_state_dir / "train_requests" / "claimed" / "rtw-20261025-1800-win.json", {})
    inc = DFA.detect_request_slots(ctx)
    if expect is None:
        assert inc == []
    else:
        assert len(inc) == 1 and expect in inc[0].line and inc[0].key == "request_slot_missed:1800:20261025"


def test_on_calendar_parser_weekend_three_hourly():
    sat_10 = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)  # Sat 10:00 ET
    due = DFA.last_due("Sat *-*-* 09:00:00", sat_10, 26)
    assert due == datetime(2026, 10, 24, 13, 0, tzinfo=timezone.utc)
    assert DFA.last_due("Mon..Fri *-*-* 12:00:00", sat_10, 26) == datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)
    assert DFA.last_due("Mon..Fri *-*-* 12:00:00", sat_10, 12) is None
    assert DFA.parse_on_calendar("hourly") is None


def test_detector_crash_becomes_an_incident_not_silence(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setitem(DFA.DETECTORS, "stop_latched", lambda c: 1 / 0)
    inc = DFA.detect_all(ctx, only=["stop_latched"])
    assert [i.key for i in inc] == ["detector_error:stop_latched"]


# ── delivery ──────────────────────────────────────────────────────────────────────────────────────


def _one_incident(ctx):
    _w(ctx.release_state_dir / "STOP.json", '{"reason": "operator stop"}')


def test_dry_run_renders_and_never_sends_or_marks(tmp_path):
    ctx = _ctx(tmp_path)
    _one_incident(ctx)
    cap = Capture()
    r = DFA.run(ctx, live=False, senders=cap.senders(), env={**MAIL_ENV, **SMS_ENV})
    assert cap.calls == []
    assert not (ctx.state_root / DFA.STATE_REL).exists() and not (ctx.state_root / DFA.RECEIPT_REL).exists()
    assert (ctx.state_root / DFA.DRY_RUN_RECEIPT_REL).exists()
    m = r["messages"][0]
    assert {c: v["status"] for c, v in m["channels"].items()} == {
        "telegram": "DRY_RUN",
        "email": "DRY_RUN",
        "sms": "DRY_RUN",
    }
    assert m["rendered"]["text"].startswith("TRADE AI FAILURE: release STOP SET")
    assert "/v3/system/releases" in m["rendered"]["text"] and len(m["rendered"]["sms"]) <= 155


def test_live_sends_all_ready_channels_then_dedupes_then_reminds(tmp_path):
    ctx = _ctx(tmp_path)
    _one_incident(ctx)
    cap = Capture()
    env = {**MAIL_ENV, **SMS_ENV}
    r = DFA.run(ctx, live=True, senders=cap.senders(), env=env)
    assert [c for c, _ in cap.calls] == ["telegram", "email", "sms"] and r["ok"]
    r2 = DFA.run(ctx, live=True, senders=cap.senders(), env=env)
    assert r2["messages"] == [] and len(cap.calls) == 3
    ctx.now = NOW + timedelta(hours=25)
    DFA.run(ctx, live=True, senders=cap.senders(), env=env)
    assert len(cap.calls) == 6


def test_sms_not_configured_is_reported_with_key_names_only(tmp_path):
    ctx = _ctx(tmp_path)
    _one_incident(ctx)
    cap = Capture()
    secret = "s3cr3t-value-never-printed"
    r = DFA.run(ctx, live=True, senders=cap.senders(), env={**MAIL_ENV, "TWILIO_SID": secret})
    sms = r["messages"][0]["channels"]["sms"]
    assert sms["status"] == "NOT_CONFIGURED" and "ENABLE_SMS" in sms["why"]
    assert [c for c, _ in cap.calls] == ["telegram", "email"]
    assert secret not in json.dumps(r)
    ready = DFA.channel_readiness(DFA.load_config(), {"ENABLE_SMS": "true", "TWILIO_SID": secret})
    assert ready["sms"]["status"] == "NOT_CONFIGURED" and "OPERATOR_SMS_EMAIL" in ready["sms"]["why"]
    assert secret not in json.dumps(ready)


def test_one_channel_failing_still_sends_the_others_and_marks(tmp_path):
    ctx = _ctx(tmp_path)
    _one_incident(ctx)
    cap = Capture(fail=("email",))
    r = DFA.run(ctx, live=True, senders=cap.senders(), env={**MAIL_ENV, **SMS_ENV})
    ch = r["messages"][0]["channels"]
    assert ch["email"]["status"] == "FAILED" and "provider down" in ch["email"]["error"]
    assert ch["telegram"]["status"] == "SENT" and ch["sms"]["status"] == "SENT" and r["ok"]


def test_no_channel_delivers_means_not_marked_and_exit_not_ok(tmp_path):
    ctx = _ctx(tmp_path)
    _one_incident(ctx)
    cap = Capture(fail=DFA.CHANNELS)
    r = DFA.run(ctx, live=True, senders=cap.senders(), env={**MAIL_ENV, **SMS_ENV})
    assert r["ok"] is False
    state = json.loads((ctx.state_root / DFA.STATE_REL).read_text())
    assert state["incidents"] == {}


def test_controller_paged_train_outcome_skips_telegram_only(tmp_path):
    ctx = _ctx(tmp_path)
    _w(
        ctx.release_state_dir / "trains" / "rt-x" / "outcome.json",
        {"train_id": "rt-x", "outcome": "ROLLED_BACK", "finished_at": NOW.isoformat()},
    )
    cap = Capture()
    r = DFA.run(ctx, live=True, senders=cap.senders(), env={**MAIL_ENV, **SMS_ENV}, only=["train_outcome"])
    assert [c for c, _ in cap.calls] == ["email", "sms"]
    assert r["messages"][0]["channels"]["telegram"]["status"] == "SKIPPED"


def test_many_incidents_fold_into_one_message_and_hourly_cap_holds(tmp_path):
    ctx = _ctx(tmp_path)
    for n in range(5):
        _w(
            ctx.release_state_dir / "trains" / f"rt-{n}" / "outcome.json",
            {"train_id": f"rt-{n}", "outcome": "STOPPED", "finished_at": NOW.isoformat()},
        )
    cap = Capture()
    r = DFA.run(ctx, live=True, senders=cap.senders(), env=MAIL_ENV, only=["train_outcome"])
    assert len(r["messages"]) == 1 and r["messages"][0]["rendered"]["text"].startswith("TRADE AI FAILURES (5)")
    state = json.loads((ctx.state_root / DFA.STATE_REL).read_text())
    state["sends"] = [NOW.isoformat()] * 6
    (ctx.state_root / DFA.STATE_REL).write_text(json.dumps(state))
    _w(ctx.release_state_dir / "STOP.json", "{}")
    r2 = DFA.run(ctx, live=True, senders=cap.senders(), env=MAIL_ENV)
    assert r2["messages"] == [] and r2["held_rate_limited"]


def test_default_telegram_sender_uses_the_chokepoint_at_p1(monkeypatch):
    import telegram_alert

    seen = {}

    def fake(message, **kw):
        seen.update(kw, message=message)
        return True

    monkeypatch.setattr(telegram_alert, "send_telegram", fake)
    res = DFA.default_senders()["telegram"]({"text": "TRADE AI FAILURE: x"}, "dfa:x")
    assert res["ok"] and seen["priority"] == "P1" and seen["producer"] == DFA.PRODUCER


def test_default_gateway_senders_use_send_via_gateway(monkeypatch):
    from scripts.lib.comms import channel_adapters as CA

    seen = []

    def fake(channel, **kw):
        seen.append((channel, kw))
        return {"delivered": channel == "email", "error": None if channel == "email" else "unsupported_channel"}

    monkeypatch.setattr(CA, "send_via_gateway", fake)
    msg = {"text": "t", "subject": "s", "body": "b", "sms": "short"}
    assert DFA.default_senders()["email"](msg, "dfa:x")["ok"] is True
    res = DFA.default_senders()["sms"](msg, "dfa:x")
    assert res["ok"] is False and res["error"] == "unsupported_channel"
    assert seen[0][1]["deliver"] is True and seen[0][1]["subject"] == "s" and seen[1][1]["body"] == "short"


def test_cli_dry_run_on_temp_root(tmp_path, capsys):
    import delivery_failure_alerts as CLI

    _w(tmp_path / "rw" / "STOP.json", '{"reason": "fixture"}')
    rc = CLI.main(
        [
            "--state-root",
            str(tmp_path / "s"),
            "--release-state-dir",
            str(tmp_path / "rw"),
            "--deploy-state-dir",
            str(tmp_path / "d"),
            "--no-github",
            "--no-systemd",
            "--now",
            NOW.isoformat(),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0 and "TRADE AI FAILURE: release STOP SET: fixture" in out and "channels: telegram=" in out
