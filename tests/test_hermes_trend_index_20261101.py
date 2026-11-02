"""The Hermes trend index: one point per UTC day, newest snapshot, parsed at most once.

Regression for the 2026-11-01 route sweep: GET /api/v2/hermes/outcome-bus/history took 75-95 s because
``load_outcome_bus_trend`` and ``load_universe_trend`` parsed every snapshot on every request (134 outcome files of up
to 22 MB = 1.7 GB; 1,100 universe files = 967 MB).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib import hermes_trend_index as H  # noqa: E402

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, ts: str, *, symbols: int = 1) -> None:
    path.write_text(json.dumps({"generated_at": ts, "run_id": path.name, "symbols": [{} for _ in range(symbols)]}))


def _point(snap: dict, ts: datetime) -> dict:
    return {
        "at": ts.isoformat(),
        "day": ts.strftime("%Y-%m-%d"),
        "run_id": snap.get("run_id"),
        "n": len(snap.get("symbols") or []),
    }


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    hist = tmp_path / "hist"
    hist.mkdir()
    return hist, tmp_path / "trend_index" / "x.json", tmp_path / "current.json"


def test_one_point_per_day_newest_snapshot_and_window(tmp_path):
    hist, idx, cur = _paths(tmp_path)
    _write(hist / "outcome_bus_2026-10-30T1000_a.json", "2026-10-30T10:00:00+00:00")
    _write(hist / "outcome_bus_2026-10-30T2200_b.json", "2026-10-30T22:00:00+00:00", symbols=2)
    _write(hist / "outcome_bus_2026-10-31T0900_c.json", "2026-10-31T09:00:00+00:00", symbols=3)
    _write(hist / "outcome_bus_2026-09-01T0900_old.json", "2026-09-01T09:00:00+00:00", symbols=9)
    _write(cur, "2026-10-31T12:00:00+00:00", symbols=4)

    pts = H.daily_points(
        history_dir=hist, prefix="outcome_bus_", days=7, point=_point, index_path=idx, current=cur, now=NOW
    )
    assert [p["day"] for p in pts] == ["2026-10-30", "2026-10-31"]
    assert pts[0]["n"] == 2  # the 22:00 snapshot, not the 10:00 one
    assert pts[1]["n"] == 4  # the current file is newer than the 09:00 history file on the same day
    assert all(p["day"] >= "2026-10-25" for p in pts)


def test_second_call_reuses_the_index_and_reparses_only_a_changed_file(tmp_path, monkeypatch):
    hist, idx, cur = _paths(tmp_path)
    f1 = hist / "outcome_bus_2026-10-30T1000_a.json"
    f2 = hist / "outcome_bus_2026-10-31T0900_c.json"
    _write(f1, "2026-10-30T10:00:00+00:00")
    _write(f2, "2026-10-31T09:00:00+00:00", symbols=3)

    calls: list[str] = []
    original = H._parse

    def spy(path: Path):
        calls.append(path.name)
        return original(path)

    monkeypatch.setattr(H, "_parse", spy)

    kwargs = dict(history_dir=hist, prefix="outcome_bus_", days=7, point=_point, index_path=idx, current=None, now=NOW)
    first = H.daily_points(**kwargs)
    parsed_first = len(calls)
    assert parsed_first == 2 and [p["n"] for p in first] == [1, 3]

    second = H.daily_points(**kwargs)
    assert len(calls) == parsed_first, "an unchanged index must not re-parse any snapshot"
    assert [p["day"] for p in second] == [p["day"] for p in first]

    _write(f2, "2026-10-31T09:00:00+00:00", symbols=5)  # size changes
    third = H.daily_points(**kwargs)
    assert len(calls) == parsed_first + 1, "only the changed snapshot is re-parsed"
    assert third[-1]["n"] == 5


def test_a_snapshot_outside_the_window_is_never_opened(tmp_path, monkeypatch):
    hist, idx, cur = _paths(tmp_path)
    old = hist / "outcome_bus_2026-01-01T0900_old.json"
    _write(old, "2026-01-01T09:00:00+00:00")

    def boom(path: Path):
        raise AssertionError(f"opened an out-of-window snapshot: {path.name}")

    monkeypatch.setattr(H, "_parse", boom)
    pts = H.daily_points(
        history_dir=hist, prefix="outcome_bus_", days=7, point=_point, index_path=idx, current=None, now=NOW
    )
    assert pts == []


def test_the_index_is_pruned_to_the_current_window(tmp_path):
    hist, idx, cur = _paths(tmp_path)
    _write(hist / "outcome_bus_2026-10-31T0900_c.json", "2026-10-31T09:00:00+00:00")
    kwargs = dict(history_dir=hist, prefix="outcome_bus_", point=_point, index_path=idx, current=None)
    H.daily_points(days=7, now=NOW, **kwargs)
    _write(hist / "outcome_bus_2026-10-31T0900_c.json", "2026-10-31T09:00:00+00:00", symbols=2)
    H.daily_points(days=1, now=NOW + timedelta(days=3), **kwargs)
    doc = json.loads(idx.read_text())
    assert set(doc["files"]) <= {"outcome_bus_2026-10-31T0900_c.json"}


def test_a_snapshot_without_a_timestamp_in_its_name_is_still_considered(tmp_path):
    hist, idx, cur = _paths(tmp_path)
    (hist / "outcome_bus_latest.json").write_text(
        json.dumps({"generated_at": "2026-10-31T09:00:00+00:00", "run_id": "x", "symbols": [{}]})
    )
    pts = H.daily_points(
        history_dir=hist, prefix="outcome_bus_", days=7, point=_point, index_path=idx, current=None, now=NOW
    )
    assert [p["day"] for p in pts] == ["2026-10-31"]
