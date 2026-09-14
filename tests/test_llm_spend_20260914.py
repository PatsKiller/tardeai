"""Spend truth, 2026-09-14. Offline: SQL is captured, never executed against a database.

Operator: "it's a $7 limit, but we never go above 7 cents or 50 cents. Something's not adding up." Then,
approved: caps count actual spend; a durable $2.00/day cap; daily, weekly and monthly spend texts with
the peak/off-peak split.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import llm_spend as s  # noqa: E402

COVERS = ["scripts/lib/llm_spend.py", "scripts/llm_spend_report.py"]
MON_1500_ET = datetime(2026, 9, 14, 19, 0, tzinfo=timezone.utc)


# ── periods follow ET calendar days ─────────────────────────────────────────

def test_period_bounds_are_et_calendar_days():
    start, end, label = s.period_bounds("yesterday", now=MON_1500_ET)
    assert start.isoformat() == "2026-09-13T04:00:00+00:00" and end.isoformat() == "2026-09-14T04:00:00+00:00"
    lw_start, lw_end, _ = s.period_bounds("last_week", now=MON_1500_ET)
    assert lw_start.date().isoformat() == "2026-09-07" and lw_end.date().isoformat() == "2026-09-14"
    lm_start, lm_end, lm_label = s.period_bounds("last_month", now=MON_1500_ET)
    assert lm_label == "August 2026" and lm_start.date().isoformat() == "2026-08-01"
    with pytest.raises(ValueError):
        s.period_bounds("fortnight", now=MON_1500_ET)


def test_peak_sql_uses_the_official_deepseek_windows_on_weekdays_only():
    from scripts.lib.deepseek_offpeak import DEEPSEEK_PEAK_UTC
    sql = s.peak_sql()
    assert "ISODOW" in sql and "BETWEEN 1 AND 5" in sql
    for a, b in DEEPSEEK_PEAK_UTC:
        assert f">= {a}" in sql and f"< {b}" in sql


@pytest.mark.parametrize("lane,model,cost,expected", [
    ("fast", "deepseek-v4-flash", 0.001, "DeepSeek (metered)"),
    ("grok", None, 0.0, "Grok (free OAuth)"),
    ("chatgpt", None, 0.0, "ChatGPT (free OAuth)"),
    ("local", "gemma3:12b", 0.0, "Local model (free)"),
])
def test_provider_labels(lane, model, cost, expected):
    assert s.provider_of(lane, model, cost) == expected


def test_synthetic_rows_are_excluded_including_caprace():
    f = s._synthetic_filter()
    assert "caprace" in f and "test" in f and "%%" in f  # escaped for bound-parameter SQL


# ── the report ──────────────────────────────────────────────────────────────

def _fake_db(sql, params=None):
    if "FROM llm_process_config" in sql:
        return [{"process_id": "advisory_desk_opinion", "category": "AdvisoryDesk", "mode": "automated",
                 "daily_soft_cap": 600, "daily_cost_cap_usd": 1.25}]
    if "FROM llm_cost_reservations" in sql:
        return [{"usd": 0.41}]
    if "GROUP BY model_lane, model_name" in sql:
        return [{"model_lane": "fast", "model_name": "deepseek-v4-flash", "calls": 469, "usd": 0.3825,
                 "tokens_in": 900000, "tokens_out": 300000, "usd_peak": 0.05},
                {"model_lane": "grok", "model_name": None, "calls": 744, "usd": 0, "tokens_in": 0, "tokens_out": 0, "usd_peak": 0}]
    if "GROUP BY process_id, trigger_mode" in sql:
        return [{"process_id": "advisory_desk_opinion", "process_name": "Advisory Desk Per-Row Opinion", "trigger_mode": "automated",
                 "calls": 469, "failures": 2, "usd": 0.3825, "tokens_in": 900000, "tokens_out": 300000,
                 "calls_peak": 98, "usd_peak": 0.0515, "models": "deepseek-v4-flash", "last_call": "2026-09-13 23:59:00"},
                {"process_id": "operator_desk", "process_name": "Operator desk", "trigger_mode": "manual",
                 "calls": 12, "failures": 0, "usd": 0.026, "tokens_in": 40000, "tokens_out": 9000,
                 "calls_peak": 0, "usd_peak": 0, "models": "deepseek-flash", "last_call": "2026-09-13 20:00:00"}]
    return [{"calls": 1358, "paid_calls": 546, "failures": 8, "usd": 0.4085, "tokens_in": 1255610, "tokens_out": 442904,
             "reasoning_tokens": 0, "cache_hit_tokens": 0, "usd_peak": 0.0563, "calls_peak": 119}]


def test_report_separates_real_counted_peak_and_scheduled(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "CAP_FILE", tmp_path / "cap.env")
    (tmp_path / "cap.env").write_text("LLM_GLOBAL_DAILY_USD_CAP=2.00\n")
    monkeypatch.setattr(s, "SEARCH_BUDGET", tmp_path / "search_budget.json")
    (tmp_path / "search_budget.json").write_text(json.dumps({"providers": {"brave": {"caller_daily": {
        "2026-09-13": {"governed_research_producer": 25}, "2026-09-01": {"x": 9}}}}}))
    r = s.build_report("yesterday", now=MON_1500_ET, db_query=_fake_db)
    t = r["totals"]
    assert t["usd"] == pytest.approx(0.4085) and t["usd_offpeak"] == pytest.approx(0.4085 - 0.0563)
    assert r["counted_by_caps_usd"] == pytest.approx(0.41) and r["global_cap_usd_per_day"] == 2.0
    kinds = {p["process_id"]: p["kind"] for p in r["by_process"]}
    assert kinds == {"advisory_desk_opinion": "scheduled", "operator_desk": "ad hoc"}
    assert [x["process_id"] for x in r["scheduled_on_peak"]] == ["advisory_desk_opinion"]
    assert r["by_provider"][0]["provider"] == "DeepSeek (metered)"
    assert r["brave"]["requests"] == 25


def test_the_telegram_text_names_real_spend_peak_and_scheduled_on_peak(tmp_path, monkeypatch):
    import llm_spend_report as rep
    monkeypatch.setattr(s, "CAP_FILE", tmp_path / "cap.env")
    monkeypatch.setattr(s, "SEARCH_BUDGET", tmp_path / "absent.json")
    monkeypatch.setattr(rep, "cc_link", lambda: "https://cc.example/v3/consumption")
    r = s.build_report("yesterday", now=MON_1500_ET, db_query=_fake_db)
    text = rep.format_report(r, cadence="daily")
    assert "Daily AI &amp; search spend" in text and "Real spend <b>$0.4085</b>" in text
    assert "Off-peak" in text and "Peak" in text and "Scheduled work ran on peak" in text
    assert "🗓 scheduled" in text and "👤 ad hoc" in text
    assert '<a href="https://cc.example/v3/consumption">' in text


def test_a_period_is_sent_once(tmp_path, monkeypatch):
    import llm_spend_report as rep
    sent = []
    fake = type(sys)("telegram_alert")
    fake.send_telegram = lambda text, **kw: sent.append(kw) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(rep, "LEDGER", tmp_path / "sent.json")
    monkeypatch.setattr(rep, "RECEIPT", tmp_path / "last_{cadence}.json")
    monkeypatch.setattr(rep.llm_spend, "build_report", lambda period, **k: s.build_report(period, now=MON_1500_ET, db_query=_fake_db))
    monkeypatch.setattr(rep, "cc_link", lambda: "")
    monkeypatch.setattr(sys, "argv", ["llm_spend_report.py", "--period", "weekly", "--send"])
    assert rep.main() == 0 and rep.main() == 0
    assert len(sent) == 1 and sent[0]["bypass_router"] is True
    assert json.loads((tmp_path / "last_weekly.json").read_text())["sent"] is True


# ── caps count actual spend ─────────────────────────────────────────────────

class _Cur:
    def __init__(self, row):
        self.row, self.sql = row, None

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return self.row


def test_calibrated_projection_uses_measured_cost_and_never_exceeds_the_worst_case():
    import scripts.lib.llm_consumption as lc
    measured = lc.calibrated_projected_usd("advisory_desk_opinion", 0.00693, cur=_Cur((15177, 0.000296)))
    assert measured["projected_usd"] == pytest.approx(0.000444) and measured["basis"].startswith("p90_settled")
    capped = lc.calibrated_projected_usd("big", 0.00693, cur=_Cur((500, 0.02)))
    assert capped["projected_usd"] == pytest.approx(0.00693)
    unmeasured = lc.calibrated_projected_usd("new_lane", 0.00693, cur=_Cur((3, 0.0001)))
    assert unmeasured["projected_usd"] == pytest.approx(0.00693) and unmeasured["basis"] == "worst_case_unmeasured"


def test_the_cap_race_test_writes_ids_the_ledger_already_excludes():
    import scripts.lib.llm_consumption as lc
    src = (ROOT / "tests" / "test_deepseek_cost_reservation.py").read_text(encoding="utf-8")
    assert 'f"caprace_' not in src and 'f"test_caprace_' in src
    assert lc.is_test_process_id("test_caprace_ga_1789010035654") and not lc.is_test_process_id("advisory_desk_opinion")
