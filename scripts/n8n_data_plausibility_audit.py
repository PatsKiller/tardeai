#!/usr/bin/env python3
"""n8n lane ``n8n-data-plausibility-audit``: the data plausibility monitor, fired by tradeai-dispatcher (2026-10-18).

Operator 2026-10-18: the data monitors run "within n8n with proper contracts". This is the lane's entry script
(config/n8n_run_allowlist.json command). It runs ``data_plausibility_monitor.lane_main``: measure every declared
contract in a read-only session, write LaneRunReceipt@v2 (produced = contracts measured), and with ``--alert``
QUEUE one host comms intent (config/host_comms_intent_routes.json data/data_plausibility_violation) when the
(contract, column, rule, severity band) set changes. It never calls a sender: the systemd unit
tradeai-data-plausibility.service keeps ``scripts/data_plausibility_monitor.py --alert`` (chokepoint send) until the
owner switch (docs/ops/packets/data-integrity-monitors-n8n-20261018/cutover.sh c3).

    --dry-run   measure and print; writes nothing (the allowlist dry_run_arg)
    (no flag)   measure + LaneRunReceipt@v2, notify nobody (the canary live_arg: DRY live_arg first)
    --alert     + queue the host intent on change (the owner-switch live_arg, a follow-up PR)

Exit: 0 the run completed (findings are output); 1 the database could not be measured or the intent could not be
queued; 2 usage. MBI_BEHAVIOR = 0: no broker, no order, no send.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import argparse  # noqa: E402

# by name, never `import data_plausibility_monitor`: the dispatcher sender gate scans only the definitions named here
from data_plausibility_monitor import LANE_ID, LAST_LANE_OUTPUT, lane_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"n8n lane {LANE_ID}")
    ap.add_argument("--dry-run", action="store_true", help="read and print; write nothing (allowlist dry_run_arg)")
    ap.add_argument("--alert", action="store_true", help="queue a host comms intent on change (owner-switch argv)")
    ap.add_argument("--json", action="store_true", help="JSON report")
    args = ap.parse_args(argv)
    flags = [f for f, on in (("--dry-run", args.dry_run), ("--alert", args.alert), ("--json", args.json)) if on]
    rc = lane_main(flags)
    if LAST_LANE_OUTPUT:  # the LaneRunReceipt@v2 output fields the executor's verdict reads
        print(f"[{LANE_ID}] rc={rc} produced_count={LAST_LANE_OUTPUT.get('produced_count')} "
              f"empty_reason={LAST_LANE_OUTPUT.get('empty_reason')} skipped={LAST_LANE_OUTPUT.get('skipped_reasons')}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
