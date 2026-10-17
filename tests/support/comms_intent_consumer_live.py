"""comms-intent consumer LIVE (2026-10-17, operator decision D2 "Queue reader first"): the lane it moves to canary.

One list for every inventory pin that reads stage / live_arg / contract counts, as tests/support/hermes_learning_cutover.py
does for the hermes cutover. LIVE: n8n-comms-intent-consumer, an n8n-native dispatcher row (no cron line ever existed)
at stage canary / dispatch live */5 with allowlist live_arg ["--apply"] and a REVIEWED health contract. It carries NO
effect key: there is no cron side to fence, and every live effect is idempotent per intent (compare-and-set
QUEUED -> CLAIMED inside BEGIN IMMEDIATE). Pins: tests/test_comms_intent_consumer_live_20261017.py; packet
docs/ops/packets/comms-intent-consumer-live-20261017/.
"""
from __future__ import annotations

LIVE = ("n8n-comms-intent-consumer",)
