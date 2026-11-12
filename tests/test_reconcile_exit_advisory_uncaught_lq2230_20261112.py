"""ANCHOR: RECONCILE_EXIT_ADVISORY_UNCAUGHT_LQ2230_20261112 — a crash in the exit-advisory reconciler is named.

Before: an exception inside ``reconcile()`` (e.g. a malformed bar from the source) exited 1 with a traceback only;
no LaneRunReceipt was written, so the lane's output_signal kept showing an older run. Synthetic data only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reconcile_exit_advisory_outcomes as r  # noqa: E402


def test_uncaught_exception_exits_1_and_writes_named_failed_receipt(monkeypatch, capsys):
    seen = {}

    def boom():
        raise TypeError("bar close is not a number")

    monkeypatch.setattr(r, "reconcile", boom)
    monkeypatch.setattr(r, "_receipt", lambda **kw: seen.update(kw))
    monkeypatch.setattr(sys, "argv", ["reconcile_exit_advisory_outcomes.py"])
    assert r.main() == 1
    assert seen["ok"] is False and seen["empty_reason"] == "unhandled_exception"
    assert "TypeError" in seen["error"] and "bar close" in seen["error"]
    assert "unhandled_exception" in capsys.readouterr().err


def test_clean_run_is_unchanged(monkeypatch):
    monkeypatch.setattr(r, "reconcile", lambda: 0)
    monkeypatch.setattr(r, "_receipt", lambda **kw: (_ for _ in ()).throw(AssertionError("no receipt on clean run")))
    monkeypatch.setattr(sys, "argv", ["reconcile_exit_advisory_outcomes.py"])
    assert r.main() == 0
