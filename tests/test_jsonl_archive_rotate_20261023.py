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
    # Every unlink is byte-verified: the two fragment-merge markers (removed only after the fragment is found
    # in the live file), rotate_store's consumed intermediates (after the manifest), recover_one's fragments,
    # recover_source's source (head in the archive, tail live) and recover's replayed fragment.
    assert src.count(".unlink(") == 6
    assert src.count("os.unlink(marker)") == 2 and src.count("os.unlink(src)") == 1
    for bad in ("shutil.rmtree", "os.remove(", "truncate(", "--force"):
        assert bad not in src


# ── LQ-20261107-295: the three data-loss classes reproduced in codex's 2026-11-04 safety audit ───────────────────
# A. a short write is counted as a full one and the fragment is unlinked anyway;
# B. an unreadable /proc view reads as "no holder" and the store rotates under an unseen writer;
# C. recover installs the rotated-aside source in front of an already-installed tail (duplicating the hot rows)
#    and never replays a .frag left by a failed _install.

STAMP_295 = "20261023T204500Z"


def _crash_state(tmp_path, *, with_archive=True):
    """The on-disk state of a crash AFTER the tail was installed and BEFORE the fragment was merged:
    live = hot tail + one row written since the install, plus an orphan .frag holding one more row."""
    cfg = _cfg()
    store = cfg["stores"][0]
    p = tmp_path / "data" / "cio" / "s1.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    original = b"".join(
        [_row(i, NOW - timedelta(days=10, minutes=-i)) for i in range(200)]
        + [_row(i, NOW - timedelta(hours=5, minutes=-i)) for i in range(200, 250)]
    )
    # the split the rotation would have computed: 200 old rows move, 50 recent stay
    probe = tmp_path / "probe.jsonl"
    probe.write_bytes(original)
    split = J.find_split(probe, fields=["at"], cutoff=NOW - timedelta(days=3), min_tail_rows=5)["split"]
    probe.unlink()
    head, tail = original[:split], original[split:]
    src = p.with_name(f".s1.jsonl.rotating-{STAMP_295}")
    src.write_bytes(original)
    p.write_bytes(tail + _row(900, NOW))
    if with_archive:
        adir = J.archive_dir(cfg, tmp_path, "s1")
        adir.mkdir(parents=True, exist_ok=True)
        gz = adir / f"s1.{STAMP_295}.jsonl.gz"
        with open(gz, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as g:
                g.write(head)
        J.RA.write_manifest(
            gz, writer=J.WRITER, label="s1", kind="jsonl_head", rows=200,
            sha256=J.RA._sha256_file(gz), sha256_uncompressed=hashlib.sha256(head).hexdigest(),
            store="data/cio/s1.jsonl", hot_days=3, cutoff=(NOW - timedelta(days=3)).isoformat(),
            before={"bytes": len(original), "lines": 250, "sha256": hashlib.sha256(original).hexdigest()},
            after={"archive": {"path": str(gz), "bytes_uncompressed": split, "lines": 200,
                               "sha256_uncompressed": hashlib.sha256(head).hexdigest()},
                   "live_tail": {"bytes": len(tail), "lines": 50, "sha256": hashlib.sha256(tail).hexdigest()}},
        )
    frag = p.with_name(f".s1.jsonl.frag-{STAMP_295}-0")
    frag.write_bytes(_row(901, NOW))
    return cfg, store, p, src, frag, original, head, tail


def test_short_write_is_completed_not_counted(tmp_path, monkeypatch):
    """A: POSIX permits a short write. Every byte must reach the file, or the call must raise."""
    payload = b'{"at": "2026-10-23T20:45:00+00:00", "i": 1}\n' * 500
    src, live = tmp_path / "src", tmp_path / "live"
    src.write_bytes(payload)
    real = os.write
    calls = {"n": 0}

    def half_write(fd, data):
        data = bytes(data)
        calls["n"] += 1
        return real(fd, data[: max(1, len(data) // 2)])

    monkeypatch.setattr(os, "write", half_write)
    n = J._append_range(src, live, 0, len(payload))
    assert n == len(payload)
    assert live.read_bytes() == payload
    assert calls["n"] > 1


def test_zero_write_raises_instead_of_counting_bytes(tmp_path, monkeypatch):
    src, live = tmp_path / "src", tmp_path / "live"
    src.write_bytes(b"one\n" * 10)
    monkeypatch.setattr(os, "write", lambda fd, data: 0)
    with pytest.raises(J.RotateError):
        J._append_range(src, live, 0, 40)


def test_unreadable_proc_view_refuses_before_touching_the_store(tmp_path):
    """B: an unreadable fd view cannot prove 'no holder'. Refuse; leave the store untouched."""
    p = _seed(tmp_path)
    before = p.read_bytes()
    proc = tmp_path / "proc"
    (proc / "777" / "fd").mkdir(parents=True)
    os.chmod(proc / "777" / "fd", 0o000)
    try:
        res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=proc, sleep=_no_sleep)
    finally:
        os.chmod(proc / "777" / "fd", 0o700)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    # the refusal names the process, so an operator knows what to look at
    assert "777:" in res["detail"], res["detail"]
    assert p.read_bytes() == before
    assert not (tmp_path / "archive").exists()


def test_fd_unknown_labels_name_the_process(tmp_path):
    proc = tmp_path / "proc"
    (proc / "4242" / "fd").mkdir(parents=True)
    (proc / "4242" / "comm").write_text("systemd\n")
    store = tmp_path / "s.jsonl"
    store.write_text("{}\n")
    os.chmod(proc / "4242" / "fd", 0o000)
    try:
        holders, unknown = J._scan_holders(store, proc)
    finally:
        os.chmod(proc / "4242" / "fd", 0o700)
    assert holders == []
    assert unknown == ["4242:systemd:fd_dir_denied"], unknown


def test_plan_totals_count_stores_blocked_by_fd_visibility(tmp_path, monkeypatch):
    """A plan can list 5 stores to rotate while --apply would refuse all 5. The totals must say so."""
    monkeypatch.setattr(J, "_scan_holders", lambda path, proc_root: ([], ["4242:systemd:fd_dir_denied"]))
    _seed(tmp_path)
    plan = J.build_plan(_cfg(), tmp_path, NOW)
    assert plan["totals"]["rotate"] == 1, plan["totals"]
    assert plan["totals"]["fd_blocked"] == 1, plan["totals"]
    assert plan["stores"][0]["fd_visibility"] == "unknown"
    assert plan["stores"][0]["fd_unknown"] == ["4242:systemd:fd_dir_denied"]


def test_missing_proc_root_refuses_instead_of_assuming_no_holder(tmp_path):
    p = _seed(tmp_path)
    before = p.read_bytes()
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW,
                         proc_root=tmp_path / "no-such-proc", sleep=_no_sleep)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    assert p.read_bytes() == before


def test_recover_does_not_duplicate_an_installed_tail_and_replays_the_fragment(tmp_path, proc):
    """C: crash after the tail install. The hot rows must stay singular and the orphan .frag must land."""
    cfg, store, p, src, frag, original, head, tail = _crash_state(tmp_path)
    out = J.recover(cfg, tmp_path, NOW, proc_root=proc, sleep=_no_sleep)
    rows = _rows_of(p.read_bytes())
    assert rows == list(range(200, 250)) + [900, 901], rows
    assert not src.exists() and not frag.exists()
    assert out[0]["ok"] is True, out
    # idempotent: a second recover changes nothing and appends nothing twice
    before = p.read_bytes()
    J.recover(cfg, tmp_path, NOW, proc_root=proc, sleep=_no_sleep)
    assert p.read_bytes() == before


def test_recover_keeps_a_source_whose_head_has_no_verified_archive(tmp_path, proc):
    """C: if the tail is installed but the archive is missing, the head exists only in the source. Keep it."""
    cfg, store, p, src, frag, original, head, tail = _crash_state(tmp_path, with_archive=False)
    live_before = p.read_bytes()
    out = J.recover(cfg, tmp_path, NOW, proc_root=proc, sleep=_no_sleep)
    assert src.exists(), "the source holds the only copy of the head: it is never removed unverified"
    assert not out[0]["ok"]
    rows = _rows_of(p.read_bytes())
    assert rows[:5] == list(range(200, 205))  # nothing was installed in front of the live tail
    assert 901 in rows  # the fragment is still replayed


def test_partial_fragment_append_resumes_and_never_duplicates(tmp_path):
    """C: a crash in the middle of the fragment write must resume, not append the whole fragment twice."""
    live = tmp_path / "live"
    frag = tmp_path / ".live.frag-x-0"
    payload = b'{"i": 2}\n{"i": 3}\n{"i": 4}\n'
    frag.write_bytes(payload)
    live.write_bytes(b'{"i": 1}\n' + payload[:9])  # the bytes that landed before the crash
    res = J._merge_fragment(frag, live, cfg=_cfg(), proc_root=tmp_path, sleep=_no_sleep)
    assert live.read_bytes() == b'{"i": 1}\n' + payload
    assert res["resumed_from"] == 9
    again = J._merge_fragment(frag, live, cfg=_cfg(), proc_root=tmp_path, sleep=_no_sleep)
    assert again["already_merged"] is True
    assert live.read_bytes() == b'{"i": 1}\n' + payload
