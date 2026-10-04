"""repair_cio_event_bus_fork: re-link a concatenated-fork bus without losing or reordering events.

Builds a real fork with CIOEventBus in tmp (never the live bus), repairs it, and proves the chain
verifies, every event survives in place with its content, the archive is byte-identical to the
original, provenance is kept, a second run is a no-op, and later appends extend the repaired chain.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import repair_cio_event_bus_fork as rp  # noqa: E402
from scripts.lib.cio_event_bus import CIOEventBus  # noqa: E402


def _bus(path: Path, tmp: Path) -> CIOEventBus:
    return CIOEventBus(bus_path=str(path), cursor_path=str(tmp / "cursor.jsonl"))


def _emit(bus: CIOEventBus, n: int, tag: str):
    for i in range(n):
        bus.emit("system.heartbeat_ok", {"tag": tag, "i": i}, source="test")


def _forked(tmp: Path) -> Path:
    """genesis + 3 common, then branch A (2) and branch B (3) concatenated A then B."""
    a, b = tmp / "a.jsonl", tmp / "b.jsonl"
    bus_a = _bus(a, tmp)
    _emit(bus_a, 3, "common")
    b.write_text(a.read_text())                     # the fork point
    _emit(bus_a, 2, "A")
    _emit(_bus(b, tmp), 3, "B")
    common = len(a.read_text().splitlines()) - 2
    live = tmp / "cio_events.jsonl"
    live.write_text(a.read_text() + "".join(b.read_text().splitlines(keepends=True)[common:]))
    return live


def _rows(p: Path):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def test_dry_run_finds_the_fork_and_changes_nothing(tmp_path):
    live = _forked(tmp_path)
    before = live.read_bytes()
    ok, msg = _bus(live, tmp_path).verify_integrity()
    assert not ok and "prev_hash mismatch at line 7" in msg
    res = rp.run(live, tmp_path / "arch", apply=False)
    assert res["status"] == "PLANNED" and res["first_break_line"] == 7 and res["fork_parent_line"] == 4
    assert res["rechained"] == 3 and live.read_bytes() == before and not (tmp_path / "arch").exists()


def test_apply_relinks_preserves_everything_and_archives(tmp_path):
    live = _forked(tmp_path)
    original = live.read_bytes()
    before = _rows(live)
    res = rp.run(live, tmp_path / "arch", apply=True, now="2026-10-04T23:00:00+00:00")
    assert res["applied"] and res["verify_ok"], res
    after = _rows(live)
    assert [r["event_id"] for r in after] == [r["event_id"] for r in before]            # order + ids
    strip = lambda r: {k: v for k, v in r.items() if k not in ("prev_hash", "event_hash", "rechain")}  # noqa: E731
    assert [strip(r) for r in after] == [strip(r) for r in before]                      # content
    assert after[:6] == before[:6]                                                      # untouched prefix
    for old, new in zip(before[6:], after[6:]):
        assert new["rechain"]["original_event_hash"] == old["event_hash"]
        assert new["rechain"]["original_prev_hash"] == old["prev_hash"]
    arch = Path(res["archive"])
    assert arch.read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == res["archive_sha256"]


def test_second_run_is_a_noop_and_new_appends_extend_the_chain(tmp_path):
    live = _forked(tmp_path)
    rp.run(live, tmp_path / "arch", apply=True)
    again = rp.run(live, tmp_path / "arch2", apply=True)
    assert again["status"] == "CHAIN_VALID_NOTHING_TO_DO" and not again["applied"]
    bus = _bus(live, tmp_path)
    _emit(bus, 2, "after")
    ok, msg = bus.verify_integrity()
    assert ok, msg


def test_refuses_duplicate_event_ids(tmp_path):
    live = _forked(tmp_path)
    rows = _rows(live)
    rows[-1]["event_id"] = rows[-2]["event_id"]
    live.write_text("".join(json.dumps(r) + "\n" for r in rows))
    res = rp.run(live, tmp_path / "arch", apply=True)
    assert res["status"] == "REFUSED_DUPLICATE_EVENT_IDS" and not res["applied"]
