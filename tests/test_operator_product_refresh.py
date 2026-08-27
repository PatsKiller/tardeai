"""The refresh must never overwrite the last good snapshot with a stub.

`cio.operator_product.current` exists so that a corrupt investment brief still
yields a last-valid product rather than "no product on disk". A refresh job
that persisted an unavailable product would destroy exactly the artifact it is
scheduled to keep fresh.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/refresh_operator_product.py"


def _run(*args):
    out = subprocess.run([sys.executable, str(SCRIPT), "--json", *args],
                         capture_output=True, text=True, cwd=str(ROOT), timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def test_dry_run_writes_nothing():
    r = _run("--dry-run")
    assert r["persisted"] is False
    assert r["skipped_reason"] == "dry-run"


def test_it_refuses_to_persist_an_unavailable_product(monkeypatch):
    """The guarantee, exercised rather than asserted from source text."""
    sys.path.insert(0, str(ROOT))
    import importlib
    mod = importlib.import_module("scripts.refresh_operator_product")
    import scripts.lib.cio_operator_product as cop

    calls: list[bool] = []

    def fake_build(*, root=None, persist=False, supplemental=None):
        calls.append(persist)
        return {"available": False, "status": "INVALID_SCHEMA",
                "last_valid_product": {"product_id": "last_good"}}

    monkeypatch.setattr(cop, "build_operator_product", fake_build)
    monkeypatch.setattr(sys, "argv", ["refresh_operator_product.py", "--json"])
    assert mod.main() == 0
    assert calls == [False], "an unavailable product must never reach persist=True"


def test_an_unavailable_brief_is_not_a_job_failure(monkeypatch):
    """Exit 0 so cron does not alert on a legitimately absent product."""
    sys.path.insert(0, str(ROOT))
    import importlib
    mod = importlib.import_module("scripts.refresh_operator_product")
    import scripts.lib.cio_operator_product as cop
    monkeypatch.setattr(cop, "build_operator_product",
                        lambda **k: {"available": False, "status": "PRODUCER_NOT_RUN"})
    monkeypatch.setattr(sys, "argv", ["refresh_operator_product.py", "--json"])
    assert mod.main() == 0


def test_unavailable_returns_precede_the_persist_block():
    """The library-level guarantee this script depends on.

    If a future edit moves persistence above the unavailable() returns, a
    corrupt brief would clobber the snapshot. Pin the ordering.
    """
    src = (ROOT / "scripts/lib/cio_operator_product.py").read_text(encoding="utf-8")
    persist_at = src.index("if persist:")
    for ret in ("return unavailable("):
        assert src.index(ret) < persist_at
    assert src.rindex("return unavailable(") < persist_at


def test_the_scheduled_declaration_is_present():
    """The dark-contract gate excuses a scheduled entrypoint only if it says so."""
    sys.path.insert(0, str(ROOT))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "guard", ROOT / "scripts/check_dark_contracts.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert guard.declared_module_string(
        "scripts/refresh_operator_product.py", "SCHEDULED_ENTRYPOINT")
    assert guard.audit()["new"] == [], "the new entrypoint must not be a dark contract"
