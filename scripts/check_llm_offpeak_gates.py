#!/usr/bin/env python3
"""check_llm_offpeak_gates.py — every allowlisted lane that pays for a model call must be off-peak-protected.

2026-11-07 (LQ-20261107-43). The n8n allowlist can name a lane whose command calls a paid model; the executor will
run it live when the lane is dispatched. Nothing required that entry to reproduce the cron line's off-peak protection,
so an entry could ship without it and no gate would notice — the executor only refuses an *unknown* `offpeak_gate`
(``n8n_run_executor.validate_entry``: ``bad_offpeak_gate``), never a *missing* one.

The protection itself lives in ``scripts/lib/llm_offpeak_guard.py`` (one place, unit-tested, gate vocabulary pinned to
the executor's). This script is its operator surface:

    python scripts/check_llm_offpeak_gates.py                     # the repo's allowlist
    python scripts/check_llm_offpeak_gates.py --allowlist <abs>   # e.g. a served release's copy, read-only
    python scripts/check_llm_offpeak_gates.py --json              # for a lane/checker to parse

Who counts: only the lanes that can reach the metered DeepSeek key (``deepseek_payers``, from each caller record's
``billing`` evidence in ``config/llm_direct_callers.json``). A lane that reaches only Grok/ChatGPT OAuth or a local
model has no DeepSeek window to honour, so it is not asked for one (LQ-20261107-247). Fail-closed: a caller with no
billing evidence is treated as a DeepSeek payer.

Exit 0 = every allowlisted DeepSeek payer declares a gate or names the wrapper; 1 = at least one does not; 2 = an input
file could not be read (never reported as clean).

READ_ONLY_ADVISORY. Reads two JSON files, writes nothing, no network, no database, no sender.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.llm_offpeak_guard import (  # noqa: E402
    OFFPEAK_GATES,
    OFFPEAK_WRAPPER,
    deepseek_payers,
    problems,
)

DEFAULT_ALLOWLIST = Path("config") / "n8n_run_allowlist.json"
DEFAULT_CALLERS = Path("config") / "llm_direct_callers.json"
AUTHORITY = "READ_ONLY_ADVISORY"


def load_lane_ids(path: Path) -> set[str]:
    """The lane ids a config file names under ``lanes``. Raises OSError / ValueError on an unreadable file."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    lanes = doc.get("lanes") if isinstance(doc, dict) else None
    if not isinstance(lanes, list):
        raise ValueError(f"{path}: no 'lanes' list")
    return {str(x.get("lane_id")) for x in lanes if isinstance(x, dict) and x.get("lane_id")}


def load_entries(path: Path) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    lanes = doc.get("lanes") if isinstance(doc, dict) else None
    if not isinstance(lanes, list):
        raise ValueError(f"{path}: no 'lanes' list")
    return [x for x in lanes if isinstance(x, dict)]


def run(allowlist: Path, callers: Path) -> tuple[list[dict], dict]:
    """The problems, plus the counts a reader needs to see the check was real. Raises OSError / ValueError."""
    entries = load_entries(allowlist)
    caller_rows = load_entries(callers)
    llm = load_lane_ids(callers)
    payers = deepseek_payers(caller_rows)
    found = problems(entries, llm_lane_ids=payers)
    overlap = sum(1 for e in entries if e.get("lane_id") in llm)
    payer_overlap = sum(1 for e in entries if e.get("lane_id") in payers)
    return found, {"allowlist": str(allowlist), "entries": len(entries), "model_caller_lanes": len(llm),
                   "deepseek_payer_lanes": len(payers), "allowlisted_model_callers": overlap,
                   "allowlisted_deepseek_payers": payer_overlap, "problems": len(found), "authority": AUTHORITY}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--allowlist", help=f"allowlist to read (default {DEFAULT_ALLOWLIST} under the repo)")
    ap.add_argument("--callers", help=f"model-caller lane ids (default {DEFAULT_CALLERS} under the repo)")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    allowlist = Path(a.allowlist) if a.allowlist else ROOT / DEFAULT_ALLOWLIST
    callers = Path(a.callers) if a.callers else ROOT / DEFAULT_CALLERS
    try:
        found, summary = run(allowlist, callers)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"CANNOT RUN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps({**summary, "items": found}, indent=1, sort_keys=True))
    elif found:
        print(f"llm off-peak gates: {len(found)} problem(s) in {summary['entries']} allowlist entries "
              f"({summary['allowlisted_deepseek_payers']} of them DeepSeek payers, "
              f"{summary['allowlisted_model_callers']} model callers)")
        for p in found:
            print(f"  x {p['lane_id']}: {p['detail']}")
    else:
        print(f"llm off-peak gates: clean — {summary['allowlisted_deepseek_payers']} allowlisted DeepSeek payer(s) of "
              f"{summary['entries']} entries, each naming {OFFPEAK_WRAPPER} or declaring offpeak_gate "
              f"({'/'.join(sorted(OFFPEAK_GATES))}); "
              f"{summary['allowlisted_model_callers'] - summary['allowlisted_deepseek_payers']} model caller(s) "
              f"pay no DeepSeek")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
