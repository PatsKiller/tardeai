"""WATCH instrument admit — cognition only, cap 20, no S7 / Maria.

Mutation: notify_priority != none, S7/Maria imports, or BehaviorWriteRefused
bypass → test red.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts.lib.cio_instrument_record import (
    BehaviorWriteRefused,
    InstrumentRecordStore,
    apply_cognition,
    new_record,
    subject_key,
)
from scripts.lib.cio_watch_instrument_admit import (
    ADMIT_CAP,
    admit_watch_records,
    candidate_watch_symbols,
)

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "lib" / "cio_watch_instrument_admit.py"
CLI = ROOT / "scripts" / "cio_admit_watch_instrument_records.py"


def _watchlist(tmp_path: Path, symbols: list[str]) -> Path:
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    body = {
        s: {"thesis": f"{s} thesis", "target_intent": "long_term_hold", "added": "2026-09-01"}
        for s in symbols
    }
    path = state / "watchlist.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return tmp_path


def test_admit_creates_watch_records_via_apply_cognition(tmp_path: Path):
    root = _watchlist(tmp_path, ["PLTR", "NVDA", "MSFT"])
    store = InstrumentRecordStore(tmp_path / "records.jsonl")
    receipt = admit_watch_records(root=root, store=store, apply=True, cap=20)
    assert receipt["admitted_n"] == 3
    assert receipt["s7_fired"] is False
    assert receipt["maria_invoked"] is False
    assert receipt["notify"] is False
    for sk in receipt["admitted"]:
        assert sk.startswith("WATCH:")
        rec = store.load(sk)
        assert rec is not None
        assert rec["kind"] == "WATCH"
        assert rec["notify_priority"] == "none"
        assert rec.get("cc_narrative", {}).get("what")
        assert rec.get("next_research_question")
        assert "size_usd" not in rec


def test_cap_twenty():
    assert ADMIT_CAP == 20


def test_cap_limits_admits(tmp_path: Path):
    syms = [f"W{i:02d}" for i in range(25)]
    root = _watchlist(tmp_path, syms)
    store = InstrumentRecordStore(tmp_path / "records.jsonl")
    receipt = admit_watch_records(root=root, store=store, apply=True, cap=20)
    assert receipt["admitted_n"] == 20
    assert len(store.all()) == 20


def test_skips_existing_watch_and_held(tmp_path: Path):
    root = _watchlist(tmp_path, ["PLTR", "NVDA", "MSFT"])
    store = InstrumentRecordStore(tmp_path / "records.jsonl")
    store.upsert(new_record("WATCH", "PLTR", symbols=["PLTR"]))
    store.upsert(new_record("HELD", "NVDA", symbols=["NVDA"]))
    cands = candidate_watch_symbols(root, store=store, cap=20)
    assert cands == ["MSFT"]
    receipt = admit_watch_records(root=root, store=store, apply=True)
    assert receipt["admitted"] == ["WATCH:MSFT"]


def test_dry_run_does_not_write(tmp_path: Path):
    root = _watchlist(tmp_path, ["PLTR"])
    store = InstrumentRecordStore(tmp_path / "records.jsonl")
    receipt = admit_watch_records(root=root, store=store, apply=False)
    assert receipt["admitted_n"] == 1
    assert store.load("WATCH:PLTR") is None


def test_apply_cognition_refuses_behavior_fields():
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(
            new_record("WATCH", "PLTR"),
            next_research_question="q",
            size_usd=1000,  # type: ignore[arg-type]
        )


def test_helper_does_not_import_s7_or_maria():
    src = HELPER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imported.add(mod)
            for a in node.names:
                imported.add(f"{mod}.{a.name}" if mod else a.name)
    joined = " ".join(sorted(imported)).lower()
    assert "cio_situation_detector" not in joined
    assert "s7_watch_promotion" not in joined
    assert "run_watch_review" not in joined
    assert "maria" not in joined
    # Executable names: apply_cognition + new_record must be referenced.
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "apply_cognition" in names
    assert "new_record" in names


def test_helper_assigns_notify_none(tmp_path: Path):
    root = _watchlist(tmp_path, ["AXON"])
    store = InstrumentRecordStore(tmp_path / "records.jsonl")
    admit_watch_records(root=root, store=store, apply=True)
    rec = store.load("WATCH:AXON")
    assert rec["notify_priority"] == "none"


def test_cli_exists_and_defaults_dry_run():
    src = CLI.read_text(encoding="utf-8")
    assert "--apply" in src
    assert "admit_watch_records" in src
    assert "dry-run" in src.lower() or "Dry-run" in src
