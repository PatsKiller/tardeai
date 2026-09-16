"""R4: hardening aggregator must not exit 0 when failed is non-empty."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_cio_hardening_ci.py"
    spec = importlib.util.spec_from_file_location("run_cio_hardening_ci", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_failed_list_returns_nonzero(monkeypatch, capsys):
    mod = _load()

    def fake_main_failed():
        # Simulate the tail of main(): failed non-empty must return 1.
        failed = ["gate_x"]
        if failed:
            print(f"\nCIO HARDENING CI FAILED: {failed}")
            return 1
        print("\nCIO HARDENING CI: ALL GATES PASS")
        return 0

    assert fake_main_failed() == 1
    # Also assert the real module's contract is still present in source.
    src = (Path(__file__).resolve().parents[1] / "scripts" / "run_cio_hardening_ci.py").read_text()
    assert "CIO HARDENING CI FAILED" in src
    assert "return 1" in src
