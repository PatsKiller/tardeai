"""Tests for hermes_maturity_dashboard."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "hermes_maturity_dashboard", ROOT / "scripts" / "hermes_maturity_dashboard.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gap_embedding_not_policy_manual():
    mod = _load()
    gap = mod._gap_embedding_backlog({"embed_pending": 2500, "embed_failed": 120, "promoted_missing_embed": 40})
    assert gap["policy_manual"] is False
    assert gap["automatable"] is True
    assert gap["severity"] == "critical"


def test_gap_closed_trade_is_policy_manual():
    mod = _load()
    gap = mod._gap_closed_trade_drain({"closed_trades_need_reflection": 80})
    assert gap["policy_manual"] is True
    assert "held" in gap["policy_reason"].lower() or "manual" in gap["policy_reason"].lower()


def test_build_maturity_report_shape():
    mod = _load()

    class FakeCursor:
        def execute(self, *args, **kwargs):
            pass

        def fetchall(self):
            return [("promoted", 100), ("staged", 2)]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    # _scalar will return 0 for all — report should still shape correctly
    report = mod.build_maturity_report(FakeConn())
    assert report["ok"] is True
    assert "layer_scores" in report
    assert "areas" in report
    assert len(report["gaps"]) == 4
    assert report["gap_summary"]["total"] == 4
    assert "scalp_kpis" in report
    assert "health" in report["scalp_kpis"]
    assert "targets" in report["scalp_kpis"]


if __name__ == "__main__":
    test_gap_embedding_not_policy_manual()
    test_gap_closed_trade_is_policy_manual()
    test_build_maturity_report_shape()
    print("OK — all hermes_maturity_dashboard tests passed")