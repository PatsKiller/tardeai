"""kb_lessons writer (2026-10-09): applications/hits are counter events, not
re-appended lesson rows; readers derive counters; vectors stored once.

Every test runs in a tmp dir (paths patched); live state is never touched.
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "scripts"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from lib import kb_lesson_counters as counters  # noqa: E402
from lib.advisory import kb_lessons as kb  # noqa: E402
from lib.advisory import kb_lessons_retention as ret  # noqa: E402


def _vec(text: str) -> list[float]:
    return kb.hash_embed(text, 32)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "RUNTIME", tmp_path)
    monkeypatch.setattr(kb, "LESSONS_PATH", tmp_path / "advisory_kb_lessons.jsonl")
    monkeypatch.setattr(kb, "CANDIDATES_PATH", tmp_path / "cands.jsonl")
    monkeypatch.setattr(kb, "APPLICATIONS_PATH", tmp_path / "apps.jsonl")
    monkeypatch.setattr(kb, "LESSONS_INDEX", tmp_path / "idx.json")
    monkeypatch.setattr(kb, "EMBEDDINGS_PATH", None)
    monkeypatch.setattr(kb, "embed_text", lambda t: (_vec(t), "test-embed"))
    return tmp_path


def _ratified(title: str = "Cash is structural") -> dict:
    c = kb.propose_lesson(title=title, body="body text", symbols=["SCHD"], verdict_types=["TRIM"],
                          source="reflection_ips")
    return kb.ratify_lesson(c["id"], by="test")


# ── reference: the pre-10-09 counter math (one re-appended row per event) ──────
def _legacy_apply(lesson: dict, kind: str, hit, cited: bool) -> dict:
    apps, hits, scored, cit = counters.base_counts(lesson)
    if kind == "application":
        apps += 1
        cit += 1 if cited else 0
        if hit is not None:
            scored += 1
            hits += 1 if hit else 0
    else:
        scored += 1
        hits += 1 if hit else 0
    out = dict(lesson)
    out.update(applications=apps, hits=hits, scored=scored, citations=cit,
               hit_rate=counters.hit_rate(hits, scored))
    return out


def test_application_does_not_append_lesson_row_and_counts(store):
    lesson = _ratified()
    size = kb.LESSONS_PATH.stat().st_size
    kb.record_application(lesson["id"], symbol="SCHD", cited_in_rationale=True, source_row_id="r1")
    kb.record_application(lesson["id"], symbol="SCHD", hit=True, source_row_id="r2")
    assert kb.record_hit(lesson["id"], hit=False, source_row_id="r1", horizon_d=5)
    assert not kb.record_hit(lesson["id"], hit=False, source_row_id="r1", horizon_d=5)  # idempotent
    assert kb.LESSONS_PATH.stat().st_size == size
    got = kb.list_lessons()[0]
    assert (got["applications"], got["hits"], got["scored"], got["citations"]) == (2, 1, 2, 1)
    assert got["hit_rate"] == 0.5
    assert got["embedding"] == _vec(f"{lesson['title']}\n{lesson['body']}")


def test_derived_counters_match_legacy_math_on_random_sequence(store):
    import random
    lesson = _ratified()
    rng = random.Random(7)
    expect = dict(kb.list_lessons()[0])
    for i in range(60):
        if rng.random() < 0.7:
            hit = rng.choice([None, None, True, False])
            cited = rng.random() < 0.3
            kb.record_application(lesson["id"], hit=hit, cited_in_rationale=cited, source_row_id=f"r{i}")
            expect = _legacy_apply(expect, "application", hit, cited)
        else:
            hit = rng.random() < 0.6
            if kb.record_hit(lesson["id"], hit=hit, source_row_id=f"h{i}", horizon_d=5):
                expect = _legacy_apply(expect, "hit", hit, False)
    got = kb.list_lessons(status=None)[0]
    for k in ("applications", "hits", "scored", "citations", "hit_rate", "status"):
        assert got[k] == expect[k], k


def test_legacy_rows_read_unchanged_and_unmarked_events_not_recounted(store):
    legacy = {"id": "L1", "ts": "2026-09-01T00:00:00+00:00", "status": "ratified", "title": "t", "body": "b",
              "applications": 7, "hits": 1, "scored": 2, "citations": 1, "hit_rate": 0.5, "embedding": [1.0, 0.0]}
    kb.LESSONS_PATH.write_text(json.dumps(legacy) + "\n")
    # legacy (unmarked) application rows are already inside the row's counters
    kb.APPLICATIONS_PATH.write_text(json.dumps({"ts": "2026-09-02T00:00:00+00:00", "kind": "application",
                                                "lesson_id": "L1", "hit": None, "cited": False}) + "\n")
    assert kb.list_lessons() == [legacy]
    kb.record_application("L1", source_row_id="r9")
    got = kb.list_lessons()[0]
    assert got["applications"] == 8 and got["scored"] == 2 and got["hit_rate"] == 0.5


def test_ratify_from_candidate_resets_and_retire_carries_counters(store):
    lesson = _ratified()
    for i in range(3):
        kb.record_application(lesson["id"], source_row_id=f"r{i}")
    retired = kb.retire_lesson(lesson["id"], reason="manual")
    assert retired["applications"] == 3
    kb.record_application(lesson["id"], source_row_id="r-after-retire")
    assert kb.list_lessons(status="retired")[0]["applications"] == 4
    again = kb.ratify_lesson(lesson["id"], by="test")  # from candidate: counters 0, as before
    assert again["applications"] == 0
    assert kb.list_lessons()[0]["applications"] == 0


def test_auto_retire_still_fires_from_derived_counters(store):
    lesson = _ratified()
    for i in range(kb.RETIRE_MIN_APPS):
        kb.record_application(lesson["id"], source_row_id=f"r{i}")
        kb.record_hit(lesson["id"], hit=False, source_row_id=f"r{i}", horizon_d=5)
    assert kb.list_lessons(status=None)[0]["status"] == "retired"


def test_embedding_stored_once_per_content_and_model(store):
    lesson = _ratified()
    kb.retire_lesson(lesson["id"])
    kb.ratify_lesson(lesson["id"])
    rows = [json.loads(x) for x in kb.LESSONS_PATH.read_text().splitlines()]
    assert all("embedding" not in r and r["embedding_ref"]["model"] == "test-embed" for r in rows)
    emb_rows = kb._embeddings_path().read_text().splitlines()
    assert len(emb_rows) == 1
    assert kb._embeddings_path().name == "advisory_kb_lessons_embeddings.jsonl"


def test_rotation_cannot_archive_the_only_vector_or_baseline(store, tmp_path):
    old = {"id": "L1", "ts": "2026-01-01T00:00:00+00:00", "status": "ratified", "title": "t", "body": "b",
           "applications": 5, "embedding": [0.6, 0.8], "embedding_model": "m"}
    kb.LESSONS_PATH.write_text(json.dumps(old) + "\n")
    kb.retire_lesson("L1")  # new slim content row, vector moved to the store
    kb.record_application("L1", source_row_id="x")
    now = datetime.now(timezone.utc) + timedelta(days=1)
    cfg = dict(ret._DEFAULTS)
    out = ret.apply(kb.LESSONS_PATH, archive_dir=tmp_path / "arch", cfg=cfg, now=now, retain_days=0)
    assert out.get("ok") is not False
    live = [json.loads(x) for x in kb.LESSONS_PATH.read_text().splitlines()]
    assert len(live) == 1 and "embedding" not in live[0]
    got = kb.list_lessons(status=None)[0]
    assert got["embedding"] == [0.6, 0.8] and got["applications"] == 6


def test_concurrent_applications_lose_no_increment(store):
    lesson = _ratified()

    def worker(n: int) -> None:
        for i in range(10):
            kb.record_application(lesson["id"], source_row_id=f"t{n}-{i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert kb.list_lessons()[0]["applications"] == 60


def test_maturity_view_uses_derived_counters(tmp_path, monkeypatch):
    from scripts.lib.maturity_control import lessons as mat
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    (rt / "advisory_kb_lessons.jsonl").write_text(json.dumps(
        {"id": "L1", "ts": "2026-10-01T00:00:00+00:00", "status": "ratified", "title": "t", "applications": 2}) + "\n")
    (rt / "advisory_kb_lesson_applications.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
        {"ts": "2026-09-30T00:00:00+00:00", "kind": "application", "lesson_id": "L1", "counter_v": 2},  # before row
        {"ts": "2026-10-02T00:00:00+00:00", "kind": "application", "lesson_id": "L1", "counter_v": 2, "cited": True},
        {"ts": "2026-10-03T00:00:00+00:00", "kind": "hit", "lesson_id": "L1", "counter_v": 2, "hit": True},
        {"ts": "2026-10-04T00:00:00+00:00", "kind": "application", "lesson_id": "L1"},  # legacy, unmarked
    ]))
    view = mat.collect_lessons(root=tmp_path)
    row = next(lsn for lsn in view["lessons"] if lsn["lesson_id"] == "L1")
    assert (row["applications"], row["hits"], row["hit_rate"], row["citations"]) == (3, 1, 1.0, 1)
