"""kb_lessons follow-ups to #1617 (2026-10-09): same-model similarity only,
counter baseline read under the lock, durable appends, lesson_promotion uses
derived counters.

Every test runs in a tmp dir (paths patched); live state is never touched and
no embedding endpoint is called (embed functions are stubbed).
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "scripts" / "lib"), str(ROOT / "scripts"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from lib.advisory import kb_lessons as kb  # noqa: E402

Q = [1.0, 0.0, 0.0, 0.0]


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "RUNTIME", tmp_path)
    monkeypatch.setattr(kb, "LESSONS_PATH", tmp_path / "advisory_kb_lessons.jsonl")
    monkeypatch.setattr(kb, "CANDIDATES_PATH", tmp_path / "cands.jsonl")
    monkeypatch.setattr(kb, "APPLICATIONS_PATH", tmp_path / "apps.jsonl")
    monkeypatch.setattr(kb, "LESSONS_INDEX", tmp_path / "idx.json")
    monkeypatch.setattr(kb, "EMBEDDINGS_PATH", None)
    monkeypatch.setattr(kb, "embed_text", lambda t: (list(Q), "test-embed"))
    calls: list[str] = []

    def fake_ollama(text, model=kb.EMBED_MODEL):
        calls.append(model)
        return None  # e.g. qwen3-embedding:8b is outside the Ollama allowlist

    monkeypatch.setattr(kb, "ollama_embed", fake_ollama)
    monkeypatch.setattr(kb, "_DIM_MISMATCH_LOGGED", set())
    return calls


def _row(lid, emb, model, title="zzz", body="yyy", **kw):
    r = {"id": lid, "ts": "2026-10-01T00:00:00+00:00", "status": "ratified", "title": title, "body": body,
         "embedding": emb, "embedding_model": model}
    r.update(kw)
    return r


def _write(rows):
    kb.LESSONS_PATH.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


# ── 1. cosine never compares across models ─────────────────────────────────────
def test_cosine_refuses_dimension_mismatch_instead_of_truncating():
    assert kb.cosine([1.0, 0.0], [1.0, 0.0, 5.0]) == 0.0
    assert kb.cosine([0.6, 0.8], [0.6, 0.8]) == pytest.approx(1.0)


def test_mixed_model_lessons_rank_by_same_model_similarity_only(store):
    qwen = [1.0, 0.0, 0.0, 0.0] + [0.0] * 4092  # old min(len) truncation scored this 1.0
    _write([
        _row("A", list(Q), "test-embed"),
        _row("B", qwen, "qwen3-embedding:8b"),
        _row("B2", qwen, "qwen3-embedding:8b"),
        _row("C", [0.6, 0.8, 0.0, 0.0], "test-embed"),
    ])
    got = [lsn["id"] for lsn in kb.retrieve_lessons_for_row(query_text="cash idle", limit=4)]
    assert got[:2] == ["A", "C"]
    assert set(got[2:]) == {"B", "B2"}
    assert store == ["qwen3-embedding:8b"]  # query embedded once per model per call, never cross-model


def test_unusable_model_falls_back_to_lexical_similarity(store):
    qwen = [0.0] * 4096
    _write([
        _row("LEX", qwen, "qwen3-embedding:8b", title="idle cash structural", body="ips target"),
        _row("NOLEX", qwen, "qwen3-embedding:8b", title="other", body="thing"),
    ])
    got = [lsn["id"] for lsn in kb.retrieve_lessons_for_row(query_text="idle cash", limit=2)]
    assert got == ["LEX", "NOLEX"]
    assert kb.lexical_similarity("idle cash", {"title": "idle cash structural", "body": ""}) == pytest.approx(2 / 3)


def test_embedding_ref_model_used_and_other_model_embedded_with_its_own_model(store, monkeypatch):
    seen: list[str] = []

    def ollama(text, model=kb.EMBED_MODEL):
        seen.append(model)
        return [0.0, 1.0, 0.0, 0.0] if model == "other-model" else None

    monkeypatch.setattr(kb, "ollama_embed", ollama)
    lesson = _row("O", [0.0, 1.0, 0.0, 0.0], None)
    lesson.pop("embedding_model")
    lesson["embedding_ref"] = {"content_sha": "x", "model": "other-model"}
    _write([lesson, _row("T", [0.0, 0.0, 1.0, 0.0], "test-embed")])
    got = kb.retrieve_lessons_for_row(query_text="q", limit=2)
    assert [lsn["id"] for lsn in got] == ["O", "T"]
    assert seen == ["other-model"]


def test_hash_model_lessons_use_hash_query(store):
    q = "thrash flip flop"
    _write([_row("H", kb.hash_embed(q), kb.HASH_EMBED_MODEL), _row("Z", [0.0] * kb.EMBED_DIM, kb.HASH_EMBED_MODEL)])
    got = [lsn["id"] for lsn in kb.retrieve_lessons_for_row(query_text=q, limit=2)]
    assert got == ["H", "Z"]
    assert store == []


def test_dimension_mismatch_same_model_is_skipped_and_logged_once(store, caplog):
    _write([_row("D1", [1.0, 0.0], "test-embed"), _row("D2", [1.0, 0.0], "test-embed")])
    with caplog.at_level(logging.WARNING, logger=kb.__name__):
        kb.retrieve_lessons_for_row(query_text="q", limit=2)
        kb.retrieve_lessons_for_row(query_text="q", limit=2)
    msgs = [r for r in caplog.records if "dimension mismatch" in r.getMessage()]
    assert len(msgs) == 1


# ── 2. retire / re-ratify read the counter baseline under the lock ─────────────
def _race(store_fn, monkeypatch):
    """A counter event racing the content-row write must never be lost."""
    real = kb.list_lessons
    state = {"thread": None}

    def racing_list(*a, **kw):
        out = real(*a, **kw)
        if state["thread"] is None:
            t = threading.Thread(target=kb._append_counter_event,
                                 args=({"kind": "application", "lesson_id": "L1", "hit": None, "cited": False},))
            state["thread"] = t
            t.start()
            t.join(timeout=0.3)  # with the fix the event blocks on the lock until the row is written
        return out

    monkeypatch.setattr(kb, "list_lessons", racing_list)
    store_fn()
    state["thread"].join(timeout=10)
    monkeypatch.setattr(kb, "list_lessons", real)
    return real(status=None)[0]


def test_retire_baseline_inside_lock_loses_no_racing_event(store, monkeypatch):
    _write([_row("L1", list(Q), "test-embed", applications=5)])
    got = _race(lambda: kb.retire_lesson("L1"), monkeypatch)
    assert got["status"] == "retired" and got["applications"] == 6


def test_reratify_baseline_inside_lock_loses_no_racing_event(store, monkeypatch):
    _write([_row("L1", list(Q), "test-embed", status="retired", applications=5)])
    got = _race(lambda: kb.ratify_lesson("L1"), monkeypatch)
    assert got["status"] == "ratified" and got["applications"] == 6


# ── 3. durable appends, tolerant embeddings store ──────────────────────────────
def test_append_once_repairs_missing_trailing_newline_and_fsyncs(tmp_path, monkeypatch):
    synced: list[int] = []
    monkeypatch.setattr(kb.os, "fsync", lambda fd: synced.append(fd))
    p = tmp_path / "x.jsonl"
    p.write_bytes(b'{"a": 1}')  # a writer died before its newline
    kb._append_once(p, json.dumps({"b": 2}) + "\n")
    kb._append_once(p, json.dumps({"c": 3}) + "\n")
    assert [json.loads(x) for x in p.read_text().splitlines()] == [{"a": 1}, {"b": 2}, {"c": 3}]
    assert len(synced) == 2
    empty = tmp_path / "new.jsonl"
    kb._append_once(empty, "{}\n")
    assert empty.read_text() == "{}\n"


def test_load_embeddings_skips_non_object_lines_with_warning(store, caplog):
    path = kb._embeddings_path()
    path.write_text("\n".join([
        json.dumps([1, 2, 3]),
        json.dumps("str"),
        json.dumps({"id": "L1", "content_sha": "s", "model": "m", "embedding": [0.1]}),
    ]) + "\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=kb.__name__):
        out = kb._load_embeddings()
    assert out == {"L1|s|m": [0.1]}
    assert sum("non-object" in r.getMessage() for r in caplog.records) == 2


# ── 4. lesson_promotion reads derived counters from the latest row ─────────────
def test_lesson_promotion_uses_latest_row_and_derived_counters(tmp_path):
    import lesson_promotion as lp

    cio = tmp_path / "data" / "cio"
    rt = tmp_path / "data" / "runtime"
    cio.mkdir(parents=True)
    rt.mkdir(parents=True)
    rows = [
        {"id": "L1", "ts": "2026-09-01T00:00:00+00:00", "status": "ratified",
         "title": "Cash overweight is structural not a trade", "applications": 0, "hit_rate": None},
        {"id": "L1", "ts": "2026-10-01T00:00:00+00:00", "status": "ratified",
         "title": "Cash overweight is structural not a trade", "applications": 2, "hits": 1, "scored": 2,
         "hit_rate": 0.5},
        {"id": "L2", "ts": "2026-09-01T00:00:00+00:00", "status": "ratified",
         "title": "Retired later lesson should be excluded"},
        {"id": "L2", "ts": "2026-10-01T00:00:00+00:00", "status": "retired",
         "title": "Retired later lesson should be excluded"},
    ]
    (rt / "advisory_kb_lessons.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (rt / "advisory_kb_lesson_applications.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
        {"ts": "2026-10-02T00:00:00+00:00", "kind": "application", "lesson_id": "L1", "counter_v": 2},
        {"ts": "2026-10-03T00:00:00+00:00", "kind": "hit", "lesson_id": "L1", "counter_v": 2, "hit": True},
    ]), encoding="utf-8")
    procs = lp.gather(tmp_path, env={"TRADEAI_CIO_DIR": str(cio)})
    kb_procs = {p["evidence"].get("applications"): p for p in procs if "Cash overweight" in p["statement"]}
    assert list(kb_procs) == [3]
    assert kb_procs[3]["evidence"]["hit_rate"] == pytest.approx(2 / 3)
    assert not any("Retired later" in p["statement"] for p in procs)
