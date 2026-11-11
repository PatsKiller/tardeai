"""LQ-20261107-1947: duplicate prevention independent of file position and recency, and of process.

Synthetic fixtures only. Operator criterion: a retry after more than 100 intervening contributions, and two concurrent
processes retrying the same answer, each yield exactly one stored memory.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.lib.cross_asset.security_research_spine as sp  # noqa: E402
from scripts.lib import cio_ask_contract as C  # noqa: E402
from scripts.lib.cio_ask_memory import SpineAskMemory  # noqa: E402

GUID = "11111111-2222-4333-8444-555555555555"
ENT = C.EntityRef(name="Synthetic Corp", symbol="SYNTH", security_guid=GUID,
                  issuer_guid="11111111-2222-4333-8444-666666666666")
ANSWER = dict(kind="ask.answer_version", summary="v1 final: synthetic answer", ref="ask_x:v1")


def _lines(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def _copies(p):
    return sum(1 for t in _lines(p) for c in t["contributions"]
               if c["artifact_id"] == "ask_x:v1" and c["kind"] == "ask.answer_version" and "accepted" not in c["kind"])


def test_retry_after_more_than_100_intervening_contributions_is_still_one_memory(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, **ANSWER)
    for i in range(120):                                  # push the answer out of the 100-contribution tip window
        mem.append(entity=ENT, kind="ask.source", summary=f"Src {i} (filing)", ref=f"ask_y:{i}")
    tip = _lines(p)[-1]
    assert not any(c["artifact_id"] == "ask_x:v1" and c["kind"] == "ask.answer_version" for c in tip["contributions"])
    before = len(_lines(p))
    r = mem.append(entity=ENT, **ANSWER)                  # the late retry
    assert r["spine"]["ok"] is True and r["spine"]["deduped"] is True
    assert len(_lines(p)) == before                       # nothing appended


def test_index_is_durable_across_instances_and_does_not_conflate_identities(tmp_path):
    p = tmp_path / "spine.jsonl"
    SpineAskMemory(spine_path=p).append(entity=ENT, **ANSWER)
    again = SpineAskMemory(spine_path=p).append(entity=ENT, **ANSWER)       # a new process-like instance
    assert again["spine"]["deduped"] is True
    other = C.EntityRef(name="Other", symbol="SYNTH", security_guid="99999999-2222-4333-8444-555555555555",
                        issuer_guid="99999999-2222-4333-8444-666666666666")
    n = len(_lines(p))
    SpineAskMemory(spine_path=p).append(entity=other, **ANSWER)             # same ticker, other identity: written
    assert len(_lines(p)) == n + 1


def test_concurrent_writers_yield_one_memory_threads(tmp_path, monkeypatch):
    p = tmp_path / "spine.jsonl"
    real = sp.upsert_research_memory

    def slow(*a, **k):                                    # widen the read-then-write window
        time.sleep(0.15)
        return real(*a, **k)

    monkeypatch.setattr(sp, "upsert_research_memory", slow)
    out = []

    def worker():
        out.append(SpineAskMemory(spine_path=p).append(entity=ENT, **ANSWER))

    ts = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(r["spine"]["ok"] is True for r in out)
    assert sum(1 for r in out if r["spine"].get("deduped") is True) == 5
    assert len(_lines(p)) == 1 and _copies(p) == 1


_CHILD = """
import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
import scripts.lib.cross_asset.security_research_spine as sp
from scripts.lib import cio_ask_contract as C
from scripts.lib.cio_ask_memory import SpineAskMemory
_real = sp.upsert_research_memory
def _slow(*a, **k):          # force the children to overlap inside the critical section (LQ-1962 R-4)
    time.sleep(0.3)
    return _real(*a, **k)
sp.upsert_research_memory = _slow
e = C.EntityRef(name="Synthetic Corp", symbol="SYNTH", security_guid=sys.argv[3], issuer_guid="11111111-2222-4333-8444-666666666666")
time.sleep(max(0.0, float(sys.argv[4]) - time.time()))
SpineAskMemory(spine_path=Path(sys.argv[2])).append(entity=e, kind="ask.answer_version", summary="v1 final: synthetic answer", ref="ask_x:v1")
"""


def test_concurrent_processes_yield_one_memory(tmp_path):
    p = tmp_path / "spine.jsonl"
    go = time.time() + 2.0
    procs = [subprocess.Popen([sys.executable, "-c", _CHILD, str(ROOT), str(p), GUID, str(go)]) for _ in range(6)]
    assert [x.wait(timeout=60) for x in procs] == [0] * 6
    assert len(_lines(p)) == 1 and _copies(p) == 1


def test_rebuild_seeds_the_index_from_a_pre_existing_spine_read_only(tmp_path, monkeypatch):
    from scripts.lib.cio_ask_memory_index import MemoryIndex

    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, **ANSWER)
    for i in range(120):
        mem.append(entity=ENT, kind="ask.source", summary=f"Src {i}", ref=f"ask_y:{i}")
    (tmp_path / "spine.jsonl.askidx").unlink()            # as if written before the index existed
    from scripts.lib import cio_ask_memory_index as mi

    mi._CACHE.clear()
    before_bytes = p.read_bytes()
    assert MemoryIndex(p).rebuild(p) >= 121
    assert p.read_bytes() == before_bytes                 # the spine was only read
    assert mem.append(entity=ENT, **ANSWER)["spine"]["deduped"] is True


def test_unavailable_lock_still_writes_and_says_so(tmp_path, monkeypatch):
    from scripts.lib import cio_ask_memory_index as mi

    def nolock(self):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(mi.MemoryIndex, "locked", nolock)
    r = SpineAskMemory(spine_path=tmp_path / "spine.jsonl").append(entity=ENT, **ANSWER)
    assert r["spine"]["ok"] is True and r["spine"]["dedupe_index"].startswith("unavailable:OSError")
    assert len(_lines(tmp_path / "spine.jsonl")) == 1     # memory never lost to an index fault


# ── LQ-20261107-1962: the index must not outlive the spine it describes ────────────────────────────────────────────
def test_r1_emptied_spine_is_not_answered_from_the_index(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, **ANSWER)
    p.write_text("")                                      # truncated / restored-empty
    r = mem.append(entity=ENT, **ANSWER)
    assert r["spine"]["ok"] is True and r["spine"].get("deduped") is not True
    assert str(r["spine"]["dedupe_index"]).startswith("reseeded:")
    assert _copies(p) == 1                                # the memory is back in the spine


def test_r1_replaced_spine_from_backup_without_the_memory_is_rewritten(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, kind="ask.source", summary="Src 0 (filing)", ref="ask_y:0")
    backup = p.read_bytes()
    mem.append(entity=ENT, **ANSWER)
    p.unlink()
    p.write_bytes(backup + b"")                           # restore: new inode, memory missing
    r = mem.append(entity=ENT, **ANSWER)
    assert r["spine"].get("deduped") is not True and _copies(p) == 1
    assert list(tmp_path.glob("spine.jsonl.askidx.stale-*"))   # old index archived, never deleted


def test_r1_unmodified_spine_still_dedupes_by_index_without_reseed(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, **ANSWER)
    r = mem.append(entity=ENT, **ANSWER)
    assert r["spine"]["deduped"] is True and r["spine"]["by"] == "index" and "dedupe_index" not in r["spine"]
    assert not list(tmp_path.glob("*.stale-*"))


def test_r1_index_without_a_stamp_is_untrusted_and_rebuilt(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, **ANSWER)
    Path(str(p) + ".askidx.meta").unlink()                # legacy (LQ-1947) index: no record of its spine
    r = mem.append(entity=ENT, **ANSWER)
    assert r["spine"]["deduped"] is True and r["spine"]["dedupe_index"] == "reseeded:no_stamp"
    assert _copies(p) == 1                                # rebuild found it in the spine: still one


def test_r2_torn_index_line_does_not_swallow_the_next_fingerprint(tmp_path):
    from scripts.lib import cio_ask_memory_index as I
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, kind="ask.source", summary="Src 0 (filing)", ref="ask_y:0")
    with Path(str(p) + ".askidx").open("a") as fh:
        fh.write("ab" * 20)                               # crash mid-write: no newline
    mem.append(entity=ENT, **ANSWER)
    I._CACHE.clear()
    idx = I.MemoryIndex(p)
    fp = I.fingerprint("SYNTH", GUID, "ask.answer_version", "ask_x:v1", "[ask.answer_version] v1 final: synthetic answer")
    assert idx.has(fp)


# ── LQ-20261107-1980: another process's reseed, same-inode restores, archive collisions ───────────────────────────────
_SHRINK_REBUILD = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import cio_ask_contract as C
from scripts.lib.cio_ask_memory import SpineAskMemory
p = Path(sys.argv[2]); p.write_text("")          # restore-to-empty by a different process
e = C.EntityRef(name="Synthetic Corp", symbol="SYNTH", security_guid=sys.argv[3], issuer_guid="11111111-2222-4333-8444-666666666666")
r = SpineAskMemory(spine_path=p).append(entity=e, kind="ask.source", summary="B src", ref="ask_b:1")
print(r["spine"].get("dedupe_index"))
"""


def test_must_reseed_by_another_process_is_seen_by_a_long_lived_cache(tmp_path):
    p = tmp_path / "spine.jsonl"
    a = SpineAskMemory(spine_path=p)
    a.append(entity=ENT, **ANSWER)
    a.append(entity=ENT, kind="ask.source", summary="A src", ref="ask_a:1")   # A's in-process cache now holds ANSWER
    out = subprocess.run([sys.executable, "-c", _SHRINK_REBUILD, str(ROOT), str(p), GUID],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip().startswith("reseeded:"), out
    assert _copies(p) == 0
    r = a.append(entity=ENT, **ANSWER)                                          # A retries: the memory is gone
    assert r["spine"].get("deduped") is not True
    assert _copies(p) == 1


def test_should_same_inode_restore_that_regrew_is_voided_by_content(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, kind="ask.source", summary="Src 0 (filing)", ref="ask_y:0")
    backup = p.read_bytes()
    mem.append(entity=ENT, **ANSWER)
    stamped = p.stat().st_size
    other = tmp_path / "other.jsonl"
    o = SpineAskMemory(spine_path=other)
    for i in range(1, 12):
        o.append(entity=ENT, kind="ask.source", summary=f"Other {i} (filing)", ref=f"ask_o:{i}")
    ino = p.stat().st_ino
    with p.open("r+b") as fh:                         # restore IN PLACE: same inode, regrown past the stamp
        fh.truncate(0)
        fh.write(backup + other.read_bytes())
    assert p.stat().st_ino == ino and p.stat().st_size > stamped and _copies(p) == 0
    r = mem.append(entity=ENT, **ANSWER)
    assert r["spine"].get("deduped") is not True and r["spine"]["dedupe_index"] == "reseeded:spine_content_changed"
    assert _copies(p) == 1


def test_growth_by_another_writer_does_not_void_the_index(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, **ANSWER)
    sp.upsert_research_memory("OTHR", silo="cio", kind="note", summary="x", artifact_id="z:1", refs=["z:1"],
                              tags=["t"], subject_guid="99999999-2222-4333-8444-555555555555", path=p)
    r = mem.append(entity=ENT, **ANSWER)
    assert r["spine"]["deduped"] is True and r["spine"]["by"] == "index" and "dedupe_index" not in r["spine"]


def test_minor_two_reseeds_in_one_second_keep_both_archives(tmp_path):
    from scripts.lib.cio_ask_memory_index import MemoryIndex
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, **ANSWER)
    idx = MemoryIndex(p)
    with idx.locked():
        idx.reseed()
        idx.reseed()
    assert len(list(tmp_path.glob("spine.jsonl.askidx.stale-*"))) == 2


def test_minor_rebuild_stamps_once(tmp_path, monkeypatch):
    from scripts.lib.cio_ask_memory_index import MemoryIndex
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    for i in range(6):
        mem.append(entity=ENT, kind="ask.source", summary=f"S{i}", ref=f"ask_s:{i}")
    n = []
    real = MemoryIndex._stamp
    monkeypatch.setattr(MemoryIndex, "_stamp", lambda self: (n.append(1), real(self))[1])
    with MemoryIndex(p).locked() as idx:
        idx.reseed()
    assert len(n) == 1
