"""api_v2 subprocess interpreter (2026-10-09 cron audit follow-up to #1575).

The served API runs from a release directory with no .venv, so `PROJECT_ROOT/.venv/bin/python` named a file
that does not exist and 34 served producer/remediation actions failed with Errno 2. Every subprocess now
launches through the module helper `_project_python()`. Paper/broker execution call paths are deliberately
left for an execution-engineering change and are pinned here so a later edit is a conscious one.
Source-level checks only: no subprocess, no network, no database.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
PAT = re.compile(r'str\(PROJECT_ROOT / "\.venv(?:/bin/python3?|" / "bin" / "python3?)"\)')

# Paper/broker execution paths left untouched on purpose (needs an execution-engineering grant).
EXCLUDED_SCRIPTS = {
    "alpaca_paper_reconciler.py",
    "paper_execution_quality_analyzer.py",
    "incubator_proposal_promoter.py",
    "paper_performance_governance.py",
    "paper_submit_readiness.py",
    "proposal_paper_submitter.py",
    "paper_trade_monitor.py",
    "paper_trade_closer.py",
}


def _helper_span():
    start = SRC.index("def _project_python() -> str:")
    return start, SRC.index("\ndef ", start + 1)


def test_no_release_venv_literal_outside_helper_except_excluded_paths():
    a, b = _helper_span()
    leftovers = []
    for m in PAT.finditer(SRC):
        if a <= m.start() < b:
            continue
        window = SRC[m.start() : m.start() + 400]
        script = re.search(r'"(?:scripts/)?(\w+\.py)"', window)
        leftovers.append(script.group(1) if script else "?")
    assert set(leftovers) <= EXCLUDED_SCRIPTS, sorted(set(leftovers) - EXCLUDED_SCRIPTS)
    assert len(leftovers) == len(EXCLUDED_SCRIPTS)


def test_subprocess_sites_use_the_helper():
    assert SRC.count("_project_python(),") >= 30
    assert '"installed": _ver(_run([_project_python(), "--version"])),' in SRC


def test_helper_prefers_running_interpreter_and_checks_files():
    a, b = _helper_span()
    body = SRC[a:b]
    first = body.split("candidates = [", 1)[1].split(",", 1)[0].strip()
    assert first == "_sys_py.executable"
    assert "is_file()" in body
