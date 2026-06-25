"""Tests for sector_research_universe full coverage."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "sector_research_universe", ROOT / "scripts" / "sector_research_universe.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_universe_covers_sectors_and_industries():
    mod = _load()
    snap = {
        "snapshot_date": "2026-06-24",
        "sectors": [{"name": "Technology", "change_pct": 1.2, "stocks": 500}],
        "industries": [
            {"name": "Software - Application", "change_pct": 2.1, "stocks": 120},
            {"name": "Exchange Traded Fund", "change_pct": 0.1, "stocks": 200},
        ],
    }
    themes = mod.build_universe_directives(snap)
    labels = [t["label"] for t in themes]
    assert any(t["kind"] == "sector" and "Technology" in t["label"] for t in themes)
    assert any("Software" in l for l in labels)
    assert not any("Exchange Traded Fund" in l for l in labels)


def test_universe_batch_rotation():
    mod = _load()
    snap = {
        "snapshot_date": "2026-06-24",
        "sectors": [{"name": f"Sector{i}", "change_pct": 0.5, "stocks": 10} for i in range(3)],
        "industries": [{"name": f"Ind{i}", "change_pct": 0.3, "stocks": 5} for i in range(5)],
    }

    class FakeCursor:
        def execute(self, *args, **kwargs):
            pass

        def fetchone(self):
            return (None,)

        def fetchall(self):
            return []

    class FakeConn:
        def commit(self):
            pass

        def cursor(self):
            return FakeCursor()

    mod._save_state({"offset": 0, "total": 0})
    r1 = mod.sync_universe_batch(FakeConn(), snap, apply=False, batch_size=2)
    assert r1["batch_size"] == 2
    assert r1["universe_total"] == 8