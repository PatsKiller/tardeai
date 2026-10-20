"""Data-integrity monitors on n8n (2026-10-18, operator: "within n8n with proper contracts"): the lanes this PR adds.

One list for every inventory pin that reads stage / live_arg / contract counts, as
tests/support/comms_intent_consumer_live.py does for the comms-intent consumer. LIVE: two n8n-native dispatcher rows
at stage canary / dispatch live at their systemd timers' own cadence, with a DRY live_arg first (``[]``: the entry
script's lane_main measures, writes LaneRunReceipt@v2 and notifies nobody) and REVIEWED health contracts. They carry NO effect key: both are
read-only monitors (overwrite-only receipts), and the alerting owner stays the systemd timer until the packet's c3
owner switch. Pins: tests/test_data_integrity_fixes_20261018.py; packet
docs/ops/packets/data-integrity-monitors-n8n-20261018/.
"""
from __future__ import annotations

LIVE = ("n8n-data-plausibility-audit", "n8n-gap-resolution-audit")
#: lane -> (script, cadence, lock, legacy systemd timer)
LANES = {
    "n8n-data-plausibility-audit": ("scripts/n8n_data_plausibility_audit.py", "20 6 * * *",
                                    "/tmp/tradeai_data_plausibility.lock", "tradeai-data-plausibility.timer"),
    "n8n-gap-resolution-audit": ("scripts/n8n_gap_resolution_audit.py", "7,37 * * * *",
                                 "/tmp/tradeai_gap_resolution.lock", "tradeai-gap-resolution.timer"),
}
