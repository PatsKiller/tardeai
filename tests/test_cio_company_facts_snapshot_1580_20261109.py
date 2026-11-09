"""LQ-20261107-1580: one company-facts rebuild must not queue every other reader behind it.

Live evidence (2026-11-09): the append-only InstrumentRecord store grew past 579 MB and was
rewritten while the portfolio-server unit sat at ``memory.high`` (``memory.events high=23,781``).
``load_snapshot`` held **one module-global lock** across ``store.all()`` + ``_build_snapshot`` +
the per-caller ``deepcopy``, and every append invalidates the memo, so a rebuild that took 4.7 s
on an idle host took 93-175 s under reclaim — and every endpoint that resolves company facts
waited behind it: ``/api/v2/cio/pages`` logged 174.7 s, and ``/api/v2/overview`` never reached
its 10 s slow-request line at all because the browser aborted at 30 s first.

The rebuild is now serialised per store file, the deep copy happens outside the lock, and a
caller that finds a rebuild already running waits at most ``_SNAPSHOT_WAIT_S`` before it is
served the previous snapshot instead of queueing. These tests pin both halves of that: the
follower must not wait for a slow build, a build fast enough to finish inside the window must
still be seen by the caller that waited for it, and one store's slow rebuild must not stall a
reader of an unrelated store.

Fail-before: with ``load_snapshot`` reverted, the follower in the first test blocks on the global
lock for the whole 4 s build and is handed the *new* snapshot (the assertion fires), and in the
third test an unrelated store's rebuild waits behind the first store's build.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from scripts.lib import cio_instrument_record
from scripts.lib.data_broker import cio_company_facts as cf


def _store_path(root):
    return Path(root) / "data" / "cio" / "cio_instrument_records.jsonl"


def _world(monkeypatch, tmp_path):
    """Fake stores the test can append to, and a fake build the test can slow down per store."""
    world = {"records": {}, "sleep": {}, "current": None, "builds": 0, "started": threading.Event()}

    class Store:
        def __init__(self, path):
            self.path = path

        def all(self):
            world["current"] = self.path
            return [dict(r) for r in world["records"].setdefault(self.path, [])]

    def store_for(root=None):
        path = _store_path(root if root is not None else tmp_path)
        if path not in world["records"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")
            world["records"][path] = []
        return Store(path)

    def build(records):
        world["builds"] += 1
        world["started"].set()
        time.sleep(world["sleep"].get(world["current"], 0.0))  # nosemgrep: tq-py-missing-as-zero -- seconds to stall a fake build, not a count or a price shown to anyone
        return {"n": len(records), "store": str(world["current"])}

    monkeypatch.setattr(cio_instrument_record, "_store_for_root", store_for)
    monkeypatch.setattr(cf, "_build_snapshot", build)
    monkeypatch.setattr(cf, "_SNAPSHOT_MEMO", {})
    return world


def _add(world, root, guid):
    """Append one record: the store is append-only, and the file's size/mtime change invalidates the memo."""
    path = _store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    world["records"].setdefault(path, []).append({"security_guid": guid})
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"security_guid": guid}) + "\n")


def _snap(n, root):
    return {"n": n, "store": str(_store_path(root))}


def _run_in_thread(fn):
    out = {}
    thread = threading.Thread(target=lambda: out.setdefault("value", fn()), daemon=True)
    thread.start()
    return thread, out


def test_a_slow_rebuild_does_not_stall_a_concurrent_reader(tmp_path, monkeypatch):
    world = _world(monkeypatch, tmp_path)
    _add(world, tmp_path, "g-1")
    assert cf.load_snapshot(tmp_path) == _snap(1, tmp_path)      # prime the memo
    _add(world, tmp_path, "g-2")
    world["started"].clear()
    world["sleep"][_store_path(tmp_path)] = 4.0                 # a rebuild no reader should wait for

    thread, built = _run_in_thread(lambda: cf.load_snapshot(tmp_path))
    assert world["started"].wait(5.0), "the builder never started"

    t0 = time.monotonic()
    served = cf.load_snapshot(tmp_path)
    waited = time.monotonic() - t0
    thread.join(15)

    assert served == _snap(1, tmp_path), "a reader arriving mid-rebuild must get the last published snapshot"
    assert waited < cf._SNAPSHOT_WAIT_S + 0.5, f"the reader queued {waited:.1f}s behind the rebuild"
    assert built["value"] == _snap(2, tmp_path), "the rebuild itself must see the append"
    # Stale, not blind: the next call gets the append.
    assert cf.load_snapshot(tmp_path) == _snap(2, tmp_path)
    assert world["builds"] == 2


def test_a_fast_rebuild_is_seen_by_the_caller_that_waited_for_it(tmp_path, monkeypatch):
    world = _world(monkeypatch, tmp_path)
    _add(world, tmp_path, "g-1")
    assert cf.load_snapshot(tmp_path) == _snap(1, tmp_path)
    _add(world, tmp_path, "g-2")
    world["started"].clear()
    world["sleep"][_store_path(tmp_path)] = 0.3                 # finishes inside _SNAPSHOT_WAIT_S

    thread, built = _run_in_thread(lambda: cf.load_snapshot(tmp_path))
    assert world["started"].wait(5.0), "the builder never started"

    served = cf.load_snapshot(tmp_path)                         # waits out the lock, reuses what it published
    thread.join(15)

    assert served == _snap(2, tmp_path)
    assert built["value"] == _snap(2, tmp_path)
    assert world["builds"] == 2, "the waiting caller must reuse the build, not start a second one"


def test_a_slow_rebuild_of_one_store_does_not_stall_another_store(tmp_path, monkeypatch):
    world = _world(monkeypatch, tmp_path)
    slow_root, fast_root = tmp_path / "slow", tmp_path / "fast"
    _add(world, slow_root, "g-1")
    _add(world, fast_root, "h-1")
    assert cf.load_snapshot(slow_root) == _snap(1, slow_root)
    assert cf.load_snapshot(fast_root) == _snap(1, fast_root)

    world["sleep"][_store_path(slow_root)] = 4.0
    _add(world, slow_root, "g-2")                               # the slow store now needs a rebuild
    world["started"].clear()
    thread, _built = _run_in_thread(lambda: cf.load_snapshot(slow_root))
    assert world["started"].wait(5.0), "the slow builder never started"

    _add(world, fast_root, "h-2")                               # an unrelated store also needs one
    t0 = time.monotonic()
    served = cf.load_snapshot(fast_root)
    waited = time.monotonic() - t0
    thread.join(15)

    assert served == _snap(2, fast_root)
    assert waited < 1.0, f"the fast store's reader waited {waited:.1f}s on the slow store's build"
