"""WAVE F3 — per-provider search budget survives process.

Rails:
  * check BEFORE call; return empty / deny when over
  * never fail open (corrupt or unreadable ledger → DENY)
  * daily + monthly per provider
  * durable file under production_state_root/data/runtime — survives cron
  * concurrent processes cannot both spend the last unit (flocked try_consume)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import search_budget as sb

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


# ── durable path ───────────────────────────────────────────────────────────

def test_ledger_path_is_under_runtime_not_a_release_checkout():
    """STORE SET: data/runtime via production_state_root — not portfolio-server/."""
    p = sb.budget_path()
    assert p.as_posix().endswith("data/runtime/search_budget.json")
    assert "portfolio-server/" not in p.as_posix()


def test_budget_path_honours_explicit_root(tmp_path: Path):
    p = sb.budget_path(tmp_path)
    assert p == tmp_path / "data" / "runtime" / "search_budget.json"


# ── never fail open ────────────────────────────────────────────────────────

def test_corrupt_ledger_denies_check_and_try_consume(tmp_path: Path):
    ledger = sb.budget_path(tmp_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{ not json", encoding="utf-8")

    with pytest.raises(sb.BudgetUnavailable):
        sb.status("brave", root=tmp_path)

    v = sb.check("brave", root=tmp_path)
    assert v["allowed"] is False
    assert "BUDGET_UNAVAILABLE" in v["reason"]
    assert v.get("fail_open") is False

    c = sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)
    assert c["allowed"] is False
    assert "BUDGET_UNAVAILABLE" in c["reason"]


def test_record_refuses_to_rebuild_a_corrupt_ledger_as_zeros(tmp_path: Path):
    """The old write path reset an unreadable ledger to {} and overwrote it —
    fail-open on the record side. F3: skip the write; bytes stay corrupt."""
    ledger = sb.budget_path(tmp_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    junk = "{ not json"
    ledger.write_text(junk, encoding="utf-8")

    sb.record("brave", allowed=True, caller="f3", now=NOW, root=tmp_path)
    assert ledger.read_text(encoding="utf-8") == junk


# ── per provider daily + monthly ───────────────────────────────────────────

def test_providers_are_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "2")
    for _ in range(2):
        assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["allowed"]
    assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["reason"] == "DAILY_EXHAUSTED"
    # tavily untouched
    assert sb.check("tavily", now=NOW, root=tmp_path)["allowed"] is True
    assert sb.status("tavily", now=NOW, root=tmp_path)["monthly_used"] == 0


def test_monthly_cap_binds_when_daily_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "2")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "100")
    assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["allowed"]
    assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["allowed"]
    assert sb.try_consume("brave", caller="f3", now=NOW, root=tmp_path)["reason"] == "MONTHLY_EXHAUSTED"


# ── survives process (fresh interpreter) ───────────────────────────────────

def test_counts_survive_a_fresh_python_process(tmp_path: Path):
    """Cron starts a new process every invocation. In-memory state is gone;
    only the durable file under data/runtime survives."""
    first = sb.try_consume("brave", caller="cron_a", now=NOW, root=tmp_path)
    assert first["allowed"] is True
    ledger = sb.budget_path(tmp_path)
    assert ledger.is_file()

    # Fresh interpreter, same root — must see the prior consume.
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    code = (
        "from pathlib import Path\n"
        "from datetime import datetime, timezone\n"
        "from scripts.lib import search_budget as sb\n"
        f"root = Path({str(tmp_path)!r})\n"
        "now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)\n"
        "st = sb.status('brave', now=now, root=root)\n"
        "print(st['monthly_used'], st['daily_used'], st['ledger_path'])\n"
        "assert st['monthly_used'] == 1 and st['daily_used'] == 1\n"
        "assert 'data/runtime/search_budget.json' in st['ledger_path']\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().startswith("1 1")


def test_try_consume_serializes_last_unit_across_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Two processes racing the last unit: exactly one may spend."""
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "1")
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_MONTHLY", "100")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    root_s = str(tmp_path)
    code = (
        "from pathlib import Path\n"
        "from datetime import datetime, timezone\n"
        "from scripts.lib import search_budget as sb\n"
        f"root = Path({root_s!r})\n"
        "now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)\n"
        "v = sb.try_consume('brave', caller='race', now=now, root=root)\n"
        "print('ALLOW' if v['allowed'] else 'DENY')\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    outcomes = []
    for p in procs:
        out, err = p.communicate(timeout=30)
        assert p.returncode == 0, err
        outcomes.append(out.strip())
    assert outcomes.count("ALLOW") == 1, outcomes
    assert outcomes.count("DENY") == 1, outcomes
    assert sb.status("brave", now=NOW, root=tmp_path)["daily_used"] == 1


# ── representative caller: brave_search never fail-open on missing shared ──

def test_brave_search_source_denies_when_shared_unavailable():
    """Representative caller wire (F3): ImportError of the shared module must
    DENY — not assign ``_shared_check = None`` and fall through to a
    release-relative local ledger."""
    src = (ROOT / "scripts" / "brave_search.py").read_text(encoding="utf-8")
    body = src.split("def _check_budget", 1)[1].split("def _record_shared", 1)[0]
    assert "never fail open" in body
    assert "_shared_check = None" not in body
    assert "shared budget unavailable — DENY" in body
    # Shared check is mandatory — verdict consulted unconditionally after import.
    assert 'verdict = _shared_check("brave")' in body


def test_guard_returns_false_when_over_so_callers_return_empty(tmp_path: Path, monkeypatch):
    """Call-site contract: over budget → guard False → caller returns []."""
    monkeypatch.setenv("SEARCH_BUDGET_BRAVE_DAILY", "0")
    assert sb.guard("brave", "f3", now=NOW, root=tmp_path) is False
    # A denied attempt is counted under denied_today, not as spend.
    st = sb.status("brave", now=NOW, root=tmp_path)
    assert st["daily_used"] == 0
    assert st["denied_today"] == 1
