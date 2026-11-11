"""LQ-20261107-1929 (SEV-1): Ask-the-CIO memory retries must not flood the research spine.

Synthetic fixtures only (public repo). A retry of sync_answer_memory re-sends the same (kind, ref, summary); the
spine write must be idempotent on it (spine vs spine), and recall must not return N copies of one line.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import cio_ask_contract as C  # noqa: E402
from scripts.lib.cio_ask_memory import SpineAskMemory  # noqa: E402

GUID = "11111111-2222-4333-8444-555555555555"
ISSUER = "11111111-2222-4333-8444-666666666666"
ENT = C.EntityRef(name="Synthetic Corp", symbol="SYNTH", security_guid=GUID, issuer_guid=ISSUER)


def _lines(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_retry_of_the_same_answer_summary_writes_the_spine_once(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    first = mem.append(entity=ENT, kind="ask.answer_version", summary="v14 final: synthetic answer", ref="ask_x:v14")
    assert first["spine"]["ok"] is True
    size = p.stat().st_size
    for _ in range(25):                                   # the retry loop
        r = mem.append(entity=ENT, kind="ask.answer_version", summary="v14 final: synthetic answer", ref="ask_x:v14")
        assert r["spine"]["ok"] is True                   # acknowledged, so the retry sees the summary as verified
    assert len(_lines(p)) == 1 and p.stat().st_size == size
    tip = _lines(p)[-1]
    copies = [c for c in tip["contributions"] if c["kind"] == "ask.answer_version" and c["artifact_id"] == "ask_x:v14"]
    assert len(copies) == 1


def test_a_new_version_or_a_different_summary_is_still_written(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, kind="ask.answer_version", summary="v1 draft", ref="ask_x:v1")
    mem.append(entity=ENT, kind="ask.answer_version", summary="v2 draft", ref="ask_x:v2")
    mem.append(entity=ENT, kind="ask.source", summary="Src A (filing, as of 2026-11-01)", ref="ask_x:v2")
    mem.append(entity=ENT, kind="ask.source", summary="Src B (news, as of 2026-11-02)", ref="ask_x:v2")   # same ref+kind
    assert len(_lines(p)) == 4


def test_retries_do_not_evict_the_original_question_from_the_window(tmp_path):
    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, kind="ask.asked", summary="Is SYNTH a buy?", ref="ask_x")
    for _ in range(150):
        mem.append(entity=ENT, kind="ask.answer_version", summary="v1 final: synthetic", ref="ask_x:v1")
    got = mem.recall(entity=ENT, limit=4)
    assert any("Is SYNTH a buy?" in (i["summary"] or "") for i in got), got


def test_recall_collapses_duplicate_spine_lines_already_on_disk(tmp_path):
    """Pollution that predates the fix (N copies of one contribution in the tip) must not fill recall."""
    from scripts.lib.cross_asset import security_research_spine as S

    p = tmp_path / "spine.jsonl"
    spine = S.empty_spine("SYNTH", subject_guid=GUID)
    spine["tags"] = ["ask_the_cio"]
    for i in range(30):
        spine = S.contribute(spine, silo="cio", kind="ask.answer_version", summary="[ask.answer_version] v14 same",
                             artifact_id="ask_x:v14", tags=["ask_the_cio", "ask_answer_version"])
    spine = S.contribute(spine, silo="cio", kind="ask.asked", summary="[ask.asked] Is SYNTH a buy?",
                         artifact_id="ask_x", tags=["ask_the_cio", "ask_asked"])
    S.append_spine(spine, path=p)
    got = SpineAskMemory(spine_path=p).recall(entity=ENT, limit=4)
    summaries = [i["summary"] for i in got]
    assert len(summaries) == len(set(summaries)) == 2, summaries


# ── dry-run compaction report (never writes) ──

def test_compaction_dry_run_reports_pure_retry_lines_and_never_writes(tmp_path):
    import hashlib

    from scripts import cio_spine_compact_dryrun as D
    from scripts.lib.cross_asset import security_research_spine as S

    p = tmp_path / "spine.jsonl"
    spine = S.empty_spine("SYNTH", subject_guid=GUID)
    S.append_spine(S.contribute(spine, silo="cio", kind="ask.asked", summary="q", artifact_id="a", tags=["ask_the_cio"]), path=p)
    tip = S.load_latest("SYNTH", path=p)
    for _ in range(5):          # pre-fix retry: same contribution appended again, nothing else changes
        tip = S.contribute(tip, silo="cio", kind="ask.answer_version", summary="s", artifact_id="a:v1", tags=["ask_the_cio"])
        S.append_spine(tip, path=p)
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    out = D.analyse(p)
    assert out["dry_run"] is True and out["lines"] == 6 and out["symbols"] == 1
    assert out["would_drop_lines"] == 3 and out["would_keep_lines"] == 3      # first, first-new-key and the live tip kept
    assert 0 < out["would_drop_bytes"] < out["size_bytes"]
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before               # byte-identical: read-only
    assert D.main(["--path", str(p), "--report", str(p)]) == 2                # refuses to overwrite the spine


def test_unreadable_dedupe_read_is_visible_in_the_receipt_and_still_writes(tmp_path, monkeypatch):
    """LQ-1943 N3 (E22): 'could not check' must not look like 'checked, not a duplicate'."""
    import scripts.lib.cross_asset.security_research_spine as sp

    p = tmp_path / "spine.jsonl"
    mem = SpineAskMemory(spine_path=p)
    mem.append(entity=ENT, kind="ask.answer_version", summary="v1 final", ref="ask_x:v1")
    real, calls = sp.load_latest, {"n": 0}

    def flaky(*a, **k):                                   # the dedupe read fails once; the upsert's own read works
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient")
        return real(*a, **k)

    monkeypatch.setattr(sp, "load_latest", flaky)
    r = mem.append(entity=ENT, kind="ask.answer_version", summary="v1 final", ref="ask_x:v1")
    assert r["spine"]["ok"] is True and r["spine"]["deduped"] == "unreadable"
    assert len(_lines(p)) == 2                            # unreadable tip must not block the write
    monkeypatch.setattr(sp, "load_latest", real)
    ok = mem.append(entity=ENT, kind="ask.answer_version", summary="v1 final", ref="ask_x:v1")
    assert ok["spine"] == {"ok": True, "deduped": True}   # readable again: a true dedupe
