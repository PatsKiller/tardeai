"""AGENTS.md 18.1.0 (PROPOSED, MINOR) — §7 standing trap: timeouts, reaper caps and kill windows.

The AGENTS.md text ships as an operator-applied patch (scratchpad `agents-timing/agents-18.1.0-proposed.patch`),
the way 18.0.0 did; this test is committed ahead of it, by design. Before the patch lands (Policy-Version
18.0.0) it only checks that what the trap will point at exists. From 18.1.0 on it also pins the trap text,
the history row and the header block.

Cause: 2026-10-21/22 trade_ai_orchestrator reaped at the 20 m cap on every market-hours run (1216-1377 s);
symbol_enrichment 224 failed / 1 success in 36 h under the health tick's orphan_wait_s 30 (real p50 136 s).
Operator 2026-10-22: "update the agents.md and documentation with the proper time settings. So another
agent doesn't come behind and do that."
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
TRAP = "## Timeouts, reaper caps and kill windows — measured, never guessed"


def _version() -> tuple[int, ...]:
    m = re.search(r"^Policy-Version:\s*(\S+)", AGENTS, re.M)
    return tuple(int(x) for x in m.group(1).split("."))


def test_trap_targets_exist():
    assert (ROOT / "docs/ops/PIPELINE_TIME_SETTINGS.md").is_file()
    assert (ROOT / "tests/test_pipeline_time_settings_20261022.py").is_file()
    assert (ROOT / "config/ci_gates/pipeline_time_settings_20261022.json").is_file()


def test_trap_text_and_history_once_applied():
    if _version() < (18, 1, 0):
        assert TRAP not in AGENTS  # never half-applied: trap and version bump travel together
        return
    assert AGENTS.count(TRAP) == 1
    seven = AGENTS.index("# 7 · Standing traps")
    seven_a = AGENTS.index("# 7A · One source of truth")
    assert seven < AGENTS.index(TRAP) < seven_a
    body = AGENTS[AGENTS.index(TRAP):AGENTS.index("## Caches and derived stores")]
    for needle in ("docs/ops/PIPELINE_TIME_SETTINGS.md", "measured runtime", "censored", "max_runtime_min",
                   "**30**", "TimeoutStartSec=330", "HEALTH_TICK_STEP_TIMEOUT_S", "orphan_wait_s", "224 failed"):
        assert needle in body, needle
    row = next(line for line in AGENTS.splitlines() if line.startswith("| 18.1.0 |"))
    assert "MINOR" in row and "APPROVE_AGENTS_POLICY_18_1_0" in row
    if _version() == (18, 1, 0) and re.search(r"^Status:\s*PROPOSED", AGENTS, re.M):
        assert re.search(r"^Effective-Date:\s*PENDING", AGENTS, re.M)
        assert re.search(r"^Supersedes:\s*18\.0\.0", AGENTS, re.M)
        assert "| 18.1.0 | 2026-10-22 | PROPOSED |" in row
