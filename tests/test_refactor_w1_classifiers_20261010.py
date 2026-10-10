"""Refactor wave 1 (cron -> n8n), 2026-10-10: classify_candidates.py, market_regime_classifier.py,
mint_identity_registry.py.

Each gets an explicit --dry-run that cannot reach its write (and wins over --apply where --apply exists);
market_regime_classifier --apply exits 1 when the snapshot write fails; the regime and mint applies write
a LaneRunReceipt@v1 whose ok_at advances only on success. Hermetic: tmp state dirs, fake DB/registry.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "persistent"
    (root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(root))
    return root


def _receipt(state, lane):
    p = state / "data" / "runtime" / f"{lane}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


# ── classify_candidates ───────────────────────────────────────────────────


@pytest.fixture
def cc(tmp_path, monkeypatch):
    mod = importlib.import_module("classify_candidates")
    st = tmp_path / "state"
    st.mkdir()
    (st / "ai_watchlist.json").write_text(
        json.dumps(
            {"watchlist": [{"symbol": "AAPL", "note": "semiconductor ai"}, {"symbol": "VFIAX"}, {"symbol": "zzzz"}]}
        )
    )
    rules = tmp_path / "rules.json"
    rules.write_text(
        json.dumps({"asset_type_overrides": {"AAPL": "stock"}, "keyword_rules": {"tech": ["semiconductor"]}})
    )
    monkeypatch.setattr(mod, "STATE", st)
    monkeypatch.setattr(mod, "CONFIG", rules)
    return mod


def test_classify_dry_run_writes_nothing(cc, capsys):
    assert cc.main(["--dry-run", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["dry_run"] is True and doc["total"] == 3 and doc["needs_review"] == 1
    assert not (cc.STATE / "classified_candidates.json").exists()
    assert not (cc.STATE / "classification_review_queue.json").exists()


def test_classify_dry_run_is_honest_to_input_change(cc, capsys):
    cc.main(["--dry-run", "--json"])
    first = json.loads(capsys.readouterr().out)["total"]
    (cc.STATE / "discovery_candidates.json").write_text(json.dumps([{"symbol": "MSFT"}]))
    cc.main(["--dry-run", "--json"])
    assert json.loads(capsys.readouterr().out)["total"] == first + 1


def test_classify_dry_run_source_order():
    src = (ROOT / "scripts" / "classify_candidates.py").read_text()
    body = src[src.index("def main(") :]
    assert body.index("if args.dry_run:") < body.index(".write_text(")


def test_classify_live_writes_both_files(cc, capsys):
    assert cc.main([]) == 0
    assert "classified=3 clean=2 needs_review=1" in capsys.readouterr().out
    q = json.loads((cc.STATE / "classification_review_queue.json").read_text())
    assert q["generated_at"] and [r["symbol"] for r in q["needs_review"]] == ["ZZZZ"]


# ── market_regime_classifier ──────────────────────────────────────────────


class _Conn:
    def close(self):
        pass


@pytest.fixture
def mrc(monkeypatch):
    mod = importlib.import_module("market_regime_classifier")
    calls = {"save": 0, "runlog": [], "alert": 0}
    snap = {
        "snapshot_id": "RS_test",
        "regime_label": "risk_on_trend",
        "confidence": 0.33,
        "stale_data": False,
        "inputs": {"a": "b"},
    }
    monkeypatch.setattr(mod, "_get_conn", lambda: _Conn())
    monkeypatch.setattr(mod, "classify", lambda conn: dict(snap))
    monkeypatch.setattr(mod, "_get_previous_regime", lambda conn: "risk_off")

    def save(conn, s, dry_run=True):
        assert dry_run is False
        calls["save"] += 1
        return mod._SAVE_OK

    mod._SAVE_OK = True
    monkeypatch.setattr(mod, "save_snapshot", save)
    monkeypatch.setattr(mod, "_record_run_log", lambda *a, **k: calls["runlog"].append(a[4]))
    monkeypatch.setattr(mod, "_alert_regime_change", lambda *a: calls.__setitem__("alert", calls["alert"] + 1))
    mod._calls = calls
    return mod


def test_regime_explicit_dry_run_wins_over_apply(state, mrc, capsys):
    assert mrc.main(["--dry-run", "--apply"]) == 0
    assert mrc._calls == {"save": 0, "runlog": [], "alert": 0}
    assert "would insert market_regime_snapshots snapshot_id=RS_test" in capsys.readouterr().out
    assert _receipt(state, "market-regime-classifier") is None


def test_regime_default_is_still_dry_run(state, mrc):
    assert mrc.main([]) == 0 and mrc._calls["save"] == 0


def test_regime_dry_run_json_stdout_stays_json(state, mrc, capsys):
    mrc.main(["--dry-run", "--json"])
    cap = capsys.readouterr()
    assert json.loads(cap.out)["mode"] == "dry_run" and "would insert" in cap.err


def test_regime_apply_success_receipt(state, mrc):
    assert mrc.main(["--apply"]) == 0
    assert mrc._calls["save"] == 1 and mrc._calls["runlog"] == ["success"] and mrc._calls["alert"] == 1
    rec = _receipt(state, "market-regime-classifier")
    assert rec["status"] == "ok" and rec["ok_at"] and rec["summary"]["snapshot_id"] == "RS_test"


def test_regime_apply_write_failure_exits_1(state, mrc):
    assert mrc.main(["--apply"]) == 0
    ok_at = _receipt(state, "market-regime-classifier")["ok_at"]
    mrc._SAVE_OK = False
    assert mrc.main(["--apply"]) == 1
    rec = _receipt(state, "market-regime-classifier")
    assert rec["status"] == "failed" and rec["ok_at"] == ok_at and mrc._calls["runlog"][-1] == "failed"


# ── mint_identity_registry ────────────────────────────────────────────────


@pytest.fixture
def mint(monkeypatch):
    mod = importlib.import_module("scripts.mint_identity_registry")
    applies = []

    def reg(rows, root=None, *, apply=False):
        applies.append(apply)
        if mod._RAISE:
            raise RuntimeError("disk full")
        return {
            "rows_seen": len(rows),
            "entities_before": 10,
            "entities_after": 11,
            "entities_added": 1,
            "by_identity_status": {},
            "symbols_indexed": 11,
            "path": "/tmp/identity_registry.json",
        }

    mod._RAISE = False
    monkeypatch.setattr(mod, "collect_rows", lambda: [{"symbol": "AAA"}])
    monkeypatch.setattr(mod, "register_all", reg)
    mod._applies = applies
    return mod


def test_mint_explicit_dry_run_wins_over_apply(state, mint, capsys):
    assert mint.main(["--dry-run", "--apply"]) == 0
    assert mint._applies == [False]
    assert "nothing written" in capsys.readouterr().out
    assert _receipt(state, "mint-identity-registry") is None


def test_mint_dry_run_source_order():
    src = (ROOT / "scripts" / "mint_identity_registry.py").read_text()
    body = src[src.index("def main(") :]
    assert body.index("if args.dry_run:") < body.index("args.propose_catalyst_gap:")
    assert body.index("args.apply = False") < body.index("register_all(rows, apply=True)")


def test_mint_apply_writes_ok_receipt(state, mint):
    assert mint.main(["--apply"]) == 0
    assert mint._applies == [True]
    rec = _receipt(state, "mint-identity-registry")
    assert rec["status"] == "ok" and rec["summary"]["entities_added"] == 1


def test_mint_apply_failure_receipt_and_raise(state, mint):
    mint._RAISE = True
    with pytest.raises(RuntimeError):
        mint.main(["--apply"])
    rec = _receipt(state, "mint-identity-registry")
    assert rec["status"] == "failed" and rec["ok_at"] is None


def test_mint_register_symbol_honours_dry_run(state, mint, monkeypatch):
    seen = []
    monkeypatch.setattr(
        mint, "register_one_verified", lambda sym, apply=False: seen.append(apply) or {"ok": True, "symbol": sym}
    )
    assert mint.main(["--register-symbol", "AAA", "--apply", "--dry-run"]) == 0
    assert seen == [False]
