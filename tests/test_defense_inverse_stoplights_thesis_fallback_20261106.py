"""THESIS safety net: a missing or stale defense projection is built in-process (2026-11-06).

The stoplights read THESIS from data/runtime/defense_engine_latest.json. When that file is missing or stale every
trigger was UNKNOWN (AMBER) even though the inputs to build it were on hand. evaluate_all now takes an optional
builder (the CLI passes the same read-only builder defense_engine_build.py runs); the result is labelled
thesis_source.source == "built_in_process" and is written to the projection path only when not dry_run.

Hermetic: the fixture from test_stoplight_dry_run_writes_nothing_20261031 (synthetic bars/holdings, strict fake
connection); the builder is injected, so no DB, no Schwab, no Telegram.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import defense_inverse_stoplights as dis  # noqa: E402
from test_stoplight_dry_run_writes_nothing_20261031 import FakeConn, lane  # noqa: E402,F401  (fixture)


def _projection(now=None, trigger=True):
    return {"schema": "DefenseProjection@v1", "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
            "hedge_readiness": {"inverse_triggers": {"QQQ": {"trigger": trigger, "exposure_pct": 50.0}}}}


def _proj_path(root):
    return root.joinpath(*dis.ENGINE_REL)


def _thesis(out, bench="QQQ"):
    return [c["lights"]["THESIS"] for c in out["candidates"] if c["bench"] == bench][0]


def test_missing_projection_is_built_in_process_and_used(lane):
    calls = []
    conn = FakeConn(strict=True)
    out = dis.evaluate_all(conn.cursor(), conn, notify=False, dry_run=True,
                           build_projection=lambda now: calls.append(now) or _projection(now))
    ts = out["thesis_source"]
    assert len(calls) == 1
    assert ts["source"] == "built_in_process" and ts["unknown_reason"] is None
    assert ts["file_reason"] == "defense engine projection not on file"
    # the built trigger drives THESIS exactly as the same projection on file does
    _proj_path(lane).parent.mkdir(parents=True)
    _proj_path(lane).write_text(json.dumps(_projection()))
    conn2 = FakeConn(strict=True)
    ref = dis.evaluate_all(conn2.cursor(), conn2, notify=False, dry_run=True)
    assert ref["thesis_source"]["source"] == "file"
    assert _thesis(out)["state"] == _thesis(ref)["state"]


def test_dry_run_never_writes_the_projection(lane):
    conn = FakeConn(strict=True)
    out = dis.evaluate_all(conn.cursor(), conn, notify=False, dry_run=True, build_projection=_projection)
    assert out["thesis_source"]["source"] == "built_in_process"
    assert out["thesis_source"]["projection_written"] is False
    assert not _proj_path(lane).exists()


def test_live_run_writes_the_built_projection(lane):
    conn = FakeConn(strict=False)
    out = dis.evaluate_all(conn.cursor(), conn, notify=False, dry_run=False, build_projection=_projection)
    assert out["thesis_source"]["projection_written"] is True
    doc = json.loads(_proj_path(lane).read_text())
    assert doc["schema"] == "DefenseProjection@v1"


def test_stale_file_triggers_the_build_fresh_file_does_not(lane):
    _proj_path(lane).parent.mkdir(parents=True)
    _proj_path(lane).write_text(json.dumps(_projection(datetime.now(timezone.utc) - timedelta(hours=200))))
    calls = []
    r = dis.resolve_thesis_inputs(build=lambda now: calls.append(1) or _projection(now), dry_run=True)
    assert calls and r["source"] == "built_in_process" and "h old" in r["file_reason"]
    _proj_path(lane).write_text(json.dumps(_projection()))
    calls.clear()
    r = dis.resolve_thesis_inputs(build=lambda now: calls.append(1) or _projection(now), dry_run=True)
    assert calls == [] and r["source"] == "file" and r["unknown_reason"] is None


def test_build_failure_stays_amber_with_the_reason(lane):
    def boom(now):
        raise RuntimeError("db down")
    conn = FakeConn(strict=True)
    out = dis.evaluate_all(conn.cursor(), conn, notify=False, dry_run=True, build_projection=boom)
    ts = out["thesis_source"]
    assert ts["source"] == "file" and "db down" in ts["build_error"]
    assert "in-process build failed" in ts["unknown_reason"]
    assert _thesis(out)["state"] == "AMBER"
    assert not _proj_path(lane).exists()


def test_no_builder_keeps_the_old_behaviour(lane):
    conn = FakeConn(strict=True)
    out = dis.evaluate_all(conn.cursor(), conn, notify=False, dry_run=True)
    assert out["thesis_source"]["source"] == "file"
    assert out["thesis_source"]["unknown_reason"] == "defense engine projection not on file"


def test_cli_builder_is_the_lane_builder(monkeypatch, tmp_path):
    import defense_engine_build as deb
    seen = {}
    monkeypatch.setattr(dis, "ROOT", tmp_path)
    monkeypatch.setattr(deb, "build", lambda root, now=None: seen.update(root=root, now=now) or {"ok": 1})
    now = datetime.now(timezone.utc)
    assert dis._build_projection_in_process(now) == {"ok": 1}
    assert seen == {"root": tmp_path, "now": now}
