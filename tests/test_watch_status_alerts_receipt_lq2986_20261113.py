"""LQ-20261107-2986: Alerts reads the evaluator's real last-run receipt (watch-alerts-eval_last.json), not a table that
does not exist. Synthetic receipts under a scratch TRADEAI_STATE_ROOT."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import watch_status_live as wsl  # noqa: E402

NOW = datetime(2026, 11, 13, 17, 0, 0, tzinfo=timezone.utc)
RTH = lambda _n: True  # noqa: E731
OFF = lambda _n: False  # noqa: E731


def _q(sql, params=None):
    return [{"as_of": NOW - timedelta(seconds=60)}]


def _receipt(tmp_path, monkeypatch, doc=None, raw=None):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    d = tmp_path / "data" / "runtime"
    d.mkdir(parents=True)
    if doc is not None:
        (d / "watch-alerts-eval_last.json").write_text(json.dumps(doc), encoding="utf-8")
    if raw is not None:
        (d / "watch-alerts-eval_last.json").write_text(raw, encoding="utf-8")


def _alerts(out):
    return {i["id"]: i for i in out["inputs"]}["alerts"]


def _iso(sec_ago):
    return (NOW - timedelta(seconds=sec_ago)).isoformat()


def test_a_fresh_receipt_makes_alerts_ok_with_its_age(tmp_path, monkeypatch):
    _receipt(tmp_path, monkeypatch, {"status": "ok", "ok_at": _iso(90), "finished_at": _iso(90)})
    a = _alerts(wsl.compute(_q, NOW, session_fn=RTH))
    assert a["state"] == "OK" and a["age_s"] == 90 and a["as_of"] and a["needs_backend"] is False


def test_an_old_receipt_is_stale_not_ok(tmp_path, monkeypatch):
    _receipt(tmp_path, monkeypatch, {"status": "ok", "ok_at": _iso(1201)})
    a = _alerts(wsl.compute(_q, NOW, session_fn=RTH))
    assert a["state"] == "STALE" and a["age_s"] == 1201
    assert _alerts(wsl.compute(_q, NOW, session_fn=OFF))["state"] == "OK"      # 26 h off-session


def test_a_failed_latest_run_is_graded_on_the_last_successful_run(tmp_path, monkeypatch):
    _receipt(tmp_path, monkeypatch, {"status": "failed", "ok_at": _iso(7200), "finished_at": _iso(30)})
    a = _alerts(wsl.compute(_q, NOW, session_fn=RTH))
    assert a["state"] == "STALE" and a["age_s"] == 7200                         # not made fresh by a failing run


def test_missing_receipt_stays_unknown(tmp_path, monkeypatch):
    _receipt(tmp_path, monkeypatch)
    out = wsl.compute(_q, NOW, session_fn=RTH)
    a = _alerts(out)
    assert a["state"] == "UNKNOWN" and a["needs_backend"] is True and "does not exist" in a["reason"]
    assert out["verdict"] == "UNKNOWN"


def test_receipt_without_ok_at_or_unreadable_stays_unknown(tmp_path, monkeypatch):
    _receipt(tmp_path, monkeypatch, {"status": "failed", "finished_at": _iso(30)})
    assert _alerts(wsl.compute(_q, NOW, session_fn=RTH))["state"] == "UNKNOWN"
    (tmp_path / "data" / "runtime" / "watch-alerts-eval_last.json").write_text("{not json", encoding="utf-8")
    a = _alerts(wsl.compute(_q, NOW, session_fn=RTH))
    assert a["state"] == "UNKNOWN" and "unreadable" in a["reason"]


def test_a_future_ok_at_is_unknown(tmp_path, monkeypatch):
    _receipt(tmp_path, monkeypatch, {"ok_at": (NOW + timedelta(hours=2)).isoformat()})
    assert _alerts(wsl.compute(_q, NOW, session_fn=RTH))["state"] == "UNKNOWN"


def test_alerts_issues_no_sql_and_never_names_the_missing_table():
    src = (ROOT / "scripts" / "lib" / "watch_status_live.py").read_text(encoding="utf-8")
    assert "to_regclass" not in src and "FROM watch_alerts_eval_runs" not in src
