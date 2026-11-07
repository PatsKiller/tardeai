"""Jobs & n8n: multi-select status/quality, last-run window (?ran=) and sort (?sort=) on GET /api/v2/jobs-history.

Operator 2026-11-06: "It needs to be able to sort and filter, multi-select by quality also. All of those pages need to
be able to filter by last run, sort, etc." Synthetic lanes only (public repo).
"""
from __future__ import annotations

import pytest

from scripts.lib import jobs_history as J

NOW = "2026-11-07T12:00:00Z"


def _row(lane_id, *, status="ok", grade="GOOD", finished=None, success=None, missed=0, title=None):
    return {
        "lane_id": lane_id, "job": lane_id, "title": title or lane_id, "scheduler": "n8n", "state": "ACTIVE",
        "status": status, "status_reason": None, "missed_count": missed, "missed_gap": None, "fix_count": 0,
        "last_fix": None, "history_sources": [], "history_gap": None, "category": None, "does": None, "breaks": None,
        "owner": None, "category_fallback": None, "category_key": "ops",
        "last_run": {"finished_at": finished, "started_at": finished} if finished else None,
        "last_success_at": success, "quality": {"grade": grade} if grade else None, "output": None,
        "cadence": {"expressions": [], "timezone": "UTC", "every_hours": 1, "market_days_only": False},
    }


ROWS = [
    _row("alpha", status="ok", grade="GOOD", finished="2026-11-07T11:30:00Z", title="Alpha"),            # 30 min
    _row("bravo", status="failed", grade="FAILED", finished="2026-11-07T02:00:00Z", title="Bravo"),     # 10 h
    _row("charlie", status="late", grade="DEGRADED", finished="2026-11-03T12:00:00Z", title="Charlie", missed=3),  # 4 d
    _row("delta", status="ok", grade="EMPTY", finished="2026-10-20T12:00:00Z", title="Delta"),          # 18 d
    _row("echo", status="not_measured", grade="UNPROVEN", finished=None, title="Echo"),                 # never
    _row("foxtrot", status="ok", grade=None, finished=None, success="2026-11-07T06:00:00Z", title="Foxtrot"),  # 6 h via success
]


@pytest.fixture
def q(monkeypatch):
    result = {"computed_at": NOW, "rows": [dict(r) for r in ROWS], "summary": {}, "categories": []}
    monkeypatch.setattr(J, "snapshot", lambda **kw: result)
    return lambda **query: J.get_jobs_history({"filter": "all", "limit": "200", **query})


def ids(out):
    return [r["lane_id"] for r in out["rows"]]


def test_quality_multi_select_is_or_and_echoed_as_list(q):
    out = q(quality="degraded,empty")
    assert set(ids(out)) == {"charlie", "delta"}
    assert out["qualities"] == ["DEGRADED", "EMPTY"] and out["quality"] == "DEGRADED,EMPTY"
    assert q(quality="good")["quality"] == "GOOD"  # single value keeps the old string echo


def test_status_multi_select_and_and_across_params(q):
    assert set(ids(q(status="failed,late"))) == {"bravo", "charlie"}
    out = q(status="ok,late", quality="good,degraded")
    assert set(ids(out)) == {"alpha", "charlie"} and out["statuses"] == ["ok", "late"]


def test_unknown_values_are_rejected(q):
    for bad in ({"quality": "good,OK"}, {"status": "ok,nope"}, {"ran": "2d"}, {"sort": "random"}):
        with pytest.raises(ValueError):
            q(**bad)


@pytest.mark.parametrize("ran,expected", [
    ("1h", {"alpha"}),
    ("24h", {"alpha", "bravo", "foxtrot"}),
    ("7d", {"alpha", "bravo", "charlie", "foxtrot"}),
    ("older", {"delta"}),
    ("never", {"echo"}),
])
def test_ran_windows(q, ran, expected):
    out = q(ran=ran)
    assert set(ids(out)) == expected and out["ran"] == ran


def test_last_run_falls_back_to_last_success():
    assert J.last_run_at(ROWS[5]).isoformat().startswith("2026-11-07T06:00")
    assert J.last_run_at(ROWS[4]) is None


def test_sorts(q):
    assert q()["sort"] == "attention" and ids(q())[0] == "bravo"  # default stays worst-first
    assert ids(q(sort="name")) == ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    assert ids(q(sort="last_run_desc")) == ["alpha", "foxtrot", "bravo", "charlie", "delta", "echo"]
    assert ids(q(sort="last_run_asc")) == ["delta", "charlie", "bravo", "foxtrot", "alpha", "echo"]  # never last
    assert ids(q(sort="quality"))[:5] == ["bravo", "delta", "charlie", "echo", "alpha"] and ids(q(sort="quality"))[-1] == "foxtrot"
    assert ids(q(sort="missed"))[0] == "charlie"


def test_sort_and_filter_combine_with_paging(q):
    out = J.get_jobs_history({"filter": "all", "ran": "7d", "sort": "last_run_asc", "limit": "2", "offset": "1"})
    assert ids(out) == ["bravo", "foxtrot"] and out["total"] == 4 and out["has_more"] is True
