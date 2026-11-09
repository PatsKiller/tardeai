"""ANCHOR: LQ1513_LEASE_AND_ACRONYM_ARCHIVE_20261109. LQ-20261107-1513.

A PROCESSING review older than the lease returns to PENDING. The row is not deleted.
An active COLA or RMD insight that is only the bare acronym is archived, then set inactive.
A cashtag or the issuer's full name stays active. Synthetic rows only. No database.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("TRADE_AI_CI", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Cur:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchall(self):
        return list(self.rows)


def _sql(cur) -> str:
    return "\n".join(sql for sql, _params in cur.calls)


def test_expired_processing_rows_return_to_pending_and_are_not_deleted():
    worker = _load("lq1513_proposal_worker", "proposal_llm_review_worker.py")
    now = datetime(2026, 11, 9, 13, 0, tzinfo=timezone.utc)
    rows = [
        {"id": 11, "proposal_id": 1, "started_at": datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc), "attempts": 1},
        {"id": 12, "proposal_id": 2, "started_at": None, "attempts": 0},
    ]
    preview = _Cur(rows)
    got = worker.requeue_expired_processing(preview, now=now, lease_s=3600, apply=False)
    assert [row["id"] for row in got] == [11, 12]
    assert preview.calls[0][1][0] == now - timedelta(seconds=3600)
    assert "UPDATE" not in _sql(preview)
    assert "DELETE" not in _sql(preview)

    applied = _Cur(rows)
    worker.requeue_expired_processing(applied, now=now, lease_s=3600, apply=True)
    text = _sql(applied)
    assert "DELETE" not in text
    assert "queue_status = 'PENDING'" in text
    assert "lease_expired" in text
    assert applied.calls[1][1][0] == [11, 12]
    assert "attempts" not in applied.calls[1][0]

    empty = _Cur([])
    assert worker.requeue_expired_processing(empty, now=now, lease_s=3600, apply=True) == []
    assert len(empty.calls) == 1


def test_a_negative_lease_is_refused():
    worker = _load("lq1513_proposal_worker_lease", "proposal_llm_review_worker.py")
    try:
        worker.requeue_expired_processing(_Cur([]), now=datetime.now(timezone.utc), lease_s=-1, apply=False)
    except ValueError as exc:
        assert "lease_s" in str(exc)
    else:
        raise AssertionError("negative lease was accepted")


def _insights():
    return [
        {
            "id": 1, "symbol": "COLA", "active": True,
            "headline": "The 2027 COLA is official",
            "raw_text": "The 2027 COLA is official and retirees will see a strong raise.",
            "structured_thesis": "", "source_reference": "news:1",
            "created_at": "2026-11-08T00:00:00Z",
        },
        {
            "id": 2, "symbol": "COLA", "active": True,
            "headline": "Traders marked $COLA",
            "raw_text": "Traders marked $COLA after a dividend increase and strong growth.",
            "structured_thesis": "", "source_reference": "news:2",
            "created_at": "2026-11-08T00:00:00Z",
        },
        {
            "id": 3, "symbol": "COLA", "active": True,
            "headline": "Bottler results",
            "raw_text": "Coca-Cola Consolidated reported a dividend increase and strong growth.",
            "structured_thesis": "", "source_reference": "news:3",
            "created_at": "2026-11-08T00:00:00Z",
        },
        {
            "id": 4, "symbol": "RMD", "active": True,
            "headline": "RMD season",
            "raw_text": "The RMD deadline is this year's required distribution.",
            "structured_thesis": "", "source_reference": "news:4",
            "created_at": "2026-11-08T00:00:00Z",
        },
        {
            "id": 5, "symbol": "KO", "active": True,
            "headline": "KO", "raw_text": "KO raised its dividend.",
            "structured_thesis": "", "source_reference": "news:5",
            "created_at": "2026-11-08T00:00:00Z",
        },
    ]


def _session():
    return {
        "acronym_stoplist": {"COLA", "RMD"},
        "names_by_symbol": {"COLA": ["Coca-Cola Consolidated"], "RMD": ["ResMed"]},
    }


def test_bare_acronym_rows_are_archived_then_deactivated_and_real_mentions_stay(tmp_path):
    mod = _load("lq1513_insight_extractor", "research_insight_extractor.py")
    preview = _Cur(_insights())
    archive = tmp_path / "archive.jsonl"
    report = mod.supersede_false_acronyms(
        preview, symbols=["COLA", "RMD"], session=_session(), apply=False, archive_path=archive)
    assert report["selected"] == 2
    assert report["ids"] == [1, 4]
    assert report["kept"] == 3
    assert report["archive"] is None
    assert not archive.exists()
    assert "UPDATE" not in _sql(preview)
    assert "DELETE" not in _sql(preview)

    applied = _Cur(_insights())
    report = mod.supersede_false_acronyms(
        applied, symbols=["cola", "rmd"], session=_session(), apply=True, archive_path=archive)
    assert report["ids"] == [1, 4]
    text = _sql(applied)
    assert "DELETE" not in text
    assert "SET active = FALSE" in text
    assert applied.calls[1][1][0] == [1, 4]
    lines = [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines()]
    assert [line["id"] for line in lines] == [1, 4]
    assert {line["prior_active"] for line in lines} == {True}
    assert {line["reason"] for line in lines} == {"bare_acronym_stoplist"}
    assert all("raw_text" not in line for line in lines)


def test_the_repair_default_reads_the_config_file(tmp_path):
    mod = _load("lq1513_insight_extractor_default", "research_insight_extractor.py")
    cfg = tmp_path / "stoplist.json"
    cfg.write_text(
        json.dumps({"schema": "ResearchInsightAcronymStoplist@v1", "symbols": ["ZZZ", "SYN"]}),
        encoding="utf-8",
    )
    assert mod.default_repair_symbols([], path=cfg) == ["SYN", "ZZZ"]
    assert mod.default_repair_symbols(["--symbols", "syn,zzz"]) == ["SYN", "ZZZ"]
    shipped = json.loads(
        (ROOT / "config" / "research_insight_acronym_stoplist.json").read_text(encoding="utf-8")
    )
    assert mod.default_repair_symbols([]) == sorted(
        str(item).strip().upper() for item in shipped["symbols"] if str(item).strip()
    )


def test_ci_refuses_the_live_archive_path():
    mod = _load("lq1513_insight_extractor_ci", "research_insight_extractor.py")
    live = mod._account_persistent_root() / "data" / "cio" / "research_insight_acronym_archive.jsonl"
    try:
        mod._refuse_live_archive_under_ci(live)
    except RuntimeError as exc:
        assert "TRADE_AI_CI" in str(exc)
    else:
        raise AssertionError("live archive path was accepted under TRADE_AI_CI")
