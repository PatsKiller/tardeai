"""conflict-resolver admitted at canary (2026-10-25; operator directive, verbatim: "You should turn on everything.
It shouldn't need me to turn on anything. Get it working.").

One list for every inventory pin that reads stage / live_arg / effect-key scope (precedent
tests/support/release_train_h0.py). n8n-native dispatcher row (no cron line, no unit), dispatch live, allowlist
live_arg ["--shadow"]: a live run appends ConflictEvent@v1 rows only on a state change (the ledger is idempotent per
finding key; an unchanged poll appends nothing) under its own ledger lock, writes one comparison report per run id
(O_EXCL) and has no sender. There is no cron side to fence, so no effect key. Pins:
tests/test_conflict_resolver_lane_20261025.py.
"""

from __future__ import annotations

LIVE = ("conflict-resolver",)
LIVE_ARG = {"conflict-resolver": ["--shadow"]}
