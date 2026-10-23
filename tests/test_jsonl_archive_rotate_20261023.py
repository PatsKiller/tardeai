"""JSONL archive rotation (2026-10-23) — scripts/ops/jsonl_archive_rotate.py.

ANCHOR: JSONL_ARCHIVE_ROTATE_20261023. Operator 2026-10-23 ~11:05 ET, "approved": rotate (archive, never delete)
the oversized append-only JSONL stores. Hermetic: every store, archive and /proc view is under tmp_path; the real
/proc is never scanned (an empty fake proc root, or one with a planted fd link); no network, no DB.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.ops import jsonl_archive_rotate as J

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 23, 20, 45, tzinfo=timezone.utc)  # Fri 16:45 ET, after the close


def _cfg(**over):
    cfg = {
        "enabled": False,
        "archive_subdir": "archive/file_prune",
        "min_rotate_bytes": 0,
        "quiesce_timeout_s": 2,
        "max_install_attempts": 20,
        "refuse_window_et": {"days": "Mon-Fri", "start": "04:00", "end": "16:15"},
        "stores": [
            {"id": "s1", "path": "data/cio/s1.jsonl", "ts_fields": ["at"], "rotate": True, "hot_days": 3,
             "min_tail_rows": 5, "retention_days": 7, "max_archive_bytes": 10_000_000},
            {"id": "lineage", "path": "data/cio/lineage.jsonl", "ts_fields": ["recorded_at"], "rotate": False},
        ],
    }
    cfg.update(over)
    return cfg


def _row(i: int, ts: datetime) -> bytes:
    return (json.dumps({"at": ts.isoformat(), "i": i, "pad": "x" * 40}, sort_keys=True) + "\n").encode()


def _seed(root: Path, n_old=200, n_new=50) -> Path:
    p = root / "data" / "cio" / "s1.jsonl"
    p.parent.mkdir(parents=True)
    with open(p, "wb") as fh:
        for i in range(n_old):
            fh.write(_row(i, NOW - timedelta(days=10, minutes=-i)))
        for i in range(n_old, n_old + n_new):
            fh.write(_row(i, NOW - timedelta(hours=5, minutes=-i)))
    return p


def _tree(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _rows_of(raw: bytes) -> list[int]:
    return [json.loads(line)["i"] for line in raw.splitlines() if line.strip()]


def _no_sleep(_s):
    time.sleep(0.001)


@pytest.fixture()
def proc(tmp_path):
    d = tmp_path / "proc"
    d.mkdir()
    return d


def test_split_keeps_hot_tail_and_min_rows(tmp_path):
    p = _seed(tmp_path)
    s = J.find_split(p, fields=["at"], cutoff=NOW - timedelta(days=3), min_tail_rows=5)
    assert s["lines"] == 250 and s["head_lines"] == 200
    assert p.read_bytes()[s["split"]:].count(b"\n") == 50
    s2 = J.find_split(p, fields=["at"], cutoff=NOW + timedelta(days=1), min_tail_rows=5)
    assert s2["lines"] - s2["head_lines"] == 5  # nothing is recent: min_tail_rows still stay
    s3 = J.find_split(p, fields=["at"], cutoff=NOW, min_tail_rows=1000)
    assert s3["split"] == 0  # fewer rows than min_tail_rows: nothing moves


def test_out_of_order_row_after_split_stays_live(tmp_path):
    p = _seed(tmp_path, n_old=20, n_new=3)
    with open(p, "ab") as fh:
        fh.write(_row(999, NOW - timedelta(days=30)))
    s = J.find_split(p, fields=["at"], cutoff=NOW - timedelta(days=3), min_tail_rows=1)
    assert 999 in _rows_of(p.read_bytes()[s["split"]:])


def test_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    _seed(tmp_path)
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"jsonl_retention": _cfg()}))
    before = _tree(tmp_path)
    assert J.main(["--dry-run", "--rules", str(rules), "--state-root", str(tmp_path), "--now", NOW.isoformat()]) == 0
    out = json.loads(capsys.readouterr().out)
    assert _tree(tmp_path) == before
    s1 = next(s for s in out["stores"] if s["id"] == "s1")
    assert s1["action"] == "rotate" and s1["archive_lines"] == 200 and s1["keep_lines"] == 50
    lin = next(s for s in out["stores"] if s["id"] == "lineage")
    assert lin["action"] == "skip" and lin["reason"] == "rotate_false"


def test_no_parseable_timestamp_is_never_rotated(tmp_path):
    p = tmp_path / "data" / "cio" / "s1.jsonl"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"".join(json.dumps({"other": i}).encode() + b"\n" for i in range(100)))
    out = J.plan_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW)
    assert out["action"] == "skip" and out["reason"] == "no_parseable_timestamp"


def test_apply_archives_head_byte_exact_with_manifest_and_tripwire(tmp_path, proc):
    p = _seed(tmp_path)
    original = p.read_bytes()
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=proc, sleep=_no_sleep, grace_s=0)
    assert res["ok"] and res["action"] == "rotated"
    gz = Path(res["archive"])
    assert gz.parent == tmp_path / "archive" / "file_prune" / "s1"
    assert gz.name == "s1.20261023T204500Z.jsonl.gz"
    head = gzip.decompress(gz.read_bytes())
    assert head + p.read_bytes() == original  # every byte is in the archive or the live file, in order
    assert _rows_of(head) == list(range(200)) and _rows_of(p.read_bytes()) == list(range(200, 250))
    man = json.loads((gz.parent / (gz.name + ".manifest.json")).read_text()) if (
        gz.parent / (gz.name + ".manifest.json")).exists() else json.loads(J.RA.manifest_path(gz).read_text())
    acc = man["line_accounting"]
    assert acc["before"] == 250 and acc["archived"] + acc["kept"] == acc["before"] and acc["equal"] is True
    assert man["before"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert man["sha256_uncompressed"] == hashlib.sha256(head).hexdigest()
    trip = [json.loads(x) for x in (gz.parent / "TRIPWIRE.jsonl").read_text().splitlines()]
    assert trip[-1]["schema"] == "RetentionArchiveTripwire@v1" and trip[-1]["archive"] == str(gz)
    assert trip[-1]["rows"] == 200
    # the renamed-aside intermediates are gone; nothing else is left beside the store
    assert sorted(x.name for x in p.parent.iterdir()) == ["s1.jsonl"]


def test_rotation_never_touches_a_rotate_false_store(tmp_path, proc):
    lin = tmp_path / "data" / "cio" / "lineage.jsonl"
    lin.parent.mkdir(parents=True)
    lin.write_bytes(b"".join(_row(i, NOW - timedelta(days=60)) for i in range(100)))
    before = lin.read_bytes()
    res = J.rotate_store(_cfg()["stores"][1], _cfg(), tmp_path, NOW, proc_root=proc, sleep=_no_sleep)
    assert res["action"] == "skip" and lin.read_bytes() == before
    assert not (tmp_path / "archive").exists()


def test_concurrent_writer_loses_no_row(tmp_path, proc):
    p = _seed(tmp_path, n_old=3000, n_new=100)
    stop = threading.Event()
    written: list[int] = []

    def writer():
        i = 100_000
        while not stop.is_set():
            fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)  # the stores' writer pattern
            try:
                os.write(fd, _row(i, NOW))
            finally:
                os.close(fd)
            written.append(i)
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        time.sleep(0.02)
        res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=proc, sleep=_no_sleep,
                             grace_s=0.05)
    finally:
        stop.set()
        t.join()
    assert res["ok"], res
    head = _rows_of(gzip.decompress(Path(res["archive"]).read_bytes()))
    live = _rows_of(p.read_bytes())
    everything = head + live
    expected = list(range(3100)) + written
    assert sorted(everything) == sorted(expected)  # nothing lost, nothing duplicated
    assert len(everything) == len(set(everything))
    assert head == list(range(3000))
    assert written, "the writer must have run during the rotation"


def test_live_file_recreated_before_install_is_merged_not_overwritten(tmp_path, proc, monkeypatch):
    p = _seed(tmp_path)
    calls = {"n": 0}
    real_quiesce = J.quiesce

    def quiesce(path, **kw):
        calls["n"] += 1
        if calls["n"] == 1:  # a writer creates a fresh live file right after the rename aside
            with open(p, "ab") as fh:
                fh.write(_row(7001, NOW))
                fh.write(_row(7002, NOW))
        return real_quiesce(path, **kw)

    monkeypatch.setattr(J, "quiesce", quiesce)
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=proc, sleep=_no_sleep, grace_s=0)
    assert res["ok"]
    assert _rows_of(p.read_bytes()) == list(range(200, 250)) + [7001, 7002]
    assert len(res["after"]["merged_fragments"]) == 1
    assert sorted(x.name for x in p.parent.iterdir()) == ["s1.jsonl"]


def test_long_lived_fd_holder_is_refused_untouched(tmp_path, proc):
    p = _seed(tmp_path)
    before = p.read_bytes()
    (proc / "4242" / "fd").mkdir(parents=True)
    os.symlink(p, proc / "4242" / "fd" / "3")
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=proc, sleep=_no_sleep)
    assert res["ok"] is False and res["reason"] == "long_lived_fd_holder" and res["holders"] == ["4242/3"]
    assert p.read_bytes() == before and not (tmp_path / "archive").exists()


def test_failure_after_rename_merges_source_back(tmp_path, proc, monkeypatch):
    p = _seed(tmp_path)
    before = p.read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(J, "_gz_sha_lines", boom)
    with pytest.raises(OSError):
        J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=proc, sleep=_no_sleep)
    assert p.read_bytes() == before  # every row is back in the live file
    assert not list(p.parent.glob(".s1.jsonl.rotating-*"))


def test_recover_puts_crashed_source_before_new_rows(tmp_path, proc):
    p = _seed(tmp_path, n_old=10, n_new=0)
    src = p.with_name(".s1.jsonl.rotating-20261023T200000Z")
    os.rename(p, src)
    with open(p, "ab") as fh:
        fh.write(_row(500, NOW))
    out = J.recover(_cfg(), tmp_path, NOW, proc_root=proc, sleep=_no_sleep)
    assert out[0]["ok"]
    assert _rows_of(p.read_bytes()) == list(range(10)) + [500]
    assert sorted(x.name for x in p.parent.iterdir()) == ["s1.jsonl"]


def test_apply_refusals(tmp_path, capsys):
    _seed(tmp_path)
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"jsonl_retention": _cfg()}))
    base = ["--rules", str(rules), "--state-root", str(tmp_path)]
    assert J.main(["--apply", *base, "--now", NOW.isoformat()]) == 1
    assert "needs --confirm APPLY" in capsys.readouterr().out
    market = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)  # Fri 10:00 ET
    assert J.main(["--apply", "--confirm", "APPLY", *base, "--now", market.isoformat()]) == 1
    assert "market_hours_window" in capsys.readouterr().out
    assert not (tmp_path / "archive").exists()
    sat = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)
    assert not J.in_refuse_window(_cfg(), sat)
    assert not J.in_refuse_window(_cfg(), datetime(2026, 10, 23, 20, 16, tzinfo=timezone.utc))
    assert J.in_refuse_window(_cfg(), datetime(2026, 10, 23, 20, 14, tzinfo=timezone.utc))


def test_retention_preview_selects_by_age_and_cap_and_removes_nothing(tmp_path):
    cfg = _cfg()
    seg = gzip.compress(b"{}\n" * 10, mtime=0)
    cfg["stores"][0]["max_archive_bytes"] = 2 * len(seg) + 1
    cfg["stores"][0]["legacy_archive_globs"] = ["data/cio/archive/s1-*.jsonl"]
    adir = tmp_path / "archive" / "file_prune" / "s1"
    adir.mkdir(parents=True)
    for stamp in ("20261022T204500Z", "20261021T204500Z", "20261001T204500Z"):
        (adir / f"s1.{stamp}.jsonl.gz").write_bytes(seg)
    (adir / "TRIPWIRE.jsonl").write_text("{}\n")
    (adir / "s1.20261020T204500Z.jsonl.gz.part").write_bytes(b"x")
    legacy = tmp_path / "data" / "cio" / "archive" / "s1-20260927T144843Z.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"{}\n" * 3)
    before = _tree(tmp_path)
    out = J.retention_preview(cfg, tmp_path, NOW, count_rows=True)
    assert _tree(tmp_path) == before
    segs = {Path(s["path"]).name: s for s in out["stores"][0]["segments"]}
    assert set(segs) == {"s1.20261022T204500Z.jsonl.gz", "s1.20261021T204500Z.jsonl.gz",
                         "s1.20261001T204500Z.jsonl.gz", legacy.name}
    assert not segs["s1.20261022T204500Z.jsonl.gz"]["would_select"]
    assert not segs["s1.20261021T204500Z.jsonl.gz"]["would_select"]
    assert segs["s1.20261001T204500Z.jsonl.gz"]["why"] == ["older_than_7d", "over_max_archive_bytes"]
    assert segs[legacy.name]["would_select"] and segs[legacy.name]["rows"] == 3
    assert segs["s1.20261001T204500Z.jsonl.gz"]["rows"] == 10
    zero = J.retention_preview(cfg, tmp_path, NOW, retention_days=0)
    assert zero["stores"][0]["would_select_count"] == 4


def test_real_rules_block_pins():
    cfg = J.load_config(ROOT / "config" / "disk_hygiene_rules.json")
    assert cfg["enabled"] is False
    by = {s["id"]: s for s in cfg["stores"]}
    assert by["cio_workflow_lineage"]["rotate"] is False
    assert "_existing_keys" in by["cio_workflow_lineage"]["rotate_blocked_reason"]
    for sid in ("aif_memory_retrievals", "research_call_accounting"):
        assert by[sid]["rotate"] is True and by[sid]["hot_days"] >= 1
        assert any("approved" in q for q in by[sid]["approval"])
    quote = "You have my authority to delete them. And the N8N agent needs to delete these on a regular."
    for s in cfg["stores"]:
        assert any(quote in q for q in s["approval"]), s["id"]
    assert cfg["refuse_window_et"] == {"days": "Mon-Fri", "start": "04:00", "end": "16:15",
                                       "why": cfg["refuse_window_et"]["why"]}


def test_removal_is_limited_to_verified_intermediates():
    src = (ROOT / "scripts" / "ops" / "jsonl_archive_rotate.py").read_text()
    assert src.count(".unlink(") == 2  # rotate_store intermediates + recover fragments, both byte-verified
    for bad in ("shutil.rmtree", "os.remove(", "truncate(", "--force"):
        assert bad not in src
