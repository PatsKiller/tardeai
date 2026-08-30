"""Slice 15 + G-ID-01 carriage: subject_guid from identity registry.

No mint. UNRESOLVED stays UNRESOLVED. Never ticker-as-GUID.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.cio_subject_guid import (
    METRICS_HIT,
    METRICS_MISS,
    UNRESOLVED,
    empty_carriage_metrics,
    lookup_subject,
    stamp_row,
    stamp_subject_guid,
)


def test_unknown_symbol_stays_unresolved():
    hit = lookup_subject("ZZZZNOTAREAL")
    assert hit["subject_guid"] is None
    assert hit["identity_status"] == UNRESOLVED
    row = stamp_row({"symbol": "ZZZZNOTAREAL", "action": "WATCH"})
    assert row["subject_guid"] is None
    assert row["identity_status"] == UNRESOLVED
    assert row["action"] == "WATCH"


def test_stamp_does_not_call_register(monkeypatch):
    import scripts.lib.identity_registry as ir
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not mint")

    monkeypatch.setattr(ir, "register", _boom)
    stamp_row({"symbols": ["SCHD"]})
    assert called["n"] == 0


def _write_registry(tmp_path: Path, *, entities: dict, by_symbol: dict) -> Path:
    reg_dir = tmp_path / "data" / "runtime"
    reg_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "IdentityRegistry@v1",
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "entities": entities,
        "by_symbol": by_symbol,
        "events": {},
        "updated_at": None,
    }
    path = reg_dir / "identity_registry.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_stamp_subject_guid_hit_sets_registry_guid(tmp_path: Path):
    guid = "0e096c36-a7eb-56f6-9096-15b444227e86"
    _write_registry(
        tmp_path,
        entities={
            guid: {
                "subject_guid": guid,
                "entity_type": "SECURITY",
                "identity_status": "CONFIRMED",
            }
        },
        by_symbol={"SCHD": guid},
    )
    metrics = empty_carriage_metrics()
    row = stamp_subject_guid({"symbol": "SCHD", "status": "NEAR"}, root=tmp_path, metrics=metrics)
    assert row["subject_guid"] == guid
    assert row["subject_guid"] != "SCHD"
    assert row["identity_status"] == "CONFIRMED"
    assert row["status"] == "NEAR"
    assert metrics[METRICS_HIT] == 1
    assert metrics[METRICS_MISS] == 0


def test_stamp_subject_guid_miss_leaves_unset_and_counts(tmp_path: Path):
    _write_registry(tmp_path, entities={}, by_symbol={})
    metrics = empty_carriage_metrics()
    row = stamp_subject_guid(
        {"symbol": "ZZZZNOTAREAL", "action": "WATCH"},
        root=tmp_path,
        metrics=metrics,
    )
    assert row["subject_guid"] is None
    assert "ZZZZNOTAREAL" != row.get("subject_guid")
    assert row["identity_status"] == UNRESOLVED
    assert row["action"] == "WATCH"
    assert metrics[METRICS_HIT] == 0
    assert metrics[METRICS_MISS] == 1


def test_stamp_subject_guid_never_tickers_as_guid(tmp_path: Path):
    """If a corrupt registry mapped ticker→ticker, refuse carriage."""
    _write_registry(
        tmp_path,
        entities={
            "SCHD": {
                "subject_guid": "SCHD",
                "entity_type": "SECURITY",
                "identity_status": "CONFIRMED",
            }
        },
        by_symbol={"SCHD": "SCHD"},
    )
    metrics = empty_carriage_metrics()
    row = stamp_subject_guid({"symbol": "SCHD"}, root=tmp_path, metrics=metrics)
    assert row["subject_guid"] is None
    assert row["subject_guid"] != "SCHD"
    assert metrics[METRICS_MISS] == 1
    assert metrics[METRICS_HIT] == 0


def test_stamp_subject_guid_does_not_call_register(tmp_path: Path, monkeypatch):
    guid = "guid-noc-test"
    _write_registry(
        tmp_path,
        entities={guid: {"subject_guid": guid, "identity_status": "CONFIRMED"}},
        by_symbol={"NOC": guid},
    )
    import scripts.lib.identity_registry as ir
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not mint")

    monkeypatch.setattr(ir, "register", _boom)
    metrics = empty_carriage_metrics()
    row = stamp_subject_guid({"symbol": "NOC"}, root=tmp_path, metrics=metrics)
    assert called["n"] == 0
    assert row["subject_guid"] == guid
    assert metrics[METRICS_HIT] == 1


def test_stamp_subject_guid_symbol_kwarg_override(tmp_path: Path):
    guid = "guid-bah-test"
    _write_registry(
        tmp_path,
        entities={guid: {"subject_guid": guid, "identity_status": "CANDIDATE"}},
        by_symbol={"BAH": guid},
    )
    metrics = empty_carriage_metrics()
    row = stamp_subject_guid({"action": "HOLD_REVIEW"}, symbol="BAH", root=tmp_path, metrics=metrics)
    assert row["symbol"] == "BAH"
    assert row["subject_guid"] == guid
    assert row["subject_guid"] != "BAH"
    assert metrics[METRICS_HIT] == 1


def test_reentry_book_stamps_when_registry_resolves(tmp_path: Path):
    """Highest-traffic writer: build_reentry_book must carriage subject_guid."""
    guid = "guid-schd-reentry"
    _write_registry(
        tmp_path,
        entities={guid: {"subject_guid": guid, "identity_status": "CONFIRMED"}},
        by_symbol={"SCHD": guid},
    )
    from scripts.lib.cio_investment_product import build_reentry_book

    book = build_reentry_book(
        prev=[{"symbol": "SCHD", "reentry_signal": "NEAR"}],
        queue={"items": []},
        lessons={"lessons": []},
        fs_rows=[],
        infl={"memory_behavior_influence": 0},
        root=tmp_path,
    )
    names = book.get("names") or []
    assert names
    schd = next(r for r in names if r.get("symbol") == "SCHD")
    assert schd.get("subject_guid") == guid
    assert schd.get("subject_guid") != "SCHD"
    carriage = book.get("identity_carriage") or {}
    assert carriage.get(METRICS_HIT, 0) >= 1
