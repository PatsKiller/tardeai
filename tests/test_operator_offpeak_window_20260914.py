"""Scheduled paid work runs in the operator's window, and the spend report checks itself against DeepSeek.

Operator, 2026-09-14: "off peak hours ... are 9 a.m. to 9 p.m. Eastern Standard Time in the U.S. and on the
weekends, and only a la carte stuff that is urgent, that's requested by the operator, is ran during peak
hours. Make sure you research exactly what the complete costs are with DeepSeek's website."

DeepSeek (api-docs.deepseek.com/quick_start/pricing): peak 01:00-04:00 and 06:00-10:00 UTC, Mon-Fri, at
twice the off-peak price. The operator window can still touch that peak:
- Sunday 21:00-24:00 ET is Monday 01:00-04:00 UTC;
- in winter (EST), weekday 20:00-21:00 ET is 01:00-02:00 UTC.

The gate refuses both.

Offline: no network, no database, no Telegram.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import deepseek_offpeak as op  # noqa: E402
from scripts.lib import llm_spend as s  # noqa: E402


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# ── the window ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "when,skip,why",
    [
        ("2026-09-15T12:30:00", True, "Tue 08:30 EDT: before 09:00"),
        ("2026-09-15T13:05:00", False, "Tue 09:05 EDT: inside"),
        ("2026-09-16T00:30:00", False, "Tue 20:30 EDT = 00:30 UTC: inside, off DeepSeek peak"),
        ("2026-09-16T01:30:00", True, "Tue 21:30 EDT: after 21:00"),
        ("2026-12-16T01:30:00", True, "Tue 20:30 EST = 01:30 UTC: inside the window but DeepSeek peak"),
        ("2026-09-19T07:00:00", False, "Sat 03:00 EDT: weekend, Saturday UTC is never peak"),
        ("2026-09-21T02:00:00", True, "Sun 22:00 EDT = Mon 02:00 UTC: DeepSeek peak"),
        ("2026-09-21T00:00:00", False, "Sun 20:00 EDT = Mon 00:00 UTC: weekend, off peak"),
    ],
)
def test_the_scheduled_window(monkeypatch, when, skip, why):
    monkeypatch.delenv("TRADEAI_ALLOW_SCHEDULED_PEAK", raising=False)
    assert op.should_scheduled_skip(_utc(when)) is skip, why


def test_the_operator_can_override_one_run(monkeypatch):
    monkeypatch.setenv("TRADEAI_ALLOW_SCHEDULED_PEAK", "1")
    assert op.should_scheduled_skip(_utc("2026-09-15T12:30:00")) is False


def _wrapper(now_utc: str) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        TRADEAI_OFFPEAK_NOW_UTC=now_utc,
        TRADEAI_OFFPEAK_PY=str(ROOT / "scripts" / "lib" / "deepseek_offpeak.py"),
        PY=sys.executable,
    )
    env.pop("TRADEAI_ALLOW_SCHEDULED_PEAK", None)
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "run_with_deepseek_offpeak.sh"), "--scheduled", "--", "echo", "RAN"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_the_cron_wrapper_skips_outside_the_window_and_runs_inside():
    outside = _wrapper("2026-09-15T12:30:00Z")
    assert (
        outside.returncode == 0 and "PEAK_SKIP gate=--gate-scheduled" in outside.stdout and "RAN" not in outside.stdout
    )
    inside = _wrapper("2026-09-15T13:05:00Z")
    assert inside.returncode == 0 and "RAN" in inside.stdout


def test_the_late_evening_timers_moved_inside_the_window():
    for unit, expected in (
        ("tradeai-advisory-lessons-reflect.timer", "OnCalendar=*-*-* 19:40:00"),
        ("tradeai-advisory-shadow-seed.timer", "OnCalendar=*-*-* 19:45:00"),
    ):
        assert expected in (ROOT / "config" / "systemd" / "user" / unit).read_text(encoding="utf-8")


# ── the report ───────────────────────────────────────────────────────────────


def test_outside_window_sql_is_eastern_weekdays_before_9_or_from_21():
    sql = s.outside_window_sql()
    assert "America/New_York" in sql and "BETWEEN 1 AND 5" in sql and "< 9" in sql and ">= 21" in sql


def test_balance_reconciliation_counts_drops_and_never_nets_top_ups():
    snaps = [
        {"ts": "2026-09-14T00:50:00+00:00", "total_balance": "12.00"},
        {"ts": "2026-09-14T06:50:00+00:00", "total_balance": "11.80"},
        {"ts": "2026-09-14T12:50:00+00:00", "total_balance": "21.80"},
        {"ts": "2026-09-14T18:50:00+00:00", "total_balance": "21.50"},
        {"ts": "bad", "total_balance": "x"},
    ]
    r = s.reconcile_balance(snaps, _utc("2026-09-14T01:00:00"), _utc("2026-09-14T23:00:00"))
    assert r["deducted_usd"] == pytest.approx(0.50) and r["topped_up_usd"] == pytest.approx(10.0)
    assert r["balance_usd"] == pytest.approx(21.50) and r["partial"] is False
    late = s.reconcile_balance(snaps, _utc("2026-09-13T00:00:00"), _utc("2026-09-14T07:00:00"))
    assert late["partial"] is True and late["deducted_usd"] == pytest.approx(0.20)
    assert s.reconcile_balance(snaps[:1], _utc("2026-09-14T01:00:00"), _utc("2026-09-14T23:00:00")) is None


def _fake_db(sql, params=None):
    if "FROM llm_process_config" in sql:
        return []
    if "FROM llm_cost_reservations" in sql:
        return [{"usd": 0.5}]
    if "GROUP BY model_lane, model_name" in sql:
        return [{"model_lane": "fast", "model_name": "deepseek-flash", "calls": 700, "usd": 0.49}]
    if "GROUP BY process_id, trigger_mode" in sql:
        return [
            {
                "process_id": "hermes_usefulness",
                "process_name": "Usefulness scorer",
                "trigger_mode": "automated",
                "calls": 300,
                "usd": 0.20,
                "calls_outside_window": 120,
                "usd_outside_window": 0.08,
            },
            {
                "process_id": "operator_desk",
                "process_name": "Operator desk",
                "trigger_mode": "manual",
                "calls": 10,
                "usd": 0.05,
                "calls_outside_window": 4,
                "usd_outside_window": 0.02,
            },
        ]
    if "model_name ILIKE 'deepseek" in sql:
        return [{"usd": 0.47}]
    return [
        {
            "calls": 700,
            "paid_calls": 700,
            "usd": 0.49,
            "usd_peak": 0.05,
            "calls_peak": 40,
            "usd_outside_window": 0.10,
            "calls_outside_window": 124,
        }
    ]


def test_the_report_names_scheduled_work_outside_the_window_and_reconciles_the_balance(tmp_path, monkeypatch):
    import llm_spend_report as rep

    monkeypatch.setattr(s, "CAP_FILE", tmp_path / "cap.env")
    monkeypatch.setattr(s, "SEARCH_BUDGET", tmp_path / "absent.json")
    hist = tmp_path / "balance.jsonl"
    hist.write_text(
        "\n".join(
            json.dumps(x)
            for x in (
                {"ts": "2026-09-13T03:50:00+00:00", "total_balance": 12.25},
                {"ts": "2026-09-14T03:50:00+00:00", "total_balance": 11.75},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(s, "BALANCE_HISTORY", hist)
    monkeypatch.setattr(rep, "cc_link", lambda: "")
    r = s.build_report("yesterday", now=_utc("2026-09-14T19:00:00"), db_query=_fake_db)
    assert r["totals"]["usd_outside_window"] == pytest.approx(0.10) and r["totals"]["calls_outside_window"] == 124
    assert [x["process_id"] for x in r["scheduled_outside_window"]] == ["hermes_usefulness"]
    assert r["deepseek_balance"]["deducted_usd"] == pytest.approx(0.50)
    assert r["deepseek_balance"]["logged_usd"] == pytest.approx(0.47)
    text = rep.format_report(r, cadence="daily")
    assert "Scheduled work outside 9 a.m.–9 p.m. ET weekdays" in text and "Usefulness scorer (120 calls" in text
    assert f"DeepSeek balance: {rep.money(0.5)} deducted vs {rep.money(0.47)} logged" in text


# ── the balance snapshot ─────────────────────────────────────────────────────


def test_balance_snapshot_dry_run_writes_nothing_and_apply_appends(tmp_path, monkeypatch):
    import deepseek_balance_snapshot as snap

    body = {
        "is_available": True,
        "balance_infos": [
            {"currency": "CNY", "total_balance": "80.00"},
            {"currency": "USD", "total_balance": "11.75", "granted_balance": "0.00", "topped_up_balance": "11.75"},
        ],
    }
    path = tmp_path / "history.jsonl"
    dry = snap.run_once(apply=False, path=path, fetcher=lambda: body, now=_utc("2026-09-14T22:50:00"))
    assert dry["snapshot"]["currency"] == "USD" and dry["snapshot"]["total_balance"] == 11.75 and not path.exists()
    snap.run_once(apply=True, path=path, fetcher=lambda: body, now=_utc("2026-09-14T22:50:00"))
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["topped_up_balance"] == 11.75
    assert "Bearer" not in path.read_text(encoding="utf-8")
