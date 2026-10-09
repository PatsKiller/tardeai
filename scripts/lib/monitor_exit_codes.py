"""Exit codes shared by monitors that run under health_tick.py.

A monitor that ran to completion and FOUND something unhealthy exits
``EXIT_FINDING`` (3). It must not exit 1: 1 is what CPython returns for an
uncaught exception and for ``sys.exit("message")``, so a monitor that used 1
for "finding" made a crash indistinguishable from a finding. health_tick.py
(n8n maturity B3.1, 2026-10-09) declares ``finding_rc: [3]`` for these steps
in config/health_tick_steps.json and treats rc 1 as a broken step.

Users: scripts/system_health_agent.py (critical component down),
scripts/moomoo/opend_health.py (OpenD data plane down),
scripts/pipeline_liveness_report.py --fail-on-finding (STARVED /
NO_ELIGIBLE_INPUT / UNKNOWN lane).

AUTHORITY: READ_ONLY_ADVISORY. Constants only; touches no financial surface.
"""
from __future__ import annotations

EXIT_OK = 0
# CPython's exit status for an uncaught exception or sys.exit("<str>"): never a finding.
EXIT_PYTHON_CRASH = 1
EXIT_FINDING = 3

__all__ = ["EXIT_OK", "EXIT_PYTHON_CRASH", "EXIT_FINDING"]
