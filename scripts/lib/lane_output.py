"""Per-attempt lane output counts (``LaneOutput@v1``): produced / attempted / skipped, for every run mode.

Lane repair 2026-10-15 (build-symbol-profiles, watchlist-entry-planner, indicator-engine). The 2026-10-15 n8n
audit (``~/n8n-maturity-verification/audit-20261015/report.txt`` §7) found that exit 0 maps to ``RUN_DONE`` and that a
receipt with ``produced_count=0`` still reads as success. The proposed ``LaneRunReceipt@v2`` fields
(``docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md`` §5, branch ``n8n/reference-arch-framework-checker``) are
``produced_count``, ``attempted_count``, ``skipped_reasons`` and ``empty_reason``. This module builds that block once
so each lane:

* puts it in its ``LaneRunReceipt@v1`` ``summary`` (a real run; v1 readers ignore the extra keys), and
* prints it as ONE bounded line, ``LANE_OUTPUT {...}``, on **stderr**, in every mode, the dry run included. The audit
  asks for attempt evidence the executor can capture without the dry run writing canonical state (a dry run has no
  receipt). ``scripts/n8n_run_executor.py`` keeps ``stdout_tail`` and ``stderr_tail`` on every ``RunReceipt``; stderr
  keeps each lane's stdout contract byte-identical (tests compare it with the frozen entrypoints).

The health contract's ``expected_output`` rule (``N8nExpectedOutput@v1``) reads ``produced_count`` from either place.

Pure: no DB, no network, no file write. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

SCHEMA = "LaneOutput@v1"
PREFIX = "LANE_OUTPUT "
MAX_REASONS = 20
MAX_LINE = 2000


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be an int >= 0, got {value!r}")
    return value


def output_block(*, produced: int, attempted: int, skipped: Optional[Mapping[str, int]] = None,
                 empty_reason: Optional[str] = None, unit: str) -> dict[str, Any]:
    """The four contract fields plus the unit. ``skipped`` keeps only reasons with a count above zero."""
    reasons = {str(k): _count(v, f"skipped_reasons[{k}]") for k, v in (skipped or {}).items() if v}
    if len(reasons) > MAX_REASONS:
        top = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_REASONS]
        reasons = dict(top)
        reasons["_truncated"] = 1
    produced = _count(produced, "produced_count")
    return {
        "schema": SCHEMA,
        "unit": unit,
        "produced_count": produced,
        "attempted_count": _count(attempted, "attempted_count"),
        "skipped_reasons": reasons,
        "empty_reason": (empty_reason or None) if produced == 0 else None,
    }


def emit(lane_id: str, mode: str, block: Mapping[str, Any], *, started_at: Optional[str] = None,
         stream=None) -> str:
    """Print the one ``LANE_OUTPUT`` line (bounded) and return it. Never raises into the caller."""
    doc = {
        "lane_id": lane_id,
        "mode": mode,
        "pid": os.getpid(),
        "started_at": started_at,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        **dict(block),
    }
    try:
        line = PREFIX + json.dumps(doc, sort_keys=True, default=str)
    except (TypeError, ValueError) as exc:
        line = PREFIX + json.dumps({"lane_id": lane_id, "mode": mode, "error": type(exc).__name__})
    if len(line) > MAX_LINE:
        doc["skipped_reasons"] = {"_truncated": 1}
        line = PREFIX + json.dumps(doc, sort_keys=True, default=str)[:MAX_LINE]
    try:
        print(line, file=stream or sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 -- evidence printing must never fail the run
        pass
    return line


def parse(text: str) -> Optional[dict[str, Any]]:
    """The last ``LANE_OUTPUT`` line in captured output (stderr tail), parsed; None when there is none."""
    for raw in reversed((text or "").splitlines()):
        if raw.startswith(PREFIX):
            try:
                return json.loads(raw[len(PREFIX):])
            except ValueError:
                return None
    return None
