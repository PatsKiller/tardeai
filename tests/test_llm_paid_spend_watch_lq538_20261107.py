"""LQ-20261107-538 Part 3: the paid-spend watch alerts once when paid spend tops the line on too many days.

Operator directive 2026-11-07 21:08 ET: "Leave the cap at 1.50. Alert when it goes over .75, 3 times in a week."
"""

from __future__ import annotations

import ast
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts import llm_paid_spend_watch as W

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 7)
# 2026-11-07 22:00 ET == 2026-11-08 03:00 UTC: the ET day is still the 7th.
NOW = datetime(2026, 11, 8, 3, 0, tzinfo=timezone.utc)


def _cfg(tmp_path: Path, **over) -> Path:
    watch = {"process_id": "due_diligence_questions", "source": "llm_consumption_log", "day_threshold_usd": 0.75,
             "days_over": 3, "window_days": 7, "dedupe_days": 7, "alert_class": "llm_paid_spend_watch"}
    watch.update(over)
    path = tmp_path / "alerts.json"
    path.write_text(json.dumps({"schema": W.CONFIG_SCHEMA, "timezone": "America/New_York", "watches": [watch]}))
    return path


class FakeCursor:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def execute(self, sql, params):
        self.log.append((sql, dict(params)))

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, by_day: dict[str, float]):
        self.rows = [(date.fromisoformat(k), v, 1) for k, v in sorted(by_day.items())]
        self.log: list = []
        self.closed = False

    def cursor(self):
        return FakeCursor(self.rows, self.log)

    def close(self):
        self.closed = True


def _run(tmp_path, by_day, *, dry_run=False, delivered=True, now=NOW, state=None):
    sent: list[dict] = []
    receipts: list[dict] = []

    def deliver(event):
        sent.append(event)
        return {"alert_class": event["alert_class"], "delivered": delivered, "receipts": []}

    state_file = state or tmp_path / "state.json"
    conn = FakeConn(by_day)
    code, report = W.run(dry_run=dry_run, config_path=_cfg(tmp_path), connect=lambda: conn, deliver=deliver,
                         now=now, state_file=state_file, write_receipt=lambda *a, **k: receipts.append(k),
                         emit=lambda s: None)
    return code, report, sent, receipts, state_file, conn


# ── the shipped config ────────────────────────────────────────────────────────────────────────────────────


def test_the_shipped_config_carries_the_operator_numbers():
    cfg = W.load_config(ROOT / W.CONFIG_REL)
    [watch] = [w for w in cfg["watches"] if w["process_id"] == "due_diligence_questions"]
    assert (watch["day_threshold_usd"], watch["days_over"], watch["window_days"]) == (0.75, 3, 7)
    assert cfg["timezone"] == "America/New_York"


def test_the_alert_class_is_in_the_critical_taxonomy_and_texts_stay_off():
    """Absent from the taxonomy, the hub refuses the event everywhere. Present but disabled, it sends email and the
    Critical chat and skips the text, which is what the directive asks until the operator says otherwise."""
    classes = json.loads((ROOT / "config/critical_text_classes.json").read_text())["classes"]
    cfg = W.load_config(ROOT / W.CONFIG_REL)
    for watch in cfg["watches"]:
        assert watch["alert_class"] in classes
        assert classes[watch["alert_class"]]["enabled"] is False


def test_the_registry_cap_is_the_operator_cap():
    reg = json.loads((ROOT / "config/llm_process_registry.json").read_text())
    [row] = [r for r in reg["processes"] if r.get("id") == "due_diligence_questions"]
    assert row["daily_cost_cap_usd"] == 1.50


def test_no_threshold_is_hardcoded_in_the_script():
    """The operator's numbers live in config. A numeric literal equal to one of them in the code is a second copy."""
    tree = ast.parse((ROOT / "scripts/llm_paid_spend_watch.py").read_text())
    numbers = {n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}
    assert not numbers & {0.75, 1.5, 3, 7}, numbers & {0.75, 1.5, 3, 7}


@pytest.mark.parametrize("over,reason", [
    ({"day_threshold_usd": 0}, "day_threshold_usd_must_be_positive"),
    ({"days_over": 8}, "days_over_exceeds_window"),
    ({"source": "llm_reservations"}, "source_unsupported"),
    ({"alert_class": ""}, "alert_class_missing"),
    ({"window_days": True}, "window_days_must_be_a_positive_integer"),
])
def test_a_bad_config_is_refused_not_guessed(tmp_path, over, reason):
    with pytest.raises(W.ConfigError) as exc:
        W.load_config(_cfg(tmp_path, **over))
    assert str(exc.value) == reason


# ── the measurement ───────────────────────────────────────────────────────────────────────────────────────


def test_the_query_excludes_free_oauth_and_groups_by_et_day(tmp_path):
    code, report, _sent, _r, _s, conn = _run(tmp_path, {})
    sql, params = conn.log[0]
    assert "COALESCE(metadata_json->>'billing', '') <> 'free_oauth'" in sql
    assert "AT TIME ZONE %(tz)s" in sql and params["tz"] == "America/New_York"
    assert (params["start"], params["end"]) == (date(2026, 11, 1), TODAY)
    assert report["et_today"] == "2026-11-07"
    assert code == 0 and conn.closed


def test_a_null_daily_row_fails_the_run_instead_of_reading_zero(tmp_path):
    class NullConn(FakeConn):
        def __init__(self):
            super().__init__({})
            self.rows = [(date(2026, 11, 5), None, 1)]

    receipts: list[dict] = []
    conn = NullConn()
    code, report = W.run(dry_run=False, config_path=_cfg(tmp_path), connect=lambda: conn, deliver=lambda e: {},
                         now=NOW, state_file=tmp_path / "s.json", write_receipt=lambda *a, **k: receipts.append(k),
                         emit=lambda s: None)
    assert code == 1 and report["error"] == "query:ValueError:paid_daily_row_incomplete:2026-11-05"
    assert receipts[0]["ok"] is False


def test_over_means_strictly_above_the_threshold():
    watch = {"process_id": "p", "day_threshold_usd": 0.75, "days_over": 3, "window_days": 7}
    daily = {date(2026, 11, d): {"paid_usd": v, "paid_calls": 1} for d, v in [(5, 0.75), (6, 0.7501), (7, 2.0)]}
    result = W.evaluate(watch, daily, TODAY)
    assert result["over_days"] == ["2026-11-06", "2026-11-07"]
    assert result["breach"] is False


def test_days_outside_the_window_do_not_count():
    watch = {"process_id": "p", "day_threshold_usd": 0.75, "days_over": 3, "window_days": 7}
    daily = {date(2026, 10, 31): {"paid_usd": 5.0, "paid_calls": 1}, date(2026, 11, 1): {"paid_usd": 1.0, "paid_calls": 1},
             date(2026, 11, 2): {"paid_usd": 1.0, "paid_calls": 1}}
    assert W.evaluate(watch, daily, TODAY)["over_count"] == 2


# ── the alert ─────────────────────────────────────────────────────────────────────────────────────────────


def test_two_days_over_does_not_alert(tmp_path):
    code, report, sent, _r, state, _c = _run(tmp_path, {"2026-11-03": 0.9, "2026-11-05": 1.2})
    assert code == 0 and sent == [] and report["watches"][0]["alert"] == "none"
    assert not state.exists()


def test_three_days_over_sends_one_alert_and_stamps_dedupe(tmp_path):
    code, report, sent, receipts, state, _c = _run(
        tmp_path, {"2026-11-02": 0.8, "2026-11-04": 1.1, "2026-11-07": 0.76, "2026-11-06": 0.2})
    assert code == 0 and len(sent) == 1
    event = sent[0]
    assert event["alert_class"] == "llm_paid_spend_watch"
    assert "3 of the last 7 days" in event["what"] and "2026-11-04 $1.10" in event["what"]
    assert event["action"]
    saved = json.loads(state.read_text())
    assert saved["watches"]["due_diligence_questions"]["last_alert_et_day"] == "2026-11-07"
    assert receipts and receipts[0]["ok"] is True and receipts[0]["produced_count"] == 1


def test_a_breach_inside_the_dedupe_window_alerts_once(tmp_path):
    days = {"2026-11-02": 0.8, "2026-11-04": 1.1, "2026-11-07": 0.76}
    _run(tmp_path, days)
    later = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)  # 6 days on: still inside
    days_later = {**days, "2026-11-08": 1.0, "2026-11-09": 1.0, "2026-11-10": 1.0}
    code, report, sent, _r, _s, _c = _run(tmp_path, days_later, now=later)
    assert code == 0 and sent == []
    assert report["watches"][0]["alert"] == "deduped"
    assert report["watches"][0]["covered_by_alert_on"] == "2026-11-07"


def test_a_breach_after_the_dedupe_window_alerts_again(tmp_path):
    _run(tmp_path, {"2026-11-02": 0.8, "2026-11-04": 1.1, "2026-11-07": 0.76})
    later = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)  # 7 days on: a new window
    code, _report, sent, _r, state, _c = _run(
        tmp_path, {"2026-11-10": 1.0, "2026-11-12": 1.0, "2026-11-14": 1.0}, now=later)
    assert code == 0 and len(sent) == 1
    assert json.loads(state.read_text())["watches"]["due_diligence_questions"]["last_alert_et_day"] == "2026-11-14"


def test_an_undelivered_alert_is_not_stamped_and_fails_the_run(tmp_path):
    code, report, sent, receipts, state, _c = _run(
        tmp_path, {"2026-11-02": 0.8, "2026-11-04": 1.1, "2026-11-07": 0.76}, delivered=False)
    assert code == 1 and len(sent) == 1 and report["watches"][0]["alert"] == "undelivered"
    assert not state.exists(), "an alert that reached nobody must be retried, not deduped"
    assert receipts[0]["ok"] is False


def test_unreadable_dedupe_state_fails_toward_alerting(tmp_path):
    bad = tmp_path / "state.json"
    bad.write_text("{not json")
    code, _report, sent, _r, _s, _c = _run(
        tmp_path, {"2026-11-02": 0.8, "2026-11-04": 1.1, "2026-11-07": 0.76}, state=bad)
    assert code == 0 and len(sent) == 1


def test_dry_run_sends_nothing_and_writes_nothing(tmp_path, capsys):
    code, report, sent, receipts, state, _c = _run(
        tmp_path, {"2026-11-02": 0.8, "2026-11-04": 1.1, "2026-11-07": 0.76}, dry_run=True)
    assert code == 0 and sent == [] and receipts == []
    assert report["watches"][0]["alert"] == "would_send"
    assert not state.exists()
    assert capsys.readouterr().out.startswith("DRY-RUN ")


def test_a_db_failure_is_a_failed_run_not_a_quiet_zero(tmp_path):
    def boom():
        raise ConnectionError("down")

    receipts: list[dict] = []
    code, report = W.run(dry_run=False, config_path=_cfg(tmp_path), connect=boom, deliver=lambda e: {},
                         now=NOW, state_file=tmp_path / "s.json", write_receipt=lambda *a, **k: receipts.append(k),
                         emit=lambda s: None)
    assert code == 1 and report["error"] == "db_connect:ConnectionError"
    assert receipts[0]["ok"] is False


# ── lane staging ──────────────────────────────────────────────────────────────────────────────────────────


def test_the_allowlist_entry_is_staged_not_live():
    lanes = {e["lane_id"]: e for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    entry = lanes[W.LANE_ID]
    assert entry["live_arg"] is None
    assert entry["dry_run_arg"] == ["--dry-run"]
    assert entry["command"][-1] == "scripts/llm_paid_spend_watch.py"
    assert entry["output_signal"] == f"data/runtime/{W.LANE_ID}_last.json"
