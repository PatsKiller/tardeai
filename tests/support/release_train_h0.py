"""Release train H.0 shadow-enable (2026-10-22; packet docs/ops/packets/release-train-arming-20261021/ §H.0).

One list for every inventory pin that reads stage / live_arg / effect-key scope, as tests/support/
hermes_scorer_canary.py does for its lane. LIVE: the five lanes H.0 moves shadow -> canary.

* release-train-request-1800/-0000/-0600/-0800: n8n-native (fired only by tradeai-fabric-release-train through Run
  Lane, no dispatch block, no cron line), allowlist live_arg ["--append", "--shadow-only"]; state stays
  NEVER_SCHEDULED until arming step F publishes the workflow. A live run appends one O_EXCL TrainWindowRequest@v1
  per window id (host-validated key rtw:<slot>:<date>:shadow), so a repeat is a duplicate refusal, not a second row.
* pr-hygiene-audit: n8n-native dispatcher row (no cron line), dispatch live, live_arg []; its receipt is an atomic
  rewrite and its single comms intent is deduped by the alert state and the intent store.

No cron side exists to fence, so none carries an effect key (the canary double-effect audit keys cron-vs-n8n overlap;
precedent tests/support/disk_hygiene_n8n.py). Pins: tests/test_release_train_n8n_20261021.py,
tests/test_pr_hygiene_audit_20261021.py.
"""

from __future__ import annotations

REQUEST_LANES = (
    "release-train-request-1800",
    "release-train-request-0000",
    "release-train-request-0600",
    "release-train-request-0800",
)
LIVE = (*REQUEST_LANES, "pr-hygiene-audit")
