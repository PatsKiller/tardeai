"""Archive rotation for advisory_kb_lessons.jsonl — tmp dirs only, never live state."""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.advisory import kb_lessons_retention as ret  # noqa: E402

NOW = datetime(2026, 10, 9, 22, 0, tzinfo=timezone.utc)


def _cfg(**over):
    cfg = ret.load_config()
    cfg.update(over)
    return cfg


def _row(lid, days_ago, **extra):
    ts = (NOW - timedelta(days=days_ago)).isoformat()
    return {"id": lid, "ts": ts, "status": "ratified", **extra}


def _write(path: Path, rows, raw_lines=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        for line in raw_lines:
            fh.write(line + "\n")


def _archived(d: Path):
    out = []
    for p in sorted(d.glob("*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as gz:
            out += [json.loads(x) for x in gz if x.strip()]
    return out


def _latest_by_id(path: Path):
    by = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            o = json.loads(line)
        except Exception:
            continue
        by[o["id"]] = o
    return by


@pytest.fixture
def store(tmp_path):
    live = tmp_path / "state" / "data" / "runtime" / "advisory_kb_lessons.jsonl"
    arch = tmp_path / "state" / "archive" / "advisory_kb_lessons"
    rows = [
        _row("a", 200, n=1), _row("a", 150, n=2), _row("a", 10, n=3),   # a: two old superseded rows
        _row("b", 120, n=1), _row("b", 100, n=2),                       # b: newest is old -> kept
        _row("c", 5, n=1),
    ]
    _write(live, rows, raw_lines=['{"id": "d", "ts": "not-a-date"}', "{broken json", ""])
    return live, arch


def test_config_defaults_and_values():
    cfg = ret.load_config()
    assert cfg["retain_days"] == 90
    assert cfg["archive_subdir"] == "archive/advisory_kb_lessons"
    assert cfg["keep_latest_per_id"] is True


def test_missing_config_falls_back_with_warning(tmp_path, caplog):
    cfg = ret.load_config(tmp_path / "nope.json")
    assert cfg["retain_days"] == 90
    assert "unreadable" in caplog.text


def test_state_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert ret.default_archive_dir() == tmp_path / "archive" / "advisory_kb_lessons"
    assert ret.default_live_path() == tmp_path / "data" / "runtime" / "advisory_kb_lessons.jsonl"


def test_plan_is_read_only(store):
    live, arch = store
    before = live.read_bytes()
    out = ret.plan(live, cfg=_cfg(), now=NOW)
    assert out["ok"] and out["rows"] == 8 and out["blank_lines"] == 1
    assert out["archive_rows"] == 3          # a@200, a@150, b@120
    assert out["old_rows_kept_as_latest_per_id"] == 1   # b@100
    assert out["unparseable_ts_rows_kept"] == 2
    assert set(out["archive_by_month"]) == {"2026-03", "2026-05", "2026-06"}
    assert live.read_bytes() == before
    assert not ret.lock_path_for(live).exists()
    assert not arch.exists()


def test_apply_moves_old_rows_and_preserves_latest(store):
    live, arch = store
    latest_before = {k: v for k, v in _latest_by_id(live).items()}
    out = ret.apply(live, archive_dir=arch, cfg=_cfg(), now=NOW)
    assert out["ok"] and out["archive_rows"] == 3 and out["keep_rows"] == 5
    assert _latest_by_id(live) == latest_before                    # readers see the same state
    kept = live.read_text(encoding="utf-8").splitlines()
    assert "{broken json" in kept and any("not-a-date" in x for x in kept)
    archived = _archived(arch)
    assert sorted((r["id"], r["n"]) for r in archived) == [("a", 1), ("a", 2), ("b", 1)]
    ok, bad = ret.verify_manifest(arch)
    assert ok, bad
    sums = (arch / "SHA256SUMS").read_text().splitlines()
    assert len(sums) == 3
    assert sorted(r["n"] for r in ret.iter_archived_rows(arch)) == [1, 1, 2]


def test_no_row_lost(store):
    live, arch = store
    before = {x for x in live.read_text(encoding="utf-8").splitlines() if x.strip()}
    ret.apply(live, archive_dir=arch, cfg=_cfg(), now=NOW)
    after = set(live.read_text(encoding="utf-8").splitlines())
    for p in arch.glob("*.jsonl.gz"):
        with gzip.open(p, "rt", encoding="utf-8") as gz:
            after |= {x.rstrip("\n") for x in gz}
    assert before <= after


def test_existing_month_archive_appends_member(tmp_path):
    live = tmp_path / "l.jsonl"
    arch = tmp_path / "arch"
    _write(live, [_row("a", 200, n=1), _row("a", 1, n=9)])
    ret.apply(live, archive_dir=arch, cfg=_cfg(), now=NOW)
    # a second old row in the same month arrives (e.g. backfill) and is rotated
    with open(live, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(_row("a", 199, n=2)) + "\n")
        fh.write(json.dumps(_row("a", 0, n=10)) + "\n")
    ret.apply(live, archive_dir=arch, cfg=_cfg(), now=NOW)
    assert sorted(r["n"] for r in _archived(arch)) == [1, 2]
    assert ret.verify_manifest(arch)[0]


def test_rerun_after_crash_does_not_duplicate(tmp_path, monkeypatch):
    live = tmp_path / "l.jsonl"
    arch = tmp_path / "arch"
    _write(live, [_row("a", 200, n=1), _row("a", 1, n=2)])
    real_replace = ret.os.replace

    def crash_on_live(src, dst):
        if Path(dst) == live:
            raise OSError("simulated crash before live rewrite")
        return real_replace(src, dst)

    monkeypatch.setattr(ret.os, "replace", crash_on_live)
    with pytest.raises(OSError):
        ret.apply(live, archive_dir=arch, cfg=_cfg(), now=NOW)
    monkeypatch.setattr(ret.os, "replace", real_replace)
    assert len(live.read_text().splitlines()) == 2          # live untouched
    out = ret.apply(live, archive_dir=arch, cfg=_cfg(), now=NOW)
    assert out["skipped_already_archived"] == 1
    assert [r["n"] for r in _archived(arch)] == [1]
    assert not live.with_name(live.name + ".rotate.tmp").exists()


def test_verify_failure_leaves_live_untouched(tmp_path, monkeypatch):
    live = tmp_path / "l.jsonl"
    arch = tmp_path / "arch"
    _write(live, [_row("a", 200, n=1), _row("a", 1, n=2)])
    before = live.read_bytes()
    monkeypatch.setattr(ret, "_append_member", lambda path, lines, level: None)  # writes nothing
    with pytest.raises(ret.RotationVerifyError):
        ret.apply(live, archive_dir=arch, cfg=_cfg(), now=NOW)
    assert live.read_bytes() == before


def test_noop_when_nothing_old(tmp_path):
    live = tmp_path / "l.jsonl"
    _write(live, [_row("a", 1)])
    out = ret.apply(live, archive_dir=tmp_path / "arch", cfg=_cfg(), now=NOW)
    assert out["action"] == "noop" and not (tmp_path / "arch").exists()


def test_keep_latest_per_id_off_archives_everything_old(store):
    live, arch = store
    out = ret.plan(live, cfg=_cfg(keep_latest_per_id=False), now=NOW)
    assert out["archive_rows"] == 4


def test_writer_appends_under_shared_lock(tmp_path, monkeypatch):
    from lib.advisory import kb_lessons as kb
    lp = tmp_path / "advisory_kb_lessons.jsonl"
    monkeypatch.setattr(kb, "LESSONS_PATH", lp)
    calls = []
    real = ret.writer_lock

    def spy(path, cfg=None):
        calls.append(Path(path))
        return real(path, cfg)

    monkeypatch.setattr(ret, "writer_lock", spy)
    kb._append_jsonl(lp, {"id": "x", "ts": NOW.isoformat()})
    kb._append_jsonl(tmp_path / "other.jsonl", {"id": "y"})
    assert calls == [lp]
    assert ret.lock_path_for(lp).exists()
    assert json.loads(lp.read_text())["id"] == "x"


def test_cli_dry_run_default(store, capsys):
    import importlib
    live, arch = store
    cli = importlib.import_module("rotate_advisory_kb_lessons")
    before = live.read_bytes()
    assert cli.main(["--live", str(live), "--archive-dir", str(arch)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "plan"
    assert live.read_bytes() == before and not arch.exists()


def test_cli_apply(store, capsys):
    import importlib
    live, arch = store
    cli = importlib.import_module("rotate_advisory_kb_lessons")
    # rows are dated relative to NOW; a large retain window keeps everything
    assert cli.main(["--apply", "--live", str(live), "--archive-dir", str(arch), "--retain-days", "100000"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "noop"
