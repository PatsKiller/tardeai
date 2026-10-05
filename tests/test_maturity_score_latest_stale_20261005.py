"""June maturity_score_latest.json is not a current score.

Readers stamp STALE when generated_at is older than 30 days and keep the
original timestamp. They do not invent a replacement score. The archived copy
data/runtime/archive/maturity_score_latest.json is never opened.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.control_plane_api import _select_rows, handle
from scripts.lib.campaign_maturity_truth import build_maturity_truth
from scripts.lib.canonical_store_registry import load_json_store
from scripts.lib.maturity_score_latest_reader import (
    ARCHIVE_REL,
    ArchivedMaturityScoreRefused,
    read_maturity_score_latest,
    stamp_maturity_score_payload,
)
from scripts.lib import maturity_score_latest_reader as reader

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_TOKEN = "data/runtime/archive/maturity_score_latest.json"
_READ_ATTRS = {"read_text", "read_bytes"}
_READ_NAMES = {"open", "load", "loads"}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_stamp_keeps_score_and_original_generated_at_when_older_than_30_days():
    generated = datetime(2026, 6, 28, 2, 7, 44, tzinfo=timezone.utc)
    raw = {"generated_at": _iso(generated), "final_maturity_score_of_5": 4.95, "meets_4_5": True}
    stamped = stamp_maturity_score_payload(raw, now=generated + timedelta(days=30, seconds=1))
    assert stamped["freshness"] == "STALE"
    assert stamped["status"] == "STALE"
    assert stamped["current"] is False
    assert stamped["original_generated_at"] == raw["generated_at"]
    assert stamped["generated_at"] == raw["generated_at"]
    assert stamped["final_maturity_score_of_5"] == 4.95
    assert stamped["meets_4_5"] is True
    assert "freshness" not in raw


def test_exactly_30_days_is_not_stale():
    generated = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)
    raw = {"generated_at": _iso(generated), "final_maturity_score_of_5": 3.25}
    stamped = stamp_maturity_score_payload(raw, now=generated + timedelta(days=30))
    assert stamped["freshness"] == "WITHIN_30D"
    assert stamped["current"] is True
    assert stamped["final_maturity_score_of_5"] == 3.25
    assert stamped["original_generated_at"] == raw["generated_at"]


def test_missing_generated_at_is_stale_without_a_new_score():
    raw = {"final_maturity_score_of_5": 4.95}
    stamped = stamp_maturity_score_payload(raw, now=datetime(2026, 10, 5, tzinfo=timezone.utc))
    assert stamped["freshness"] == "STALE"
    assert stamped["original_generated_at"] is None
    assert stamped["final_maturity_score_of_5"] == 4.95
    assert "generated_at" not in stamped


def _forbid_archive_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tripwire: opening or reading the archived score path is a failure."""
    real_read = Path.read_text
    real_open = Path.open

    def reject(self: Path) -> None:
        if self.name == "maturity_score_latest.json" and "archive" in self.parts:
            raise AssertionError(f"opened archived maturity score {self}")

    def guarded_read(self: Path, *args, **kwargs):
        reject(self)
        return real_read(self, *args, **kwargs)

    def guarded_open(self: Path, *args, **kwargs):
        reject(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    monkeypatch.setattr(Path, "open", guarded_open)


def test_reader_refuses_archive_path_before_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    archive = tmp_path / ARCHIVE_REL
    _write(archive, {"generated_at": "2026-10-05T00:00:00Z", "final_maturity_score_of_5": 4.95})
    _forbid_archive_io(monkeypatch)
    with pytest.raises(ArchivedMaturityScoreRefused):
        read_maturity_score_latest(archive)
    assert ARCHIVE_REL == ARCHIVE_TOKEN


def test_load_json_store_stamps_stale_and_does_not_rewrite_file(tmp_path: Path):
    live = tmp_path / "data/runtime/maturity_score_latest.json"
    original = _iso(datetime.now(timezone.utc) - timedelta(days=40))
    _write(live, {"generated_at": original, "final_maturity_score_of_5": 4.95})
    before = live.read_bytes()
    loc = load_json_store("runtime.maturity", root=tmp_path)
    assert loc["status"] == "STALE"
    assert loc["available"] is False
    assert loc["current"] is False
    assert loc["original_generated_at"] == original
    data = loc["data"]
    assert data["freshness"] == "STALE"
    assert data["original_generated_at"] == original
    assert data["generated_at"] == original
    assert data["final_maturity_score_of_5"] == 4.95
    assert live.read_bytes() == before


def test_load_json_store_leaves_a_recent_score_unstale(tmp_path: Path):
    live = tmp_path / "data/runtime/maturity_score_latest.json"
    original = _iso(datetime.now(timezone.utc) - timedelta(days=2))
    _write(live, {"generated_at": original, "final_maturity_score_of_5": 2.5})
    loc = load_json_store("runtime.maturity", root=tmp_path)
    assert loc["status"] == "AVAILABLE"
    assert loc["data"]["freshness"] == "WITHIN_30D"
    assert loc["data"]["final_maturity_score_of_5"] == 2.5
    assert loc["data"]["original_generated_at"] == original


def test_other_stores_are_not_stamped(tmp_path: Path):
    path = tmp_path / "data/runtime/identity_registry.json"
    _write(path, {"generated_at": "2020-01-01T00:00:00Z", "entities": []})
    loc = load_json_store("identity.registry", root=tmp_path)
    assert loc["status"] == "AVAILABLE"
    assert "freshness" not in loc["data"]
    assert loc["data"]["generated_at"] == "2020-01-01T00:00:00Z"


def test_load_json_store_refuses_archive_without_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    archive = tmp_path / ARCHIVE_REL
    _write(archive, {"generated_at": "2026-10-05T00:00:00Z", "final_maturity_score_of_5": 4.95})

    def fake_resolve(store_id: str, *, root=None):
        return {"exists": True, "path": archive, "primary_path": archive, "used_alias": None}

    monkeypatch.setattr("scripts.lib.canonical_store_registry.resolve_store", fake_resolve)
    _forbid_archive_io(monkeypatch)
    loc = load_json_store("runtime.maturity", root=tmp_path)
    assert loc["status"] == "STALE"
    assert loc["available"] is False
    assert loc["current"] is False
    assert loc["data"] is None
    assert loc["original_generated_at"] is None


def test_select_rows_stamps_stale_score_and_skips_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    live = tmp_path / "data/runtime/maturity_score_latest.json"
    original = _iso(datetime.now(timezone.utc) - timedelta(days=31))
    _write(live, {"generated_at": original, "final_maturity_score_of_5": 4.95})
    archive = tmp_path / ARCHIVE_REL
    _write(archive, {"generated_at": "2026-10-05T00:00:00Z", "final_maturity_score_of_5": 1.0})
    _forbid_archive_io(monkeypatch)
    rows, quality = _select_rows((archive, live), domain="maturity")
    assert quality == "STALE"
    assert rows[0]["freshness"] == "STALE"
    assert rows[0]["original_generated_at"] == original
    assert rows[0]["generated_at"] == original
    assert rows[0]["final_maturity_score_of_5"] == 4.95
    assert rows[0]["current"] is False
    empty, empty_quality = _select_rows((archive,), domain="maturity")
    assert empty == []
    assert empty_quality == "UNAVAILABLE"


def test_served_truth_stamps_stale_and_does_not_read_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    live = tmp_path / "data/runtime/maturity_score_latest.json"
    original = _iso(datetime.now(timezone.utc) - timedelta(days=99))
    _write(live, {"generated_at": original, "final_maturity_score_of_5": 4.95})
    archive = tmp_path / ARCHIVE_REL
    _write(archive, {"generated_at": "2026-10-05T00:00:00Z", "final_maturity_score_of_5": 1.0})
    (tmp_path / "SOURCE_COMMIT").write_text("abc123\n", encoding="utf-8")
    monkeypatch.setattr(reader, "persistent_maturity_score_path", lambda: live)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    _forbid_archive_io(monkeypatch)
    payload = build_maturity_truth(root=tmp_path)
    assert payload.get("final_maturity_score_of_5") is None
    hist = payload["historical_body_superseded"]
    assert hist["freshness"] == "STALE"
    assert hist["status"] == "STALE"
    assert hist["current"] is False
    assert hist["original_generated_at"] == original
    assert hist["generated_at"] == original
    assert hist.get("final_maturity_score_of_5") is None
    assert hist["archive_copy_path"] == ARCHIVE_TOKEN
    assert hist["archive_copy_disposition"] == "REFUSED_NOT_CURRENT"
    status, body = handle("/api/v3/control-plane/maturity")
    assert status == 200
    served = body["data"]["historical_body_superseded"]
    assert served["freshness"] == "STALE"
    assert served["original_generated_at"] == original
    assert body["data"].get("final_maturity_score_of_5") is None


def test_archive_only_root_is_not_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    archive = tmp_path / ARCHIVE_REL
    _write(archive, {"generated_at": "2026-10-05T00:00:00Z", "final_maturity_score_of_5": 4.95})
    missing = tmp_path / "missing" / "maturity_score_latest.json"
    monkeypatch.setattr(reader, "persistent_maturity_score_path", lambda: missing)
    _forbid_archive_io(monkeypatch)
    payload = build_maturity_truth(root=tmp_path)
    hist = payload["historical_body_superseded"]
    assert payload.get("final_maturity_score_of_5") is None
    assert hist["current"] is False
    assert hist["status"] == "ABSENT"
    assert hist["archive_copy_disposition"] == "REFUSED_NOT_CURRENT"
    assert hist["archive_copy_path"] == ARCHIVE_TOKEN
    assert hist.get("final_maturity_score_of_5") is None


def _is_read_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _READ_ATTRS:
        return True
    if isinstance(func, ast.Name) and func.id in _READ_NAMES:
        return True
    return False


def _first_lineno(fn: ast.AST, pred) -> int | None:
    found = None
    for node in ast.walk(fn):
        if pred(node):
            lineno = getattr(node, "lineno", None)
            if isinstance(lineno, int) and (found is None or lineno < found):
                found = lineno
    return found


def test_repo_tripwire_does_not_read_archived_maturity_score():
    """Fail if production code reads data/runtime/archive/maturity_score_latest.json."""
    allowed = {"scripts/lib/maturity_score_latest_reader.py"}
    offenders: list[str] = []
    scan_roots = [ROOT / "scripts", ROOT / "apps"]
    suffixes = {".py", ".ts", ".tsx", ".js", ".mjs"}
    for base in scan_roots:
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix not in suffixes or not path.is_file():
                continue
            if any(part in {".git", "node_modules", "__pycache__", ".venv", "dist"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if ARCHIVE_TOKEN not in text:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel not in allowed:
                offenders.append(rel)
                continue
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if not _is_read_call(node):
                    continue
                segment = ast.get_source_segment(text, node) or ""
                if ARCHIVE_TOKEN in segment:
                    offenders.append(f"{rel}:{node.lineno}:read")
            fn = next(
                (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "read_maturity_score_latest"),
                None,
            )
            assert fn is not None
            raise_at = _first_lineno(fn, lambda n: isinstance(n, ast.Raise))
            read_at = _first_lineno(fn, _is_read_call)
            assert raise_at is not None and read_at is not None and raise_at < read_at, (
                "archive refusal must run before the score file is read"
            )
    assert offenders == []
