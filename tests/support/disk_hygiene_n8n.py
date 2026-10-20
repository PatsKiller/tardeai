"""Disk hygiene + disk-usage monitor on the n8n fabric (2026-10-18, operator: "a script with rules that's repeatable,
n8n should run this weekly; and also monitor when a threshold is over 80%, fix and move to n8n where monitored").

One list for every inventory pin that reads stage / live_arg / contract counts, as tests/support/
comms_intent_consumer_live.py does. LIVE: two n8n-native dispatcher rows (no cron line ever existed) at stage canary /
dispatch live: disk-usage-monitor (*/15, live_arg ["--apply"]) and disk-hygiene (Sun 04:00 ET, live_arg ["--plan"]:
a manifest, never a deletion). Neither carries an effect key: there is no cron side to fence; the monitor's only
effects are its own state file and one comms intent per band change (the store dedupes), and the hygiene plan writes
a manifest. Pins: tests/test_disk_hygiene_20261018.py; packet docs/ops/packets/disk-hygiene-n8n-20261018/.

2026-10-19 (operator, after /tmp hit 97% inodes with bytes free): + tmp-hygiene (daily 05:00 ET, live_arg ["--plan"]:
a /tmp manifest with inodes, never a deletion), same shape and no effect key. Pins: tests/test_tmp_hygiene_20261019.py.
"""
from __future__ import annotations

LIVE = ("disk-usage-monitor", "disk-hygiene", "tmp-hygiene")
