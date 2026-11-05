"""pr-hygiene-audit canary pin (2026-10-22; split out 2026-10-27 when the retired release train was removed).

One list for every inventory pin that reads stage / live_arg / effect-key scope. pr-hygiene-audit is an n8n-native
dispatcher row (no cron line, no unit), dispatch live, live_arg []; its receipt is an atomic rewrite and its single
comms intent is deduped by the alert state and the intent store, so there is no cron side to fence and no effect key.
The four release-train request lanes that shared this list until 2026-10-27 were archived with the train
(archive/release_train_20261026/). Pins: tests/test_pr_hygiene_audit_20261021.py.
"""

from __future__ import annotations

LIVE = ("pr-hygiene-audit",)
