"""The cutover factory maps a cron line's env prefix when the allowlist command declares the same pair.

2026-11-07 (LQ-20261107-26, n8n overnight onboarding wave): the operator's hot-tier cron lines carry an env prefix
(`SCALP_HOT_TIER=1 MOMENTUM_SCALP_OUTER_DEADLINE_S=170 ...`) and `parse_lane_argv` reported every assignment as
`unmapped_wrapper:env:NAME`, so no such lane could ever reach READY_CANARY — the already-shadow lanes included.
The executor runs the allowlist `command` verbatim, so a `command` that declares the same `env NAME=value` pair
before the script reproduces the cron line exactly; the assignment is mapped, and a declared name carrying a
different value is refused instead of silently drifting (the live scalp line's budget moved 100 -> 170).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import n8n_cutover_wave as W  # noqa: E402

ENTRY = ["env", "SCALP_HOT_TIER=1", "MOMENTUM_SCALP_OUTER_DEADLINE_S=170",
         "$PY", "scripts/run_finviz_momentum_scalp_scan.py", "--hot-list-only"]
LINE = ("*/2 6-9 * * 1-5 cd $PROJ && SCALP_HOT_TIER=1 MOMENTUM_SCALP_OUTER_DEADLINE_S=170 "
        "flock -n /tmp/zq.lock timeout 180 "
        "bash scripts/market_day_gate.sh $PY scripts/run_finviz_momentum_scalp_scan.py --hot-list-only --apply "
        ">> logs/zq.log 2>&1")


def test_a_declared_env_prefix_is_mapped_not_unmapped():
    p = W.parse_lane_argv(W.command_of(LINE), ENTRY)
    assert p["problems"] == [], p["problems"]
    assert p["env_wrapper"] == ["SCALP_HOT_TIER=1", "MOMENTUM_SCALP_OUTER_DEADLINE_S=170"]
    assert p["live_arg"] == ["--apply"] and p["market_gate"] is True


def test_an_undeclared_env_prefix_stays_unmapped():
    p = W.parse_lane_argv(W.command_of(LINE.replace("SCALP_HOT_TIER=1 ", "")),
                          ["$PY", "scripts/run_finviz_momentum_scalp_scan.py", "--hot-list-only"])
    assert "unmapped_wrapper:env:MOMENTUM_SCALP_OUTER_DEADLINE_S" in p["problems"]


def test_a_declared_name_with_a_different_value_is_refused():
    stale = ["env", "SCALP_HOT_TIER=1", "MOMENTUM_SCALP_OUTER_DEADLINE_S=100",
             "$PY", "scripts/run_finviz_momentum_scalp_scan.py", "--hot-list-only"]
    p = W.parse_lane_argv(W.command_of(LINE), stale)
    assert any(r.startswith("wrapper_env_value_differs:MOMENTUM_SCALP_OUTER_DEADLINE_S=170")
               for r in p["problems"]), p["problems"]
    assert "unmapped_wrapper:env:MOMENTUM_SCALP_OUTER_DEADLINE_S" not in p["problems"]
