"""registry-runtime-truth lane (2026-10-19; packet docs/ops/packets/registry-runtime-truth-20261018/): the lane it adds
at canary.

One list for every inventory pin that reads stage / live_arg / contract counts, as tests/support/
comms_intent_consumer_live.py does for the comms-intent consumer. LIVE: registry-runtime-truth, an n8n-native
dispatcher row (no cron line ever existed) at stage canary / dispatch live daily 07:20 ET with allowlist live_arg
["--apply"] and a REVIEWED health contract. Measure-only: it carries NO effect key (no cron side to fence; its only
writes are its own receipt and at most one deduped host comms intent per run). Pins:
tests/test_registry_runtime_truth_20261018.py.
"""
from __future__ import annotations

LIVE = ("registry-runtime-truth",)
