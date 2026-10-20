"""Active Trader motion watchdog (2026-10-19, operator decision: n8n owns the supervision of the motion runtime).

One list for every inventory pin that reads stage / live_arg / contract counts, as tests/support/
comms_intent_consumer_live.py does. LIVE: active-trader-motion-watchdog, an n8n-native dispatcher row (no cron line
ever existed) at stage canary / dispatch live */5 with allowlist live_arg ["--apply"] and a REVIEWED health contract.
It carries NO effect key: there is no cron side to fence, and its only effects (a state file and at most one comms
intent per band change, deduped by the state file and the comms store) are idempotent per band. Pins:
tests/test_active_trader_motion_watchdog_20261019.py; packet docs/ops/packets/active-trader-motion-n8n-20261019/.
"""
from __future__ import annotations

LIVE = ("active-trader-motion-watchdog",)
