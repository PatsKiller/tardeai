"""n8n program 0.4b-fix (2026-11-06): four native n8n lanes carry scheduler.stage canary.

Without a stage the relay live-list render dropped them (native_n8n_no_stage) and the relay refused every fire with
relay_live_not_enabled from 2026-10-30. Pinned by tests/test_n8n_native_lane_stage_20261106.py; the canary census
(tests/test_canary_wave1_20261011.py) admits them through LIVE.
"""
from __future__ import annotations

WORKFLOWS = {
    "crontab-snapshot-for-health-agent": "c0d4c7845e5c4fcc",
    "n8n-incident-fanin": "722fac0e043ea5c4",
    "n8n-pilot-dispatch": "078e8fcbea0c5020",
    "n8n-research-intake-consumer": "21fd15d5f8a4c4da",
}
LIVE = frozenset(WORKFLOWS)
