"""n8n refactor wave 1 (W2), 2026-10-10 — llm_spend_report.py (cron:L963/L964/L965).

Operator 2026-10-09 ~23:00 ET: "start with refactoring ... do dry run and unit test". The script gains
``--dry-run`` (reaches no ledger, receipt, artifact or send), ``--prepare`` (the preparer half of the
preparer/sender split: message artifact + LaneRunReceipt@v1, never a send), ``--period auto`` (the three
crontab lines' days in one argv) and ``ok_at`` on the sender's receipt. The ``--send`` path is unchanged.
Offline: build_report is stubbed; nothing touches a database or Telegram.
"""

from __future__ import annotations

import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import llm_spend_report as rep  # noqa: E402

COVERS = ["scripts/llm_spend_report.py", "scripts/lib/lane_last_receipt.py"]


def _report(usd: float = 0.42, start: str = "2026-10-08T04:00:00+00:00") -> dict:
    return {
        "label": "Thu Oct 8",
        "start_utc": start,
        "totals": {
            "usd": usd,
            "usd_per_day": usd,
            "calls": 10,
            "paid_calls": 4,
            "failures": 0,
            "tokens_in": 1000,
            "tokens_out": 200,
            "usd_offpeak": usd,
            "usd_peak": 0.0,
            "calls_offpeak": 10,
            "calls_peak": 0,
        },
        "counted_by_caps_usd": usd,
        "global_cap_usd_per_day": 2.0,
        "by_provider": [],
        "by_process": [],
        "scheduled_on_peak": [],
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Point every durable path at tmp, stub the report builder and the sender."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rt = tmp_path / "data" / "runtime"
    monkeypatch.setattr(rep, "LEDGER", rt / "llm_spend_report_sent.json")
    monkeypatch.setattr(rep, "RECEIPT", rt / "llm_spend_report_last_{cadence}.json")
    monkeypatch.setattr(rep, "PREPARED", rt / "llm_spend_report_prepared_{cadence}.json")
    monkeypatch.setattr(rep, "PREPARE_RECEIPT", rt / "llm_spend_report_prepare_last.json")
    monkeypatch.setattr(rep, "cc_link", lambda: "")
    state = {"usd": 0.42}
    monkeypatch.setattr(rep.llm_spend, "build_report", lambda period, **k: _report(state["usd"]))
    sent: list[str] = []
    fake = type(sys)("telegram_alert")
    fake.send_telegram = lambda text, **kw: sent.append(text) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    return {"root": tmp_path, "rt": rt, "sent": sent, "state": state}


def _files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def _forbid(monkeypatch, *names):
    calls = []
    for name in names:
        monkeypatch.setattr(rep, name, lambda *a, _n=name, **k: calls.append(_n) or pytest.fail(f"{_n} reached"))
    return calls


def test_dry_run_writes_nothing_sends_nothing_and_never_reaches_prepare_or_send(env, monkeypatch, capsys):
    calls = _forbid(monkeypatch, "prepare", "send")
    import lib.lane_last_receipt as llr

    monkeypatch.setattr(llr, "write_lane_receipt", lambda *a, **k: pytest.fail("receipt reached"))
    assert rep.main(["--period", "daily", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run — nothing written, nothing sent" in out and '"would_send": true' in out
    assert env["sent"] == [] and calls == []
    assert _files(env["root"]) == []


def test_dry_run_reports_the_real_state_mutation_tested(env, capsys):
    rep.main(["--period", "daily", "--dry-run"])
    first = capsys.readouterr().out
    env["state"]["usd"] = 3.75  # the underlying spend changes -> the report changes with it
    env["rt"].mkdir(parents=True)
    rep.LEDGER.write_text(json.dumps({"daily:2026-10-08": "2026-10-08T11:05:00+00:00"}))
    rep.main(["--period", "daily", "--dry-run"])
    second = capsys.readouterr().out
    assert first != second
    assert "$3.75" in second and '"would_send": false' in second and "2026-10-08T11:05:00" in second
    assert _files(env["root"]) == ["data/runtime/llm_spend_report_sent.json"]  # only what the test wrote


def test_source_order_dry_run_branch_returns_before_any_write():
    src = inspect.getsource(rep.main)
    i_dry = src.index("if args.dry_run:")
    assert src.index("continue", i_dry) < src.index("prepare(period") < src.index("send(period")
    assert "write_lane_receipt" not in inspect.getsource(rep.dry_run)
    assert "write_text" not in inspect.getsource(rep.dry_run)


def test_prepare_writes_the_artifact_and_receipt_and_never_sends(env):
    assert rep.main(["--period", "weekly", "--prepare"]) == 0
    assert env["sent"] == []
    art = json.loads((env["rt"] / "llm_spend_report_prepared_weekly.json").read_text())
    assert art["schema"] == "LlmSpendReportMessage@v1" and art["key"] == "weekly:2026-10-08"
    assert "Weekly AI &amp; search spend" in art["text"] and art["already_sent_at"] is None
    rc = json.loads((env["rt"] / "llm_spend_report_prepare_last.json").read_text())
    assert rc["schema"] == "LaneRunReceipt@v1" and rc["status"] == "ok" and rc["ok_at"] == rc["finished_at"]
    assert not rep.LEDGER.exists()  # preparing is not sending


def test_send_path_unchanged_once_per_key_and_receipt_gains_ok_at(env):
    assert rep.main(["--period", "daily", "--send"]) == 0
    assert rep.main(["--period", "daily", "--send"]) == 0
    assert len(env["sent"]) == 1
    rc = json.loads((env["rt"] / "llm_spend_report_last_daily.json").read_text())
    assert rc["sent"] is True and rc["ok_at"] == rc["ran_at"] and rc["schema"] == "LlmSpendReportRun@v1"


def test_failed_send_exits_2_and_carries_ok_at(env):
    assert rep.main(["--period", "daily", "--send"]) == 0
    ok_at = json.loads((env["rt"] / "llm_spend_report_last_daily.json").read_text())["ok_at"]
    rep.LEDGER.unlink()
    sys.modules["telegram_alert"].send_telegram = lambda text, **kw: False
    assert rep.main(["--period", "daily", "--send"]) == 2
    rc = json.loads((env["rt"] / "llm_spend_report_last_daily.json").read_text())
    assert rc["sent"] is False and rc["ok_at"] == ok_at


@pytest.mark.parametrize(
    "when, expected",
    [
        (datetime(2026, 10, 9, 11, 5, tzinfo=timezone.utc), ["daily"]),  # Fri
        (datetime(2026, 10, 12, 11, 5, tzinfo=timezone.utc), ["daily", "weekly"]),  # Mon
        (datetime(2026, 10, 1, 11, 5, tzinfo=timezone.utc), ["daily", "monthly"]),  # Thu the 1st
        (datetime(2027, 2, 1, 12, 5, tzinfo=timezone.utc), ["daily", "weekly", "monthly"]),  # Mon the 1st
        (datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc), ["daily", "weekly"]),  # Mon 22:00 ET = Tue UTC
    ],
)
def test_period_auto_matches_the_crontab_days_in_eastern_time(when, expected):
    assert rep.due_periods(when) == expected


def test_auto_dry_run_covers_every_due_period(env, monkeypatch, capsys):
    monkeypatch.setattr(rep, "due_periods", lambda now=None: ["daily", "weekly", "monthly"])
    assert rep.main(["--period", "auto", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.count("dry run — nothing written") == 3
    assert _files(env["root"]) == []


def test_send_prepare_and_dry_run_are_mutually_exclusive(env):
    with pytest.raises(SystemExit):
        rep.main(["--period", "daily", "--send", "--dry-run"])


def test_ledger_and_receipts_resolve_under_the_state_root_not_the_checkout():
    src = Path(rep.__file__).read_text(encoding="utf-8")
    assert 'PROJECT_ROOT / "data" / "runtime"' not in src
    assert "state_root()" in src and "TRADEAI_STATE_ROOT" in src


def test_proposed_allowlist_argv_is_dispatcher_eligible_and_send_is_not():
    from tests.test_agents_policy_4_1_0_amendment import dispatcher_eligible

    prep = {
        "lane_id": "llm-spend-report",
        "command": ["$PY", "scripts/llm_spend_report.py", "--period", "auto"],
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--prepare"],
    }
    assert dispatcher_eligible(prep) == (True, "ok")
    send = dict(prep, live_arg=["--send"])
    ok, why = dispatcher_eligible(send)
    assert not ok and "send" in why
