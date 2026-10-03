"""CIO Desk scorecard reads counts that are current, and says so when it has none.

2026-10-03, after #1405 fixed the outcome counter: the Outcomes card still read
"1127 outcomes due; matured=0" because the light scorecard read
cio_brain_learning_slice.json, a file no job writes (last written 2026-09-30).
The Hermes card read "DeepSeek non-error 24h=0" because a recovered lane's row
was rewritten without the counts the monitor had just measured.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_scorecard as sc  # noqa: E402

PAST = "2026-01-01T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "rel"
    # The stale one-off slice that used to drive the card.
    slice_path = root / "data" / "runtime" / "cio_brain_learning_slice.json"
    slice_path.parent.mkdir(parents=True, exist_ok=True)
    slice_path.write_text(json.dumps({
        "ok": True, "as_of": "2026-09-30T13:24:00+00:00", "memory_behavior_influence": 0,
        "learning": {"outcomes": {"due": 1127, "matured": 0}},
        "learning_cockpit": {"outcomes_due": 1127},
    }), encoding="utf-8")
    _jsonl(root / "data" / "cio" / "outcome_checkpoints.jsonl", [
        {"checkpoint_id": "a", "status": "SCHEDULED", "due_at": PAST},
        {"checkpoint_id": "b", "status": "SCHEDULED", "due_at": PAST},
        {"checkpoint_id": "b", "status": "RESOLVED", "due_at": PAST, "outcome_id": "o1"},
        {"checkpoint_id": "c", "status": "NOT_PRICE_RESOLVABLE", "due_at": PAST},
        {"checkpoint_id": "d", "status": "SCHEDULED", "due_at": FUTURE},
    ])
    _jsonl(root / "data" / "cio" / "outcome_observations.jsonl", [])
    sc._LIVE_COCKPIT.update({"key": None, "value": None})
    return root


def _outcomes(root: Path) -> dict:
    return sc._outcomes_tile(sc._light_brain(root))


def _metric(tile: dict, label: str):
    return next(m["value"] for m in tile["metrics"] if m["label"] == label)


def test_outcomes_card_uses_the_live_store_not_the_stale_slice(tmp_path):
    tile = _outcomes(_root(tmp_path))
    assert _metric(tile, "Outcomes due") == 1
    assert _metric(tile, "Matured") == 1
    assert _metric(tile, "Not price-resolvable") == 1
    assert "1127" not in tile["verdict"]
    assert tile["status"] == "working"


def test_live_counts_recompute_only_when_the_store_changes(tmp_path, monkeypatch):
    root = _root(tmp_path)
    from scripts.lib import r17_checkpoint_binding as r17

    calls = {"n": 0}
    real = r17.learning_cockpit_from_store

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(r17, "learning_cockpit_from_store", counting)
    _outcomes(root)
    _outcomes(root)
    assert calls["n"] == 1
    with (root / "data" / "cio" / "outcome_checkpoints.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"checkpoint_id": "e", "status": "SCHEDULED", "due_at": PAST}) + "\n")
    assert _metric(_outcomes(root), "Outcomes due") == 2
    assert calls["n"] == 2


def test_a_live_count_failure_falls_back_to_the_file(tmp_path, monkeypatch):
    root = _root(tmp_path)
    from scripts.lib import r17_checkpoint_binding as r17

    def boom(*a, **k):
        raise OSError("store unreadable")

    monkeypatch.setattr(r17, "learning_cockpit_from_store", boom)
    assert _metric(_outcomes(root), "Outcomes due") == 1127


def _lane_root(tmp_path: Path, lanes: dict) -> Path:
    root = tmp_path / "lanes"
    path = root / "data" / "runtime" / "research_lane_health.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"lanes": lanes}), encoding="utf-8")
    return root


def test_hermes_card_says_not_reported_instead_of_zero(tmp_path):
    ok = {"ok": True, "firing": []}
    tile = sc._hermes_tile(_lane_root(tmp_path, {"deepseek": dict(ok), "cio-hermes-queue": dict(ok),
                                                 "coverage-stall": dict(ok)}))
    assert tile["status"] == "working"
    assert "not reported" in tile["verdict"]
    assert _metric(tile, "DeepSeek ok 24h") is None


def test_hermes_card_shows_a_measured_count(tmp_path):
    lanes = {"deepseek": {"ok": True, "firing": [], "non_error_24h": 97, "attempts_24h": 97},
             "cio-hermes-queue": {"ok": True, "firing": []}}
    tile = sc._hermes_tile(_lane_root(tmp_path, lanes))
    assert "non-error 24h=97" in tile["verdict"]
    assert _metric(tile, "DeepSeek ok 24h") == 97


def test_recovered_lane_keeps_the_counts_it_measured():
    import research_lane_health as rlh

    state = {"deepseek": {"lane": "deepseek", "ok": False, "firing": ["x"], "last_alert": 1, "signature": "s"}}
    report = {"as_of": "2026-10-03T16:00:00+00:00",
              "lanes": [{"lane": "deepseek", "ok": True, "firing": [], "non_error_24h": 97, "attempts_24h": 98}]}
    out = rlh.reconcile_recovered(state, report)["deepseek"]
    assert out["ok"] is True and out["non_error_24h"] == 97 and out["attempts_24h"] == 98
    assert out["recovered_from"] == "s"
