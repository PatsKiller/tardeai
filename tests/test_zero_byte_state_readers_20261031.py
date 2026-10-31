"""0-byte state files (disk full on 2026-10-30) are read as missing, never crash, and are no longer produced.

After the disk-full night ``tax_lots.json``, ``fund_holdings_cache.json`` and ``aec_memory_spines.json`` sat at
0 bytes: the tax-lots rebuild and the hourly AEC cycle crashed on every run. Each reader now treats an empty file
as missing (with a warning), the tax-lots rebuild recovers from its newest valid backup, and the writers write
atomically (temp + fsync + rename). Fixtures only; synthetic symbols; no DB, no network.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_spines():
    # Unit test of the memory-spine module itself: load it by file path, the convention the existing
    # aec_memory_spines tests use (tests/test_aec_narrator_20260919.py). Production readers still go through
    # scripts/lib/intelligence_client.py (memory chokepoint ratchet).
    spec = importlib.util.spec_from_file_location("aec_memory_spines", ROOT / "scripts/lib/aec_memory_spines.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(mod)
    return mod


spines = _load_spines()


def test_aec_spines_empty_file_is_missing_and_save_is_atomic(tmp_path, caplog):
    p = tmp_path / "aec_memory_spines.json"
    p.write_bytes(b"")
    caplog.set_level(logging.WARNING)
    snap = spines.load(p)
    assert all(v == [] for v in snap.spines.values())
    assert "is empty (0 bytes)" in caplog.text
    spines.save(snap, p)
    assert json.loads(p.read_text())["spines"] == snap.spines
    assert not list(tmp_path.glob(".*.tmp"))


def test_aec_spines_real_corruption_still_raises(tmp_path):
    p = tmp_path / "aec_memory_spines.json"
    p.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        spines.load(p)


@pytest.fixture
def lots_env(tmp_path, monkeypatch):
    import rebuild_tax_lots_from_transactions as rb

    state = tmp_path / "state"
    (state / "backups").mkdir(parents=True)
    monkeypatch.setattr(rb, "LOTS_PATH", state / "tax_lots.json")
    monkeypatch.setattr(rb, "BACKUP_DIR", state / "backups")
    return rb, state


def test_tax_lots_empty_file_recovers_from_newest_valid_backup(lots_env, caplog):
    rb, state = lots_env
    (state / "tax_lots.json").write_bytes(b"")
    (state / "backups" / "tax_lots.json.bak-20261028T204500Z").write_text(json.dumps({"AAA:acct1": [{"q": 1}]}))
    (state / "backups" / "tax_lots.json.bak-20261029T204500Z").write_text(json.dumps({"BBB:acct1": [{"q": 2}]}))
    (state / "backups" / "tax_lots.json.bak-20261030T111500Z").write_bytes(b"")  # the damaged night
    caplog.set_level(logging.WARNING)
    lots, src = rb._load_lots()
    assert lots == {"BBB:acct1": [{"q": 2}]}
    assert src.endswith("bak-20261029T204500Z")
    assert "is empty (0 bytes)" in caplog.text


def test_tax_lots_empty_without_backup_refuses_cleanly(lots_env):
    rb, state = lots_env
    (state / "tax_lots.json").write_bytes(b"")
    with pytest.raises(FileNotFoundError):
        rb._load_lots()


def test_tax_lots_normal_file_reads_unchanged(lots_env):
    rb, state = lots_env
    (state / "tax_lots.json").write_text(json.dumps({"CCC:acct2": []}))
    assert rb._load_lots() == ({"CCC:acct2": []}, None)


def test_lookthrough_cache_empty_is_missing_and_writes_are_atomic(tmp_path, monkeypatch):
    import portfolio_lookthrough_themes as lt

    p = tmp_path / "fund_holdings_cache.json"
    p.write_bytes(b"")
    assert lt._load(p, {"default": True}) == {"default": True}
    monkeypatch.setattr(lt, "_state_write_targets", lambda: [tmp_path])
    lt._write_state_json("fund_holdings_cache.json", {"ETF_A": {"AAA": 0.1}})
    assert json.loads(p.read_text()) == {"ETF_A": {"AAA": 0.1}}
    assert not list(tmp_path.glob(".*.tmp"))
